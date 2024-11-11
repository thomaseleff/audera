""" audera-server """

import socket
import pyaudio
import time
import struct

import audera


class App():
    """ A `class` that represents the `audera` server application. """

    def __init__(self):
        """ Initializes an instance of the `audera` server application. """

        # Initialize PyAudio and Socket for audio
        self.audio = pyaudio.PyAudio()

        # Assign device-index
        # --TODO: The name of the device should be set dynamically
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if "Line 1" in device_info.get("name", ""):
                audera.DEVICE_INDEX = i
                break

        if audera.DEVICE_INDEX is None:
            print("ERROR: 'Line 1 (Virtual Audio Cable)' not found.")
            self.audio.terminate()

        # Initialize socket for audio
        self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.audio_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Initialize socket for ping-requests
        self.ping_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ping_socket.bind(("0.0.0.0", audera.PING_PORT))

        # Open the audio stream capture
        self.stream = self.audio.open(
            rate=audera.RATE,
            channels=audera.CHANNELS,
            format=audera.FORMAT,
            input=True,
            input_device_index=audera.DEVICE_INDEX,
            frames_per_buffer=audera.CHUNK
        )

    def run(self):
        """ Streams audio and handles ping-requests. """

        # Logging
        print("Streaming audio.")

        try:
            while True:

                # Handle audio streaming
                data = self.stream.read(audera.CHUNK)
                timestamp = time.time()
                packet = struct.pack("d", timestamp) + data
                self.audio_socket.sendto(
                    packet, ("<broadcast>", audera.AUDIO_PORT)
                )

                # Quick timeout for non-blocking ping handling
                self.ping_socket.settimeout(0.01)

                # Handle ping requests
                try:
                    ping_data, client_address = self.ping_socket.recvfrom(8)

                    # Echo back to client
                    self.ping_socket.sendto(ping_data, client_address)

                except socket.timeout:
                    continue

        except KeyboardInterrupt:
            print("Stopping server...")
        finally:
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()
            self.audio_socket.close()
            self.ping_socket.close()
