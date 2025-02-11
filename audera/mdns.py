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

from audera import struct, dal


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


class PlayerBroadcaster():
    """ A `class` that represents a multi-cast DNS service broadcaster for a remote
    audio output player.

    Parameters
    ----------
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    zc: `zeroconf.Zeroconf`
        An instance of the `zeroconf` multi-cast DNS service.
    player: `audera.struct.player.Player`
        An `audera.struct.player.Player` object.
    service_type: `str`
        The type of mDNS service to broadcast.
    service_description: `str`
        The description of the mDNS service.
    service_port: `int`
        The mDNS service broadcast port.
    """

    def __init__(
        self,
        logger: logging.Logger,
        zc: Zeroconf,
        player: struct.player.Player,
        service_type: str,
        service_description: str,
        service_port: int
    ):
        """ Creates an instance of the multi-cast DNS service broadcaster.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        zc: `zeroconf.Zeroconf`
            An instance of the `zeroconf` multi-cast DNS service.
        player: `audera.struct.player.Player`
            An `audera.struct.player.Player` object.
        service_type: `str`
            The type of mDNS service to broadcast.
        service_description: `str`
            The description of the mDNS service.
        service_port: `int`
            The mDNS service broadcast port.
        """

        # Logging
        self.logger = logger

        # Initialize mDNS
        self.zc: Zeroconf = zc
        self.player: struct.player.Player = player
        self.service_type: str = service_type
        self.service_description: str = service_description
        self.service_port: int = service_port

    @property
    def info(self) -> ServiceInfo:
        """ Returns a `zeroconf.ServiceInfo` object from the `audera.struct.player.Player` object. """
        return ServiceInfo(
            type_=self.service_type,
            name=self.registered_name,
            server=self.registered_name,
            addresses=[socket.inet_aton(self.player.address)],
            port=self.service_port,
            weight=0,
            priority=0,
            properties={**self.player.to_dict(), **{"description": self.service_description}}
        )

    @property
    def registered_name(self) -> str:
        """ Returns the registered name of the mDNS service from the `audera.struct.player.Player` object. """
        return 'raop@%s.%s' % (
                self.player.mac_address.replace(':', ''),
                self.service_type
            )  # (r)emote (a)udio (o)utput (p)layer

    async def register(self):
        """ Registers the mDNS service and connects the remote audio output player to the local network. """

        try:

            # Register the mDNS service
            self.zc.register_service(info=self.info)

            # Connect the remote audio output player
            self.player = dal.players.connect(self.player.uuid)

            # Logging
            self.logger.info(
                "mDNS service {%s} registered successfully at {%s:%s}." % (
                    self.service_type,
                    self.player.address,
                    self.service_port
                )
            )

        except Exception as e:  # All other `mDNS service errors`

            # Logging
            self.logger.error(
                '[%s] mDNS service {%s} registration failed. %s.' % (
                    type(e).__name__,
                    self.service_type,
                    str(e)
                )
            )

    def update(
        self,
        player: struct.player.Player
    ):
        """ Updates the mDNS service within the local network from
        an `audera.struct.player.Player` object.

        Parameters
        ----------
        player: `audera.struct.player.Player`
            An `audera.struct.player.Player` object.
        """

        # Update the mDNS service
        if not self.player == player:
            try:
                self.player = player
                self.zc.update_service(self.info)

                # Connect the remote audio output player
                self.player = dal.players.connect(self.player.uuid)

                # Logging
                self.logger.info(
                    "mDNS service {%s} updated successfully at {%s:%s}." % (
                        self.service_type,
                        self.player.address,
                        self.service_port
                    )
                )

            except Exception as e:  # All other `mDNS service errors`

                # Logging
                self.logger.error(
                    '[%s] mDNS service {%s} update failed. %s.' % (
                        type(e).__name__,
                        self.service_type,
                        str(e)
                    )
                )

    def unregister(self):
        """ Unregisters the mDNS service and disconnects the remote audio output player from the local network. """
        if self.zc and self.player:

            # Exit
            self.zc.unregister_service(self.info)
            self.zc.close()

            # Disconnect the remote audio output player
            self.player = dal.players.disconnect(self.player.uuid)

            # Logging
            self.logger.info("mDNS services un-registered successfully.")


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

    async def browse(self):
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

        # Connect remote audio output player
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and (name not in self.players):

                player: struct.player.Player = struct.player.Player.from_service_info(info)
                player.connected = True
                player = dal.players.update(player)
                self.players[name] = player

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} connected." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

        # Disconnect remote audio output player
        if state_change == ServiceStateChange.Removed:
            if name in self.players:

                player = self.players[name]
                player = dal.players.disconnect(player.uuid)

                del self.players[name]

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} disconnected." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

        # Update remote audio output player
        if state_change == ServiceStateChange.Updated:
            info = zeroconf.get_service_info(service_type, name)
            if info and (name in self.players):

                player: struct.player.Player = struct.player.Player.from_service_info(info)
                player = dal.players.update(player)
                self.players[name] = player

                # Logging
                self.logger.info(
                    "Remote audio output player {%s (%s)} updated." % (
                        player.name,
                        player.uuid.split('-')[0]  # Short uuid of the player
                    )
                )

    def refresh(self):
        """ Refresh the mDNS service browser. """

        # Cancel the existing mDNS service browser
        if self.browser:
            self.browser.cancel()

        # Restart the mDNS service browser
        self.browser = ServiceBrowser(
            zc=self.zc,
            type_=self.type_,
            handlers=[self.on_service_state_change_callback]
        )

    def close(self):
        """ Closes the remote audio output player mDNS service browser within the local network. """
        if self.browser:
            self.zc.close()
