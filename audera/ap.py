""" Access point management """

import subprocess
import platform
from audera import struct


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
        self.os = platform.system()

    def start(self):
        """ Starts a wi-fi access point for credential sharing. """

        if self.os == 'Linux':
            subprocess.run(
                ['nmcli', 'device', 'wifi', 'hotspot', 'ifname', 'wlan0', 'con-name', self.hostname, 'ssid', self.hostname],
                check=True
            )
        else:
            raise AccessPointError()

    def stop(self) -> subprocess.CompletedProcess:
        """ Stops a wi-fi access point. """

        if self.os == 'Linux':
            subprocess.run(
                ['nmcli', 'connection', 'delete', self.hostname],
                check=True
            )
        else:
            raise AccessPointError()


# Exception(s)
class AccessPointError(Exception):
    pass
