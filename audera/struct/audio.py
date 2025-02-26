""" Audio-stream """

from __future__ import annotations
from typing import Literal
from dataclasses import dataclass, field
import json
import pyaudio
import numpy as np
from pytensils import config


# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: Literal[1, 2] = 2
RATE: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = 44100
DEVICE_INDEX: int = 0
_BITRATES = {
    pyaudio.paInt8: 8,
    pyaudio.paInt16: 16,
    pyaudio.paInt24: 24,
    pyaudio.paInt32: 32
}
_NUMPY_DTYPES = {
    pyaudio.paInt8: np.uint8,
    pyaudio.paInt16: np.int16,
    pyaudio.paInt24: np.int32,
    pyaudio.paInt32: np.float32
}
_FORMATS = {
    8: pyaudio.paInt8,
    16: pyaudio.paInt16,
    24: pyaudio.paInt24,
    32: pyaudio.paInt32
}


def format_to_bitrate(format: int) -> int:
    """ Converts the audio format to a bit-rate. """
    return _BITRATES[format]


def format_to_numpy_dtype(format: int) -> int:
    """ Converts the audio format to a numpy data-type. """
    return _NUMPY_DTYPES[format]


def bitrate_to_format(bitrate: int) -> int:
    """ Converts the audio bit-rate to a format. """
    return _FORMATS[bitrate]


@dataclass
class Interface():
    """ A `class` that represents an audio stream interface.

    Attributes
    ----------
    format : `int`
        The format of the audio stream.
    rate : `Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000]`
        The sampling frequency of the audio stream.
    channels : `Literal[1, 2]`
        The number of audio channels of the audio stream.
    chunk : `int`
        The number of frames per audio chunk.
    """
    format: int = field(default=FORMAT)
    rate: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = field(default=RATE)
    channels: Literal[1, 2] = field(default=CHANNELS)
    chunk: int = field(default=CHUNK)

    def __post_init__(self):
        """ Adds bit-rate. """
        self.bit_rate: int = format_to_bitrate(self.format)

    def from_dict(dict_object: dict) -> Interface:
        """ Returns an `Interface` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to an `Interface` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in ['format', 'rate', 'channels', 'chunk']
            if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Interface(
            format=dict_object['format'],
            rate=dict_object['rate'],
            channels=dict_object['channels'],
            chunk=dict_object['chunk']
        )

    def from_config(config: config.Handler) -> Interface:
        """ Returns a `audera.struct.audio.Interface` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Interface.from_dict(config.to_dict()['interface'])

    def to_dict(self):
        """ Returns the `audera.struct.audio.Interface` object as a `dict`. """
        return {
            'format': self.format,
            'bit_rate': self.bit_rate,
            'rate': self.rate,
            'channels': self.channels,
            'chunk': self.chunk
        }

    def __repr__(self):
        """ Returns the `audera.struct.audio.Interface` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.audio.Interface`
            An instance of an `audera.struct.audio.Interface` object.
        """
        if isinstance(compare, Interface):
            return (
                self.format == compare.format
                and self.rate == compare.rate
                and self.channels == compare.channels
                and self.chunk == compare.chunk
            )
        return False


@dataclass
class Device():
    """ A `class` that represents a hardware audio device.

    Attributes
    ----------
    name: `str`
        The name of the audio device.
    index: `int`
        The hardware index of the audio device.
    type: `Literal['intput', 'output']`
        The type of the audio device.
    """
    name: str = field(default='default')
    index: int = field(default=DEVICE_INDEX)
    type: Literal['input', 'output'] = field(default='input')

    def from_dict(dict_object: dict) -> Device:
        """ Returns a `audera.struct.audio.Device` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to a `audera.struct.audio.Device` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in ['name', 'index', 'type']
            if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Device(**dict_object)

    def get_default_device(type_: Literal['input', 'output']) -> Device:
        """ Gets the default input audio device and returns a `audera.struct.audio.Device`
        object.

        Parameters
        ----------
        type: `Literal['intput', 'output']`
            The type of the audio device.
        """

        # Open a temporary audio port
        _audio = pyaudio.PyAudio()

        # Get the default audio input device
        if type_.strip().lower() == 'input':
            device_index = _audio.get_default_input_device_info()['index']

        if type_.strip().lower() == 'output':
            device_index = _audio.get_default_output_device_info()['index']

        device_info = _audio.get_device_info_by_index(device_index)
        name = device_info['name']

        # Close the temporary audio port
        _audio.terminate()

        return Device(
            name=name,
            index=device_index,
            type=type_
        )

    def from_config(config: config.Handler) -> Device:
        """ Returns a `audera.struct.audio.Device` object from a `pytensils.config.Handler` object.

        Parameters
        ----------
        config: `pytensils.config.Handler`
            An instance of an `pytensils.config.Handler` object.
        """
        return Device.from_dict(config.to_dict()['device'])

    def to_dict(self):
        """ Returns the `audera.struct.audio.Device` object as a `dict`. """
        return {
            'name': self.name,
            'index': self.index,
            'type': self.type
        }

    def __repr__(self):
        """ Returns the `audera.struct.audio.Device` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.struct.audio.Device`
            An instance of an `audera.struct.audio.Device` object.
        """
        if isinstance(compare, Device):
            return (
                self.name == compare.name
                and self.index == compare.index
                and self.type == compare.type
            )
        return False
