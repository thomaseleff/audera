""" Multi-cast DNS management

Allows for resolving hostnames to IP addresses within local networks
that do not include a local name server.
"""

from typing import Union
import logging
import socket
from zeroconf import Zeroconf, ServiceInfo


def get_local_ip_address():
    """ Connects to an external ip-address, which determines the appropriate
    interface for the connection, and then returns the local ip-address used
    in that connection.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("208.67.220.123", 80))  # DuckDuckGo
        ip_address = s.getsockname()[0]
    return ip_address


class Runner:
    """ A `class` that represents a multi-cast DNS service runner. """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        info: ServiceInfo
    ):
        """ Creates an instance of the multi-cast DNS service runner.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        zc: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        info: `zeroconf.ServiceInfo`
            An instance of the `zeroconf` multi-cast DNS service parameters.
        """

        # Logging
        self.logger = logger

        # Initialize mDNS
        self.zc: Zeroconf = zc
        self.info: ServiceInfo = info
        # self.time_out: float = time_out

    def register(self):
        """ Registers the mDNS service within the local network. """

        # Register the mDNS service
        try:
            self.zc.register_service(self.info)

            # Logging
            self.logger.info(
                "mDNS service {%s} registered successfully at {%s:%s}." % (
                    self.info.type,
                    socket.inet_ntoa(self.info.addresses[0]),
                    self.info.port
                )
            )

        except Exception as e:  # All other `mDNS service errors`

            # Logging
            self.logger.critical(
                '[%s] mDNS service {%s} registration failed. %s.' % (
                    type(e).__name__,
                    self.info.type,
                    str(e)
                )
            )
            # self.logger.info(
            #     ''.join([
            #         "The mDNS service encountered",
            #         " an error, retrying in %.2f [sec.]." % (
            #             self.time_out
            #         )
            #     ])
            # )

            # Timeout
            # time.sleep(self.time_out)

    def unregister(self):
        """ Unregisters the mDNS service within the local network. """
        if self.zc and self.info:

            # Logging
            self.logger.info("mDNS service un-registered successfully.")

            # Exit
            self.zc.unregister_service(self.info)
            self.zc.close()


class Connection:
    """ A `class` that represents a multi-cast DNS service client connection. """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        type: str,
        name: str,
        time_out: float
    ):
        """ Creates an instance of the multi-cast DNS service client connection.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        zc: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        type: `str`
            The type of multi-cast DNS service to search.
        name: `str`
            The name of the multi-cast DNS service to search.
        time_out: `float`
            The time-out in seconds of the connection.
        """

        # Logging
        self.logger = logger

        # Initialize mDNS
        self.zc: Zeroconf = zc
        self.type: str = type
        self.name: str = name

        # Initialize retry parameters
        self.max_retries: int = 5
        self.retry: int = 1
        self.time_out: float = time_out

    def browse(self) -> Union[ServiceInfo, None]:
        """ Browse for a the mDNS service within the local network. """

        # Initialize the mDNS service information
        info = None

        while self.retry < self.max_retries + 1:

            # Logging
            self.logger.info(
                ''.join([
                    "Waiting on a connection to the mDNS service,",
                    " retrying in %.2f [sec.]." % (
                        self.time_out
                    )
                ])
            )

            # Get the mDNS service information
            info: ServiceInfo = self.zc.get_service_info(
                type_=self.type,
                name=self.name,
                timeout=self.time_out*1000
            )

            # Retry until the maximum retries is exceeded
            if not info:
                self.retry += 1

            if self.retry > self.max_retries:
                self.logger.info("mDNS service {%s} is unavailable." % (self.type))
                break

            # Return the mDNS service information
            if info:
                self.logger.info("mDNS service {%s} discovered successfully at {%s:%s}." % (
                        self.type,
                        socket.inet_ntoa(info.addresses[0]),
                        info.port
                    )
                )
                break

        # Exit
        self.zc.close()

        return info
