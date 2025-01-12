""" Multi-cast DNS management

Allows for resolving hostnames to IP addresses within local networks
that do not include a local name server.
"""

from typing import Union, Dict
import logging
import uuid
import socket
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceStateChange
from threading import Event
from audera import dal, struct


def get_local_ip_address() -> str:
    """ Connects to an external ip-address, which determines the appropriate
    interface for the connection, and then returns the local ip-address used
    in that connection.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("208.67.220.123", 80))  # DuckDuckGo
        ip_address = s.getsockname()[0]
    return str(ip_address)


def get_local_mac_address() -> str:
    """ Returns the local hardware mac-address. """
    mac = "%12X" % uuid.getnode()
    mac = ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
    return str(mac)


class Broadcaster():
    """ A `class` that represents a multi-cast DNS service broadcaster.

    Parameters
    ----------
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    zc: `zeroconf.Zeroconf`
        An instance of the `zeroconf` multi-cast DNS service.
    info: `zeroconf.ServiceInfo`
        An instance of the `zeroconf` multi-cast DNS service parameters.
    """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        info: ServiceInfo
    ):
        """ Creates an instance of the multi-cast DNS service broadcaster.

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

    def register(self):
        """ Registers the mDNS service within the local network. """

        # Register the mDNS service
        try:
            self.zc.register_service(self.info, allow_name_change=True)

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
            self.logger.error(
                '[%s] mDNS service {%s} registration failed. %s.' % (
                    type(e).__name__,
                    self.info.type,
                    str(e)
                )
            )

    def update(self, info: ServiceInfo):
        """ Updates the mDNS service within the local network.

        Parameters
        ----------
        info: `zeroconf.ServiceInfo`
            An instance of the `zeroconf` multi-cast DNS service parameters.
        """

        # Update the mDNS service
        if not (
            self.info.type == info.type and
            self.info.name == info.name and
            self.info.addresses == info.addresses and
            self.info.port == info.port and
            self.info.properties == info.properties
        ):
            try:
                self.info = info
                self.zc.register_service(info, allow_name_change=True)

                # Logging
                self.logger.info(
                    "mDNS service {%s} updated successfully at {%s:%s}." % (
                        self.info.type,
                        socket.inet_ntoa(self.info.addresses[0]),
                        self.info.port
                    )
                )

            except Exception as e:  # All other `mDNS service errors`

                # Logging
                self.logger.error(
                    '[%s] mDNS service {%s} update failed. %s.' % (
                        type(e).__name__,
                        self.info.type,
                        str(e)
                    )
                )

    def unregister(self):
        """ Unregisters the mDNS service within the local network. """
        if self.zc and self.info:

            # Logging
            self.logger.info("mDNS services un-registered successfully.")

            # Exit
            self.zc.unregister_service(self.info)
            self.zc.close()


class Connection():
    """ A `class` that represents a multi-cast DNS service connection.

    Parameters
    ----------
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    zc: `zeroconf.Zeroconf`
        An instance of the `zeroconf` multi-cast DNS service.
    type_: `str`
        The type of multi-cast DNS service to search.
    name: `str`
        The name of the multi-cast DNS service to search.
    time_out: `float`
        The time-out in seconds of the connection.
    """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        type_: str,
        name: str,
        time_out: float
    ):
        """ Creates an instance of the multi-cast DNS service connection.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        zc: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        type_: `str`
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
        self.type_: str = type_
        self.name: str = name

        # Initialize retry parameters
        self.max_retries: int = 5
        self.retry: int = 1
        self.time_out: float = time_out

    def connect(self) -> Union[ServiceInfo, None]:
        """ Connect to an mDNS service within the local network by name. """

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
                type_=self.type_,
                name=self.name,
                timeout=self.time_out*1000
            )

            # Retry until the maximum retries is exceeded
            if not info:
                self.retry += 1

            if self.retry > self.max_retries:
                self.logger.info("mDNS service {%s} is unavailable." % (self.type_))
                break

            # Return the mDNS service information
            if info:
                self.logger.info("mDNS service {%s} discovered successfully at {%s:%s}." % (
                        self.type_,
                        socket.inet_ntoa(info.addresses[0]),
                        info.port
                    )
                )
                break

        # Exit
        self.zc.close()

        return info


class PlayerBrowser():
    """ A `class` that represents a multi-cast DNS service browser for remote
    audio output players.

    Parameters
    ----------
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    zc: `zeroconf.Zeroconf`
        An instance of the `zeroconf` multi-cast DNS service.
    type_: `str`
        The type of multi-cast DNS service to browse.
    time_out: `float`
        The time-out in seconds of the browser.
    """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        type_: str,
        time_out: float
    ):
        """ Creates an instance of the multi-cast DNS service browser for remote
        audio output players.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        zc: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        type_: `str`
            The type of multi-cast DNS service to browse.
        time_out: `float`
            The time-out in seconds of the browser.
        """

        # Logging
        self.logger = logger

        # Initialize mDNS
        self.zc: Zeroconf = zc
        self.type_: str = type_

        # Initialize timeout parameters
        self.delay: Event = Event()
        self.time_out: float = time_out

        # Initialize remote audio output players
        self.players: Dict[str, Union[ServiceInfo, None]] = {}

        # Initialize service browser
        self.browser: Union[ServiceBrowser, None] = None

    def browse(self) -> Union[ServiceInfo, None]:
        """ Browses for the remote audio output player mDNS service within the local network. """

        # Logging
        self.logger.info(
            ''.join([
                "Browsing for mDNS service {%s}." % (
                    self.type_
                )
            ])
        )

        self.browser = ServiceBrowser(
            zc=self.zc,
            type_=self.type_,
            handlers=[self.on_service_state_change_callback]
        )

    def on_service_state_change_callback(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: int
    ):
        """ Callback that manages the list of remote audio output players available on the local network
        for a specific multi-cast DNS service.

        Parameters
        ----------
        zeroconf: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        service_type: `str`
            The type of multi-cast DNS service to browse.
        name: `str`
            The name of the multi-cast DNS remote audio output player.
        state_change: `int`
            The browser state of the remote audio output player.
        """

        # Add remote audio output player
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:

                player: struct.player.Player = struct.player.Player.from_service_info(info)
                player.connected = True
                _ = dal.players.update(player)
                self.players[name] = player

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} connected." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

        # Remove remote audio output player
        elif state_change == ServiceStateChange.Removed:
            if name in self.players:

                player = self.players[name]
                player = dal.players.disconnect(player.uuid)

                # --TODO Remove the player from the session

                del self.players[name]

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} disconnected." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

        # Update remote audio output player
        elif state_change == ServiceStateChange.Updated:
            info = zeroconf.get_service_info(service_type, name)
            if info and (name in self.players):

                player: struct.player.Player = struct.player.Player.from_service_info(info)
                _ = dal.players.update(player)
                self.players[name] = player

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} updated." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

    def close(self):
        """ Closes the remote audio output player mDNS service browser within the local network. """
        if self.browser:
            self.zc.close()
