""" Network interfaces """

import socket
import netifaces
import uuid
import subprocess
import platform


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


def check_internet_access() -> bool:
    """ Returns `True` when the network device is connected to the internet. """
    try:

        # Try to resolve Cloudflare's public DNS to check if DNS resolution works
        socket.gethostbyname("www.cloudflare.com")

        # Ping Cloudflare DNS to check for internet access
        os_name = platform.system()

        if os_name == 'Linux' or os_name == 'Darwin':  # macOS and Linux
            result = subprocess.run(['ping', '-c', '1', '1.1.1.1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return True
            else:
                return False

        if os_name == 'Windows':
            result = subprocess.run(['ping', '-n', '1', '1.1.1.1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return True
            else:
                return False

    except socket.gaierror:
        return False


def get_local_ip_address() -> str:
    """ Connects to an external ip-address, which determines the appropriate
    interface for the connection, and then returns the local ip-address used
    in that connection.
    """
    if check_internet_access():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('1.1.1.1', 80))  # Cloudflare
            ip_address = s.getsockname()[0]
        return str(ip_address)
    else:
        raise NetworkConnectionError()


def get_available_networks():
    """ Retrieves the list of available wi-fi networks for a network device. """

    if platform.system() == 'Linux':
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'SSID', 'device', 'wifi', 'list'],
                capture_output=True,
                text=True,
                check=True
            )
            networks = result.stdout.strip().split('\n')
            return [net for net in networks if net]
        except subprocess.CalledProcessError:
            return []
    else:
        raise NetworkConnectionError()


def connect_to_network(
    ssid: str,
    password: str
):
    """ Connects to a wi-fi network {ssid} with {password}.

    Parameters
    ----------
    ssid: `str`
        The name of the wi-fi network.
    password: `str`
        The password of the wi-fi network.
    """
    if platform.system() == 'Linux':
        subprocess.run(
            ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
            check=True
        )
    else:
        raise NetworkConnectionError()


# Exception(s)
class NetworkConnectionError(Exception):
    pass
