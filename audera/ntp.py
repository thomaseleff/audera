""" Network time protocol (ntp) synchronizer """

from typing import Union, Literal
import ntplib


class Synchronizer:
    """ A `class` that represents a network time protocol server. """
    def __init__(
        self,
        server: Union[str, Literal['pool.ntp.org', 'time.cloudflare.com', 'time.google.com']] = 'time.cloudflare.com',
        port: int = 123
    ):
        """ An instance of the network time protocol server for syncing system time.

        Parameters
        ----------
        server: `Union[str, Literal['pool.ntp.org', 'time.cloudflare.com', 'time.google.com']]`
            The network time protocol server.
        port: `int`
            The network time protocol port.
        """
        self.server = server
        self.port = port
        self.client = ntplib.NTPClient()

    def sync(self) -> ntplib.NTPStats:
        """ Returns the current time statistics from the network time protocol server.
        """
        return self.client.request(self.server, version=3, port=self.port)

    def offset(self) -> float:
        """ Reterns the offset between the network time protocol server and the local machine time.
        """
        response = self.sync()
        return response.offset
