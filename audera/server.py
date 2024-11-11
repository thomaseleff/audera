""" audera-server """

import socket
import pyaudio
import time
import struct

# Server configuration
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
AUDIO_PORT = 5000
PING_PORT = 5001  # Additional port for ping-pong

# Initialize PyAudio and Socket for audio
audio = pyaudio.PyAudio()
audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
audio_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

# Additional socket for handling ping requests
ping_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ping_socket.bind(("0.0.0.0", PING_PORT))

# Start audio stream capture
stream = audio.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

print("Streaming audio and handling ping requests...")

try:
    while True:
        # Handle audio streaming
        data = stream.read(CHUNK)
        timestamp = time.time()
        packet = struct.pack("d", timestamp) + data
        audio_socket.sendto(packet, ("<broadcast>", AUDIO_PORT))

        # Quick timeout for non-blocking ping handling
        ping_socket.settimeout(0.01)

        # Handle ping requests
        try:
            ping_data, client_address = ping_socket.recvfrom(8)

            # Echo back to client
            ping_socket.sendto(ping_data, client_address)
        except socket.timeout:
            continue

except KeyboardInterrupt:
    print("Stopping server...")
finally:
    stream.stop_stream()
    stream.close()
    audio.terminate()
    audio_socket.close()
    ping_socket.close()
