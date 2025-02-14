""" Player service """

import ntplib
import asyncio
import time
import struct
import platform
# from collections import deque
from zeroconf import Zeroconf

import audera


class Service():
    """ A `class` that represents the `audera` remote audio output player service.

    The player service runs the following tasks within an async event loop,
        - Network time protocol (ntp) synchronization
        - Shairport-sync remote audio output player service for `airplay` connectivity
        - Audera remote audio output player service for `audera` connectivity

    The player service can be run from the command-line,

    ``` bash
    audera run player
    ```

    Or, through a Python session,

    ``` python
    import asyncio
    import audera

    if __name__ == '__main__':
        asyncio.run(audera.player.Service().run())
    ```

    """

    def __init__(self):
        """ Initializes an instance of the `audera` player service. """

        # Logging
        self.logger = audera.logging.get_player_logger()

        # Initialize identity

        # The `update` method will either get the existing identity, create a new identity or
        #   update the existing identity with new network interface settings. Unlike other
        #   `audera` structure objects, where equality is based on every object attribute,
        #   identities are only considered to be the same if they share the same uuid and
        #   mac address. Finally, the name of an identity is immutable, when an identity is updated
        #   the same name is always retained.

        self.mac_address = audera.netifaces.get_local_mac_address()
        self.player_ip_address = audera.netifaces.get_local_ip_address()
        self.identity: audera.struct.identity.Identity = audera.dal.identities.update(
            audera.struct.identity.Identity(
                name=audera.struct.identity.generate_cool_name(),
                uuid=audera.struct.identity.generate_uuid_from_mac_address(self.mac_address),
                mac_address=self.mac_address,
                address=self.player_ip_address
            )
        )

        # Initialize player

        # The `get-or-create` method will either get the existing player or create a new player
        #   from an identity. This ensures that when the ip-address of a player changes, a new
        #   player is always created.

        self.player: audera.struct.player.Player = audera.struct.player.Player.from_config(
            audera.dal.players.get_or_create(self.identity)
        )

        # Initialize playback session

        # The player supports only a single active playback session at a time. When a new streamer
        #   connects, the player automatically disconnects and closes the previous playback
        #   session.

        self.playback_session: audera.sessions.Playback = audera.sessions.Playback()

        # Initialize mDNS

        # The player broadcasts the `audera` mDNS service, `raop@{mac_address}._audera._tcp.local`,
        #   over the network. The broadcast properties include all the attributes of the player.

        self.mdns: audera.mdns.PlayerBroadcaster = audera.mdns.PlayerBroadcaster(
            logger=self.logger,
            zc=Zeroconf(),
            player=self.player,
            service_type=audera.MDNS_TYPE,
            service_description=audera.DESCRIPTION,
            service_port=audera.STREAM_PORT
        )

        # Initialize audio stream

        # The `get-interface` and `get-device` methods will either get the existing audio
        #   interface / output device or will create a new default audio interface / output device.
        #   The interface describes the parameters of the digital audio stream (format, sampling
        #   frequency, number of channels, and the number of frames for each broadcasted audio
        #   chunk). The device determines which hardware output device is playing the audio
        #   stream. The system default audio output device is automatically selected.

        self.audio_output = audera.devices.Output(
            interface=audera.dal.interfaces.get_interface(),
            device=audera.dal.devices.get_device('output')
        )

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer(server='pool.ntp.org')
        self.ntp_offset: float = 0.0
        self.streamer_offset: float = 0.0

        # Initialize buffer
        self.buffer: asyncio.Queue = asyncio.Queue(audera.BUFFER_SIZE)

        # Initialize process control parameters
        self.mdns_broadcaster_event: asyncio.Event = asyncio.Event()
        self.sync_event: asyncio.Event = asyncio.Event()
        self.buffer_event: asyncio.Event = asyncio.Event()

    def get_playback_time(self) -> float:
        """ Returns the playback time based on the current time, streamer time offset and
        network time protocol (ntp) server offset.
        """
        return float(time.time() + self.streamer_offset + self.ntp_offset)

    async def ntp_synchronizer(self):
        """ The async `micro-service` for network time protocol (ntp) synchronization.

        The purpose of ntp synchronization is to ensure that the time on the player coincides with
        all `audera` streamers on the local network by regularly synchronizing the clocks with a
        reference time source.

        The player attempts to start the time-synchronization service as an _independent_ task,
        restarting the service forever until the task is either cancelled by the event loop or
        cancelled manually through `KeyboardInterrupt`.
        """

        while True:
            try:

                # Update the local machine time offset from the network time protocol (ntp) server
                self.ntp_offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'The player ntp time offset is %.7f [sec.].' % (
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
                asyncio.CancelledError,  # Player services cancelled
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'Communication with the npt server {%s} cancelled.' % (
                        self.ntp.server
                    )
                )

                # Exit the loop
                break

    async def shairport_sync_player(self):
        """ The async `micro-service` for the shairport-sync remote audio output player
        service that supports audio receiving, playback and synchronization from / with
        `airplay` streamers.

        The purpose of the shairport-sync player is to allow for connectivity with the remote
        audio output player via `airplay` streamers as an alternative to the `audera` streamer.

        The player attempts to start the shairport-sync service as an _independent_ task once.
        If the operating system of the player is not compatible or the service fails to start, then
        the task completes without starting the shairport-sync service.

        If the shairport-sync service is started successfully, then the task periodically checks
        the status of the service, restarting the service continuously with `audera.TIME_OUT` until
        the task is either cancelled by the event loop or cancelled manually through
        `KeyboardInterrupt`.
        """

        while True:

            # Check the operating-system
            operating_system = platform.system()
            if operating_system not in ['Linux', 'Darwin']:

                # Logging
                self.logger.warning(
                    ''.join([
                        'The shairport-sync service is only available',
                        ' on Linux and MacOS.'
                    ])
                )

                # Exit the loop
                break

            # Start the shairport-sync service as a subprocess
            process = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "start", "shairport-sync",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()

            if process.returncode == 0:

                # Logging
                self.logger.info(
                    'The shairport-sync service started successfully.'
                )

            else:

                # Logging
                self.logger.error(
                    'The shairport-sync service failed to start.'
                )

                if stderr:

                    # Logging
                    self.logger.error(
                        '[%s] [shairport_sync_player()] %s.' % (
                            'CalledProcessError', stderr.decode().strip()
                        )
                    )

                # Exit the loop
                break

            try:

                # Monitor the status of the shairport-sync service subprocess
                while True:

                    status_process = await asyncio.create_subprocess_exec(
                        "systemctl", "is-active", "--quiet", "shairport-sync"
                    )
                    await status_process.wait()

                    if status_process.returncode != 0:

                        # Logging
                        self.logger.info(
                            ''.join([
                                "The shairport-sync service encountered",
                                " an error, retrying in %.2f [sec.]." % (
                                    audera.TIME_OUT
                                )
                            ])
                        )

                    # Wait, yielding to other tasks in the event loop
                    await asyncio.sleep(audera.TIME_OUT)

            except (
                asyncio.CancelledError,  # Player services cancelled
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Stop the shairport-sync service
                await asyncio.create_subprocess_exec(
                    "sudo", "systemctl", "stop", "shairport-sync"
                )

                # Exit the loop
                break

    async def audera_player(self):
        """ The async `micro-service` for the audera remote audio output player service that
        supports audio receiving, playback, and synchronization from / with `audera` streamers.

        The player attempts to start the audio streamer synchronization service, audio stream receiver
        service, and playback service as _dependent_ tasks together.

        If all services complete successfully or lose connection to the audio streamer, then the event
        loop periodically attempts to reconnect to the audio streamer, restarting the services continuously
        with `audera.TIME_OUT` until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Schedule the mDNS broadcaster service
        mdns_broadcaster = asyncio.create_task(self.mdns_broadcaster())

        # Schedule the audio stream synchronizer server
        streamer_synchronizer = asyncio.create_task(self.streamer_synchronizer())

        # Schedule the audio stream receiver server
        audio_receiver = asyncio.create_task(self.audio_receiver())

        # Schedule the audio stream playback service
        audio_playback = asyncio.create_task(self.audio_playback())

        await asyncio.gather(
            mdns_broadcaster,
            streamer_synchronizer,
            audio_receiver,
            audio_playback,
            return_exceptions=True
        )

    async def mdns_broadcaster(self):
        """ Multi-cast DNS remote audio output player service broadcaster.

        The purpose of the mDNS broadcaster is to continuously transmit the remote audio output
        player service, including all the attributes of the player.

        The remote audio output player starts the mDNS service as an _independent_ task,
        until the task is either cancelled by the event loop or cancelled manually through
        `KeyboardInterrupt`.
        """

        # Register and broadcast the mDNS service
        try:
            await self.mdns.register()

            # Set the mDNS broadcaster event to allow for the audio streamer synchronization,
            #   audio stream capture and playback services to start.

            self.mdns_broadcaster_event.set()

            # Update the mDNS parameters with the latest player attributes continuously
            while self.mdns_broadcaster_event.is_set():

                # Get the latest player attributes
                self.player: audera.struct.player.Player = audera.dal.players.get_player(self.player.uuid)

                # Update the mDNS service
                self.mdns.update(self.player)

                # Wait, yielding to other tasks in the event loop
                await asyncio.sleep(audera.TIME_OUT)

        except (
            asyncio.CancelledError,  # mDNS-services cancelled
            KeyboardInterrupt,  # mDNS-services cancelled manually
        ):

            # Logging
            self.logger.info(
                'Broadcasting mDNS service {%s} cancelled.' % (
                    audera.MDNS_TYPE
                )
            )

        finally:

            # Close the mDNS service broadcaster
            self.mdns.unregister()

            # Stop all services
            await self.stop_services()

    async def streamer_synchronizer(self):
        """ The async server for audio streamer synchronization.

        The purpose of streamer time synchronization is to ensure that the time on the remote
        audio output player coincides with the audio streamer on the local network by regularly
        receiving the current time as a reference time source.

        The player attempts to start the server as a _dependent_ tasks, receiving continuous
        connections with audio streamers forever until the task completes, is cancelled by the event
        loop or is cancelled manually through `KeyboardInterrupt`.

        The audio streamer synchronizer depends on the mDNS broadcaster.
        """

        # Wait for the mDNS broadcaster
        await self.mdns_broadcaster_event.wait()

        # Communicate with the audio streamer until the mDNS broadcaster is cancelled by the event loop
        #   or cancelled manually through `KeyboardInterrupt`

        while self.mdns_broadcaster_event.is_set():

            # Initialize the audio streamer synchronizer
            streamer_synchronizer = await asyncio.start_server(
                client_connected_cb=(
                    lambda reader, writer: self.streamer_synchronizer_callback(
                        reader=reader,
                        writer=writer
                    )
                ),
                host='0.0.0.0',  # No specific destination address
                port=audera.PING_PORT
            )

            # Serve streamer connections forever
            async with streamer_synchronizer:
                await asyncio.gather(streamer_synchronizer.serve_forever())

    async def streamer_synchronizer_callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ The async streamer synchronizer callback that is started when an audio streamer connects
        to `https://0.0.0.0:{audera.PING_PORT}`.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader passed from `asyncio.start_server()` used to
                synchronize with the audio streamer.
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from `asyncio.start_server()` used to
                synchronize with the audio streamer.
        """

        # Retrieve the audio streamer ip-address
        streamer_address, _ = writer.get_extra_info('peername')

        # Manage the audio playback session and audio streamer connection
        if self.playback_session.streamer_connection.streamer_address != streamer_address:

            # Logging
            self.logger.info(
                'Audio streamer {%s} connected.' % (
                    streamer_address
                )
            )

            # Retain the latest audio streamer ip-address
            await self.playback_session.attach_streamer(streamer_address)

        # Communicate with the audio streamer
        try:

            # Read the current time from the audio streamer for calculating the time offset
            packet = await reader.read(8)  # 8 bytes
            timestamp = struct.unpack("d", packet)[0]

            # Update the player local machine time offset from the audio streamer
            self.streamer_offset = timestamp - time.time() + self.ntp_offset

            # Respond to the audio streamer with the audio streamer offset time on the remote audio output
            #   player and wait for the response to be received.

            writer.write(
                struct.pack(
                    "d",
                    self.streamer_offset
                )
            )  # 8 bytes
            await writer.drain()

            # Logging
            self.logger.info(
                'Remote audio output player synchronized with audio streamer {%s} with time offset %.7f [sec.].' % (
                    streamer_address,
                    self.streamer_offset
                )
            )

            # Set the audio streamer synchronizer event to allow for the audio stream capture
            #   and playback services to start.

            self.sync_event.set()

        except (
            asyncio.TimeoutError,  # Streamer communication timed-out
            ConnectionResetError,  # Streamer disconnected
            ConnectionAbortedError  # Streamer aborted the connection
        ):

            # Logging
            self.logger.info(
                'Audio streamer {%s} disconnected.' % (
                    streamer_address
                )
            )

        except (
            asyncio.CancelledError,  # Player services cancelled
            asyncio.IncompleteReadError,  # Player incomplete read
            KeyboardInterrupt  # Player services cancelled manually
        ):

            # Logging
            self.logger.info(
                ''.join([
                    'Multi-player synchronization with audio streamer',
                    ' {%s} was cancelled.' % (
                        streamer_address
                    )
                ])
            )

        except OSError as e:

            # Logging
            self.logger.error(
                '[%s] [streamer_synchronizer_callback()] %s.' % (
                    type(e).__name__, str(e)
                )
            )

        finally:

            # Close the connection
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # Streamer disconnected
                ConnectionAbortedError  # Streamer aborted the connection
            ):
                pass

            # Stop synchronization and playback services
            self.sync_event.clear()

    async def audio_receiver(self):
        """ The async server for audio receiving and buffering.

        The player attempts to start the server as a _dependent_ tasks, receiving continuous
        connections with audio streamers forever until the task completes, is cancelled by the event
        loop or is cancelled manually through `KeyboardInterrupt`.

        The audio receiver service depends on the audio streamer synchronizer.
        """

        # Wait for the audio streamer synchronizer
        await self.sync_event.wait()

        # Receive the audio stream from the audio streamer until the streamer synchronizer is cancelled by
        #   the event loop or cancelled manually through `KeyboardInterrupt`

        while self.sync_event.is_set():

            # Initialize the audio receiver
            audio_receiver = await asyncio.start_server(
                client_connected_cb=(
                    lambda reader, writer: self.audio_receiver_callback(
                        reader=reader,
                        writer=writer
                    )
                ),
                host='0.0.0.0',  # No specific destination address
                port=audera.STREAM_PORT
            )

            # Serve streamer connections forever
            async with audio_receiver:
                await asyncio.gather(audio_receiver.serve_forever())

    async def audio_receiver_callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ The async audio receiver callback that is started when an audio streamer connects
        to `https://0.0.0.0:{audera.STREAM_PORT}`.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader passed from `asyncio.start_server()` used to
                receive the audio stream from the audio streamer.
        writer: `asyncio.StreamWriter`
            The unused asynchronous network stream writer passed from `asyncio.start_server()`.
        """

        # Retrieve the streamer ip-address
        streamer_address, _ = writer.get_extra_info('peername')

        # Retain the latest playback session
        await self.playback_session.attach_stream_writer(streamer_address, writer)

        # Receive audio stream
        try:
            while self.playback_session.streamer_connection.streamer_address == streamer_address:

                # Parse audio stream packet
                packet = await reader.readuntil(
                    separator=(
                        audera.PACKET_TERMINATOR  # 4 bytes
                        + audera.NAME.encode()  # 6 bytes
                        + audera.PACKET_ESCAPE  # 1 byte
                        + audera.PACKET_ESCAPE  # 1 byte
                    )
                )

                # Add audio stream packet to the buffer
                await self.buffer.put(packet)

                # Trigger audio stream playback
                self.buffer_event.set()

                # Yield to other tasks in the event loop
                # await asyncio.sleep(0)

        except (
            asyncio.TimeoutError,  # Streamer communication timed-out
            ConnectionResetError,  # Streamer disconnected
            ConnectionAbortedError  # Streamer aborted the connection
        ):

            # Logging
            self.logger.info(
                'Audio streamer {%s} disconnected.' % (
                    streamer_address
                )
            )

        except (
            asyncio.CancelledError,  # Player services cancelled
            asyncio.IncompleteReadError,  # Player incomplete read
            KeyboardInterrupt  # Player services cancelled manually
        ):

            # Logging
            self.logger.info(
                ''.join([
                    'The audio stream from audio streamer',
                    ' {%s} was cancelled.' % (
                        streamer_address
                    )
                ])
            )

        finally:

            # Close the playback session
            await self.playback_session.close()

            # Reset the buffer and the buffer event
            await self.buffer.join()
            self.buffer_event.clear()

    async def audio_playback(self):
        """ Plays a timestamped audio stream packet from the playback buffer, discarding incomplete
        or late packets.

        The player attempts to start the audio stream playback service as a _dependent_ task, until the
        task completes, is cancelled by the event loop or is cancelled manually through `KeyboardInterrupt`.

        The audio playback service depends on the audio receiver.
        """

        # Wait for the audio stream buffer event
        await self.buffer_event.wait()

        # Logging
        self.logger.info(
            ' '.join([
                "Playing {%s}-bit audio at {%s}" % (
                    self.audio_output.interface.bit_rate,
                    self.audio_output.interface.rate
                ),
                "with {%s} channel(s) through output device {%s (%s)}." % (
                    self.audio_output.interface.channels,
                    self.audio_output.device.name,
                    self.audio_output.device.index
                )
            ])
        )

        # Set the playback state of the remote audio output player
        self.player = audera.dal.players.play(self.player.uuid)

        # Play the audio stream from the playback buffer until the streamer synchronizer is cancelled
        #   by the event loop or cancelled manually through `KeyboardInterrupt`

        try:
            while self.buffer_event.is_set():

                # Wait for packets in the buffer queue, timeout if the buffer is not
                #   populating to yield to other tasks in the event loop

                # await asyncio.wait_for(
                #     self.buffer_event.wait(),
                #     timeout=audera.TIME_OUT
                # )

                # Manage / update the parameters of the digital audio stream

                # The `update` method opens a new audio stream with an updated interface and
                #   device settings and returns `True` when the stream is updated, closing the
                #   previous audio stream. If the interface and device settings are unchanged
                #   then the previous audio stream is retained.

                if self.audio_output.update(
                    interface=audera.dal.interfaces.get_interface(),
                    device=audera.dal.devices.get_device('output')
                ):

                    # Logging
                    self.logger.info(
                        ' '.join([
                            "Playing {%s}-bit audio at {%s}" % (
                                self.audio_output.interface.bit_rate,
                                self.audio_output.interface.rate
                            ),
                            "with {%s} channel(s) through output device {%s (%s)}." % (
                                self.audio_output.interface.channels,
                                self.audio_output.device.name,
                                self.audio_output.device.index
                            )
                        ])
                    )

                # Get the next audio stream packet from the buffer queue
                packet = await self.buffer.get()

                # Parse the timestamp and audio data from the packet, adding offset to adjust
                #   player side timestamps

                length = struct.unpack(">I", packet[:4])[0]
                target_play_time = struct.unpack("d", packet[4:12])[0]
                chunk = packet[12:-12]

                # Discard incomplete packets
                if len(chunk) != length:

                    # Logging
                    self.logger.warning(
                        'Incomplete packet with target playback time %.6f [sec.].' % (
                            target_play_time
                        )
                    )

                    # Signal the end of the buffer queue task
                    self.buffer.task_done()

                    continue

                # Discard late packets
                playback_time = self.get_playback_time()
                if playback_time > target_play_time:

                    # Logging
                    self.logger.warning(
                        'Late packet %.6f [sec.] with target playback time %.6f [sec.].' % (
                            target_play_time - playback_time,
                            target_play_time
                        )
                    )

                    # Signal the end of the buffer queue task
                    self.buffer.task_done()

                    continue

                # Calculate the time to wait until the target playback time
                sleep_time = target_play_time - playback_time

                # Sleep until the target playback time
                if sleep_time >= 0:
                    await asyncio.sleep(sleep_time)

                    # Play the audio stream data
                    self.audio_output.stream.write(chunk)

                # Signal the end of the buffer queue task
                self.buffer.task_done()

                # Play silence when the buffer is empty
                # self.audio_output.stream.write(self.audio_output.silent_chunk)

                # Reset the buffer event when the buffer is empty
                # if not self.buffer:
                #     self.buffer_event.clear()

                # Set the playback state of the remote audio output player
                # self.player = audera.dal.players.stop(self.player.uuid)

                # Yield to other tasks in the event loop
                # await asyncio.sleep(0)

        except (
            asyncio.CancelledError,  # Player services cancelled
            KeyboardInterrupt  # Player services cancelled manually
        ):

            # Logging
            self.logger.info(
                'The audio stream playback was cancelled.'
            )

            # Reset the buffer and the buffer event
            # self.buffer.clear()
            # self.buffer_event.clear()

            # Timeout
            # await asyncio.sleep(audera.TIME_OUT)

        except OSError as e:  # All other streamer communication I / O errors

            # Logging
            self.logger.error(
                '[%s] [audio_playback()] %s.' % (
                    type(e).__name__, str(e)
                )
            )

            # Reset the buffer and the buffer event
            # self.buffer.clear()
            # self.buffer_event.clear()

            # Timeout
            # await asyncio.sleep(audera.TIME_OUT)

        finally:

            # Set the playback state of the remote audio output player
            self.player = audera.dal.players.stop(self.player.uuid)

            # Reset the buffer and the buffer event
            await self.buffer.join()
            self.buffer_event.clear()

            # Close the audio services
            self.audio_output.stream.stop_stream()
            self.audio_output.stream.close()
            self.audio_output.port.terminate()

    async def stop_services(self):
        """ Stops the async tasks. """
        self.mdns_broadcaster_event.clear()
        self.sync_event.clear()
        self.buffer_event.clear()

    async def start_services(self):
        """ Runs the async time-synchronization service, shairport-sync player service, and the `audera`
        player service.
        """

        # Schedule the time-synchronization service
        ntp_synchronizer = asyncio.create_task(self.ntp_synchronizer())

        # Schedule the shairport-sync player service
        shairport_sync_player = asyncio.create_task(self.shairport_sync_player())

        # Schedule the `audera` player service
        audera_player = asyncio.create_task(self.audera_player())

        services = [
            ntp_synchronizer,
            shairport_sync_player,
            audera_player
        ]

        # Run services
        try:
            while services:
                done, services = await asyncio.wait(
                    services,
                    return_when=asyncio.FIRST_COMPLETED
                )

                done: set[asyncio.Task]
                services: set[asyncio.Task]

                for service in done:
                    if service.exception():

                        # Logging
                        self.logger.error(
                            '[%s] [%s()] %s.' % (
                                type(service.exception()).__name__,
                                service.get_coro().__name__,
                                service.exception()
                            )
                        )

        # Wait for services to complete
        finally:
            await asyncio.gather(
                *services,
                return_exceptions=True
            )

    async def run(self):
        """ Starts all async remote audio output player services. """

        # Logging
        for line in audera.LOGO:
            self.logger.message(line)
        self.logger.message('')
        self.logger.message('')
        self.logger.message('>>> Running the player service.')
        self.logger.message('')
        self.logger.message('    Player information')
        self.logger.message('')
        self.logger.message('        name    : %s' % self.player.name)
        self.logger.message('        uuid    : %s' % self.player.uuid)
        self.logger.message('        address : %s' % self.player.address)
        self.logger.message('')

        # Run services
        await self.start_services()
