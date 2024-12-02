""" Multicast DNS management

Allows for resoling hostnames to IP addresses within local networks
that do not include a local name server.
"""

import logging
from zeroconf import Zeroconf, ServiceInfo


class Service:
    """ A `class` that represents a multi-cast DNS server service. """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        info: ServiceInfo
    ):
        """ Creates an instance of the multi-cast DNS server service.

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

        try:
            self.zc.register_service(self.info)

            # Logging
            self.logger.info(
                "mDNS service {%s} registered successfully." % (
                    self.info.type
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
    pass
