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
import uuid
import concurrent.futures
from zeroconf import Zeroconf, ServiceInfo

import audera


class Service():
    """ A `class` that represents the `audera` server-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-services. """

        # Logging
        self.logger = audera.logging.get_server_logger()

        # Initialize mDNS
        self.mac_address = uuid.getnode()
        self.server_ip_address = audera.mdns.get_local_ip_address()
        self.mdns: audera.mdns.Runner = audera.mdns.Runner(
            logger=self.logger,
            zc=Zeroconf(),
            info=ServiceInfo(
                type_=audera.MDNS_TYPE,
                name=audera.MDNS_NAME,
                addresses=[socket.inet_aton(self.server_ip_address)],
                port=audera.STREAM_PORT,
                weight=0,
                priority=0,
                properties={"description": audera.DESCRIPTION}
            )
        )

        # Initialize time synchronization
        self.ntp: audera.ntp.Synchronizer = audera.ntp.Synchronizer()
        self.offset: float = 0.0

        # Initialize playback delay
        self.playback_delay: float = audera.PLAYBACK_DELAY

        # Initialize clients for broadcasting the audio stream
        self.clients: Dict[str, asyncio.StreamWriter] = {}

        # Initialize process control parameters
        self.mdns_runner_event: asyncio.Event = asyncio.Event()

    async def start_mdns_services(self):
        """ Starts the async service for the multi-cast DNS service.

        The `server` attempts to start the mDNS service as an
        _independent_ task, until the task is either cancelled by
        the event loop or cancelled manually through `KeyboardInterrupt`.
        """
        loop = asyncio.get_running_loop()

        # Register and broadcast the mDNS service
        try:

            # The mDNS service must be started in a separate thread,
            #   since zeroconf relies on its own async event loop that must be run
            #   separately from the `server` async event loop.

            # mdns_thread = threading.Thread(target=self.mdns.register, daemon=True)
            # mdns_thread.start()

            with concurrent.futures.ThreadPoolExecutor() as pool:
                mdns_server = loop.run_in_executor(pool, self.mdns.register)

                await asyncio.gather(mdns_server)

            # Start the `server` services
            self.mdns_runner_event.set()

            # Yield to other tasks in the event loop
            while self.mdns_runner_event.is_set():
                await asyncio.sleep(0)

        except (
            asyncio.CancelledError,  # mDNS-services cancelled
            KeyboardInterrupt,  # mDNS-services cancelled manually
        ):

            # Logging
            self.logger.info(
                'mDNS service {%s} cancelled.' % (
                    audera.MDNS_TYPE
                )
            )

        # Close the mDNS service
        self.mdns.unregister()

    async def start_time_synchonization(self):
        """ Starts the async service for time-synchronization.

        The `server` attempts to start the time-synchronization service
        as an _independent_ task, restarting the service forever until
        the task is either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Communicate with the server
        while self.mdns_runner_event.is_set():

            try:

                # Update the server local machine time offset from the network
                #   time protocol (ntp) server
                self.offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'The server time offset is %.7f [sec.].' % (
                        self.offset
                    )
                )

                # Yield to other tasks in the event loop
                await asyncio.sleep(0)

            except ntplib.NTPException:

                # Logging
                self.logger.info(
                    ''.join([
                        'Communication with the network time protocol (ntp) server {%s} failed,' % (
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
                    'Communication with the network time protocol (npt) server {%s} cancelled.' % (
                        self.ntp.server
                    )
                )

                # Exit the loop
                break

            await asyncio.sleep(audera.SYNC_INTERVAL)

    async def start_stream_service(
        self
    ):
        """ Starts the async audio stream service, capturing audio data from
        the input device and broadcasts the audio stream to all connected clients
        as timestamped packets.

        The `server` attempts to start the stream service as an _independent_ task,
        restarting the service forever with `audera.TIME_OUT` until the task is
        either cancelled by the event loop or cancelled manually through
        `KeyboardInterrupt`.

        When cancelled, the service disconnects any / all connected clients.
        """

        # Wait for the mDNS connection
        await self.mdns_runner_event.wait()

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
                "No input audio device found."
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

        # Logging
        self.logger.info(
            ' '.join([
                "Streaming audio over PORT {%s} at RATE {%s}" % (
                    audera.STREAM_PORT,
                    audera.RATE
                ),
                "with {%s} CHANNEL(s) for input DEVICE {%s}." % (
                    audera.CHANNELS,
                    audera.DEVICE_INDEX
                )
            ])
        )

        # Serve audio stream
        while self.mdns_runner_event.is_set():

            try:

                # Read the next audio data chunk
                chunk = stream.read(
                    audera.CHUNK,
                    exception_on_overflow=False
                )

                # Convert the audio data chunk to a timestamped packet,
                #   including the length of the packet as well as the
                #   packet terminator.

                # Assign the timestamp as the target playback time
                #   accounting for a fixed playback delay from the
                #   current time on the server
                length = struct.pack(">I", len(chunk))
                target_play_time = struct.pack(
                    "d",
                    time.time() + self.playback_delay + self.offset
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

                # Retain the list of client-connections
                clients = copy.copy(self.clients)

                # Broadcast the packet to the clients concurrently and drain
                #    the writer with timeout for flow control, disconnecting
                #    any / all clients that are too slow

                results = await asyncio.gather(
                    *[
                        self.broadcast(
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
                    'The audio stream was cancelled.'
                )

                # Retain list of client-connections
                clients = copy.copy(self.clients)

                # Cleanup any / all remaining clients
                for client_ip, client_writer in clients.items():

                    # Logging
                    self.logger.info(
                        'Client {%s} disconnected.' % (
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

            except OSError as e:  # All other server-communication I / O errors

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

        # Close the audio services
        stream.stop_stream()
        stream.close()
        audio.terminate()

    async def broadcast(
        self,
        client_ip: str,
        writer: asyncio.StreamWriter,
        packet: bytes
    ) -> bool:
        """ Broadcasts the audio stream to all connected clients as timestamped packets.

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
            await writer.drain()
        except (
            asyncio.TimeoutError,  # Client-communication timed-out
            ConnectionResetError,  # Client disconnected
            ConnectionAbortedError,  # Client aborted the connection
        ):

            # Logging
            self.logger.info(
                'Client {%s} disconnected.' % (
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
        """ The async client-registration task that is started when a client
        connects to `0.0.0.0:audera.STREAM_PORT`.

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
            'Client {%s} connected.' % (
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
                'Client {%s} unable to operate with TCP_NODELAY.' % (
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
        """ The async client-communication task that is started when a client
        connects to `0.0.0.0:audera.PING_PORT`.

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
            'Received communication from client {%s}.' % (
                client_ip
            )
        )

        # Communicate with the client
        try:

            # Read the ping-communication
            message = await reader.read(4)
            if message == b"ping":

                # Serve the response-communication containing
                #   the current time on the server for the client
                #   to calculate the time offset
                #   and wait for the response to be received
                writer.write(
                    struct.pack(
                        "d",
                        time.time()
                    )
                )  # 8 bytes
                await writer.drain()

        except (
            asyncio.TimeoutError,  # Client-communication timed-out
            asyncio.CancelledError,  # Server-services cancelled
            KeyboardInterrupt  # Server-services cancelled manually
        ):

            # Logging
            self.logger.info(
                'Communication with client {%s} cancelled.' % (
                    client_ip
                )
            )

        except OSError as e:

            # Logging
            self.logger.error(
                '[%s] [handle_communication()] %s.' % (
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
        """ Starts the async servers for client-registration
        and client-communication with client(s).

        The `server` attempts to start the servers as _dependent_
        tasks, each serving continuous connections with client(s) forever until
        the tasks complete, are cancelled by the event loop or are cancelled
        manually through `KeyboardInterrupt`.
        """

        # Wait for the mDNS connection
        await self.mdns_runner_event.wait()

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

        # Stop the `server` services
        await self.stop_services()

    async def stop_services(self):
        """ Stops the async services. """
        self.mdns_runner_event.clear()

    async def start_services(self):
        """ Runs the async mDNS service, time-synchronization service,
        audio stream service, and client-communication server independently.

        The `client` attempts to start the time-synchronization service,
        the audio stream service and the bundle of servers as _independent_ tasks.
        """

        # Initialize the mDNS service
        start_mdns_services = asyncio.create_task(
            self.start_mdns_services()
        )

        # Initialize the time-synchronization service
        # start_time_synchonization_services = asyncio.create_task(
        #     self.start_time_synchonization()
        # )

        # Initialize the audio stream service

        #   The audio stream service is independent of the
        #       other `audera` server-services.
        #   The audio stream service reads audio chunks from
        #       the audio-input device and creates a time-stamped
        #       audio packet that is broadcasted to all connected
        #       clients concurrently.

        start_stream_services = asyncio.create_task(
            self.start_stream_service()
        )

        # Initialize the `audera` servers
        start_server_services = asyncio.create_task(
            self.start_server_services()
        )

        tasks = [
            start_mdns_services,
            # start_time_synchonization_services,
            start_stream_services,
            start_server_services
        ]

        # Run services
        try:
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

        # Stop services
        finally:
            await asyncio.gather(
                *tasks,
                return_exceptions=True
            )

    async def run(self):
        """ Starts all async server-services. """

        # Logging
        for line in audera.LOGO:
            self.logger.message(line)
        self.logger.message('')
        self.logger.message('')
        self.logger.message('    Running the server-service.')
        self.logger.message('')
        self.logger.message(
            '    Audio stream address: {%s:%s}' % (
                self.server_ip_address,
                audera.STREAM_PORT
            ))
        self.logger.message(
            '    Client-communication address: {%s:%s}' % (
                self.server_ip_address,
                audera.PING_PORT
            ))
        self.logger.message('')

        # Run services
        await self.start_services()
