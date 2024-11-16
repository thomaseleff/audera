""" Server-service """

import pyaudio
import sys
import asyncio
import time
import struct

import audera


class Service():
    """ A `class` that represents the `audera` server-services. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-services. """

        # Logging
        self.server_logger = audera.logging.get_server_logger()

        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()

        # Assign device-index
        # --TODO: The name of the device should be set dynamically
        # --TODO: This should wait until an audio device is found

        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if "Line 1" in device_info.get("name", ""):
                audera.DEVICE_INDEX = i
                break

        if audera.DEVICE_INDEX is None:

            # Logging
            self.server_logger.error(
                "ERROR: No input audio device found."
            )

            # Exit
            self.audio.terminate()
            sys.exit(audera.errors.DEVICE_ERROR)

        # Initialize audio stream-capture
        self.stream = self.audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            input=True,
            input_device_index=audera.DEVICE_INDEX,
            frames_per_buffer=audera.CHUNK
        )

    async def serve_stream(
        self,
        writer: asyncio.StreamWriter
    ):
        """ Handles async audio-streams to clients.

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
        self.server_logger.info(
            'INFO: Client {%s} connected.' % (
                client_ip
            )
        )

        # Serve audio stream
        while True:
            try:

                # Read the next audio data chunk
                chunk = self.stream.read(audera.CHUNK)
                timestamp = time.time()
                packet = struct.pack("d", timestamp) + chunk

                # Serve the audio data chunk as a timestamped packet
                #   and wait for the packet to be received
                writer.write(packet)
                await writer.drain()

            except (
                asyncio.TimeoutError,  # When the client-communication
                                       #    times-out
                ConnectionResetError,  # When the client-disconnects
                ConnectionAbortedError,  # When the client-disconnects
            ):

                # Logging
                self.server_logger.info(
                    'INFO: Client {%s} disconnected.' % (
                        client_ip
                    )
                )

                # Exit the loop
                break

            except (
                asyncio.CancelledError,  # When the server-services are
                                         #    cancelled
                KeyboardInterrupt  # When the server-services are cancelled
            ):

                # Logging
                self.server_logger.info(
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
            ConnectionResetError,  # When the client-disconnects
            ConnectionAbortedError,  # When the client-disconnects
        ):
            pass

    async def serve_communication(
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
        self.server_logger.info(
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
            asyncio.TimeoutError,  # When the client-communication times-out
            asyncio.CancelledError,  # When the server-services are cancelled
            KeyboardInterrupt  # When the server-services are cancelled
        ):

            # Logging
            self.server_logger.info(
                'INFO: Communication with client {%s} cancelled.' % (
                    client_ip
                )
            )

        except OSError as e:

            # Logging
            self.server_logger.error(
                'ERROR:[%s] [serve_communication()] %s' % (
                    type(e).__name__, str(e)
                )
            )

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (
                ConnectionResetError,  # When the client-disconnects
                ConnectionAbortedError,  # When the client-disconnects
            ):
                pass

    async def start_services(self):
        """ Starts the async services for audio streaming
        and client-communication.
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
                lambda reader, writer: self.serve_communication(
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

    def run(self):
        """ Runs the async server-services. """

        # Logging
        for line in audera.LOGO:
            self.server_logger.info(line)
        self.server_logger.info('')
        self.server_logger.info('')
        self.server_logger.info('    Running the server-service.')
        self.server_logger.info('')
        self.server_logger.info(
            '    Audio stream address: {%s:%s}' % (
                audera.SERVER_IP,
                audera.STREAM_PORT
            ))
        self.server_logger.info(
            '    Client-communication address: {%s:%s}' % (
                audera.SERVER_IP,
                audera.PING_PORT
            ))
        self.server_logger.info('')
        self.server_logger.info(
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

        # Create an event-loop for handling all services
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Run services
        try:
            loop.run_until_complete(self.start_services())

        except KeyboardInterrupt:

            # Logging
            self.server_logger.info(
                "INFO: Shutting down the server-services."
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
            self.server_logger.info(
                'INFO: The server-services exited successfully.'
            )

            # Close audio services
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()
