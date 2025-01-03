""" Audio playback session """

from __future__ import annotations
from typing import Literal, List
from dataclasses import dataclass, field
import json
from pytensils import config


@dataclass
class Session():
    """ A `class` that represents an audio playback session.

    Attributes
    ----------
    name: `str`
        The name of the audio playback session.
    uuid: `str`
        A unique universal identifier.
    mac_address: `str`
        The media access control address of the network adapter.
    address: `str`
        The ip-address of the network device.
    group: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    players: `List[str]`
        A list of unique universal identifiers for `audera.struct.player.Player` objects.
    provider: `Literal['audera']`
        The manufacturer / provider of the network device.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """
    name: str
    uuid: str
    mac_address: str
    address: str
    group: str = field(default='')
    players: List[str] = field(default_factory=list)
    provider: Literal['audera'] = field(default='audera')
    volume: float = field(default=0.50)

    def from_dict(dict_object: dict) -> Session:
        """ Returns an `audera.struct.player.Session` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to an `audera.struct.player.Session` object.
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
                'group',
                'players',
                'provider',
                'volume'
            ] if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Session(**dict_object)

    def from_config(config: config.Handler) -> Session:
        """ Returns an `audera.struct.player.Session` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Session.from_dict(config.to_dict()['session'])

    def to_dict(self):
        """ Returns an `audera.struct.player.Session` object as a `dict`. """
        return {
            'name': self.name,
            'uuid': self.uuid,
            'mac_address': self.mac_address,
            'address': self.address,
            'group': self.group,
            'players': self.players,
            'provider': self.provider,
            'volume': self.volume
        }

    def __repr__(self):
        """ Returns an `audera.struct.player.Session` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.player.Session`
            An instance of an `audera.struct.player.Session` object.
        """
        if isinstance(compare, Session):
            return (
                self.name == compare.name
                and self.uuid == compare.uuid
                and self.mac_address == compare.mac_address
                and self.address == compare.address
                and self.group == compare.group
                and self.players == compare.players
                and self.provider == compare.provider
                and self.volume == compare.volume
            )

        return False
