""" Audio-player """

from __future__ import annotations
from typing import Literal, List
from dataclasses import dataclass, field
import json
from zeroconf import ServiceInfo
from pytensils import config, utils


@dataclass
class Player():
    """ A `class` that represents a remote audio output player.

    Attributes
    ----------
    name: `str`
        The name of the audio player.
    uuid: `str`
        A unique universal identifier.
    mac_address: `str`
        The media access control address of the network adapter.
    address: `str`
        The ip-address of the network device.
    provider: `Literal['audera']`
        The manufacturer / provider of the network device.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    channels: `Literal[1, 2]`
        Either `1` for mono or `2` for stereo audio playback.
    enabled: `bool`
        Whether the audio player can be added to playback / groups.
    connected: `bool`
        Whether the audio player is connected to the network.
    playing: `bool`
        Whether the audio player is currently playing.
    """
    name: str
    uuid: str
    mac_address: str
    address: str
    provider: Literal['audera'] = field(default='audera')
    volume: float = field(default=0.50)
    channels: Literal[1, 2] = field(default=2)
    enabled: bool = field(default=True)
    connected: bool = field(default=True)
    playing: bool = field(default=True)

    @property
    def short_uuid(self) -> str:
        """ Returns the short unique universal identifier of the `audera.struct.player.Player`
        object.
        """
        return self.uuid.split('-')[0]

    def from_dict(dict_object: dict) -> Player:
        """ Returns an `audera.struct.player.Player` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to an `audera.struct.player.Player` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in [
                'name',
                'uuid',
                'mac_address',
                'address',
                'provider',
                'volume',
                'channels',
                'enabled',
                'connected',
                'playing'
            ] if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        # Convert datatypes
        dict_object['uuid'] = str(dict_object['uuid'])

        return Player(**dict_object)

    def from_config(config: config.Handler) -> Player:
        """ Returns an `audera.struct.player.Player` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Player.from_dict(config.to_dict()['player'])

    def from_service_info(info: ServiceInfo) -> Player:
        """ Returns an `audera.struct.player.Player` object from a `zeroconf.ServiceInfo` object.

        Parameters
        ----------
        info: `zeroconf.ServiceInfo`
            An instance of the `zeroconf` multi-cast DNS service parameters.
        """

        # Unpack the mDNS service info into a dictionary
        properties = {
            key.decode('utf-8'): value.decode('utf-8') if isinstance(value, bytes) else value
            for key, value in info.properties.items()
        }

        return Player(
            name=utils.as_type(properties['name'], 'str'),
            uuid=utils.as_type(properties['uuid'], 'str'),
            mac_address=utils.as_type(properties['mac_address'], 'str'),
            address=utils.as_type(properties['address'], 'str'),
            provider=utils.as_type(properties['provider'], 'str'),
            volume=utils.as_type(properties['volume'], 'float'),
            channels=utils.as_type(properties['channels'], 'int'),
            enabled=utils.as_type(properties['enabled'], 'bool'),
            connected=utils.as_type(properties['connected'], 'bool'),
            playing=utils.as_type(properties['playing'], 'bool'),
        )

    def to_dict(self):
        """ Returns an `audera.struct.player.Player` object as a `dict`. """
        return {
            'name': self.name,
            'uuid': self.uuid,
            'mac_address': self.mac_address,
            'address': self.address,
            'provider': self.provider,
            'volume': self.volume,
            'channels': self.channels,
            'enabled': self.enabled,
            'connected': self.connected,
            'playing': self.playing
        }

    def __repr__(self):
        """ Returns an `audera.struct.player.Player` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.player.Player`
            An instance of an `audera.struct.player.Player` object.
        """
        if isinstance(compare, Player):
            return (
                self.name == compare.name
                and self.uuid == compare.uuid
                and self.mac_address == compare.mac_address
                and self.address == compare.address
                and self.provider == compare.provider
                and self.volume == compare.volume
                and self.channels == compare.channels
                and self.enabled == compare.enabled
                and self.connected == compare.connected
                and self.playing == compare.playing
            )

        return False


@dataclass
class Group():
    """ A `class` that represents a group of remote output audio players.

    Attributes
    ----------
    name: `str`
        The name of the group player.
    uuid: `str`
        A unique universal identifier.
    players: `List[str]`
        A list of unique universal identifiers for `audera.struct.player.Player` objects.
    provider: `Literal['audera']`
        The manufacturer / provider of the network device.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    enabled: `bool`
        Whether the audio player can be added to playback / groups.
    playing: `bool`
        Whether the audio player is currently playing.
    """
    name: str
    uuid: str
    players: List[str] = field(default_factory=list)
    provider: Literal['audera'] = field(default='audera')
    volume: float = field(default=0.50)
    enabled: bool = field(default=True)
    playing: bool = field(default=False)

    def from_dict(dict_object: dict) -> Group:
        """ Returns an `audera.struct.player.Group` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to an `audera.struct.player.Group` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in [
                'name',
                'uuid',
                'players',
                'provider',
                'volume',
                'enabled',
                'playing'
            ] if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        # Convert datatypes
        dict_object['uuid'] = str(dict_object['uuid'])

        return Group(**dict_object)

    def from_config(config: config.Handler) -> Group:
        """ Returns an `audera.struct.player.Group` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Group.from_dict(config.to_dict()['group'])

    def to_dict(self):
        """ Returns an `audera.struct.player.Group` object as a `dict`. """
        return {
            'name': self.name,
            'uuid': self.uuid,
            'players': self.players,
            'provider': self.provider,
            'enabled': self.enabled,
            'volume': self.volume,
            'playing': self.playing
        }

    def __repr__(self):
        """ Returns an `audera.struct.player.Group` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.player.Group`
            An instance of an `audera.struct.player.Group` object.
        """
        if isinstance(compare, Group):
            return (
                self.name == compare.name
                and self.uuid == compare.uuid
                and self.players == compare.players
                and self.provider == compare.provider
                and self.enabled == compare.enabled
                and self.volume == compare.volume
                and self.playing == compare.playing
            )

        return False
