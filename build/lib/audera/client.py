""" audera-client """

import socket
import pyaudio
import time
import struct
from collections import deque
import statistics

import audera


class App():
    """ A `class` that represents the `audera` client application. """

    def __init__(self):
        """ Initializes an instance of the `audera` client application. """

        # Initialize PyAudio and Sockets
        self.audio = pyaudio.PyAudio()
        self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.audio_socket.bind(("", audera.AUDIO_PORT))

        self.ping_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ping_socket.settimeout(1)  # Timeout for pings

        # Start audio output stream
        self.stream = self.audio.open(
            format=audera.FORMAT,
            channels=audera.CHANNELS,
            rate=audera.RATE,
            output=True,
            frames_per_buffer=audera.CHUNK
        )

        # Buffer and variables for adaptive buffer management
        self.buffer = deque()
        self.buffer_time = audera.BASE_BUFFER_TIME
        self.rtt_history = []

    def measure_rtt(self):

        """ Send a ping to the server and measure RTT. """
        self.ping_socket.sendto(b'ping', (audera.SERVER_IP, audera.PING_PORT))
        start_time = time.time()
        try:
            _, _ = self.ping_socket.recvfrom(8)  # Receive pong response
            return time.time() - start_time
        except socket.timeout:
            return None

    def adjust_buffer_time(self):
        """ Adjust buffer time based on RTT and jitter. """

        if len(self.rtt_history) >= audera.RTT_HISTORY_SIZE:
            mean_rtt = statistics.mean(self.rtt_history)
            jitter = statistics.stdev(self.rtt_history)

            # Adjust buffer based on RTT and jitter
            if jitter < 0.01 and mean_rtt < 0.1:  # Low jitter and RTT
                new_buffer_time = max(
                    audera.MIN_BUFFER_TIME, self.buffer_time - 0.05
                )
            elif jitter > 0.05 or mean_rtt > 0.15:  # High jitter or RTT
                new_buffer_time = min(
                    audera.MAX_BUFFER_TIME, self.buffer_time + 0.05
                )
            else:
                new_buffer_time = self.buffer_time  # Maintain current buffer

            # Apply and clear RTT history
            self.buffer_time = new_buffer_time
            self.rtt_history.clear()

    def run(self):
        """ Streams audio and handles ping-requests. """

        # Logging
        print("Receiving and playing audio.")

        try:
            last_ping_time = 0
            while True:

                # Periodically measure RTT
                if time.time() - last_ping_time > audera.PING_INTERVAL:
                    rtt = self.measure_rtt()
                    if rtt is not None:
                        self.rtt_history.append(rtt)
                    self.adjust_buffer_time()
                    last_ping_time = time.time()

                # Receive and buffer audio
                packet, _ = self.audio_socket.recvfrom(
                    audera.CHUNK * audera.CHANNELS * 2 + 8
                )
                timestamp, data = struct.unpack("d", packet[:8])[0], packet[8:]
                target_play_time = timestamp + self.buffer_time
                current_time = time.time()

                # Buffer and play packets on time
                self.buffer.append((target_play_time, data))
                while self.buffer and self.buffer[0][0] <= current_time:
                    _, play_data = self.buffer.popleft()
                    self.stream.write(play_data)

        except KeyboardInterrupt:
            print("Stopping client...")
        finally:
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()
            self.audio_socket.close()
            self.ping_socket.close()
