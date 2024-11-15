""" Client-service """

import pyaudio
import asyncio
import socket
import time
import struct
from collections import deque
import statistics

import audera


class Service():
    """ A `class` that represents the `audera` client-service. """

    def __init__(self):
        """ Initializes an instance of the `audera` client-service. """

        # Logging
        self.client_logger = audera.logging.get_client_logger()

        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()

        # Initialize audio stream-playback
        self.stream = self.audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            output=True,
            frames_per_buffer=audera.CHUNK
        )

        # Initialize buffer and rtt-history
        self.buffer = deque()
        self.buffer_time = audera.BUFFER_TIME
        self.rtt_history = []

    async def receive_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ Receives the async audio stream from the server.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader used to
                receive the audio stream from the server.
        writer: `asyncio.StreamWriter`
            The unused asynchronous network stream writer.
        """

        # Logging
        self.client_logger.info(
            ' '.join([
                "INFO: Receiving audio over PORT {%s} at RATE {%s}" % (
                    audera.STREAM_PORT,
                    audera.RATE
                ),
                "with {%s} CHANNEL(s)." % (
                    audera.CHANNELS
                )
            ])
        )

        # Receive audio stream
        while True:
            try:

                # Parse audio stream packet
                packet = await reader.read(
                    audera.CHUNK * audera.CHANNELS * 2 + 8
                )

                # Exit the loop when there is no active audio stream
                if not packet:
                    break

                # Parse the time-stamp and audio data from the packet
                receive_time = time.time()
                timestamp, data = (
                    struct.unpack("d", packet[:8])[0],
                    packet[8:]
                )
                target_play_time = timestamp + self.buffer_time

                # Add audio data to the buffer
                self.buffer.append(
                    (
                        max(0, target_play_time - receive_time),
                        data
                    )
                )

                # Playback buffered audio data
                if len(self.buffer) >= audera.BUFFER_SIZE:
                    for _ in range(len(self.buffer)):
                        buffered_delay, buffered_data = (
                            self.buffer.popleft()
                        )
                        await asyncio.sleep(buffered_delay)
                        self.stream.write(buffered_data)

            except (
                asyncio.TimeoutError,  # When the server-communication
                                       #    times-out
                ConnectionResetError,  # When the server-disconnects
                ConnectionAbortedError,  # When the server-disconnects
            ):

                # Logging
                self.client_logger.info(
                    'INFO: Server {%s} disconnected.' % (
                        audera.SERVER_IP
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # When the client-services are
                                         #    cancelled
                KeyboardInterrupt  # When the client-services are cancelled
            ):

                # Logging
                self.client_logger.info(
                    'INFO: Audio stream from server {%s} cancelled.' % (
                        audera.SERVER_IP
                    )
                )

                # Exit the loop
                break

        # Close the connection
        writer.close()
        try:
            await writer.wait_closed()
        except (
            ConnectionResetError,  # When the server-disconnects
            ConnectionAbortedError,  # When the server-disconnects
        ):
            pass

    async def receive_communication(self):
        """ Receives async server-communication, measures round-trip time (RTT)
        and adjusts the audio playback buffer-time.
        """

        # Communicate with the server
        while True:

            # Measure round-trip time (RTT)
            try:
                rtt = await self.measure_rtt()

            except (
                asyncio.TimeoutError,  # When the server-communication
                                       #    times-out
                asyncio.CancelledError,  # When the client-services are
                                         #    cancelled
                KeyboardInterrupt  # When the client-services are cancelled
            ):

                # Logging
                self.client_logger.info(
                    'INFO: Communication with server {%s} cancelled.' % (
                        audera.SERVER_IP
                    )
                )

                # Exit the loop
                break

            except OSError as e:

                # Logging
                self.client_logger.error(
                    'ERROR:[%s] [measure_rtt()] %s' % (
                        type(e).__name__, str(e)
                    )
                )

                rtt = None

            # Perform audio playback buffer-time adjustment
            if rtt:

                # Add the RTT measurement to the history
                self.rtt_history.append(rtt)

                # Adjust the buffer-time based on RTT and jitter
                #   Only adjust after the RTT_HISTORY_SIZE is met
                if len(self.rtt_history) >= audera.RTT_HISTORY_SIZE:
                    mean_rtt = statistics.mean(self.rtt_history)
                    jitter = statistics.stdev(self.rtt_history)

                    # Logging
                    self.client_logger.info(
                        ''.join([
                            'INFO: Audio playback buffer-time statistics',
                            ' (jitter {%.4f},' % (jitter),
                            ' avg. rtt {%.4f}).' % (mean_rtt)
                        ])
                    )

                    # Decrease the buffer time for low jitter and RTT
                    if (
                        jitter < audera.LOW_JITTER
                        and mean_rtt < audera.LOW_RTT
                    ):
                        new_buffer_time = max(
                            audera.MIN_BUFFER_TIME, self.buffer_time - 0.05
                        )

                    # Increase the buffer-time for high jitter or RTT
                    elif (
                        jitter > audera.HIGH_JITTER
                        or mean_rtt > audera.HIGH_RTT
                    ):
                        new_buffer_time = min(
                            audera.MAX_BUFFER_TIME, self.buffer_time + 0.05
                        )

                    # Otherwise maintain the current buffer-time
                    else:
                        new_buffer_time = self.buffer_time

                    # Update the buffer-time and clear the RTT history
                    self.buffer_time = new_buffer_time
                    self.rtt_history.pop(0)

                    # Logging
                    self.client_logger.info(
                        ''.join([
                            'INFO: Audio playback buffer-time adjusted',
                            ' to %.2f [sec.].' % (
                                self.buffer_time
                            )
                        ])
                    )

            await asyncio.sleep(audera.PING_INTERVAL)

    async def measure_rtt(self):
        """ Measures round-trip time (RTT) """

        # Initialize the connection to the ping-communication server
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                audera.SERVER_IP,
                audera.PING_PORT
            ),
            timeout=audera.TIME_OUT
        )

        # Record the start-time
        start_time = time.time()

        # Ping the server
        writer.write(b"ping")
        await writer.drain()

        # Wait for return response (4 bytes)
        await reader.read(4)

        # Calculate round-trip time
        rtt = time.time() - start_time

        # Logging
        self.client_logger.info(
            'INFO: Round-trip time (rtt) is %.4f [sec.].' % (rtt)
        )

        # Close the connection
        writer.close()
        await writer.wait_closed()

        return rtt

    async def start_services(self):
        """ Starts the async services for audio streaming
        and client-communication.
        """

        # Handle server-availability
        while True:
            try:

                # Initialize the connection to the audio stream server
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        audera.SERVER_IP,
                        audera.STREAM_PORT
                    ),
                    timeout=audera.TIME_OUT
                )

                # Initialize the audio stream coroutine
                receive_stream = asyncio.create_task(
                    self.receive_stream(reader=reader, writer=writer)
                )

                # Initialize the ping-communication coroutine
                receive_communication = asyncio.create_task(
                    self.receive_communication()
                )

                await asyncio.gather(
                    receive_stream,
                    receive_communication
                )

            except (
                asyncio.TimeoutError,  # When the server-communication is not
                                       #    available
                OSError  # All other server-communication I / O errors
            ):

                # Logging
                self.client_logger.info(
                    ''.join([
                        "INFO: Waiting on a connection to the server,",
                        " retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

            except KeyboardInterrupt:

                # Logging
                self.client_logger.info(
                    'INFO: Audio stream from server {%s} cancelled.' % (
                        audera.SERVER_IP
                    )
                )

                # Exit the loop when the services are cancelled
                break

    def run(self):
        """ Starts the async services for audio streaming
        and server-communication.
        """

        # Logging
        for line in audera.LOGO:
            self.client_logger.info(line)
        self.client_logger.info('')
        self.client_logger.info('')
        self.client_logger.info('    Running the client-service.')
        self.client_logger.info('')
        self.client_logger.info(
            '    Audio stream address: {%s:%s}' % (
                audera.SERVER_IP,
                audera.STREAM_PORT
            )
        )
        self.client_logger.info(
            '    Client address: {%s}' % (
                socket.gethostbyname(socket.gethostname()),
            )
        )
        self.client_logger.info('')
        self.client_logger.info(
            ''.join([
                "INFO: Waiting on a connection to the server,",
                " retrying in %.2f [sec.]." % (
                    audera.TIME_OUT
                )
            ])
        )

        # Create an event-loop for handling all services
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Run services
        try:
            loop.run_until_complete(self.start_services())

        except KeyboardInterrupt:

            # Logging
            self.client_logger.info(
                "INFO: Shutting down the client-services."
            )

            # Cancel any / all remaining running services
            services = asyncio.all_tasks(loop=loop)
            for service in services:
                service.cancel()
            loop.run_until_complete(
                asyncio.gather(
                    *services,
                    return_exceptions=True
                )
            )

        finally:

            # Close the event-loop
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

            # Logging
            self.client_logger.info(
                'INFO: The client-services exited successfully.'
            )

            # Close audio services
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()
