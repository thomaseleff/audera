""" Streamer service """

from typing import Dict
import ntplib
import asyncio
import socket
import time
import struct
import copy
import concurrent.futures
from zeroconf import Zeroconf

import audera


class Service():
    """ A `class` that represents the `audera` streamer service.

    The streamer service runs the following `micro-services` within an async event loop,
        - Remote audio output player mDNS browsing with player connection and playback session management
        - Network time protocol (ntp) synchronization
        - Multi-player synchronization
        - Audio stream capture and broadcasting

    The streamer service can be run using the command-line,

    ``` bash
    audera run streamer
    ```

    Or, through a Python session,

    ``` python
    import asyncio
    import audera

    if __name__ == '__main__':
        asyncio.run(audera.streamer.Service().run())
    ```

    """

    def __init__(self):
        """ Initializes an instance of the `audera` streamer service. """

        # Logging
        self.logger = audera.logging.get_server_logger()

        # Initialize identity

        # The `update` method will either get the existing identity, create a new identity or
        #   update the existing identity with new network interface settings. Unlike other
        #   `audera` structure objects, where equality is based on every object attribute,
        #   identities are only considered to be the same if they share the same uuid and
        #   mac address. Finally, the name of an identity is immutable, when an identity is updated
        #   the same name is always retained.

        self.mac_address = audera.mdns.get_local_mac_address()
        self.server_ip_address = audera.mdns.get_local_ip_address()
        self.identity: audera.struct.identity.Identity = audera.struct.identity.Identity.from_config(
            audera.dal.identities.update(
                audera.struct.identity.Identity(
                    name=audera.struct.identity.generate_cool_name(),
                    uuid=audera.struct.identity.generate_uuid_from_mac_address(self.mac_address),
                    mac_address=self.mac_address,
                    address=self.server_ip_address
                )
            )
        )

        # Initialize session

        # The `update` method will either get the existing session, create a new session or
        #   update the existing session with new players. If a session already exists then the
        #   same session volume will be retained. Currently, any / all available players are
        #   automatically attached to the current playback session. An available player is any
        #   player that is both enabled and connected to the local network.

        self.session: audera.struct.session.Session = audera.struct.session.Session.from_config(
            audera.dal.sessions.update(
                audera.struct.session.Session(
                    name=self.identity.name,
                    uuid=self.identity.uuid,
                    mac_address=self.identity.mac_address,
                    address=self.identity.address,
                    players=audera.dal.players.get_all_available_player_uuids(),
                    provider='audera'
                )
            )
        )

        # Initialize mDNS

        # The streamer browses the network for remote audio output players that are broadcasting
        #   the `audera` mDNS service, `roap@{mac_address}._audera._tcp.local`. The browser
        #   automatically attaches players to the current session when they connect, removes
        #   players when they disconnect, and updates players when any of the mDNS service
        #   properties change.

        self.mdns: audera.mdns.PlayerBrowser = audera.mdns.PlayerBrowser(
            logger=self.logger,
            zc=Zeroconf(),
            type_=audera.MDNS_TYPE,
            time_out=audera.TIME_OUT
        )

        # Initialize audio stream

        # The `get-interface` and `get-device` methods will either get the existing audio
        #   interface / input-device or will create a new default audio interface / input-device.
        #   The interface describes the parameters of the digital audio stream (format, sampling
        #   frequency, number of channels, and the number of frames for each broadcasted audio
        #   chunk). The device determines which hardware input device is supplying the audio
        #   stream. The system default audio input device is automatically selected by default.

        self.audio_input = audera.struct.audio.Input(
            interface=audera.dal.interfaces.get_interface(),
            device=audera.dal.devices.get_device()
        )

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer()
        self.ntp_offset: float = 0.0

        # Initialize playback delay
        self.playback_delay: float = audera.PLAYBACK_DELAY

        # Initialize clients for broadcasting the audio stream
        self.players: Dict[str, asyncio.StreamWriter] = {}

        # Initialize process control parameters
        self.mdns_browser_event: asyncio.Event = asyncio.Event()

    def get_playback_time(self) -> float:
        """ Returns the playback time based on the current time, playback delay and
        network time protocol (ntp) server offset.
        """
        return float(time.time() + self.playback_delay + self.ntp_offset)

    async def mdns_browser(self):
        """ The async `micro-service` for the multi-cast DNS remote audio output player service
        browser.

        The purpose of the mDNS browser is to automatically connect, disconnect and update the
        status of any / all remote audio output players.

        The streamer starts the mDNS service as an _independent_ task, until the task is either
        cancelled by the event loop or cancelled manually through `KeyboardInterrupt`.
        """
        loop = asyncio.get_running_loop()

        # Browse for remote audio output players broadcasting the mDNS service
        try:

            # The mDNS service must be started in a separate thread
            #   since zeroconf relies on its own async event loop.

            # Remote audio output player registration / disconnection / removal
            #   takes place within the mDNS browser.

            with concurrent.futures.ThreadPoolExecutor() as pool:
                mdns_browser = loop.run_in_executor(pool, self.mdns.browse)
                await asyncio.gather(mdns_browser)

            # Set the mDNS browser event to allow for the multi-player synchronization,
            #   audio stream capture and broadcasting `micro-services` to start.

            self.mdns_browser_event.set()

            # Manage the playback session, opening connections to all remote audio
            #   output players attached to the session continuously

            while self.mdns_browser_event.is_set():

                if self.mdns.players:

                    # Automatically attach any / all available players to the current playback session
                    self.session.players = audera.dal.players.get_all_available_player_uuids()
                    _ = audera.dal.sessions.update(self.session)

                    # Open connections to all players concurrently
                    await asyncio.gather(
                        *[
                            self.open_connection(player) for player
                            in audera.dal.sessions.get_session_players(self.session.uuid)
                        ],
                        return_exceptions=True
                    )

                await asyncio.sleep(audera.TIME_OUT)

        except (
            asyncio.CancelledError,  # mDNS-services cancelled
            KeyboardInterrupt,  # mDNS-services cancelled manually
        ):

            # Logging
            self.logger.info(
                'Browsing for mDNS service {%s} cancelled.' % (
                    audera.MDNS_TYPE
                )
            )

        # Close the mDNS service browser
        self.mdns.close()

        # Detach any / all remote audio output players
        audera.dal.sessions.detach_players(
            self.session.uuid,
            [
                player.uuid for player
                in audera.dal.sessions.get_session_players(self.session.uuid)
            ]
        )

        # Close any / all remote audio output player streams
        for ip_address, connection in self.players.items():

            # Logging
            self.logger.info(
                'Remote audio output player {%s} disconnected.' % (
                    ip_address
                )
            )

            # Close the connection
            connection.close()
            try:
                await connection.wait_closed()
            except (
                ConnectionResetError,  # Player disconnected
                ConnectionAbortedError,  # Player aborted the connection
            ):
                pass

            # Remove the remote audio output player
            del self.players[ip_address]

    async def open_connection(
        self,
        player: audera.struct.player.Player
    ):
        """ Opens a connection to a remote audio output player when attached to the
        current playback session.

        Parameters
        ----------
        player: `audera.struct.player.Player`
            An instance of an `audera.struct.player.Player` object.
        """

        # Register the remote audio output player
        if player.address not in self.players.keys():

            # Logging
            self.logger.info(
                'Streaming audio to remote audio output player {%s (%s)}.' % (
                    player.name,
                    player.uuid.split('-')[0]  # Short uuid of the player
                )
            )

            # Open the connection to the remote audio output player
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    player.address,
                    audera.STREAM_PORT
                ),
                timeout=audera.TIME_OUT
            )

            # Configure the stream socket options for low-latency communication
            try:
                client_socket: socket.socket = writer.get_extra_info('socket')
                client_socket: socket.socket = socket.socket()
                client_socket.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_NODELAY,
                    1
                )

            except Exception:

                # Logging
                self.logger.warning(
                    'Remote audio output player {%s (%s)} unable to operate with TCP_NODELAY.' % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

            # Initialize audio playback to the remote audio output player
            _ = audera.dal.players.play(player.uuid)

            # Retain the remote audio output player for the current playback session
            self.players[player.address] = writer

    async def ntp_synchronizer(self):
        """ The async `micro-service` for network time protocol (ntp) synchronization.

        The purpose of ntp synchronization is to ensure that the time on the streamer
        coincides with all other `audera` remote audio output players on the local network
        by regularly synchronizing the clocks with a reference time source.

        The streamer attempts to start the time-synchronization service as an _independent_ task,
        restarting the service forever until the task is either cancelled by the event loop or
        cancelled manually through `KeyboardInterrupt`.
        """

        while True:
            try:

                # Update the local machine time offset from the network time protocol (ntp) server
                self.ntp_offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'The server ntp time offset is %.7f [sec.].' % (
                        self.ntp_offset
                    )
                )

                # Wait, yielding to other tasks in the event loop
                await asyncio.sleep(audera.SYNC_INTERVAL)

            except ntplib.NTPException:

                # Logging
                self.logger.info(
                    ''.join([
                        'Communication with the ntp server {%s} failed,' % (
                            self.ntp.server
                        ),
                        ' retrying in %.2f [min.].' % (
                            audera.SYNC_INTERVAL / 60
                        )
                    ])
                )

                # Wait, yielding to other tasks in the event loop
                await asyncio.sleep(audera.SYNC_INTERVAL)

            except (
                asyncio.CancelledError,  # Streamer services cancelled
                KeyboardInterrupt  # Streamer services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'Communication with the npt server {%s} cancelled.' % (
                        self.ntp.server
                    )
                )

                # Exit the loop
                break

    async def multi_player_synchronizer(self):
        """ Starts the async server for multi-player synchronization.

        The purpose of multi-player synchronization is to ensure that the time on the streamer
        coincides with all other `audera` remote audio output players on the local network
        by regularly sending its current time as a reference time source.

        The streamer attempts to start the server as an _dependent_ task, serving continuous
        connections with remote audio output players forever until the task completes, is
        cancelled by the event loop or is cancelled manually through `KeyboardInterrupt`.

        The multi-player synchronization service depends on the mDNS browser.
        """

        # Wait for the mDNS browser
        await self.mdns_browser_event.wait()

        # Initialize the multi-player synchronizer
        multi_player_synchronizer = await asyncio.start_server(
            client_connected_cb=(
                lambda reader, writer: self.multi_player_synchronizer_callback(
                    reader=reader,
                    writer=writer
                )
            ),
            host='0.0.0.0',  # No specific destination address
            port=audera.PING_PORT
        )

        # Serve player connections forever
        async with (multi_player_synchronizer):
            await asyncio.gather(multi_player_synchronizer.serve_forever())

        # Stop all services
        await self.stop_services()

    async def multi_player_synchronizer_callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ The async multi-player synchronizer callback that is started when a remote audio
        output player connects to `https://0.0.0.0:{audera.PING_PORT}`.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader passed from `asyncio.start_server()` used to
                receive a `ping` response from the player.
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from `asyncio.start_server()` used to
                serve the current streamer time response to the player.
        """

        # Retrieve the remote audio output player ip-address
        address, _ = writer.get_extra_info('peername')
        player = audera.dal.players.get_player_by_address(address)

        # Communicate with the player
        try:

            # Read the ping-communication
            message = await reader.read(4)
            if message == b"ping":

                # Serve the response-communication containing the current time on the streamer
                #   for the player to calculate the time offset and wait for the response to be
                #   received.

                writer.write(
                    struct.pack(
                        "d",
                        time.time() + self.ntp_offset
                    )
                )  # 8 bytes
                await writer.drain()

            # Logging
            self.logger.info(
                'Remote audio output player {%s (%s)} synchronized.' % (
                    player.name,
                    player.uuid.split('-')[0]  # Short uuid of the player
                )
            )

        except (
            asyncio.TimeoutError,  # Streamer communication timed-out
            asyncio.CancelledError,  # Streamer services cancelled
            KeyboardInterrupt  # Streamer services cancelled manually
        ):

            # Logging
            self.logger.info(
                'Multi-player sync with remote audio output player {%s (%s)} cancelled.' % (
                    player.name,
                    player.uuid.split('-')[0]  # Short uuid of the player
                )
            )

        except OSError as e:

            # Logging
            self.logger.error(
                '[%s] [multi_player_synchronizer()] %s.' % (
                    type(e).__name__, str(e)
                )
            )

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # Player disconnected
                ConnectionAbortedError,  # Player aborted the connection
            ):
                pass

    async def audio_streamer(self):
        """ The async audio stream `micro-service` for audio capturing and broadcasting. The
        streamer captures audio data from the hardware audio input-device and broadcasts the audio
        stream to all connected remote audio output players as timestamped packets concurrently.

        The streamer attempts to start the stream service as an _dependent_ task, restarting the
        service forever with `audera.TIME_OUT` until the task is either cancelled by the event
        loop or cancelled manually through `KeyboardInterrupt`.

        The audio stream service depends on the mDNS browser.
        """

        # Wait for the mDNS browser
        await self.mdns_browser_event.wait()

        # Logging
        self.logger.info(
            ' '.join([
                "Streaming {%s}-bit audio at {%s}" % (
                    self.audio_input.interface.bit_rate,
                    self.audio_input.interface.rate
                ),
                "with {%s} channel(s) from input device {%s (%s)}." % (
                    self.audio_input.interface.channels,
                    self.audio_input.device.name,
                    self.audio_input.device.index
                )
            ])
        )

        # Retain the current number of connected remote audio output players, if a new player
        #   is attached then time-out to allow for the remote audio output player
        #   buffers to empty to resynchronize audio.

        previous_num_players = len(self.players.keys())

        # Serve the audio stream until the mDNS browser is cancelled by the event loop or
        #   cancelled manually through `KeyboardInterrupt`

        while self.mdns_browser_event.is_set():

            try:

                # Manage / update the parameters of the digital audio stream

                # The `update` method opens a new audio stream with an updated interface and
                #   device settings and returns `True` when the stream is updated, closing the
                #   previous audio stream. If the interface and device settings are unchanged
                #   then the previous audio stream is retained.

                if self.audio_input.update(
                    interface=audera.dal.interfaces.get_interface(),
                    device=audera.dal.devices.get_device()
                ):

                    # Logging
                    self.logger.info(
                        ' '.join([
                            "Streaming {%s}-bit audio at {%s}" % (
                                self.audio_input.interface.bit_rate,
                                self.audio_input.interface.rate
                            ),
                            "with {%s} channel(s) from input device {%s (%s)}." % (
                                self.audio_input.interface.channels,
                                self.audio_input.device.name,
                                self.audio_input.device.index
                            )
                        ])
                    )

                    # Timout to allow for the remote audio output player buffers to empty
                    #   when a new audio stream is opened.

                    await asyncio.sleep(audera.TIME_OUT)

                # Retain the current connected remote audio output players for broadcasting
                players = copy.copy(self.players)

                # Timout to allow for the remote audio output player buffers to empty
                #   when a new player is attached since the previous broadcast. By allowing
                #   the buffers to empty, no player will try to play pre-buffered audio out of
                #   sync with the other players.

                if len(players.keys()) > previous_num_players:

                    # Logging
                    self.logger.info(
                        ''.join([
                            "Allowing remote audio output player buffers to drain.",
                            " Restarting the audio stream in %.2f [sec]." % (
                                audera.TIME_OUT
                            )
                        ])
                    )

                    # Reset the number of audio players
                    previous_num_players = len(players.keys())

                    await asyncio.sleep(audera.TIME_OUT)

                # Update the number of remote audio output players when a player is detached since
                #   the previous broadcast.

                if len(players.keys()) < previous_num_players:
                    previous_num_players = len(players.keys())

                # Read the next audio data chunk from the audio stream
                chunk = self.audio_input.stream.read(
                    self.audio_input.interface.chunk,
                    exception_on_overflow=False
                )

                # Convert the audio data chunk to a timestamped packet, including the length of
                #   the packet as well as the packet terminator.

                # Assign the timestamp as the target playback time accounting for a fixed playback
                #   delay from the current time on the server

                length = struct.pack(">I", len(chunk))
                target_play_time = struct.pack(
                    "d",
                    self.get_playback_time()
                )
                packet = (
                    length  # 4 bytes
                    + target_play_time  # 8 bytes
                    + chunk
                    + audera.PACKET_TERMINATOR  # 4 bytes
                    + audera.NAME.encode()  # 6 bytes
                    + audera.PACKET_ESCAPE  # 1 byte
                    + audera.PACKET_ESCAPE  # 1 byte
                )

                # Broadcast the packet to the players concurrently and drain the writer with timeout
                #   for flow control, disconnecting any / all players that are too slow

                results = await asyncio.gather(
                    *[
                        self.broadcast(
                            writer=writer,
                            packet=packet
                        ) for writer in players.values()
                    ],
                    return_exceptions=True
                )

                # Detach disconnected players
                for address, result in zip(players.keys(), results):
                    if result is False and address in self.players:

                        player = audera.dal.players.get_player_by_address(address)
                        player = audera.dal.players.disconnect(player.uuid)

                        del self.players[address]

                        # Logging
                        self.logger.info(
                            'Remote audio output player {%s (%s)} detached.' % (
                                player.name,
                                player.uuid.split('-')[0]  # Short uuid of the player
                            )
                        )

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

            except (
                asyncio.CancelledError,  # Streamer services cancelled
                KeyboardInterrupt  # Streamer services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'The audio stream was cancelled.'
                )

                # Exit the loop
                break

            except OSError as e:  # All other streamer communication I / O errors

                # Logging
                self.logger.error(
                    '[%s] %s.' % (
                        type(e).__name__, str(e)
                    )
                )
                self.logger.info(
                    ''.join([
                        "The audio stream capture encountered",
                        " an error, retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

        # Close the audio stream
        self.audio_input.stream.stop_stream()
        self.audio_input.stream.close()
        self.audio_input.port.terminate()

    async def broadcast(
        self,
        writer: asyncio.StreamWriter,
        packet: bytes
    ) -> bool:
        """ Broadcasts a timestamped audio stream packet to all connected remote audio output
        players.

        Parameters
        ----------
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the player used to write the
                audio stream to the player over a TCP connection.
        packet: `bytes`
            The timestamped audio data chunk.
        """

        # Broadcast the packet to the remote audio output player and drain the writer
        #   with timeout for flow control, disconnecting the player if it is too slow

        try:
            writer.write(packet)
            await writer.drain()
        except (
            asyncio.TimeoutError,  # Player communication timed-out
            ConnectionResetError,  # Player disconnected
            ConnectionAbortedError,  # Player aborted the connection
        ):

            # Close the connection
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # Player disconnected
                ConnectionAbortedError,  # Player aborted the connection
            ):
                pass

            return False
        return True

    async def stop_services(self):
        """ Stops the async `micro-services`. """
        self.mdns_browser_event.clear()

    async def start_services(self):
        """ Runs the async mDNS service, time-synchronization service, multi-player
        synchronization service and the audio stream service.
        """

        # Schedule the mDNS service
        mdns_browser = asyncio.create_task(self.mdns_browser())

        # Schedule the time-synchronization service
        ntp_synchronizer = asyncio.create_task(self.ntp_synchronizer())

        # Schedule the multi-player synchronization server
        multi_player_synchronizer = asyncio.create_task(self.multi_player_synchronizer())

        # Schedule the audio stream service
        audio_streamer = asyncio.create_task(self.audio_streamer())

        services = [
            mdns_browser,
            ntp_synchronizer,
            multi_player_synchronizer,
            audio_streamer
        ]

        # Run services
        try:
            while services:
                done, services = await asyncio.wait(
                    services,
                    return_when=asyncio.FIRST_COMPLETED
                )

                done: set[asyncio.Future]
                services: set[asyncio.Future]

                for task in done:
                    if task.exception():

                        # Logging
                        self.logger.error(
                            '[%s] An unhandled exception was raised. %s.' % (
                                type(task.exception()).__name__,
                                task.exception()
                            )
                        )

        # Wait for services to complete
        finally:
            await asyncio.gather(
                *services,
                return_exceptions=True
            )

    async def run(self):
        """ Starts all async streamer `micro-services`. """

        # Logging
        for line in audera.LOGO:
            self.logger.message(line)
        self.logger.message('')
        self.logger.message('')
        self.logger.message('    Running the streamer service.')
        self.logger.message('')
        self.logger.message(
            '    Audio stream address: {%s:%s}' % (
                self.server_ip_address,
                audera.STREAM_PORT
            ))
        self.logger.message(
            '    Multi-player synchronization address: {%s:%s}' % (
                self.server_ip_address,
                audera.PING_PORT
            ))
        self.logger.message('')

        # Start services
        await self.start_services()
