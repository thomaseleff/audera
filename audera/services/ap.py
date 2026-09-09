"""Access point management"""

import socket
import time
from typing import Literal

from audera import io
from audera.errors import CommandError
from audera.services import netifaces, platform, system


class AccessPoint:
    """A `class` that represents a Wi-Fi access point.

    Parameters
    ----------
    name: `str`
        The name of the access point.
    url: `str`
        The url web-address for accessing the access point.
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
        interface: Literal['wlan0'],
        ap_interface: Literal['ap0'] = 'ap0',
    ):
        """Creates an instance of a Wi-Fi access point.

        Parameters
        ----------
        name: `str`
            The name of the access point.
        url: `str`
            The url web-address for accessing the access point.
        interface: `Literal['wlan0']`
            The wireless network interface.
        ap_interface: `Literal['ap0']`
            The network interface for the access point.
        """
        self.url = url.replace('https://', '').replace('http://', '')
        self.interface = interface
        self.ap_interface = ap_interface
        self.hostname = socket.gethostname()

    @platform.requires('dietpi')
    def start(self):
        """Starts a Wi-Fi access point for credential sharing."""
        self.create()
        self.up()

    @platform.requires('dietpi')
    def stop(self):
        """Stops a Wi-Fi access point."""
        self.down()
        self.delete()

    @platform.requires('dietpi')
    def create(self):
        """Creates the Wi-Fi access point connection."""

        # Stop both services that hold the wlan0 phy. While `wpa_supplicant` holds the phy, the
        # `iw ... interface add` below fails with EBUSY. A missing, stopped, or unreachable unit is
        # non-fatal here.
        for unit in ('NetworkManager', 'wpa_supplicant'):
            try:
                system.systemctl('stop', unit)
            except CommandError:
                pass  # not installed / not running / systemd unreachable

        # The `finally` always restarts NetworkManager, so a failure below never leaves it stopped.
        try:
            # Reset any stale access point interface before re-adding it.
            netifaces.delete_interface(self.ap_interface)

            # Configure the access point interface
            netifaces.add_ap_interface(self.interface, self.ap_interface)
            netifaces.set_link_up(self.ap_interface)

            # Configure dnsmasq

            # Re-configure dnsmasq each time the access-point is started because the
            #   player identity may change overtime.

            # `ipv4.method=shared` makes NetworkManager run its own dnsmasq for `ap0`, reading extra
            # config only from `dnsmasq-shared.d/`. NM owns DHCP, so this file holds only address
            # records; a `dhcp-range`/`interface=` line would collide and break dnsmasq startup.
            io.write_text(
                '/etc/NetworkManager/dnsmasq-shared.d/audera-captive.conf',
                '\n'.join(
                    [
                        f'address=/{self.url}/10.42.0.1',
                        # Wildcard: resolve every domain to the portal so setup opens on join.
                        'address=/#/10.42.0.1',
                    ]
                ),
            )

        finally:
            # Restart NetworkManager unconditionally. This is unguarded so a failed restart surfaces.
            # The restart blocks until NM is up, which exceeds the default 15s bound on a Pi Zero W
            # (armv6) while the wifi driver loads, so give it explicit headroom.
            system.systemctl('restart', 'NetworkManager', timeout=45)

        # Add the access point connection
        if not self.connection_exists():
            # Create the access point
            try:
                netifaces.connection_add(
                    'type',
                    'wifi',
                    'ifname',
                    f'{self.ap_interface}',
                    'con-name',
                    f'{self.hostname}',
                    'autoconnect',
                    'no',
                    'ssid',
                    f'{self.hostname}',
                    '802-11-wireless.mode',
                    'ap',
                    '802-11-wireless.band',
                    'bg',
                    '802-11-wireless.channel',
                    '6',
                    'ipv4.method',
                    'shared',
                    'ipv4.addresses',
                    '10.42.0.1/24',
                    'ipv4.gateway',
                    '10.42.0.1',
                    'ipv6.method',
                    'ignore',
                )
            except CommandError:
                raise AccessPointError(
                    'Unable to add the Wi-Fi access point connection {%s} on interface {%s}.'
                    % (self.hostname, self.ap_interface)
                )

            # Wait for the service, time-out if the service fails to start after 10 seconds
            time_out = 0

            while time_out < 10:
                time.sleep(1)

                if self.connection_exists():
                    break

                time_out += 1

            if not self.connection_exists():
                raise AccessPointError(
                    'Unable to add the Wi-Fi access point connection {%s} on interface {%s}.'
                    % (self.hostname, self.ap_interface)
                )

    @platform.requires('dietpi')
    def delete(self):
        """Delets the Wi-Fi access point connection."""
        if self.connection_exists():
            try:
                netifaces.connection_delete(self.hostname)
            except CommandError:
                raise AccessPointError(
                    'Unable to delete the Wi-Fi access point {%s} on interface {%s}.' % (self.hostname, self.ap_interface)
                )

        # Tear down the access point interface unconditionally; an absent interface is fine.
        netifaces.delete_interface(self.ap_interface)

    @platform.requires('dietpi')
    def up(self):
        """Resumes the Wi-Fi access point."""
        try:
            netifaces.connection_up(self.hostname)
        except CommandError:
            raise AccessPointError(
                'Unable to start the Wi-Fi access point {%s} on interface {%s}.' % (self.hostname, self.ap_interface)
            )

    @platform.requires('dietpi')
    def down(self):
        """Pauses the Wi-Fi access point."""
        if self.connection_exists():
            try:
                netifaces.connection_down(self.hostname)
            except CommandError:
                raise AccessPointError(
                    'Unable to stop the Wi-Fi access point {%s} on interface {%s}.' % (self.hostname, self.ap_interface)
                )

    @platform.requires('dietpi')
    def connection_exists(self) -> bool:
        """Returns whether the network-manager connection exists."""
        return netifaces.connection_exists(con_name=self.hostname)


# Exception(s)
class AccessPointError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
