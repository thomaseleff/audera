""" Audera

`audera` is an open-source multi-room audio streaming system written in Python
for DIY home entertainment enthusiasts.
"""

from typing import Union, List, Literal
import pyaudio

from audera import logging

__all__ = ['logging']

# Logo
LOGO: List[str] = [
    r" ________  ___  ___  ________  _______  ________  ________      ",
    r"|\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \     ",
    r"\ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \    ",
    r" \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \   ",
    r"  \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \  ",
    r"   \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\ ",
    r"    \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__| "
]
NAME: str = 'audera'
DESCRIPTION: str = ''.join([
    '`audera` is an open-source multi-room audio streaming system written in',
    ' Python for DIY home entertainment enthusiasts.'
])

# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: Literal[1, 2] = 1
RATE: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = 44100
AUDIO_PORT: int = 5000
PING_PORT: int = 5001
DEVICE_INDEX: Union[int, None] = None
TRANSMIT_MODE: Literal['TCP', 'UDP'] = 'TCP'

# Server configuration
SERVER_IP: str = "192.168.1.17"

# Client configuration
BASE_BUFFER_TIME: float = 0.2  # Base buffer time
MAX_BUFFER_TIME: float = 0.5  # Maximum buffer in seconds for high jitter
MIN_BUFFER_TIME: float = 0.1  # Minimum buffer time for low jitter
PING_INTERVAL: float = 2.0  # Ping every 2 seconds
RTT_HISTORY_SIZE: int = 10  # History size for RTT measurements
