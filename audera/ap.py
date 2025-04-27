""" Access point management """

from typing_extensions import Literal
import subprocess
import time
from audera import struct, platform


class AccessPoint():
    """ A `class` that represents a Wi-Fi access point.

    Parameters
    ----------
    name: `str`
        The name of the access point.
    url: `str`
        The url web-address for accessing the access point.
    interface: `str`
        The network interface for the access point.
    identity: `audera.struct.identity.Identity`
        The `audera.struct.identity.Identity` containing the unique identity of the
            network device.
    """

    def __init__(
        self,
        name: str,
        url: str,
        interface: Literal['wlan0'],
        identity: struct.identity.Identity
    ):
        """ Creates an instance of a Wi-Fi access point.

        Parameters
        ----------
        name: `str`
            The name of the access point.
        url: `str`
            The url web-address for accessing the access point.
        interface: `str`
            The network interface for the access point.
        identity: `audera.struct.identity.Identity`
            The `audera.struct.identity.Identity` containing the unique identity of the
                network device.
        """
        self.url = url.replace('https://', '').replace('http://', '')
        self.interface = interface
        self.hostname = '-'.join([name.strip().lower(), identity.short_uuid])

    @platform.requires('dietpi')
    def start(self):
        """ Starts a Wi-Fi access point for credential sharing. """

        # Configure dnsmasq

        # Re-configure dnsmasq each time the access-point is started because the
        #   player identity may change overtime.

        with open("/etc/NetworkManager/dnsmasq.conf", "w") as f:
            f.write(f"interface={self.interface}\n")
            f.write("dhcp-range=10.42.0.10,10.42.0.100,12h\n")
            f.write("dhcp-option=3,10.42.0.1\n")
            f.write("dhcp-option=6,10.42.0.1\n")
            f.write(f"address=/{self.url}/127.0.0.1")  # The default nicegui ip-address

        # Add the access point connection
        if not self.connection_exists():
            add_connection_result = subprocess.run(
                [
                    "nmcli", "connection", "add",
                    "type", "wifi",
                    "ifname", "wlan0",
                    "con-name", f"{self.hostname}",
                    "autoconnect", "no",
                    "ssid", f"{self.hostname}",
                    "802-11-wireless.mode", "ap",
                    "802-11-wireless.band", "bg",
                    "802-11-wireless.channel", "6",
                    "ipv4.method", "shared",
                    "ipv4.addresses", "10.42.0.1/24",
                    "ipv4.gateway", "10.42.0.1",
                    "ipv6.method", "ignore"
                ],
                check=True
            )

            # Wait for the service
            if add_connection_result.returncode == 0:

                # Check the service, time-out if the service fails to start after 10 seconds
                time_out = 0

                while time_out < 10:
                    time.sleep(1)

                    if self.connection_exists():
                        break

                    time_out += 1

                if not self.connection_exists():
                    raise AccessPointError(
                        'Unable to add the Wi-Fi access point connection {%s} on interface {%s}.' % (
                            self.hostname,
                            self.interface
                        )
                    )

        # Start the access point
        try:
            subprocess.run(
                ["nmcli", "connection", "up", self.hostname],
                check=True
            )
        except subprocess.CalledProcessError:
            raise AccessPointError(
                'Unable to start the Wi-Fi access point {%s} on interface {%s}.' % (
                    self.hostname,
                    self.interface
                )
            )

    @platform.requires('dietpi')
    def stop(self):
        """ Stops a Wi-Fi access point. """
        if self.connection_exists():
            try:
                subprocess.run(
                    ["nmcli", "connection", "down", self.hostname],
                    check=True
                )
            except subprocess.CalledProcessError:
                raise AccessPointError(
                    'Unable to stop the Wi-Fi access point {%s} on interface {%s}.' % (
                        self.hostname,
                        self.interface
                    )
                )

    @platform.requires('dietpi')
    def connection_exists(self) -> bool:
        """ Returns whether the network-manager connection exists. """
        try:
            subprocess.run(
                ["nmcli", "connection", "show", self.hostname],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except subprocess.CalledProcessError:
            return False


# Exception(s)
class AccessPointError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
