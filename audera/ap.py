""" Access point management """

from typing_extensions import Literal
import subprocess
import time
from audera import struct, platform, netifaces


class AccessPoint():
    """ A `class` that represents a Wi-Fi access point.

    Parameters
    ----------
    name: `str`
        The name of the access point.
    url: `str`
        The url web-address for accessing the access point.
    identity: `audera.struct.identity.Identity`
        The `audera.struct.identity.Identity` containing the unique identity of the
            network device.
    interface: `str`
        The wireless network interface.
    ap_interface: `str`
        The network interface for the access point.
    """

    @platform.requires('dietpi')
    def __init__(
        self,
        name: str,
        url: str,
        identity: struct.identity.Identity,
        interface: Literal['wlan0'],
        ap_interface: Literal['ap0'] = 'ap0'
    ):
        """ Creates an instance of a Wi-Fi access point.

        Parameters
        ----------
        name: `str`
            The name of the access point.
        url: `str`
            The url web-address for accessing the access point.
        identity: `audera.struct.identity.Identity`
            The `audera.struct.identity.Identity` containing the unique identity of the
                network device.
        interface: `Literal['wlan0']`
            The wireless network interface.
        ap_interface: `Literal['ap0']`
            The network interface for the access point.
        """
        self.url = url.replace('https://', '').replace('http://', '')
        self.interface = interface
        self.ap_interface = ap_interface
        self.hostname = '-'.join([name.strip().lower(), identity.short_uuid])

    @platform.requires('dietpi')
    def start(self):
        """ Starts a Wi-Fi access point for credential sharing. """
        self.create()
        self.up()

    @platform.requires('dietpi')
    def stop(self):
        """ Stops a Wi-Fi access point. """
        self.down()
        self.delete()

    @platform.requires('dietpi')
    def create(self):
        """ Creates the Wi-Fi access point connection. """

        # Stop network-manager
        try:
            subprocess.run(
                ["systemctl", "stop", "NetworkManager"],
                check=True
            )
        except subprocess.CalledProcessError:
            pass  # Network-manager is not running

        # Configure the access point interface
        subprocess.run(
            ["iw", "dev", f"{self.interface}", "interface", "add", f"{self.ap_interface}", "type", "__ap"],
            check=True
        )
        subprocess.run(
            ["ip", "link", "set", f"{self.ap_interface}", "up"],
            check=True
        )

        # Configure dnsmasq

        # Re-configure dnsmasq each time the access-point is started because the
        #   player identity may change overtime.

        with open("/etc/NetworkManager/dnsmasq.conf", "w") as f:
            f.write(f"interface={self.ap_interface}\n")
            f.write("dhcp-range=10.42.0.10,10.42.0.100,12h\n")
            f.write("dhcp-option=3,10.42.0.1\n")
            f.write("dhcp-option=6,10.42.0.1\n")
            f.write(f"address=/{self.url}/10.42.0.1")

        # Restart network-manager
        subprocess.run(
            ["systemctl", "restart", "NetworkManager"],
            check=True
        )

        # Add the access point connection
        if not self.connection_exists():

            # Create the access point
            add_connection_result = subprocess.run(
                [
                    "nmcli", "connection", "add",
                    "type", "wifi",
                    "ifname", f"{self.ap_interface}",
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
                ]
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
                            self.ap_interface
                        )
                    )

    @platform.requires('dietpi')
    def delete(self):
        """ Delets the Wi-Fi access point connection. """
        if self.connection_exists():
            try:
                subprocess.run(
                    ["nmcli", "connection", "delete", f"{self.hostname}"],
                    check=True
                )
            except subprocess.CalledProcessError:
                raise AccessPointError(
                    'Unable to delete the Wi-Fi access point {%s} on interface {%s}.' % (
                        self.hostname,
                        self.ap_interface
                    )
                )

    @platform.requires('dietpi')
    def up(self):
        """ Resumes the Wi-Fi access point. """
        try:
            subprocess.run(
                ["nmcli", "connection", "up", f"{self.hostname}"],
                check=True
            )
        except subprocess.CalledProcessError:
            raise AccessPointError(
                'Unable to start the Wi-Fi access point {%s} on interface {%s}.' % (
                    self.hostname,
                    self.ap_interface
                )
            )

    @platform.requires('dietpi')
    def down(self):
        """ Pauses the Wi-Fi access point. """
        if self.connection_exists():
            try:
                subprocess.run(
                    ["nmcli", "connection", "down", f"{self.hostname}"],
                    check=True
                )
            except subprocess.CalledProcessError:
                raise AccessPointError(
                    'Unable to stop the Wi-Fi access point {%s} on interface {%s}.' % (
                        self.hostname,
                        self.ap_interface
                    )
                )

    @platform.requires('dietpi')
    def connection_exists(self) -> bool:
        """ Returns whether the network-manager connection exists. """
        return netifaces.connection_exists(con_name=self.hostname)


# Exception(s)
class AccessPointError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
