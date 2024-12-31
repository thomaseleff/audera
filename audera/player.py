""" Audio-player """

from __future__ import annotations
from typing import Literal, List
from dataclasses import dataclass, field
import json
from pytensils import config


@dataclass
class NetworkInterface():
    """ A `class` that represents a network interface. """
    uuid: str
    mac_address: str
    address: str

    def from_dict(dict_object: dict) -> NetworkInterface:
        """ Returns a `NetworkInterface` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to a `NetworkInterface` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in [
                'uuid',
                'mac_address',
                'address',
            ] if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return NetworkInterface(**dict_object)

    def to_dict(self):
        """ Returns the `NetworkInterface` object as a `dict`. """
        return {
            'uuid': self.uuid,
            'mac_address': self.mac_address,
            'address': self.address
        }

    def __repr__(self):
        """ Returns the `NetworkInterface` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.audio.NetworkInterface`
            An instance of an `audera.audio.NetworkInterface` object.
        """
        if isinstance(compare, NetworkInterface):
            return (
                self.uuid == compare.uuid
                and self.mac_address == compare.mac_address
                and self.address == compare.address
            )

        return False


@dataclass
class Player():
    """ A `class` that represents an audio player. """
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

    def from_dict(dict_object: dict) -> Player:
        """ Returns a `Player` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to a `Player` object.
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

        return Player(**dict_object)

    def from_config(config: config.Handler) -> Player:
        """ Returns a `Player` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Player.from_dict(config.to_dict()['player'])

    def to_dict(self):
        """ Returns the `Player` object as a `dict`. """
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
        """ Returns the `Player` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.audio.Player`
            An instance of an `audera.audio.Player` object.
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
    """ A `class` that represents a group of audio players. """
    name: str
    uuid: str
    players: List[Player]
    provider: Literal['audera'] = field(default='audera')
    volume: float = field(default=0.50)
    enabled: bool = field(default=True)
    playing: bool = field(default=False)

    def from_dict(dict_object: dict) -> Group:
        """ Returns a `Group` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to a `Group` object.
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

        return Group(**dict_object)

    def to_dict(self):
        """ Returns the `Group` object as a `dict`. """
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
        """ Returns the `Group` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.audio.Group`
            An instance of an `audera.audio.Group` object.
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
