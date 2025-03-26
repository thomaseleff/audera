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

        subprocess.run(
            ['nmcli', 'device', 'wifi', 'hotspot', 'ifname', 'wlan0', 'con-name', self.hostname, 'ssid', self.hostname],
            check=True
        )

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
