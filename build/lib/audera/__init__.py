""" Audera """

from typing import Union
import pyaudio

# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: int = 1
RATE: int = 44100
AUDIO_PORT: int = 5000
PING_PORT: int = 5001  # Additional port for ping-pong
DEVICE_INDEX: Union[int, None] = None

# Server configuration
SERVER_IP: str = "192.168.1.17"

# Client configuration
BASE_BUFFER_TIME: float = 0.2  # Base buffer time
MAX_BUFFER_TIME: float = 0.5  # Maximum buffer in seconds for high jitter
MIN_BUFFER_TIME: float = 0.1  # Minimum buffer time for low jitter
PING_INTERVAL: float = 2.0  # Ping every 2 seconds
RTT_HISTORY_SIZE: int = 10  # History size for RTT measurements
