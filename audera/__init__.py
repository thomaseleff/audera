""" audera

`audera` is an open-source multi-room audio streaming system written in Python
for DIY home audio enthusiasts.
"""

from typing import List
import errno

from audera import netifaces, ntp, mdns, struct, dal, devices, sessions, logging

__all__ = ['netifaces', 'ntp', 'mdns', 'struct', 'dal', 'devices', 'sessions', 'logging']

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

# Network configuration
MDNS_TYPE = f"_{NAME.lower()}._tcp.local."
STREAM_PORT: int = 5000
PING_PORT: int = 5001

# Synchronization configuration
SYNC_INTERVAL: int = 600  # The time interval in seconds between time synchonization
PING_INTERVAL: float = 30  # The time interval in seconds between pings

# Packet configuration
PACKET_TERMINATOR: bytes = b'\xFF\xFE\xFD\xFC'  # The bytes suffix that indicates the end of a packet
PACKET_ESCAPE: bytes = b'\x00'  # The bytes escape character to avoid false packet terminator sequences

# Audio playback configuration
PLAYBACK_DELAY: float = 0.5  # The initial playback delay in seconds
BUFFER_SIZE: int = 5  # The number of audio packets to buffer before playback
MAX_PLAYBACK_DELAY: float = 5  # The max. playback delay in seconds for high jitter
MIN_PLAYBACK_DELAY: float = 1  # The min. playback delay in seconds for low jitter
RTT_HISTORY_SIZE: int = 10  # The history size for round-trip time measurements
LOW_JITTER: float = 0.01  # The threshold for identifying low-jitter.
HIGH_JITTER: float = 0.05  # The threshold for identifying high-jitter.
LOW_RTT: float = 0.1  # The threshold for identifying low-rtt.
HIGH_RTT: float = 0.5  # The threshold for identifying high-rtt.

# Orchestration configuration
TIME_OUT: float = 5  # The general time-out in seconds for network operations


# Errors
class errors:
    """ A `class` that represents static error codes. """
    DEVICE_ERROR: int = errno.EIO
