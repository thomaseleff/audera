""" Device configuration-layer """

from typing import Union
import os
from pytensils import config
from audera import audio
from audera.dal import path


PATH: Union[str, os.PathLike] = path.HOME
FILE_NAME: str = 'device.json'
DTYPES: dict = {
    'device': {
        'index': 'int'
    }
}


def exists() -> bool:
    """ Returns `True` when the device configuration file exists. """
    if os.path.isfile(
        os.path.abspath(os.path.join(PATH, FILE_NAME))
    ):
        return True
    else:
        return False


def create() -> config.Handler:
    """ Creates the device configuration file and returns the contents
    as a `pytensils.config.Handler` object.
    """

    # Create the device configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'device': audio.Device.get_default_device().to_dict()})

    return Config


def get() -> config.Handler:
    """ Returns the contents of the device configuration as a
    `pytensils.config.Handler` object. """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create() -> config.Handler:
    """ Creates or reads the device configuration file and returns the contents as
    a `pytensils.config.Handler` object.
    """
    if exists():
        return get()
    else:
        return create()


def save(device: audio.Device) -> config.Handler:
    """ Saves the device configuration to `~/.audera/device.json`.

    Parameters
    ----------
    device: `audera.audio.Device`
        An instance of an `audera.audio.Device` object.
    """

    # Create the device configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name=FILE_NAME,
        create=True
    )
    Config = Config.from_dict({'device': device.to_dict()})

    return Config


def update(new: audio.Device) -> config.Handler:
    """ Updates the device configuration file `~/.audera/device.json`.

    Parameters
    ----------
    new: `audera.audio.Device`
        An instance of an `audera.audio.Device` object.
    """

    # Read the configuration file
    Config = get_or_create()

    # Convert the config to an audio device object
    Device = audio.Device.from_config(config=Config)

    # Compare and update
    if not Device == new:

        # Update the device configuration object and write to the configuration file
        Config = Config.from_dict({'device': new.to_dict()})

        return Config

    else:
        return Config


def get_device() -> audio.Device:
    """ Returns the contents of the configuration file as an `audio.Device` object. """
    return audio.Device.from_dict(get_or_create().to_dict()['device'])


def get_device_index() -> int:
    """ Returns the current selected audio device index as an `int`. """

    # Read the configuration file
    Device = get_device()
    return Device.index


def delete():
    if exists():
        os.remove(os.path.join(PATH, FILE_NAME))
