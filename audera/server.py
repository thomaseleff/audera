""" Server-application """

import sys
import asyncio
import pyaudio
import time
import struct

import audera


class Service():
    """ A `class` that represents the `audera` server-application. """

    def __init__(self):
        """ Initializes an instance of the `audera` server-application. """

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
            self.server_logger.error(
                "ERROR: No input audio device found."
            )
            self.audio.terminate()
            sys.exit(audera.errors.DEVICE_ERROR)

        #   Use socket.SOCK_STREAM for TCP, which helps keep the buffer size
        #       small and avoids having to treat lost, out-of-order, or
        #       incomplete packets.
        # if audera.TRANSMIT_MODE == 'TCP':
        #     self.audio_socket = socket.socket(
        #         socket.AF_INET,
        #         socket.SOCK_STREAM
        #     )
        #     self.audio_socket.bind(
        #         (audera.SERVER_IP, audera.AUDIO_PORT)
        #     )
        #     self.audio_socket.listen(1)

        # Initialize socket for audio
        #   Use socket.SOCK_DGRAM for UDP, which is faster but lacks delivery
        #       guarantees.
        # if audera.TRANSMIT_MODE == 'UDP':
        #     self.audio_socket = socket.socket(
        #         socket.AF_INET,
        #         socket.SOCK_DGRAM
        #     )
        #     self.audio_socket.setsockopt(
        #         socket.SOL_SOCKET,
        #         socket.SO_BROADCAST,
        #         1
        #     )
        #     self.conn = None

        # Initialize socket for ping-requests
        # self.ping_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # self.ping_socket.bind(("0.0.0.0", audera.PING_PORT))

        # Open the audio stream capture
        self.stream = self.audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            input=True,
            input_device_index=audera.DEVICE_INDEX,
            frames_per_buffer=audera.CHUNK
        )

    async def handle_client(self, stream_writer: asyncio.StreamWriter):
        """ Handles async client connections, streams audio and
        handles ping-requests.
        """
        print(f"Client connected: {stream_writer.get_extra_info('peername')}")
        try:
            while True:

                # Handle audio streaming
                data = self.stream.read(audera.CHUNK)
                timestamp = time.time()
                packet = struct.pack("d", timestamp) + data

                stream_writer.write(packet)
                await stream_writer.drain()

        except (asyncio.CancelledError, ConnectionResetError):
            print("Client disconnected.")

        finally:
            stream_writer.close()
            await stream_writer.wait_closed()

    async def start_server(self):
        """ Start the async server and handle client connections. """
        server = await asyncio.start_server(
            self.handle_client,
            audera.SERVER_IP,
            audera.AUDIO_PORT
        )
        print(f"Server started on port {audera.AUDIO_PORT}")

        async with server:
            await server.serve_forever()

    def run(self):
        """ Streams audio and handles ping-requests. """

        # Logging
        for line in audera.LOGO:
            self.server_logger.info(line)
        self.server_logger.info('')
        self.server_logger.info('')
        self.server_logger.info('    Running the `audera` server-application.')
        self.server_logger.info('')
        self.server_logger.info(
            '    Server address: https://%s:%s' % (
                audera.SERVER_IP,
                audera.AUDIO_PORT
            ))
        self.server_logger.info('')
        self.server_logger.info(
            ' '.join([
                "INFO: Streaming audio over PORT {%s} at RATE {%s}" % (
                    audera.AUDIO_PORT,
                    audera.RATE
                ),
                "with {%s} CHANNEL(s) for input DEVICE {%s}." % (
                    audera.CHANNELS,
                    audera.DEVICE_INDEX
                )
            ])
        )

        try:
            asyncio.run(self.start_server())

        except KeyboardInterrupt:
            print("Server shutting down.")

        finally:
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()

        # Open connection
        # if audera.TRANSMIT_MODE == 'TCP':
        #     self.conn, _ = self.audio_socket.accept()

        # try:
        #     while True:

        #         # Handle audio streaming
        #         data = self.stream.read(audera.CHUNK)
        #         timestamp = time.time()
        #         packet = struct.pack("d", timestamp) + data

        #         # Send packet
        #         if audera.TRANSMIT_MODE == 'TCP':
        #             try:
        #                 self.conn.sendall(packet)
        #             except ConnectionResetError:
        #                 self.conn, _ = self.audio_socket.accept()

        #         # if audera.TRANSMIT_MODE == 'UDP':
        #             self.audio_socket.sendto(
        #                 packet, ("<broadcast>", audera.AUDIO_PORT)
        #             )

        #         # Quick timeout for non-blocking ping handling
        #         self.ping_socket.settimeout(0.01)

        #         # Handle ping requests
        #         try:
        #             ping_data, client_address = self.ping_socket.recvfrom(8)

        #             # Echo back to client
        #             self.ping_socket.sendto(ping_data, client_address)

        #             # Logging
        #             self.server_logger.info(
        #                 'INFO: Received communication from {%s}.' % (
        #                     client_address[0]
        #                 )
        #             )

        #         except socket.timeout:
        #             continue

        # except KeyboardInterrupt:

        #     # Logging
        #     self.server_logger.info(
        #         'INFO: Audio streaming terminated successfully.'
        #     )

        # finally:
        #     self.stream.stop_stream()
        #     self.stream.close()
        #     self.audio.terminate()

        #     if audera.TRANSMIT_MODE == 'TCP':
        #         self.conn.close()

        #     if audera.TRANSMIT_MODE == 'UDP':
        #         self.audio_socket.close()

        #     self.ping_socket.close()
