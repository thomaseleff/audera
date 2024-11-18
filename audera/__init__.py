""" Audera

`audera` is an open-source multi-room audio streaming system written in Python
for DIY home audio enthusiasts.
"""

from typing import Union, List, Literal
import errno
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
    ' Python for DIY home audio enthusiasts.'
])

# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: Literal[1, 2] = 2
RATE: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = 44100
DEVICE_INDEX: Union[int, None] = None

# Server configuration
SERVER_IP: str = "192.168.1.17"
STREAM_PORT: int = 5000
PING_PORT: int = 5001

# Client configuration
BUFFER_SIZE: int = 5  # The number of audio packets to buffer before playback
BUFFER_TIME: float = 0.2  # The initial buffer time
MAX_BUFFER_TIME: float = 0.5  # The max. buffer-time in seconds for high jitter
MIN_BUFFER_TIME: float = 0.1  # The min. buffer-time in seconds for low jitter
PING_INTERVAL: float = 2  # The time interval in seconds between pings
RTT_HISTORY_SIZE: int = 10  # The history size for round-trip time measurements
TIME_OUT: float = 5  # The time-out in seconds of the server connection
LOW_JITTER: float = 0.01  # The threshold for identifying low-jitter.
HIGH_JITTER: float = 0.05  # The threshold for identifying high-jitter.
LOW_RTT: float = 0.1  # The threshold for identifying low-RTT.
HIGH_RTT: float = 0.15  # The threshold for identifying high-RTT.


# Errors
class errors:
    """ A `class` that represents static error codes. """
    DEVICE_ERROR: int = errno.EIO
