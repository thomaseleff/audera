""" Server-service """

from typing import Dict
import pyaudio
import ntplib
import asyncio
import socket
import sys
import time
import struct
import copy

import audera


class Service():
    """ A `class` that represents the `audera` server-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-services. """

        # Logging
        self.logger = audera.logging.get_server_logger()

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer()
        self.offset: float = 0.0

        # Initialize clients for broadcasting the audio stream
        self.clients: Dict[str, asyncio.StreamWriter] = {}

    async def start_time_synchonization(self):
        """ Starts the async service for time-synchronization. """

        # Communicate with the server
        while True:

            try:

                # Update the server local machine time offset from the network
                #   time protocol (ntp) server
                self.offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'INFO: The server time offset is %.7f [sec.].' % (
                        self.offset
                    )
                )

            except ntplib.NTPException:

                # Logging
                self.logger.info(
                    ''.join([
                        'INFO: Communication with the network time protocol (ntp) server {%s} failed,' % (
                            self.ntp.server
                        ),
                        ' retrying in %.2f [min.].' % (
                            audera.SYNC_INTERVAL / 60
                        )
                    ])
                )

            await asyncio.sleep(audera.SYNC_INTERVAL)

    async def start_stream_service(
        self
    ):
        """ Starts async audio stream capture, broadcasting the audio stream
        to all connected clients.
        """

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

        # Serve audio stream
        while True:
            try:

                # Read the next audio data chunk
                chunk = stream.read(
                    audera.CHUNK,
                    exception_on_overflow=False
                )

                # Convert the audio data chunk to a timestamped packet
                captured_time = time.time() + self.offset
                packet = struct.pack("d", captured_time) + chunk

                # Retain the list of client-connections
                clients = copy.copy(self.clients)

                # Broadcast the packet to the clients concurrently and drain
                #    the writer with timeout for flow control, disconnecting
                #    any client that is too slow

                results = await asyncio.gather(
                    *[
                        self.broadcast_to_clients(
                            client_ip=client_ip,
                            writer=writer,
                            packet=packet
                        ) for (client_ip, writer) in clients.items()
                    ],
                    return_exceptions=True
                )

                # Remove disconnected clients
                for client_ip, result in zip(clients.keys(), results):
                    if result is False and client_ip in self.clients:
                        del self.clients[client_ip]

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

            except (
                asyncio.CancelledError,  # Server-services cancelled
                KeyboardInterrupt  # Server-services cancelled manually
            ):

                # Logging
                self.logger.info(
                    'INFO: The audio stream was cancelled.'
                )

                # Retain list of client-connections
                clients = copy.copy(self.clients)

                # Cleanup any / all remaining clients
                for client_ip, client_writer in clients.items():

                    # Logging
                    self.logger.info(
                        'INFO: Client {%s} disconnected.' % (
                            client_ip
                        )
                    )

                    # Close the connection
                    client_writer.close()
                    try:
                        await client_writer.wait_closed()
                    except (
                        ConnectionResetError,  # Client disconnected
                        ConnectionAbortedError,  # Client aborted the connection
                    ):
                        pass

                    # Disconnect the client
                    if client_ip in self.clients:
                        del self.clients[client_ip]

                # Exit the loop
                break

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

        # Close the audio services
        stream.stop_stream()
        stream.close()
        audio.terminate()

    async def broadcast_to_clients(
        self,
        client_ip: str,
        writer: asyncio.StreamWriter,
        packet: bytes
    ) -> bool:
        """ Broadcasts the audio packet to the client.

        Parameters
        ----------
        client_ip: `str`
            The ip-address of the client.
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the
                client used to write the audio stream to the
                client over a TCP connection.
        packet: `bytes`
            The timestamped audio data chunk.
        """

        # Broadcast the packet to the client and drain the writer
        #    with timeout for flow control, disconnecting the client
        #    if it is too slow
        try:
            writer.write(packet)
            await asyncio.wait_for(
                writer.drain(),
                timeout=audera.TIME_OUT
            )
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

            # Close the connection
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # Client disconnected
                ConnectionAbortedError,  # Client aborted the connection
            ):
                pass

            return False
        return True

    async def register_client(
        self,
        writer: asyncio.StreamWriter
    ):
        """ Handles async client-registration.

        Parameters
        ----------
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from
                `asyncio.start_server()` used to write the
                audio stream to the client over a TCP connection.
        """

        # Retrieve the client ip-address and port
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

        # Register client
        self.clients[client_ip] = writer

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

        # Retrieve the client ip-address and port
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
        """ Starts the async services for client-registration
        and server-communication with client(s).
        """

        # Initialize the client-registration server
        registration_server = await asyncio.start_server(
            client_connected_cb=(
                lambda _, writer: self.register_client(
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
        async with registration_server, communication_server:
            await asyncio.gather(
                registration_server.serve_forever(),
                communication_server.serve_forever()
            )

    async def start_services(self):
        """ Runs multiple async services independently.
        """

        # Initialize the `audera` server-services
        start_time_synchonization_services = asyncio.create_task(
            self.start_time_synchonization()
        )
        start_stream_services = asyncio.create_task(
            self.start_stream_service()
        )
        start_server_services = asyncio.create_task(
            self.start_server_services()
        )

        tasks = [
            start_time_synchonization_services,
            start_stream_services,
            start_server_services
        ]

        # Run services

        #   The stream service is independent of the
        #       other `audera` server-services.
        #   The stream service reads audio chunks from
        #       the audio-input device and creates a time-stamped
        #       audio packet that is broadcasted to all connected
        #       clients concurrently.

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
                        'ERROR: [%s] An unhandled exception was raised. %s.' % (
                            type(task.exception()).__name__,
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
