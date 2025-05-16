""" Remote audio device identity """

from __future__ import annotations
from dataclasses import dataclass
import coolname
import uuid
import json
from pytensils import config


def generate_cool_name(num: int = 2) -> str:
    """ Generates a unique name.

    Parameters
    ----------
    num: `int`
        The number of words in the name.
    """
    return str(coolname.generate_slug(num))


def generate_uuid_from_mac_address(mac_address: str) -> str:
    """ Generates a unique universal identifier from a mac-address.

    Parameters
    ----------
    mac_address: `str`
        The media access control address of the network adapter.
    """
    return str(
        uuid.uuid3(
            namespace=uuid.NAMESPACE_DNS,
            name=mac_address.replace(':', '')
        )
    )


@dataclass
class Identity():
    """ A `class` that represents the identity of a remote audio device.

    Attributes
    ----------
    name: `str`
        The name of the remote audio output device.
    uuid: `str`
        A unique universal identifier.
    mac_address: `str`
        The media access control address of the network adapter.
    address: `str`
        The ip-address of the remote audio output device.
    """
    name: str
    uuid: str
    mac_address: str
    address: str

    @property
    def short_uuid(self) -> str:
        """ Returns the short unique universal identifier of the `audera.struct.identity.Identity`
        object.
        """
        return self.uuid.split('-')[0]

    def from_dict(dict_object: dict) -> Identity:
        """ Returns an `audera.struct.player.Identity` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to an `audera.struct.player.Identity` object.
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

        return Identity(**dict_object)

    def from_config(config: config.Handler) -> Identity:
        """ Returns an `audera.struct.player.Identity` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Identity.from_dict(config.to_dict()['identity'])

    def to_dict(self):
        """ Returns an `audera.struct.player.Identity` object as a `dict`. """
        return {
            'name': self.name,
            'uuid': self.uuid,
            'mac_address': self.mac_address,
            'address': self.address
        }

    def __repr__(self):
        """ Returns an `audera.struct.player.Identity` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.player.Identity`
            An instance of an `audera.struct.player.Identity` object.
        """
        if isinstance(compare, Identity):
            return (self.mac_address == compare.mac_address)

        return False
