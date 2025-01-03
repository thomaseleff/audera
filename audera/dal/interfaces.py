""" Interface configuration-layer """

from typing import Union
import os
from pytensils import config
from audera.struct import audio
from audera.dal import path


PATH: Union[str, os.PathLike] = path.HOME
FILE_NAME: str = 'interface.json'
DTYPES: dict = {
    'interface': {
        'format': 'int',
        'rate': 'int',
        'channels': 'int',
        'chunk': 'int'
    }
}


def exists() -> bool:
    """ Returns `True` when the interface configuration file exists. """
    if os.path.isfile(
        os.path.abspath(os.path.join(PATH, FILE_NAME))
    ):
        return True
    else:
        return False


def create() -> config.Handler:
    """ Creates the interface configuration file and returns the contents
    as a `pytensils.config.Handler` object.
    """

    # Create the interface configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'interface': audio.Interface().to_dict()})

    return Config


def get() -> config.Handler:
    """ Returns the contents of the interface configuration as a
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


def get_or_create() -> config.Handler:
    """ Creates or reads the interface configuration file and returns the contents as
    a `pytensils.config.Handler` object.
    """
    if exists():
        return get()
    else:
        return create()


def save(interface: audio.Interface) -> config.Handler:
    """ Saves the interface configuration to `~/.audera/interface.json`.

    Parameters
    ----------
    interface: `audera.struct.audio.Interface`
        An instance of an `audera.struct.audio.Interface` object.
    """

    # Create the interface configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'interface': interface.to_dict()})

    return Config


def update(new: audio.Interface) -> config.Handler:
    """ Updates the interface configuration file `~/.audera/interface.json`.

    Parameters
    ----------
    new: `audera.struct.audio.Interface`
        An instance of an `audera.struct.audio.Interface` object.
    """

    # Read the configuration file
    Config = get_or_create()

    # Convert the config to an audio interface object
    Interface = audio.Interface.from_config(config=Config)

    # Compare and update
    if not Interface == new:

        # Update the interface configuration object and write to the configuration file
        Config = Config.from_dict({'interface': new.to_dict()})

        return Config

    else:
        return Config


def delete():
    """ Deletes the configuration file associated with a `audera.struct.audio.Interface` object. """
    if exists():
        os.remove(os.path.join(PATH, FILE_NAME))


def get_interface() -> audio.Interface:
    """ Returns the current selected audio interface as an `audera.struct.audio.Interface` object. """
    return audio.Interface.from_config(get_or_create())


def get_interface_format() -> int:
    """ Returns the current selected audio format as an `int`. """

    # Read the configuration file
    Interface = get_interface()
    return Interface.format


def get_interface_rate() -> int:
    """ Returns the current selected audio sampling frequency as an `int`. """

    # Read the configuration file
    Interface = get_interface()
    return Interface.rate


def get_interface_channels() -> int:
    """ Returns the current selected audio channels as an `int`. """

    # Read the configuration file
    Interface = get_interface()
    return Interface.channels


def get_interface_chunk() -> int:
    """ Returns the current selected audio chunk size as an `int`. """

    # Read the configuration file
    Interface = get_interface()
    return Interface.chunk
