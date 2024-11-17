""" Server-service """

import pyaudio
import asyncio
import socket
import sys
import time
import struct

import audera


class Service():
    """ A `class` that represents the `audera` server-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-services. """

        # Logging
        self.logger = audera.logging.get_server_logger()

        # Initialize buffer
        self.buffer = asyncio.Queue(maxsize=audera.BUFFER_SIZE)

    async def start_stream_capture(
        self
    ):
        """ Starts async audio stream capture, creating an audio
        packet buffer queue for handling async audio streams to
        clients. """

        # Initialize PyAudio
        audio = pyaudio.PyAudio()

        # Assign device-index
        # --TODO: The name of the device should be set dynamically
        # --TODO: This should wait until an audio device is found

        for i in range(audio.get_device_count()):
            device_info = audio.get_device_info_by_index(i)
            if "Line 1" in device_info.get("name", ""):
                audera.DEVICE_INDEX = i
                break

        if audera.DEVICE_INDEX is None:

            # Logging
            self.logger.error(
                "ERROR: No input audio device found."
            )

            # Exit
            audio.terminate()
            sys.exit(audera.errors.DEVICE_ERROR)

        # Initialize audio stream-capture
        stream = audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            input=True,
            input_device_index=audera.DEVICE_INDEX,
            frames_per_buffer=audera.CHUNK
        )

        # Capture audio stream
        while True:

            # Read the next audio data chunk
            try:
                chunk = stream.read(
                    audera.CHUNK,
                    exception_on_overflow=False
                )

                # Convert the audio data chunk to a timestamped packet
                packet = struct.pack("d", time.time()) + chunk

                # Append the packet to the buffer queue
                #   If the buffer queue is full, the operation
                #       waits until a new slot is available in the queue.
                await self.buffer.put(packet)

            except IOError as e:

                # Logging
                self.logger.error(
                    'ERROR: [%s] %s.' % (
                        type(e).__name__, str(e)
                    )
                )
                self.logger.info(
                    ''.join([
                        "INFO: The audio stream capture encountered",
                        " an error, retrying in %.2f [sec.]." % (
                            audera.TIME_OUT
                        )
                    ])
                )

                # Timeout
                await asyncio.sleep(audera.TIME_OUT)

            except (
                asyncio.CancelledError,  # Server-services cancelled
                KeyboardInterrupt  # Server-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'INFO: The audio stream capture was cancelled.'
                )

                # Exit the loop
                break

        # Close the audio services
        stream.stop_stream()
        stream.close()
        audio.terminate()

    async def serve_stream(
        self,
        writer: asyncio.StreamWriter
    ):
        """ Handles async audio streams to clients.

        Parameters
        ----------
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from
                `asyncio.start_server()` used to write the
                audio stream to the client over a TCP connection.
        """

        # Retrieve the client ip address and port
        client_ip, _ = writer.get_extra_info('peername')

        # Logging
        self.logger.info(
            'INFO: Client {%s} connected.' % (
                client_ip
            )
        )

        # Configure the client socket options for low-latency communication
        try:
            client_socket: socket.socket = writer.get_extra_info('socket')
            client_socket.setsockopt(
                socket.IPPROTO_TCP,
                socket.TCP_NODELAY,
                1
            )
        except Exception:

            # Logging
            self.logger.warning(
                'WARNING: Client {%s} unable to operate with TCP_NODELAY.' % (
                    client_ip
                )
            )

        # Serve audio stream
        while True:
            try:

                # Serve each / every timestamped packet in the packet buffer queue
                packet = await self.buffer.get()
                writer.write(packet)

                # Drain the writer with timeout for flow control,
                #    disconnecting any client that is too slow
                try:
                    await asyncio.wait_for(
                        writer.drain(),
                        timeout=audera.TIME_OUT
                    )
                except asyncio.TimeoutError:

                    # Logging
                    self.logger.error(
                        'ERROR: Client {%s} disconnected due to flow control.' % (
                            client_ip
                        )
                    )

                    # Exit the loop
                    break

            except (
                asyncio.TimeoutError,  # Client-communication timed-out
                ConnectionResetError,  # Client disconnected
                ConnectionAbortedError,  # Client aborted the connection
            ):

                # Logging
                self.logger.info(
                    'INFO: Client {%s} disconnected.' % (
                        client_ip
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # Server-services cancelled
                KeyboardInterrupt  # Server-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'INFO: Audio stream to client {%s} cancelled.' % (
                        client_ip
                    )
                )

                # Exit the loop
                break

        # Close the connection
        writer.close()
        try:
            await writer.wait_closed()
        except (
            ConnectionResetError,  # Client disconnected
            ConnectionAbortedError,  # Client aborted the connection
        ):
            pass

    async def handle_communication(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ Handles async ping-communication from clients.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader passed from
                `asyncio.start_server()` used to receive a `ping`
                response from the client.
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from
                `asyncio.start_server()` used to serve a `pong`
                response to the client.
        """

        # Retrieve the client ip address and port
        client_ip, _ = writer.get_extra_info('peername')

        # Logging
        self.logger.info(
            'INFO: Received communication from client {%s}.' % (
                client_ip
            )
        )

        # Communicate with the client
        try:

            # Read the ping-communication
            message = await reader.read(4)
            if message == b"ping":

                # Serve the pong-communication
                #   and wait for the response to be received
                writer.write(b"pong")
                await writer.drain()

        except (
            asyncio.TimeoutError,  # Client-communication timed-out
            asyncio.CancelledError,  # Server-services cancelled
            KeyboardInterrupt  # Server-services cancelled manually
        ):

            # Logging
            self.logger.info(
                'INFO: Communication with client {%s} cancelled.' % (
                    client_ip
                )
            )

        except OSError as e:

            # Logging
            self.logger.error(
                'ERROR: [%s] [handle_communication()] %s.' % (
                    type(e).__name__, str(e)
                )
            )

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # Client disconnected
                ConnectionAbortedError,  # Client aborted the connection
            ):
                pass

    async def start_server_services(self):
        """ Starts the async services for audio streaming
        and client-communication with client(s).
        """

        # Initialize the audio stream server
        stream_server = await asyncio.start_server(
            client_connected_cb=(
                lambda _, writer: self.serve_stream(
                    writer=writer
                )
            ),
            host='0.0.0.0',  # No specific destination address
            port=audera.STREAM_PORT
        )

        # Initialize the ping-communication server
        communication_server = await asyncio.start_server(
            client_connected_cb=(
                lambda reader, writer: self.handle_communication(
                    reader=reader,
                    writer=writer
                )
            ),
            host='0.0.0.0',  # No specific destination address
            port=audera.PING_PORT
        )

        # Serve client-connections and communication
        async with stream_server, communication_server:
            await asyncio.gather(
                stream_server.serve_forever(),
                communication_server.serve_forever()
            )

    async def start_services(self):
        """ Runs multiple async services independently.
        """

        # Initialize the `audera` clients-services
        start_stream_capture = asyncio.create_task(
            self.start_stream_capture()
        )
        start_server_services = asyncio.create_task(
            self.start_server_services()
        )

        tasks = [
            start_stream_capture,
            start_server_services
        ]

        # Run services

        #   The stream-capture service is independent of the
        #       other `audera` server-services.
        #   The stream-capture service reads audio chunks from
        #       the audio-input device and creates a time-stamped
        #       audio packet buffer queue that is shared across all
        #       client-connections.
        #   When a client connects, the `audera` server-services
        #       read audio packets from the packet buffer queue and
        #       serve them to the client for playback.

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
                        'ERROR: An unhandled exception was raised. %s.' % (
                            task.exception()
                        )
                    )

        await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

    async def run(self):
        """ Runs the async server-services. """

        # Logging
        for line in audera.LOGO:
            self.logger.info(line)
        self.logger.info('')
        self.logger.info('')
        self.logger.info('    Running the server-service.')
        self.logger.info('')
        self.logger.info(
            '    Audio stream address: {%s:%s}' % (
                audera.SERVER_IP,
                audera.STREAM_PORT
            ))
        self.logger.info(
            '    Client-communication address: {%s:%s}' % (
                audera.SERVER_IP,
                audera.PING_PORT
            ))
        self.logger.info('')
        self.logger.info(
            ' '.join([
                "INFO: Streaming audio over PORT {%s} at RATE {%s}" % (
                    audera.STREAM_PORT,
                    audera.RATE
                ),
                "with {%s} CHANNEL(s) for input DEVICE {%s}." % (
                    audera.CHANNELS,
                    audera.DEVICE_INDEX
                )
            ])
        )

        # Run services
        await self.start_services()
