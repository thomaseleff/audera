""" Identity configuration-layer """

from typing import Union
import os
from pytensils import config
from audera.struct import identity
from audera.dal import path


PATH: Union[str, os.PathLike] = path.HOME
FILE_NAME: str = 'identity.json'
DTYPES: dict = {
    'identity': {
        'name': 'str',
        'uuid': 'str',
        'mac_address': 'str',
        'address': 'str'
    }
}


def exists() -> bool:
    """ Returns `True` when the identity configuration file exists. """
    if os.path.isfile(
        os.path.abspath(os.path.join(PATH, FILE_NAME))
    ):
        return True
    else:
        return False


def create(identity_: identity.Identity) -> config.Handler:
    """ Creates the identity configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    identity_: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """

    # Create the identity configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'identity': identity_.to_dict()})

    return Config


def get() -> config.Handler:
    """ Returns the contents of the identity configuration as a
    `pytensils.config.Handler` object.
    """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create(identity_: identity.Identity) -> config.Handler:
    """ Creates or reads the identity configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    identity_: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """
    if exists():
        return get()
    else:
        return create(identity_)


def save(identity_: identity.Identity) -> config.Handler:
    """ Saves the identity configuration to `~/.audera/identity.json`.

    Parameters
    ----------
    identity_: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """

    # Create the identity configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'identity': identity_.to_dict()})

    return Config


def update(new: identity.Identity) -> config.Handler:
    """ Updates the identity configuration file `~/.audera/identity.json`.

    Parameters
    ----------
    new: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """

    # Read the configuration file
    Config = get_or_create(new)

    # Convert the config to an audio identity object
    identity_: identity.Identity = identity.Identity.from_config(config=Config)

    # Compare and update
    if not identity_ == new:

        # Update the identity configuration object and write to the configuration file
        Config = Config.from_dict(
            {
                'identity': {
                    'name': identity_.name,  # Retain the existing name
                    'uuid': new.uuid,
                    'mac_address': new.mac_address,
                    'address': new.address
                }
            }
        )

        return Config

    else:
        return Config


def delete():
    """ Deletes the configuration file associated with a `audera.struct.identity.Identity` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.identity.Identity` object.
    """
    if exists():
        os.remove(os.path.join(PATH, FILE_NAME))


def get_identity() -> identity.Identity:
    """ Returns the identity of the remote audio device as an `audera.struct.identity.Identity` object. """
    return identity.Identity.from_config(get())


def get_identity_mac_address() -> str:
    """ Returns the mac-address of the remote audio device as an `str`. """

    # Read the configuration file
    identity_ = get_identity()
    return identity_.mac_address


def get_identity_ip_address(uuid: str) -> str:
    """ Returns the ip-address of the remote audio device as an `str`. """

    # Read the configuration file
    identity_ = get_identity()
    return identity_.address
