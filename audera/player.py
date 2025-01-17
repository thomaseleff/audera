""" Player service """

from typing import Union
import ntplib
import asyncio
import socket
import time
import struct
import platform
from collections import deque
import concurrent.futures
from zeroconf import Zeroconf, ServiceInfo
# import statistics

import audera


class Service():
    """ A `class` that represents the `audera` player service.

    The player service runs the following `micro-services` within an async event loop,
        - Remote audio output player mDNS broadcasting
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

        self.mac_address = audera.mdns.get_local_mac_address()
        self.player_ip_address = audera.mdns.get_local_ip_address()
        self.identity: audera.struct.identity.Identity = audera.struct.identity.Identity.from_config(
            audera.dal.identities.update(
                audera.struct.identity.Identity(
                    name=audera.struct.identity.generate_cool_name(),
                    uuid=audera.struct.identity.generate_uuid_from_mac_address(self.mac_address),
                    mac_address=self.mac_address,
                    address=self.player_ip_address
                )
            )
        )

        # Initialize player

        # The `get-or-create` method will either get the existing player or create a new player
        #   from an identity. This ensures that when the ip-address of a player changes, a new
        #   player is always created.

        self.player: audera.struct.player.Player = audera.struct.player.Player.from_config(
            audera.dal.players.get_or_create(self.identity)
        )

        # Initialize mDNS

        # The player broadcasts the `audera` mDNS service, `raop@{mac_address}._audera._tcp.local`,
        #   over the network. The broadcast properties include all the attributes of the player.

        self.mdns: audera.mdns.Broadcaster = audera.mdns.Broadcaster(
            logger=self.logger,
            zc=Zeroconf(),
            info=ServiceInfo(
                type_=audera.MDNS_TYPE,
                name='raop@%s.%s' % (
                    self.identity.mac_address.replace(':', ''),
                    audera.MDNS_TYPE
                ),  # (r)emote (a)udio (o)utput (p)layer
                addresses=[socket.inet_aton(self.identity.address)],
                port=audera.STREAM_PORT,
                weight=0,
                priority=0,
                properties={**self.player.to_dict(), **{"description": audera.DESCRIPTION}}
            )
        )
        self.streamer_ip_address: str = None

        # Initialize audio stream

        # The `get-interface` and `get-device` methods will either get the existing audio
        #   interface / output device or will create a new default audio interface / output device.
        #   The interface describes the parameters of the digital audio stream (format, sampling
        #   frequency, number of channels, and the number of frames for each broadcasted audio
        #   chunk). The device determines which hardware output device is playing the audio
        #   stream. The system default audio output device is automatically selected.

        self.audio_output = audera.struct.audio.Output(
            interface=audera.dal.interfaces.get_interface(),
            device=audera.dal.devices.get_device('output')
        )

        # Initialize playback session

        # The player supports only a single active playback session at a time. When a new streamer
        #   connects, the player automatically disconnects and closes the previous playback
        #   session.

        self.playback_session: Union[asyncio.StreamWriter, None] = None

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer()
        self.ntp_offset: float = 0.0
        self.streamer_offset: float = 0.0

        # Initialize buffer and rtt-history
        self.buffer: deque = deque()
        self.rtt_history: list[float] = []

        # Initialize process control parameters
        self.mdns_broadcaster_event: asyncio.Event = asyncio.Event()
        self.sync_event: asyncio.Event = asyncio.Event()
        self.buffer_event: asyncio.Event = asyncio.Event()

    def get_playback_time(self) -> float:
        """ Returns the playback time based on the current time, streamer time offset and
        network time protocol (ntp) server offset.
        """
        return float(time.time() + self.streamer_offset + self.ntp_offset)

    async def mdns_broadcaster(self):
        """ The async `micro-service` for the multi-cast DNS remote audio output player service
        broadcaster.

        The purpose of the mDNS broadcaster is to continuously transmit the remote audio output
        player service, including all the attributes of the player.

        The remote audio output player starts the mDNS service as an _independent_ task,
        until the task is either cancelled by the event loop or cancelled manually through
        `KeyboardInterrupt`.
        """
        loop = asyncio.get_running_loop()

        # Register and broadcast the mDNS service
        try:

            # The mDNS service must be started in a separate thread since zeroconf relies on
            #   its own async event loop.

            with concurrent.futures.ThreadPoolExecutor() as pool:
                mdns_broadcaster = loop.run_in_executor(pool, self.mdns.register)
                await asyncio.gather(mdns_broadcaster)

            # Set the mDNS broadcaster event to allow for the streamer synchronization,
            #   audio stream capture and playback `micro-services` to start.

            self.mdns_broadcaster_event.set()

            # Update the mDNS parameters with the latest player attributes continuously
            while self.mdns_broadcaster_event.is_set():

                # # Get the latest player attributes
                # self.player: audera.struct.player.Player = audera.struct.player.Player.from_config(
                #     audera.dal.players.get_or_create(self.identity)
                # )

                # # Update the mDNS service
                # self.mdns.update(
                #     info=ServiceInfo(
                #         type_=audera.MDNS_TYPE,
                #         name='raop@%s.%s' % (
                #             self.identity.mac_address.replace(':', ''),
                #             audera.MDNS_TYPE
                #         ),  # (r)emote (a)udio (o)utput (p)layer
                #         addresses=[socket.inet_aton(self.identity.address)],
                #         port=audera.STREAM_PORT,
                #         weight=0,
                #         priority=0,
                #         properties={**self.player.to_dict(), **{"description": audera.DESCRIPTION}}
                #     )
                # )

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

        # Close the mDNS service broadcaster
        self.mdns.unregister()

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

                    # Timeout
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

        The player attempts to start the audio stream receiver service, playback service, and
        stream synchronization service as _dependent_ tasks together.

        If all services complete successfully or lose connection to the streamer, then the event
        loop periodically attempts to reconnect to the streamer, restarting the services continuously
        with `audera.TIME_OUT` until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.

        The `audera` player service depends on the mDNS broadcaster.
        """

        # Wait for the mDNS broadcaster
        await self.mdns_broadcaster_event.wait()

        while self.mdns_broadcaster_event.is_set():
            try:

                # Schedule the audio stream synchronizer service
                streamer_synchronizer = asyncio.create_task(self.streamer_synchronizer())

                # Schedule the audio stream receiver server
                audio_receiver = asyncio.create_task(self.audio_receiver())

                # Schedule the audio stream playback service
                playback = asyncio.create_task(self.playback())

                await asyncio.gather(
                    streamer_synchronizer,
                    audio_receiver,
                    playback,
                    return_exceptions=True
                )

            except (
                asyncio.TimeoutError,  # Streamer communication timed-out
                ConnectionRefusedError  # Streamer refused the connection
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        "Waiting on a connection to the streamer,",
                        " retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

            except OSError as e:  # All other streamer communication I / O errors

                # Logging
                self.logger.error(
                    ''.join([
                        '[%s] [audera_player()] %s,' % (
                            type(e).__name__, str(e)
                        ),
                        " retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

            except (
                asyncio.CancelledError,  # Player services cancelled
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from streamer',
                        ' {%s} was cancelled.' % (
                            self.streamer_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

    async def streamer_synchronizer(self):
        """ The async streamer synchronizer `micro-service` for streamer time synchronization.

        The purpose of streamer time synchronization is to ensure that the time on the remote
        audio output player coincides with the streamer on the local network by regularly
        receiving the current time as a reference time source.
        """

        # Communicate with the streamer
        while True:

            # Measure round-trip time (rtt)
            try:
                await asyncio.wait_for(
                    self.sync(),
                    timeout=audera.TIME_OUT
                )

                # Set the streamer synchronizer event to allow for the audio stream capture
                #   and playback `micro-services` to start.

                self.sync_event.set()

            except (
                asyncio.TimeoutError,  # Streamer communication timed-out
                ConnectionRefusedError  # Streamer refused the connection
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        "Unable to synchronize with the streamer,",
                        " retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

            except (
                asyncio.CancelledError,  # Player services cancelled
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'Communication with streamer {%s} cancelled.' % (
                        self.streamer_ip_address
                    )
                )

                # Exit the loop
                break

            except OSError as e:  # All other streamer communication I / O errors

                # Logging
                self.logger.error(
                    '[%s] [streamer_synchronizer()] %s.' % (
                        type(e).__name__, str(e)
                    )
                )

                # rtt = None

            # # Perform audio playback playback delay adjustment
            # if rtt:

            #     # Add the rtt measurement to the history
            #     self.rtt_history.append(rtt)

            #     # Adjust the playback delay based on rtt and jitter
            #     #   Only adjust after the RTT_HISTORY_SIZE is met
            #     if len(self.rtt_history) >= audera.RTT_HISTORY_SIZE:
            #         mean_rtt = statistics.mean(self.rtt_history)
            #         jitter = statistics.stdev(self.rtt_history)

            #         # Logging
            #         self.logger.info(
            #             ''.join([
            #                 'Latency statistics',
            #                 ' (jitter {%.4f},' % (jitter),
            #                 ' avg. rtt {%.4f}).' % (mean_rtt)
            #             ])
            #         )

            #         # Decrease the playback delay for low jitter and rtt
            #         if (
            #             jitter < audera.LOW_JITTER
            #             and mean_rtt < audera.LOW_RTT
            #         ):
            #             new_buffer_time = max(
            #                 audera.MIN_PLAYBACK_DELAY, self.playback_delay - 0.05
            #             )

            #         # Increase the playback delay for high jitter or rtt
            #         elif (
            #             jitter > audera.HIGH_JITTER
            #             or mean_rtt > audera.HIGH_RTT
            #         ):
            #             new_buffer_time = min(
            #                 audera.MAX_PLAYBACK_DELAY, self.playback_delay + 0.05
            #             )

            #         # Otherwise maintain the current playback delay
            #         else:
            #             new_buffer_time = self.playback_delay

            #         # Update the playback delay and clear the rtt history
            #         self.playback_delay = new_buffer_time
            #         self.rtt_history.clear()

            #         # Logging
            #         self.logger.info(
            #             ''.join([
            #                 'Audio playback playback delay adjusted',
            #                 ' to %.2f [sec.].' % (
            #                     self.playback_delay
            #                 )
            #             ])
            #         )

            await asyncio.sleep(audera.PING_INTERVAL)

        # Stop all services
        await self.stop_services()

    async def sync(self):
        """ Synchronizes with the streamer and measures round-trip time (rtt). """

        # Open the connection to the streamer
        reader, writer = await asyncio.open_connection(
            self.streamer_ip_address,
            audera.PING_PORT
        )

        # Record the start-time
        start_time = time.time() + self.ntp_offset

        # Ping the streamer
        writer.write(b"ping")
        await writer.drain()

        # Wait for return response containing the current time on the streamer for
        #   calculating time offset

        packet = await reader.read(8)  # 8 bytes
        timestamp = struct.unpack("d", packet)[0]
        current_time = time.time() + self.ntp_offset

        # Calculate round-trip time
        rtt = current_time - start_time

        # Logging
        self.logger.info(
            'Round-trip time (rtt) is %.4f [sec.].' % (rtt)
        )

        # Update the player local machine time offset from the streamer
        self.streamer_offset = timestamp - current_time

        self.logger.info(
            'The player time offset is %.7f [sec.].' % (
                self.streamer_offset
            )
        )

        # Close the connection
        writer.close()
        await writer.wait_closed()

        # return rtt

    async def audio_receiver(self):
        """ Starts the async server for audio receiving and buffering.

        The player attempts to start the server as a _dependent_ tasks, receiving continuous
        connections with streamers forever until the task completes, is cancelled by the event
        loop or is cancelled manually through `KeyboardInterrupt`.

        The audio receiver service depends on the streamer synchronizer.
        """

        # Wait for the streamer synchronizer
        await self.sync_event.wait()

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
                receive the audio stream from the streamer.
        writer: `asyncio.StreamWriter`
            The unused asynchronous network stream writer passed from `asyncio.start_server()`.
        """

        # Retrieve the streamer ip-address
        self.streamer_ip_address, _ = writer.get_extra_info('peername')

        # Logging
        self.logger.info(
            'Streamer {%s} connected.' % (
                self.streamer_ip_address
            )
        )

        # Clear any existing playback session
        if self.playback_session:

            # Close the connection
            self.playback_session.close()
            try:
                await self.playback_session.wait_closed()
            except (
                ConnectionResetError,  # Streamer disconnected
                ConnectionAbortedError  # Streamer aborted the connection
            ):
                pass

            # Logging
            self.logger.info('Closing the previous playback session.')

        # Retain the latest playback session
        self.playback_session = writer

        # Receive audio stream
        while self.playback_session == writer:
            try:

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
                self.buffer.append(packet)

                # Trigger playback
                if len(self.buffer) >= audera.BUFFER_SIZE:
                    self.buffer_event.set()

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

            except (
                asyncio.TimeoutError,  # Streamer communication timed-out
                ConnectionResetError,  # Streamer disconnected
                ConnectionAbortedError  # Streamer aborted the connection
            ):

                # Logging
                self.logger.info(
                    'Streamer {%s} disconnected.' % (
                        self.streamer_ip_address
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # Player services cancelled
                asyncio.IncompleteReadError,  # Player incomplete read
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from streamer',
                        ' {%s} was cancelled.' % (
                            self.streamer_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

        # Clear the connection
        if self.playback_session:
            self.streamer_ip_address = None
            self.playback_session = None

        # Close the connection
        writer.close()
        try:
            await writer.wait_closed()
        except (
            ConnectionResetError,  # Streamer disconnected
            ConnectionAbortedError  # Streamer aborted the connection
        ):
            pass

    async def playback(self):
        """ Plays a timestamped audio stream packet from the playback buffer, discarding incomplete
        or late packets.

        The player attempts to start the audio stream playback service as a _dependent_ task along
        with the receive stream service and the handle communication service.

        The audio stream playback service depends on the streamer synchronizer.
        """

        # Wait for the streamer synchronizer
        await self.sync_event.wait()

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

        while self.sync_event.is_set():

            try:

                # Wait for enough packets in the buffer queue, timeout if the buffer is not
                #   populating to yield to other tasks in the event loop

                await asyncio.wait_for(
                    self.buffer_event.wait(),
                    timeout=audera.TIME_OUT
                )

                # Parse the audio stream packet from the buffer queue
                while self.buffer:

                    # Set the playback state of the remote audio output player
                    self.player = audera.dal.players.play(self.player.uuid)

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

                    packet = self.buffer.popleft()

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
                        continue

                    # Calculate the time to wait until the target playback time
                    sleep_time = target_play_time - playback_time

                    # Sleep until the target playback time
                    if sleep_time >= 0:
                        await asyncio.sleep(sleep_time)

                        # Play the audio stream data
                        self.audio_output.stream.write(chunk)

                # Play silence when the buffer is empty
                self.audio_output.stream.write(self.audio_output.silent_chunk)

                # Reset the buffer event when the buffer is empty
                if not self.buffer:
                    self.buffer_event.clear()

                # Set the playback state of the remote audio output player
                self.player = audera.dal.players.stop(self.player.uuid)

            except asyncio.TimeoutError:  # Audio playback buffer queue is empty

                # Reset the buffer and the buffer event
                self.buffer.clear()
                self.buffer_event.clear()

            except (
                asyncio.CancelledError,  # Player services cancelled
                KeyboardInterrupt  # Player services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from streamer',
                        ' {%s} was cancelled.' % (
                            self.streamer_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

            except OSError as e:  # All other streamer communication I / O errors

                # Logging
                self.logger.error(
                    '[%s] [playback()] %s.' % (
                        type(e).__name__, str(e)
                    )
                )

                # Exit the loop
                break

        # Close audio services
        self.audio_output.stream.stop_stream()
        self.audio_output.stream.close()
        self.audio_output.port.terminate()

    async def stop_services(self):
        """ Stops the async `micro-services`. """
        self.mdns_broadcaster_event.clear()
        self.sync_event.clear()
        self.buffer_event.clear()

    async def start_services(self):
        """ Runs the async mDNS broadcaster service, time-synchronization service, shairport-sync
        player service, and the `audera` player service.
        """

        # Schedule the mDNS broadcaster service
        mdns_broadcaster = asyncio.create_task(self.mdns_broadcaster())

        # Schedule the time-synchronization service
        ntp_synchronizer = asyncio.create_task(self.ntp_synchronizer())

        # Schedule the shairport-sync player service
        shairport_sync_player = asyncio.create_task(self.shairport_sync_player())

        # Schedule the `audera` player service
        audera_player = asyncio.create_task(self.audera_player())

        services = [
            mdns_broadcaster,
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
        """ Starts all async remote audio output player `micro-services`. """

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
