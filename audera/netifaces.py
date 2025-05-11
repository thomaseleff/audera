""" Network interfaces """

from typing_extensions import Union, Literal, Dict, List
import asyncio
import socket
import netifaces
import uuid
import subprocess

from audera import platform


def get_gateway_ip_address() -> str:
    """ Returns the local gateway ip-address. """
    gateways = netifaces.gateways()
    gateway_address = gateways['default'][netifaces.AF_INET][0]
    return str(gateway_address)


def get_interface_ip_address(interface: Literal['wlan0'] = 'wlan0') -> str:
    """ Returns the interface ip-address.

    Parameters
    ----------
    interface: `str`
        The network interface for the Wi-Fi connection.
    """
    address = netifaces.ifaddresses(interface)
    interface_address = address[netifaces.AF_INET][0]['addr']
    return str(interface_address)


def get_local_mac_address() -> str:
    """ Returns the local hardware mac-address. """
    mac = "%12X" % uuid.getnode()
    mac = ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
    return str(mac)


def connected(interface: Literal['wlan0'] = 'wlan0') -> bool:
    """ Returns `True` when the network device is connected to the internet.

    Parameters
    ----------
    interface: `str`
        The network interface for the Wi-Fi connection.
    """
    try:

        # Try to resolve Cloudflare's public DNS to check if DNS resolution works
        socket.gethostbyname("www.cloudflare.com")

        # Ping Cloudflare DNS to check for internet access
        if platform.NAME in ['dietpi', 'linux', 'darwin']:
            result = subprocess.run(
                ['ping', '-c', '3', '-I', interface, '1.1.1.1'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if result.returncode == 0:
                return True
            else:
                return False

        elif platform.NAME == 'windows':
            result = subprocess.run(
                ['ping', '-n', '3', '1.1.1.1'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
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
def get_preferred_security_type(supported_security_types: Union[List[str], None]) -> str:
    """ Returns the preferred security type from a list of supported security types. WPA / WPA2
    security protocols are preferred, with experimental support for WPA3. WEP and WPA2-enterprise
    are not currently supported.

    Parameters
    ----------
    supported_security_types: `Union[List[str], None]`
        The list of supported security protocols.
    """

    if not supported_security_types:
        return None  # Open network

    supported_security_types = [s.upper() for s in supported_security_types]

    if any(x in supported_security_types for x in ["WPA2", "WPA1", "WPA"]):
        return "wpa-psk"  # WPA/WPA2
    if any(x in supported_security_types for x in ["SAE", "WPA3"]):
        return "sae"  # WPA3
    else:
        raise NetworkConnectionError(
            "Unknown supported security types ['%s']." % ("', '".join(supported_security_types))
        )


@platform.requires('dietpi')
def has_supported_security_type(supported_security_types: Union[List[str], None]) -> bool:
    """ Returns `True` when there is a valid security type in the list of supported
    security types, otherwise returns `False`.

    Parameters
    ----------
    supported_security_types: `Union[List[str], None]`
        The list of supported security protocols.
    """
    if not supported_security_types:
        return True  # Open network

    if any(x in supported_security_types for x in ["WPA2", "WPA1", "WPA", "SAE", "WPA3"]):
        return True

    return False


@platform.requires('dietpi')
async def get_wifi_networks(interface: Literal['wlan0'] = 'wlan0') -> Dict[str, List[str]]:
    """ Returns a dictionary of network SSIDs and their security types.

    Parameters
    ----------
    interface : Literal['wlan0']
        The Wi-Fi network interface to scan on.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmcli", "--terse",
            "--fields", "SSID,SECURITY",
            "device", "wifi", "list",
            "ifname", interface,
            "rescan", "yes",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return {}

        output = stdout.decode().strip()
        networks = {}
        for line in output.split('\n'):
            if not line:
                continue
            parts = line.split(":")
            ssid = parts[0].strip()
            security = parts[1].strip() if len(parts) > 1 else ""
            if ssid and ssid != "--":
                networks[ssid] = security.split() if security else []

        return {k: v for k, v in networks.items() if has_supported_security_type(v)}

    except Exception:
        return {}


@platform.requires('dietpi')
def connection_exists(con_name: str) -> bool:
    """ Returns whether the network-manager connection exists.

    Parameters
    ----------
    con_name: `str`
        The connection name.
    """
    try:
        subprocess.run(
            ["nmcli", "connection", "show", f"{con_name}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        return False


@platform.requires('dietpi')
async def connect(
    ssid: str,
    supported_security_types: Union[List[str], None],
    password: Union[str, None],
    interface: Literal['wlan0'] = 'wlan0'
):
    """ Connects to a Wi-Fi network {ssid} with {password}.

    Parameters
    ----------
    ssid: `str`
        The name of the Wi-Fi network.
    supported_security_types: `Union[List[str], None]`
        The list of supported security protocols.
    password: `Union[str, None]`
        The password of the Wi-Fi network.
    interface: `Literal['wlan0']`
        The network interface for Wi-Fi connections.
    """
    if not ssid:
        raise NetworkConnectionError('Invalid value. {ssid} cannot be empty.')

    if supported_security_types and not password:
        raise NetworkConnectionError('Invalid value. {password} cannot be empty for a secure network.')

    if password and not supported_security_types:
        raise NetworkConnectionError('Invalid value. {supported_security_types} cannot be empty for a secure network.')

    # Delete the connection if it already exists
    if connection_exists(con_name=ssid):
        delete_connection_result = subprocess.run(
            ["nmcli", "connection", "delete", f"{ssid}"],
            check=True
        )

        # Wait for the service
        if delete_connection_result.returncode == 0:

            # Check the service, time-out if the service fails to start after 10 seconds
            time_out = 0

            while time_out < 10:
                await asyncio.sleep(1)

                if not connection_exists(con_name=ssid):
                    break

                time_out += 1

            if connection_exists(con_name=ssid):
                raise NetworkConnectionError(
                    'Unable to delete Wi-Fi connection {%s} on interface {%s}.' % (
                        ssid,
                        interface
                    )
                )

    # Add the connection
    if password:
        add_connection_result = subprocess.run(
            [
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", f"{interface}",
                "con-name", f"{ssid}",
                "ssid", f"{ssid}",
                "wifi-sec.key-mgmt", f"{get_preferred_security_type(supported_security_types)}",
                "wifi-sec.psk", f"{password}",
                "connection.autoconnect", "yes"
            ],
            check=True
        )
    else:
        add_connection_result = subprocess.run(
            [
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", f"{interface}",
                "con-name", f"{ssid}",
                "ssid", f"{ssid}",
                "connection.autoconnect", "yes"
            ],
            check=True
        )

    # Wait for the service
    if add_connection_result.returncode == 0:

        # Check the service, time-out if the service fails to start after 10 seconds
        time_out = 0

        while time_out < 10:
            await asyncio.sleep(1)

            if connection_exists(con_name=ssid):
                break

            time_out += 1

        if not connection_exists(con_name=ssid):
            raise NetworkConnectionError(
                'Unable to add Wi-Fi connection {%s} on interface {%s}.' % (
                    ssid,
                    interface
                )
            )

    result = subprocess.run(
        ["nmcli", "connection", "up", f"{ssid}"],
        check=True
    )

    if result.returncode == 0:

        # Check connection
        time_out = 0

        while time_out < 10:
            await asyncio.sleep(1)

            if connected(interface):
                break

            time_out += 1

        if not connected(interface):
            raise InternetConnectionError('Network `%s` has no internet.' % ssid)

    elif result.returncode == 3:
        raise NetworkTimeoutError('Connection timed-out.')

    elif result.returncode == 10:
        raise NetworkNotFoundError('Invalid value. Network `%s` does not exist.' % ssid)

    else:
        raise NetworkConnectionError('Unable to connect to `%s`.' % ssid)


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
