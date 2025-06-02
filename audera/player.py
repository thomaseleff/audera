""" Player service """

import asyncio
import time
import struct
from zeroconf import Zeroconf

import audera


class Service():
    """ A `class` that represents the `audera` remote audio output player service.

    The player service runs the following tasks within an async event loop,
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
        #   identities are only considered to be the same if they share the same mac address and
        #   ip-address. Finally, the name and uuid of an identity are immutable, when an identity is updated
        #   the same name and uuid are always retained.

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

        # The `update` method will either get the existing player, create a new player or
        #   update an existing player from the identity.

        self.player: audera.struct.player.Player = audera.dal.players.update_identity(self.identity)

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

        # Initialize audio stream playback

        # The `get-interface` and `get-device` methods will either get the existing audio
        #   interface / output device or will create a new default audio interface / output device.
        #   The interface describes the parameters of the digital audio stream (format, sampling
        #   frequency, number of channels, and the number of frames for each broadcasted audio
        #   chunk). The device determines which hardware output device is playing the audio
        #   stream. The system default audio output device is automatically selected.

        self.audio_output = audera.devices.Output(
            logger=self.logger,
            interface=audera.dal.interfaces.get_interface(),
            device=audera.dal.devices.get_device('output'),
            buffer_size=audera.BUFFER_SIZE,
            playback_timing_tolerance=audera.PLAYBACK_TIMING_TOLERANCE
        )

        # Initialize time synchronization
        self.rtt: float = 0.0

        # Initialize process control parameters
        self.mdns_broadcaster_event: asyncio.Event = asyncio.Event()
        self.sync_event: asyncio.Event = asyncio.Event()
        self.buffer_event: asyncio.Event = asyncio.Event()

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
            if audera.platform.NAME not in ['dietpi', 'linux', 'darwin']:

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

                # Logging
                self.logger.info(
                    'The shairport-sync service was cancelled.'
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
            audio_playback
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

            # Record the local start-time of time synchronization with the audio streamer
            #   as the timestamp of the request packet transmission, `t1`

            t1 = time.time()

            # Send the audio streamer the local start-time
            writer.write(
                struct.pack(
                    "d",
                    t1
                )
            )  # 8 bytes
            await writer.drain()

            # Read the network times from the audio streamer for calculating the time offset
            #   and network delay. The packet contains both the timestamp of the request packet
            #   reception, `t2` as well as the timestamp of the response packet transmission, `t3`

            packet = await reader.readexactly(16)  # 16 bytes

            # Record the local end-time of time synchronization with the audio streamer
            #   as the timestamp of the response packet reception, `t4`

            t4 = time.time()

            # Unpack the network times from the audio streamer
            t2, t3 = struct.unpack("!dd", packet)

            # Update the player local machine time offset from the audio streamer
            self.audio_output.time_offset = ((t2 - t1) + (t3 - t4)) / 2

            # Update the round-trip time (rtt)
            self.rtt = (t4 - t1) - (t3 - t2)

            # Respond to the audio streamer with the audio streamer offset time on the remote audio output
            #   player and wait for the response to be received.

            writer.write(
                struct.pack(
                    "!dd",
                    self.audio_output.time_offset,
                    self.rtt
                )
            )  # 16 bytes
            await writer.drain()

            # Logging
            self.logger.info(
                ''.join([
                    'Remote audio output player synchronized with audio streamer {%s}' % (
                        streamer_address
                    ),
                    ' with round-trip time (rtt) %.4f [sec.] and time offset %.7f [sec.].' % (
                        self.rtt,
                        self.audio_output.time_offset
                    )
                ])
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
                await self.audio_output.buffer.put(packet)

                # Trigger audio stream playback
                if self.audio_output.buffer.qsize() == audera.BUFFER_SIZE:
                    self.buffer_event.set()

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
            self.audio_output.clear_buffer()
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

        # Play the audio stream from the playback buffer until audio playback is cancelled
        #   by the event loop or cancelled manually through `KeyboardInterrupt`

        self.audio_output.start()

        # Manage / update the parameters of the digital audio stream
        try:
            while True:

                # The `update` method opens a new audio stream with an updated interface and
                #   device settings and returns `True` when the stream is updated, closing the
                #   previous audio stream. If the interface and device settings are unchanged
                #   then the previous audio stream is retained.

                if self.audio_output.update(
                    interface=audera.dal.interfaces.get_interface(),
                    device=audera.dal.devices.get_device('output')
                ):

                    # Clear the buffer
                    self.audio_output.clear_buffer()

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

                    # Restart the audio stream
                    self.audio_output.start()

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

        except OSError as e:  # All other streamer communication I / O errors

            # Logging
            self.logger.error(
                '[%s] [audio_playback()] %s.' % (
                    type(e).__name__, str(e)
                )
            )
            self.logger.error(
                    "The audio stream playback encountered an error."
            )

        except (
            asyncio.CancelledError,  # Player services cancelled
            KeyboardInterrupt  # Player services cancelled manually
        ):

            # Logging
            self.logger.info(
                'The audio stream playback was cancelled.'
            )

        finally:

            # Set the playback state of the remote audio output player
            self.player = audera.dal.players.stop(self.player.uuid)

            # Reset the buffer and the buffer event
            self.audio_output.clear_buffer()
            self.buffer_event.clear()

            # Close the audio services
            self.audio_output.close()

    async def stop_services(self):
        """ Stops the async tasks. """
        self.mdns_broadcaster_event.clear()
        self.sync_event.clear()
        self.buffer_event.clear()

    async def start_services(self):
        """ Runs the async time-synchronization service, shairport-sync player service, and the `audera`
        player service.
        """

        # Schedule the shairport-sync player service
        shairport_sync_player = asyncio.create_task(self.shairport_sync_player())

        # Schedule the `audera` player service
        audera_player = asyncio.create_task(self.audera_player())

        services = [
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
