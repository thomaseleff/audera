""" Network interfaces """

from typing_extensions import Union
import asyncio
import socket
import netifaces
import uuid
import subprocess

from audera import platform


def get_gateway_ip_address():
    """ Returns the local gateway ip-address. """
    gateways = netifaces.gateways()
    gateway_address = gateways['default'][netifaces.AF_INET][0]
    return str(gateway_address)


def get_local_mac_address() -> str:
    """ Returns the local hardware mac-address. """
    mac = "%12X" % uuid.getnode()
    mac = ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
    return str(mac)


def connected() -> bool:
    """ Returns `True` when the network device is connected to the internet. """
    try:

        # Try to resolve Cloudflare's public DNS to check if DNS resolution works
        socket.gethostbyname("www.cloudflare.com")

        # Ping Cloudflare DNS to check for internet access
        if platform.NAME in ['dietpi', 'linux', 'darwin']:
            result = subprocess.run(['ping', '-c', '1', '1.1.1.1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return True
            else:
                return False

        elif platform.NAME == 'windows':
            result = subprocess.run(['ping', '-n', '1', '1.1.1.1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return True
            else:
                return False
        else:
            return False

    except socket.gaierror:
        return False


def get_local_ip_address() -> str:
    """ Connects to an external ip-address, which determines the appropriate
    interface for the connection, and then returns the local ip-address used
    in that connection.
    """
    if connected():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('1.1.1.1', 80))  # Cloudflare
            ip_address = s.getsockname()[0]
        return str(ip_address)
    else:
        raise NetworkConnectionError('Unable to determine the local ip-address.')


@platform.requires('dietpi')
async def connect(
    ssid: str,
    password: Union[str, None]
):
    """ Connects to a wi-fi network {ssid} with {password}.

    Parameters
    ----------
    ssid: `str`
        The name of the wi-fi network.
    password: `str`
        The password of the wi-fi network.
    """
    if not ssid:
        raise NetworkConnectionError('Invalid value. {ssid} cannot be empty.')

    if password:
        result = subprocess.run(
            ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
            check=True
        )
    else:
        result = subprocess.run(
            ['nmcli', 'device', 'wifi', 'connect', ssid],
            check=True
        )

    if result.returncode == 0:

        # Check connection
        time_out = 0

        while time_out < 10:
            await asyncio.sleep(1)

            if connected():
                break

            time_out += 1

        if not connected():
            raise InternetConnectionError('{%s} has no internet.' % ssid)

    elif result.returncode == 3:
        raise NetworkTimeoutError('Connection timed-out.')

    elif result.returncode == 10:
        raise NetworkNotFoundError('Invalid value. ssid {%s} does not exist.' % ssid)

    else:
        raise NetworkConnectionError('Unable to connect to {ssid}.')


# Exception(s)
class NetworkConnectionError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class NetworkTimeoutError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class NetworkNotFoundError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class InternetConnectionError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
