""" Audio-stream """

from __future__ import annotations
from typing import Literal
from dataclasses import dataclass, field
import copy
import json
import pyaudio
from pytensils import config


# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: Literal[1, 2] = 2
RATE: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = 44100
DEVICE_INDEX: int = 0


def format_to_bitrate(format: int) -> int:
    """ Converts the audio format to a bit-rate. """
    bitrates = {
        pyaudio.paInt8: 8,
        pyaudio.paInt16: 16,
        pyaudio.paInt24: 24,
        pyaudio.paInt32: 32
    }
    return bitrates[format]


def bitrate_to_format(bitrate: int) -> int:
    """ Converts the audio bit-rate to a format. """
    formats = {
        8: pyaudio.paInt8,
        16: pyaudio.paInt16,
        24: pyaudio.paInt24,
        32: pyaudio.paInt32
    }
    return formats[bitrate]


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
    """
    name: str = field(default='default')
    index: int = field(default=DEVICE_INDEX)

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
            key for key in ['index']
            if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Device(**dict_object)

    def get_default_device() -> Device:
        """ Gets the default audio device and returns a `audera.struct.audio.Device` object. """

        # Open a temporary audio port
        _audio = pyaudio.PyAudio()

        # Get the default audio input device
        device_index = _audio.get_default_input_device_info()['index']
        device_info = _audio.get_device_info_by_index(device_index)
        name = device_info['name']

        # Close the temporary audio port
        _audio.terminate()

        return Device(
            name=name,
            index=device_index
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
            'index': self.index
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
            )
        return False


class Input():
    """ A `class` that represents an audio device input.

    Parameters
    ----------
    interface: `audera.struct.audio.Interface`
        An `audera.struct.audio.Interface` object.
    device: `audera.struct.audio.Device`
        An `audera.struct.audio.Device` object.
    """

    def __init__(
        self,
        interface: Interface,
        device: Device
    ):
        """ Initializes an instance of an audio input.

        Parameters
        ----------
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object.
        """

        # Initialize the audio stream
        self.interface = interface
        self.device = device
        self.port = pyaudio.PyAudio()
        self.stream = self.port.open(
            format=interface.format,
            rate=interface.rate,
            channels=interface.channels,
            frames_per_buffer=interface.chunk,
            input=True,
            input_device_index=device.index
        )

    def to_dict(self):
        """ Returns the `audera.struct.audio.Input` object as a `dict`. """
        return {
            'state': 'active' if self.stream.is_active() else 'stopped',
            'format': self.interface.format,
            'rate': self.interface.rate,
            'channels': self.interface.channels,
            'chunk': self.interface.chunk,
            'device_index': self.device.index
        }

    def __repr__(self):
        """ Returns the `audera.struct.audio.Input` object as a json-formatted `str`. """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        """ Returns `True` when compare is an instance of self.

        Parameters
        ----------
        compare: `audera.audio.Input`
            An instance of an `audera.audio.Input` object.
        """
        if isinstance(compare, Input):
            return (
                self.interface.format == compare.interface.format
                and self.interface.rate == compare.interface.rate
                and self.interface.channels == compare.interface.channels
                and self.interface.chunk == compare.interface.chunk
                and self.device.index == compare.device.index
            )
        return False

    def update(self, interface: Interface, device: Device):
        """ Opens a new audio stream with an updated interface and device settings and
        returns `True` when a the stream is updated.

        Parameters
        ----------
        interface: `audera.audio.Interface`
            An instance of an `audera.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An instance of an `audera.struct.audio.Device` object.
        """

        if not (
            self.interface == interface
            and self.device == device
        ):

            # Manage / close the audio stream
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()

            # Update the input interface
            if not self.interface == interface:
                self.interface = copy.deepcopy(interface)

            # Update the input device
            if not self.device == device:
                self.device = copy.deepcopy(device)

            # Open a new audio stream with the latest settings
            self.stream = self.port.open(
                format=self.interface.format,
                rate=self.interface.rate,
                channels=self.interface.channels,
                frames_per_buffer=self.interface.chunk,
                input=True,
                input_device_index=self.device.index
            )

            return True

        else:
            return False
