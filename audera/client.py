""" audera-client """

import socket
import pyaudio
import time
import struct
from collections import deque
import statistics

# Client configuration
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
AUDIO_PORT = 5000
PING_PORT = 5001  # Port for ping-pong
SERVER_IP = "192.168.x.x"
BASE_BUFFER_TIME = 0.2  # Base buffer time
MAX_BUFFER_TIME = 0.5  # Maximum buffer in seconds for high jitter
MIN_BUFFER_TIME = 0.1  # Minimum buffer time for low jitter
PING_INTERVAL = 2  # Ping every 2 seconds
RTT_HISTORY_SIZE = 10  # History size for RTT measurements

# Initialize PyAudio and Sockets
audio = pyaudio.PyAudio()
audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
audio_socket.bind(("", AUDIO_PORT))

ping_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ping_socket.settimeout(1)  # Timeout for pings

# Start audio output stream
stream = audio.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    output=True,
    frames_per_buffer=CHUNK
)

# Buffer and variables for adaptive buffer management
buffer = deque()
buffer_time = BASE_BUFFER_TIME
rtt_history = []

print("Receiving audio and adapting buffer size based on RTT...")


def measure_rtt():
    """Send a ping to the server and measure RTT."""
    ping_socket.sendto(b'ping', (SERVER_IP, PING_PORT))
    start_time = time.time()
    try:
        _, _ = ping_socket.recvfrom(8)  # Receive pong response
        return time.time() - start_time
    except socket.timeout:
        return None


def adjust_buffer_time():
    """Adjust buffer time based on RTT and jitter."""
    if len(rtt_history) >= RTT_HISTORY_SIZE:
        mean_rtt = statistics.mean(rtt_history)
        jitter = statistics.stdev(rtt_history)

        # Adjust buffer based on RTT and jitter
        if jitter < 0.01 and mean_rtt < 0.1:  # Low jitter and RTT
            new_buffer_time = max(MIN_BUFFER_TIME, buffer_time - 0.05)
        elif jitter > 0.05 or mean_rtt > 0.15:  # High jitter or RTT
            new_buffer_time = min(MAX_BUFFER_TIME, buffer_time + 0.05)
        else:
            new_buffer_time = buffer_time  # Maintain current buffer

        # Apply and clear RTT history
        global buffer_time
        buffer_time = new_buffer_time
        rtt_history.clear()


try:
    last_ping_time = 0
    while True:
        # Periodically measure RTT
        if time.time() - last_ping_time > PING_INTERVAL:
            rtt = measure_rtt()
            if rtt is not None:
                rtt_history.append(rtt)
            adjust_buffer_time()
            last_ping_time = time.time()

        # Receive and buffer audio
        packet, _ = audio_socket.recvfrom(CHUNK * CHANNELS * 2 + 8)
        timestamp, data = struct.unpack("d", packet[:8])[0], packet[8:]
        target_play_time = timestamp + buffer_time
        current_time = time.time()

        # Buffer and play packets on time
        buffer.append((target_play_time, data))
        while buffer and buffer[0][0] <= current_time:
            _, play_data = buffer.popleft()
            stream.write(play_data)

except KeyboardInterrupt:
    print("Stopping client...")
finally:
    stream.stop_stream()
    stream.close()
    audio.terminate()
    audio_socket.close()
    ping_socket.close()
