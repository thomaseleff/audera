""" Network time protocol (ntp) synchronizer """

from typing import Literal
import time
import ntplib


class Synchronizer:
    """ A `class` that represents a network time protocol server. """
    def __init__(
        self,
        server: Literal['pool.ntp.org'] = 'pool.ntp.org'
    ):
        """ An instance of the network time protocol server for syncing
        system time.

        Parameters
        ----------
        server: `Literal['pool.ntp.org']`
            The network time protocol server.
        """
        self.server = server
        self.Client = ntplib.NTPClient()

    def sync(self) -> ntplib.NTPStats:
        """ Retrieves the current time statistics from the network
        time protocol server.
        """
        return self.Client.request(self.server, version=3)

    def offset(self) -> float:
        """ Reterns the offset between the network time protocol
        server and the local machine time.
        """
        response = self.sync()
        return response.tx_time - time.time()
