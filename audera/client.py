""" Client-service """

import pyaudio
import ntplib
import asyncio
import socket
import platform
import time
import struct
from collections import deque
from zeroconf import Zeroconf
# import statistics

import audera


class Service():
    """ A `class` that represents the `audera` client-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` client-services. """

        # Logging
        self.logger = audera.logging.get_client_logger()

        # Initialize mDNS
        self.mdns: audera.mdns.Connection = audera.mdns.Connection(
            logger=self.logger,
            zc=Zeroconf(),
            type=audera.MDNS_TYPE,
            name=audera.MDNS_NAME,
            time_out=audera.TIME_OUT
        )
        self.server_ip_address: str = None
        self.stream_port: int = None
        self.ping_port: int = audera.PING_PORT

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer()
        self.ntp_offset: float = 0.0
        self.server_offset: float = 0.0

        # Initialize buffer and rtt-history
        self.buffer: deque = deque()
        self.buffer_event: asyncio.Event = asyncio.Event()
        self.rtt_history: list[float] = []

        # Initialize silent packet
        self.silent_data: bytes = b'\x00' * (
            audera.CHUNK * audera.CHANNELS * 2
        )

        # Initialize process control parameters
        self.mdns_connection_event: asyncio.Event = asyncio.Event()

    def get_playback_time(self) -> float:
        """ Returns the playback time based on the current time, server time offset and
        network time protocol (ntp) server offset.
        """
        return float(time.time() + self.server_offset + self.ntp_offset)

    async def start_mdns_services(self):
        """ Starts the async service for the multi-cast DNS service connection.

        The `server` attempts to connect the mDNS service as an
        _independent_ task, until the task is either cancelled by
        the event loop or cancelled manually through `KeyboardInterrupt`.
        """

        # Browse mDNS services and retain the ip-address of the server service
        info = self.mdns.browse()

        # Retain mDNS service settings
        if info:
            self.server_ip_address = socket.inet_ntoa(info.addresses[0])
            self.stream_port = info.port

            # Start all other `client` services
            self.mdns_connection_event.set()

        # Yield to other tasks in the event loop
        await asyncio.sleep(0)

    async def start_shairport_services(self):
        """ Starts async shairport-sync connectivity to Airplay
        streaming devices.

        The `client` attempts to start the shairport-sync service
        as an _independent_ task once. If the operating system of the
        `client` is not compatible or the service fails to start, then
        the task completes without starting the shairport-sync service.

        If the shairport-sync service is started successfully,
        then the task periodically checks the status of the service,
        restarting the service continuously with `audera.TIME_OUT` until
        the task is either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
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
                        '[%s] [start_shairport_services()] %s.' % (
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
                asyncio.CancelledError,  # Client-services cancelled
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Stop the shairport-sync service
                await asyncio.create_subprocess_exec(
                    "sudo", "systemctl", "stop", "shairport-sync"
                )

                # Exit the loop
                break

    async def start_time_synchronization(self):
        """ Starts the async service for time-synchronization.

        The `client` attempts to start the time-synchronization service
        as an _independent_ task, restarting the service forever until
        the task is either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Communicate with the server
        while True:

            try:

                # Update the client local machine time offset from the network
                #   time protocol (ntp) server
                self.ntp_offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'The client ntp time offset is %.7f [sec.].' % (
                        self.ntp_offset
                    )
                )

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

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

            except (
                asyncio.CancelledError,  # Client-services cancelled
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'Communication with the npt server {%s} cancelled.' % (
                        self.ntp.server
                    )
                )

                # Exit the loop
                break

            await asyncio.sleep(audera.SYNC_INTERVAL)

    async def receive_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ Receives the async audio stream from the server and
        adds on-time packets into the playback buffer queue,
        discarding late or incomplete packets.

        The `client` attempts to start the receive stream service
        as a _dependent_ task along with the playback stream and
        the handle communication service.

        If all services complete successfully or lose connection to
        the server, then the event loop periodically attempts to reconnect
        to the server, restarting the services continuously with `audera.TIME_OUT`
        until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader used to
                receive the audio stream from the server.
        writer: `asyncio.StreamWriter`
            The unused asynchronous network stream writer.
        """

        # Logging
        self.logger.info(
            ' '.join([
                "Receiving audio over PORT {%s} at RATE {%s}" % (
                    self.stream_port,
                    audera.RATE
                ),
                "with {%s} CHANNEL(s)." % (
                    audera.CHANNELS
                )
            ])
        )

        # Receive audio stream
        while self.mdns_connection_event.is_set():
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
                asyncio.TimeoutError,  # Server-communication timed-out
                ConnectionResetError,  # Server disconnected
                ConnectionAbortedError,  # Server aborted the connection
            ):

                # Logging
                self.logger.info(
                    'Server {%s} disconnected.' % (
                        self.server_ip_address
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # Client-services cancelled
                asyncio.IncompleteReadError,  # Client incomplete read
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from server',
                        ' {%s} was cancelled.' % (
                            self.server_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

        # Close the connection
        writer.close()
        try:
            await writer.wait_closed()
        except (
            ConnectionResetError,  # Server disconnected
            ConnectionAbortedError,  # Server aborted the connection
        ):
            pass

    async def playback_stream(self):
        """ Continuously play audio stream data from the playback buffer
        queue.

        The `client` attempts to start the playback stream service
        as a _dependent_ task along with the receive stream service and
        the handle communication service.

        If all services complete successfully or lose connection to
        the server, then the event loop periodically attempts to reconnect
        to the server, restarting the services continuously with `audera.TIME_OUT`
        until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Initialize PyAudio
        audio = pyaudio.PyAudio()

        # Initialize audio stream-playback
        stream = audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            output=True,
            frames_per_buffer=audera.CHUNK
        )

        # Play audio stream data
        while self.mdns_connection_event.is_set():
            try:

                # Wait for enough packets in the buffer queue,
                #   timeout if the buffer is not populating to
                #   yield to other tasks in the event loop
                await asyncio.wait_for(
                    self.buffer_event.wait(),
                    timeout=audera.TIME_OUT
                )

                # Parse the audio stream packet from the buffer queue
                while self.buffer:
                    packet = self.buffer.popleft()

                    # Parse the timestamp and audio data from the packet,
                    #   adding offset to adjust client-side timestamps
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
                        stream.write(chunk)

                # Play silence when the buffer is empty
                stream.write(self.silent_data)

                # Reset the buffer event when the buffer is empty
                if not self.buffer:
                    self.buffer_event.clear()

            except asyncio.TimeoutError:  # Audio playback buffer queue is empty

                # Logging
                self.logger.info(
                    'Server {%s} disconnected.' % (
                        self.server_ip_address
                    )
                )

                # Reset the buffer and the buffer event
                self.buffer.clear()
                self.buffer_event.clear()

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # Client-services cancelled
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from server',
                        ' {%s} was cancelled.' % (
                            self.server_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

            except OSError as e:  # All other server-communication I / O errors

                # Logging
                self.logger.error(
                    '[%s] [playback_stream()] %s.' % (
                        type(e).__name__, str(e)
                    )
                )

                # Exit the loop
                break

        # Close audio services
        stream.stop_stream()
        stream.close()
        audio.terminate()

    async def handle_communication(self):
        """ Receives async server-communication, measures round-trip time (rtt)
        and adjusts the audio playback playback delay.

        The `client` attempts to start the handle communication service
        as a _dependent_ task along with the receive stream service and the
        playback stream service.

        If all services complete successfully or lose connection to
        the server, then the event loop periodically attempts to reconnect
        to the server, restarting the services continuously with `audera.TIME_OUT`
        until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Communicate with the server
        while self.mdns_connection_event.is_set():

            # Measure round-trip time (rtt)
            try:
                await self.communicate()

            except asyncio.TimeoutError:  # Server-communication timed-out

                # Logging
                self.logger.info(
                    'Server {%s} disconnected.' % (
                        self.server_ip_address
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # Client-services cancelled
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'Communication with server {%s} cancelled.' % (
                        self.server_ip_address
                    )
                )

                # Exit the loop
                break

            except OSError as e:  # All other server-communication I / O errors

                # Logging
                self.logger.error(
                    '[%s] [handle_communication()] %s.' % (
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

    async def communicate(self):
        """ Communicates with the server and measures round-trip time (rtt). """

        # Initialize the connection to the ping-communication server
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                self.server_ip_address,
                self.ping_port
            ),
            timeout=audera.TIME_OUT
        )

        # Record the start-time
        start_time = time.time() + self.ntp_offset

        # Ping the server
        writer.write(b"ping")
        await writer.drain()

        # Wait for return response containing the current
        #   time on the server for calculating time offset
        packet = await reader.read(8)  # 8 bytes
        timestamp = struct.unpack("d", packet)[0]
        current_time = time.time() + self.ntp_offset

        # Calculate round-trip time
        rtt = current_time - start_time

        # Logging
        self.logger.info(
            'Round-trip time (rtt) is %.4f [sec.].' % (rtt)
        )

        # Update the client local machine time offset from the server
        self.server_offset = timestamp - current_time

        self.logger.info(
            'The client time offset is %.7f [sec.].' % (
                self.server_offset
            )
        )

        # Close the connection
        writer.close()
        await writer.wait_closed()

        # return rtt

    async def start_client_services(self):
        """ Starts the async services for audio streaming
        and client-communication with the server.

        The `client` attempts to start the receive stream service,
        playback stream service and handle communication service
        as _dependent_ tasks together.

        If all services complete successfully or lose connection to
        the server, then the event loop periodically attempts to reconnect
        to the server, restarting the services continuously with `audera.TIME_OUT`
        until the tasks are either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Wait for the mDNS connection
        await self.mdns_connection_event.wait()

        # Handle server-availability
        while self.mdns_connection_event.is_set():
            try:

                # Initialize the connection to the audio stream server
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.server_ip_address,
                        self.stream_port
                    ),
                    timeout=audera.TIME_OUT
                )

                # Initialize the audio stream capture service coroutine
                receive_stream = asyncio.create_task(
                    self.receive_stream(reader=reader, writer=writer)
                )

                # Initialize the audio stream playback service coroutine
                playback_stream = asyncio.create_task(
                    self.playback_stream()
                )

                # Initialize the ping-communication service coroutine
                handle_communication = asyncio.create_task(
                    self.handle_communication()
                )

                await asyncio.gather(
                    receive_stream,
                    playback_stream,
                    handle_communication,
                    return_exceptions=True
                )

            except (
                asyncio.TimeoutError,  # Server-communication timed-out
                ConnectionRefusedError  # Server refused the connection
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        "Waiting on a connection to the server,",
                        " retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

            except OSError as e:  # All other server-communication I / O errors

                # Logging
                self.logger.error(
                    ''.join([
                        '[%s] [start_client_services()] %s,' % (
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
                asyncio.CancelledError,  # Client-services cancelled
                KeyboardInterrupt  # Client-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    ''.join([
                        'The audio stream from server',
                        ' {%s} was cancelled.' % (
                            self.server_ip_address
                        )
                    ])
                )

                # Exit the loop
                break

    async def start_services(self):
        """ Runs the async shairport-sync service independently of the
        async services for audio streaming and client-communication.

        The `client` attempts to start the shairport-sync service,
        the time-synchronization service and the bundle of client
        services (receive stream service, playback stream service
        and handle communication service) as _independent_ tasks.
        """

        # Initialize the shairport-sync service

        #   The shairport-sync service is independent of the
        #       other `audera` client-services, and, is only
        #       applicable when running on Linux or MacOS.
        #   Creating the task outside of the `audera` start-
        #       services loop will allow the shairport-sync
        #       service task to run independently, and,
        #       for the shairport-sync service to only run
        #       on the applicable architecture.
        #   Finally, by running the shairport-sync service
        #       independently, the `audera` client can be used
        #       for creating multi-room audio systems that are
        #       compatible with Airplay without having to rely
        #       on the `audera` streaming server.

        start_shairport_services = asyncio.create_task(
            self.start_shairport_services()
        )

        # Initialize the mDNS service
        start_mdns_services = asyncio.create_task(
            self.start_mdns_services()
        )

        # Initialize the time-synchronization service
        start_time_synchronization_services = asyncio.create_task(
            self.start_time_synchronization()
        )

        # Initialize the `audera` client-services
        start_client_services = asyncio.create_task(
            self.start_client_services()
        )

        tasks = [
            start_shairport_services,
            start_mdns_services,
            start_time_synchronization_services,
            start_client_services
        ]

        # Run services
        while tasks:
            done, tasks = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            done: set[asyncio.Future]
            tasks: set[asyncio.Future]

            for task in done:
                if task.exception():

                    # Logging
                    self.logger.error(
                        '[%s] An unhandled exception was raised. %s.' % (
                            type(task.exception()).__name__,
                            task.exception()
                        )
                    )

        await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

    async def run(self):
        """ Starts all async client-services.
        """

        # Logging
        for line in audera.LOGO:
            self.logger.message(line)
        self.logger.message('')
        self.logger.message('')
        self.logger.message('    Running the client-service.')
        self.logger.message('')
        self.logger.message(
            '    Client address: {%s}' % (
                audera.mdns.get_local_ip_address(),
            )
        )
        self.logger.message('')
        self.logger.info(
            ''.join([
                "Waiting on the shairport-sync service to begin,",
                " retrying in %.2f [sec.]." % (
                    audera.TIME_OUT
                )
            ])
        )

        # Run services
        await self.start_services()
