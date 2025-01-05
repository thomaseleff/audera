""" Server-service """

from typing import Dict
import ntplib
import asyncio
import socket
import time
import struct
import copy
import concurrent.futures
from zeroconf import Zeroconf, ServiceInfo

import audera


class Service():
    """ A `class` that represents the `audera` server-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-services. """

        # Logging
        self.logger = audera.logging.get_server_logger()

        # Initialize identity
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

        # Initialize mDNS
        self.mdns: audera.mdns.Browser = audera.mdns.Browser(
            logger=self.logger,
            zc=Zeroconf(),
            type_=audera.MDNS_TYPE,
            time_out=audera.TIME_OUT
        )
        # self.mdns: audera.mdns.Runner = audera.mdns.Runner(
        #     logger=self.logger,
        #     zc=Zeroconf(),
        #     info=ServiceInfo(
        #         type_=audera.MDNS_TYPE,
        #         name='server@%s.%s' % (
        #             self.mac_address.replace(':', ''),
        #             audera.MDNS_TYPE
        #         ),
        #         addresses=[socket.inet_aton(self.server_ip_address)],
        #         port=audera.STREAM_PORT,
        #         weight=0,
        #         priority=0,
        #         properties={
        #             "mac_address": self.mac_address,
        #             "description": audera.DESCRIPTION
        #         }
        #     )
        # )

        # Initialize audio stream capture
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
        self.clients: Dict[str, asyncio.StreamWriter] = {}

        # Initialize process control parameters
        # self.mdns_runner_event: asyncio.Event = asyncio.Event()
        self.mdns_browser_event: asyncio.Event = asyncio.Event()

    def get_playback_time(self) -> float:
        """ Returns the playback time based on the current time, playback delay and
        network time protocol (ntp) server offset.
        """
        return float(time.time() + self.playback_delay + self.ntp_offset)

    async def start_mdns_services(self):
        """ Starts the async service for the multi-cast DNS service browser.

        The `server` attempts to start the mDNS service as an
        _independent_ task, until the task is either cancelled by
        the event loop or cancelled manually through `KeyboardInterrupt`.
        """
        loop = asyncio.get_running_loop()

        # Browse for remote audio output players broadcasting the mDNS service
        try:

            # The mDNS service must be started in a separate thread,
            #   since zeroconf relies on its own async event loop that must be run
            #   separately from the `server` async event loop.

            with concurrent.futures.ThreadPoolExecutor() as pool:
                mdns_server = loop.run_in_executor(pool, self.mdns.browse)

                await asyncio.gather(mdns_server)

            # Start the `server` services
            self.mdns_browser_event.set()

            # Yield to other tasks in the event loop
            while self.mdns_browser_event.is_set():

                # Register / update each remote audio output player discovered
                #    by the mDNS service browser concurrently.

                if self.mdns.players:
                    await asyncio.gather(
                        *[
                            self.register_player(info=info)
                            for info in self.mdns.players.values()
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
                'mDNS service {%s} cancelled.' % (
                    audera.MDNS_TYPE
                )
            )

        # Close the mDNS service
        self.mdns.close()

        # """ Starts the async service for the multi-cast DNS service.

        # The `server` attempts to start the mDNS service as an
        # _independent_ task, until the task is either cancelled by
        # the event loop or cancelled manually through `KeyboardInterrupt`.
        # """
        # loop = asyncio.get_running_loop()

        # # Register and broadcast the mDNS service
        # try:

        #     # The mDNS service must be started in a separate thread,
        #     #   since zeroconf relies on its own async event loop that must be run
        #     #   separately from the `server` async event loop.

        #     with concurrent.futures.ThreadPoolExecutor() as pool:
        #         mdns_server = loop.run_in_executor(pool, self.mdns.register)

        #         await asyncio.gather(mdns_server)

        #     # Start the `server` services
        #     self.mdns_runner_event.set()

        #     # Yield to other tasks in the event loop
        #     while self.mdns_runner_event.is_set():
        #         await asyncio.sleep(0)

        # except (
        #     asyncio.CancelledError,  # mDNS-services cancelled
        #     KeyboardInterrupt,  # mDNS-services cancelled manually
        # ):

        #     # Logging
        #     self.logger.info(
        #         'mDNS service {%s} cancelled.' % (
        #             audera.MDNS_TYPE
        #         )
        #     )

        # # Close the mDNS service
        # self.mdns.unregister()

    async def start_ntp_synchronization(self):
        """ Starts the async service for time-synchronization.

        The `server` attempts to start the time-synchronization service
        as an _independent_ task, restarting the service forever until
        the task is either cancelled by the event loop or cancelled
        manually through `KeyboardInterrupt`.
        """

        # Communicate with the server
        while True:

            try:

                # Update the server local machine time offset from the network
                #   time protocol (ntp) server
                self.ntp_offset = self.ntp.offset()

                # Logging
                self.logger.info(
                    'The server ntp time offset is %.7f [sec.].' % (
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
        await self.mdns_browser_event.wait()

        # Logging
        self.logger.info(
            ' '.join([
                "Streaming FORMAT {%s-bit} audio at RATE {%s}" % (
                    self.audio_input.interface.format,
                    self.audio_input.interface.rate
                ),
                "with {%s} CHANNEL(s) from input DEVICE {%s (%s)}." % (
                    self.audio_input.interface.channels,
                    self.audio_input.device.name,
                    self.audio_input.device.index
                )
            ])
        )

        # Serve audio stream
        while self.mdns_browser_event.is_set():

            try:

                # Manage / update audio stream capture
                if self.audio_input.update(
                    interface=audera.dal.interfaces.get_interface(),
                    device=audera.dal.devices.get_device()
                ):

                    # Logging
                    self.logger.info(
                        ' '.join([
                            "Streaming FORMAT {%s-bit} audio at RATE {%s}" % (
                                self.audio_input.interface.format,
                                self.audio_input.interface.rate
                            ),
                            "with {%s} CHANNEL(s) from input DEVICE {%s (%s)}." % (
                                self.audio_input.interface.channels,
                                self.audio_input.device.name,
                                self.audio_input.device.index
                            )
                        ])
                    )

                # Read the next audio data chunk
                chunk = self.audio_input.stream.read(
                    self.audio_input.interface.chunk,
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
        self.audio_input.stream.stop_stream()
        self.audio_input.stream.close()
        self.audio_input.port.terminate()

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

    async def register_player(
        self,
        info: ServiceInfo
    ):
        """ Registers a remote audio output player when it is discovered by
        the mDNS browser.

        Parameters
        ----------
        info: `zeroconf.ServiceInfo`
            An instance of the `zeroconf` multi-cast DNS service parameters.
        """

        # Unpack the mDNS service info into a dictionary
        properties = {
            key.decode('utf-8'): value.decode('utf-8') if isinstance(value, bytes) else value
            for key, value in info.properties.items()
        }

        # Update the player configuration-file
        player: audera.struct.player.Player = audera.struct.player.Player.from_config(
            audera.dal.players.update(
                audera.struct.player.Player(
                    name=properties['name'],
                    uuid=properties['uuid'],
                    mac_address=properties['mac_address'],
                    address=socket.inet_ntoa(info.addresses[0])
                )
            )
        )

        # Register the client ip-address
        if player.address not in self.clients.keys():

            # Logging
            self.logger.info(
                'Registered client {%s}.' % (
                    player.address
                )
            )

            # Initialize the connection to the remote audio output player
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
                    'Client {%s} unable to operate with TCP_NODELAY.' % (
                        player.address
                    )
                )

            # Register client
            self.clients[player.address] = writer

    #     # Retrieve the client ip-address and port
    #     client_ip, _ = writer.get_extra_info('peername')

    #     # Logging
    #     self.logger.info(
    #         'Client {%s} connected.' % (
    #             client_ip
    #         )
    #     )

    #     # Configure the client socket options for low-latency communication
    #     try:
    #         client_socket: socket.socket = writer.get_extra_info('socket')
    #         client_socket.setsockopt(
    #             socket.IPPROTO_TCP,
    #             socket.TCP_NODELAY,
    #             1
    #         )
    #     except Exception:

    #         # Logging
    #         self.logger.warning(
    #             'Client {%s} unable to operate with TCP_NODELAY.' % (
    #                 client_ip
    #             )
    #         )

    #     # Register client
    #     self.clients[client_ip] = writer

    async def start_multi_player_synchronization(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        """ The async multi-player synchronization task that is started when a client
        connects to `0.0.0.0:audera.PING_PORT`.

        Parameters
        ----------
        reader: `asyncio.StreamReader`
            The asynchronous network stream reader passed from
                `asyncio.start_server()` used to receive a `ping`
                response from the client.
        writer: `asyncio.StreamWriter`
            The asynchronous network stream writer passed from
                `asyncio.start_server()` used to serve a datetime
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
                        time.time() + self.ntp_offset
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

    async def start_multi_player_synchronization_server(self):
        """ Starts the async server for multi-player synchronization.

        The `server` attempts to start the servers as _dependent_
        tasks, each serving continuous connections with client(s) forever until
        the tasks complete, are cancelled by the event loop or are cancelled
        manually through `KeyboardInterrupt`.
        """

        # Wait for the mDNS connection
        await self.mdns_browser_event.wait()

        # # Initialize the client-registration server
        # registration_server = await asyncio.start_server(
        #     client_connected_cb=(
        #         lambda _, writer: self.register_client(
        #             writer=writer
        #         )
        #     ),
        #     host='0.0.0.0',  # No specific destination address
        #     port=audera.STREAM_PORT
        # )

        # Initialize the ping-communication server
        multi_player_synchronization_server = await asyncio.start_server(
            client_connected_cb=(
                lambda reader, writer: self.start_multi_player_synchronization(
                    reader=reader,
                    writer=writer
                )
            ),
            host='0.0.0.0',  # No specific destination address
            port=audera.PING_PORT
        )

        # Serve client-connections and communication
        async with (
            # registration_server,
            multi_player_synchronization_server
        ):
            await asyncio.gather(
                # registration_server.serve_forever(),
                multi_player_synchronization_server.serve_forever()
            )

        # Stop the `server` services
        await self.stop_services()

    async def stop_services(self):
        """ Stops the async services. """
        self.mdns_browser_event.clear()

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
        start_ntp_synchronization_services = asyncio.create_task(
            self.start_ntp_synchronization()
        )

        # Initialize the multi-player synchronization server
        start_multi_player_synchronization_server = asyncio.create_task(
            self.start_multi_player_synchronization_server()
        )

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

        tasks = [
            start_mdns_services,
            start_ntp_synchronization_services,
            start_multi_player_synchronization_server,
            start_stream_services
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
            '    Multi-player synchronization address: {%s:%s}' % (
                self.server_ip_address,
                audera.PING_PORT
            ))
        self.logger.message('')

        # Run services
        await self.start_services()
