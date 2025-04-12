""" Access point management """

import subprocess
from audera import struct, platform


class AccessPoint():
    """ A `class` that represents a wi-fi access point.

    Parameters
    ----------
    name: `str`
        The name of the access-point.
    identity: `audera.struct.identity.Identity`
        The `audera.struct.identity.Identity` containing the unique identity of the
            network device.
    """

    def __init__(
        self,
        name: str,
        identity: struct.identity.Identity
    ):
        """ Creates an instance of a wi-fi access point.

        Parameters
        ----------
        name: `str`
            The name of the access-point.
        identity: `audera.struct.identity.Identity`
            The `audera.struct.identity.Identity` containing the unique identity of the
                network device.
        """
        self.hostname = '-'.join([name.strip().lower(), identity.short_uuid])

    @platform.requires('dietpi')
    def start(self):
        """ Starts a wi-fi access point for credential sharing. """

        # Configure hostapd
        with open("/etc/hostapd/hostapd.conf", "w") as f:
            f.write("interface=wlan0\n")
            f.write("driver=nl80211\n")
            f.write(f"ssid={self.hostname}\n")
            f.write("hw_mode=g\n")
            f.write("channel=6\n")
            f.write("wmm_enabled=0\n")
            f.write("macaddr_acl=0\n")
            f.write("auth_algs=1\n")
            f.write("ignore_broadcast_ssid=0\n")
            f.write("wpa=2\n")
            f.write("rsn_pairwise=CCMP\n")
            f.write(f"hostname={self.hostname}\n")

        # Enable hostapd
        with open("/etc/default/hostapd", "a") as f:
            f.write("DAEMON_CONF=\"/etc/hostapd/hostapd.conf\"\n")

        # Start hostapd
        subprocess.run(["sudo", "systemctl", "unmask", "hostapd"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "hostapd"], check=True)
        subprocess.run(["sudo", "systemctl", "start", "hostapd"], check=True)

        # Configure dnsmasq
        with open("/etc/dnsmasq.conf", "a") as f:
            f.write("interface=wlan0\n")
            f.write("dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h\n")

        # Enable dnsmasq
        subprocess.run(["sudo", "systemctl", "enable", "dnsmasq"], check=True)

        # Start dnsmasq
        subprocess.run(["sudo", "systemctl", "restart", "dnsmasq"], check=True)

    @platform.requires('dietpi')
    def stop(self):
        """ Stops a wi-fi access point. """

        subprocess.run(
            ['nmcli', 'connection', 'delete', self.hostname],
            check=True
        )


# Exception(s)
class AccessPointError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
