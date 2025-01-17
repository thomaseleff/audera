""" Device configuration-layer """

from typing import Union, Literal
import os
from pytensils import config
from audera.struct import audio
from audera.dal import path


PATH: Union[str, os.PathLike] = path.HOME
DTYPES: dict = {
    'device': {
        'name': 'str',
        'index': 'int',
        'type': 'str'
    }
}


def exists(type_: Literal['input', 'output']) -> bool:
    """ Returns `True` when the device configuration file exists.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """
    if os.path.isfile(
        os.path.abspath(os.path.join(PATH, '%s_device.json' % type_))
    ):
        return True
    else:
        return False


def create(type_: Literal['input', 'output']) -> config.Handler:
    """ Creates the device configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """

    # Create the device configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='%s_device.json' % type_,
        create=True
    )
    Config = Config.from_dict({'device': audio.Device.get_default_device(type_).to_dict()})

    return Config


def get(type_: Literal['input', 'output']) -> config.Handler:
    """ Returns the contents of the device configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='%s_device.json' % type_
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create(type_: Literal['input', 'output']) -> config.Handler:
    """ Creates or reads the device configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """
    if exists(type_):
        return get(type_)
    else:
        return create(type_)


def save(device: audio.Device) -> config.Handler:
    """ Saves the device configuration to `~/.audera/device.json`.

    Parameters
    ----------
    device: `audera.struct.audio.Device`
        An instance of an `audera.struct.audio.Device` object.
    """

    # Create the device configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='%s_device.json' % device.type,
        create=True
    )
    Config = Config.from_dict({'device': device.to_dict()})

    return Config


def update(new: audio.Device) -> config.Handler:
    """ Updates the device configuration file `~/.audera/device.json`.

    Parameters
    ----------
    new: `audera.struct.audio.Device`
        An instance of an `audera.struct.audio.Device` object.
    """

    # Read the configuration file
    Config = get_or_create(new.type)

    # Convert the config to an audio device object
    Device = audio.Device.from_config(config=Config)

    # Compare and update
    if not Device == new:

        # Update the device configuration object and write to the configuration file
        Config = Config.from_dict({'device': new.to_dict()})

        return Config

    else:
        return Config


def delete(type_: Literal['input', 'output']):
    """ Deletes the configuration file associated with a `audera.struct.audio.Device` object.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """
    if exists(type_):
        os.remove(os.path.join(PATH, '%s_device.json' % type_))


def get_device(type_: Literal['input', 'output']) -> audio.Device:
    """ Returns the current selected audio device as an `audera.struct.audio.Device` object.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """
    return audio.Device.from_config(get_or_create(type_))


def get_device_name(type_: Literal['input', 'output']) -> int:
    """ Returns the current selected audio device name as an `str`.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """

    # Read the configuration file
    device = get_device(type_)
    return device.name


def get_device_index(type_: Literal['input', 'output']) -> int:
    """ Returns the current selected audio device index as an `int`.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """

    # Read the configuration file
    device = get_device(type_)
    return device.index


def get_device_type(type_: Literal['input', 'output']) -> int:
    """ Returns the current selected audio device type as an `str`.

    Parameters
    ----------
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """

    # Read the configuration file
    device = get_device(type_)
    return device.type
