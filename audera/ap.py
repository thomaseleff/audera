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
        The name of the access-point.
    url: `str`
        The url web-address for accessing the access-point.
    interface: `str`
        The network interface for the access-point.
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
            The name of the access-point.
        url: `str`
            The url web-address for accessing the access-point.
        interface: `str`
            The network interface for the access-point.
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

        # Configure hostapd
        with open("/etc/hostapd/hostapd.conf", "w") as f:
            f.write(f"interface={self.interface}\n")
            f.write("driver=nl80211\n")
            f.write(f"ssid={self.hostname}\n")
            f.write("hw_mode=g\n")
            f.write("channel=6\n")
            f.write("wmm_enabled=0\n")
            f.write("macaddr_acl=0\n")
            f.write("auth_algs=1\n")
            f.write("ignore_broadcast_ssid=0\n")

        # Update the hostapd service
        with open("/etc/default/hostapd", "w") as f:
            f.write("DAEMON_CONF=\"/etc/hostapd/hostapd.conf\"\n")

        # Start hostapd
        subprocess.run(["sudo", "systemctl", "unmask", "hostapd"], check=True)
        try:
            hostapd_result = subprocess.run(["sudo", "systemctl", "start", "hostapd"], check=True)
        except subprocess.CalledProcessError as e:
            raise AccessPointError("Failed to start hostapd. %s" % e)

        # Wait for the service
        if hostapd_result.returncode == 0:

            # Check the service, time-out if the service fails to start after 10 seconds
            time_out = 0

            while time_out < 10:
                time.sleep(1)

                if self.hostapd_is_active():
                    break

                time_out += 1

            if not self.hostapd_is_active():
                raise AccessPointError(
                    'Unable to start the Wi-Fi access-point {%s} on interface {%s}.' % (
                        self.hostname,
                        self.interface
                    )
                )

        # Configure dnsmasq
        with open("/etc/dnsmasq.conf", "w") as f:
            f.write(f"interface={self.interface}\n")
            f.write(f"address=/{self.url}/127.0.0.1")

        # Start dnsmasq
        subprocess.run(["sudo", "systemctl", "unmask", "dnsmasq"], check=True)
        try:
            dnsmasq_result = subprocess.run(["sudo", "systemctl", "start", "dnsmasq"], check=True)
        except subprocess.CalledProcessError as e:
            raise AccessPointError("Failed to start dnsmasq. %s" % e)

        # Wait for the service
        if dnsmasq_result.returncode == 0:

            # Check the service, time-out if the service fails to start after 10 seconds
            time_out = 0

            while time_out < 10:
                time.sleep(1)

                if self.dnsmasq_is_active():
                    break

                time_out += 1

            if not self.dnsmasq_is_active():
                raise AccessPointError(
                    'Unable to start the DNS server to route traffic from {%s} to {127.0.0.1} on interface {%s}.' % (
                        'https://%s' % self.url,
                        self.interface
                    )
                )

    @platform.requires('dietpi')
    def stop(self):
        """ Stops a Wi-Fi access point. """

        if self.hostapd_is_active():
            try:
                subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
            except subprocess.CalledProcessError as e:
                raise AccessPointError("Failed to stop hostapd. %s" % e)

        if self.dnsmasq_is_active():
            try:
                subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
            except subprocess.CalledProcessError as e:
                raise AccessPointError("Failed to stop dnsmasq. %s" % e)

    @platform.requires('dietpi')
    def hostapd_is_active() -> bool:
        """ Returns the active status of the Wi-Fi access point. """
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', 'hostapd'],
                check=True,
                capture_output=True
            )
            return result.stdout.decode().strip() == 'active'
        except subprocess.CalledProcessError:
            return False

    @platform.requires('dietpi')
    def dnsmasq_is_active() -> bool:
        """ Returns the active status of the local DNS server service. """

        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', 'dnsmasq'],
                check=True,
                capture_output=True
            )
            return result.stdout.decode().strip() == 'active'
        except subprocess.CalledProcessError:
            return False


# Exception(s)
class AccessPointError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
