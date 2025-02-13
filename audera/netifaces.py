""" Network interfaces """

import socket
import netifaces
import uuid


def get_gateway_ip_address():
    """ Returns the local gateway ip-address. """
    gateways = netifaces.gateways()
    gateway_address = gateways['default'][netifaces.AF_INET][0]
    return str(gateway_address)


def get_local_ip_address() -> str:
    """ Connects to an external ip-address, which determines the appropriate
    interface for the connection, and then returns the local ip-address used
    in that connection.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("208.67.220.123", 80))  # DuckDuckGo
        ip_address = s.getsockname()[0]
    return str(ip_address)


def get_local_mac_address() -> str:
    """ Returns the local hardware mac-address. """
    mac = "%12X" % uuid.getnode()
    mac = ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
    return str(mac)
