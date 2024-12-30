""" Audio-stream """

from __future__ import annotations
from typing import Literal, Union
from dataclasses import dataclass, field
import copy
import json
import pyaudio

# Interface configuration
CHUNK: int = 1024
FORMAT: int = pyaudio.paInt16
CHANNELS: Literal[1, 2] = 1
RATE: Literal[5000, 8000, 11025, 22050, 44100, 48000, 92000] = 44100
DEVICE_INDEX: Union[int, None] = None


@dataclass
class Interface():
    """ A `class` that represents an audio stream interface.

    Attributes
    ----------
    format : `int`
        The bit-rate of the audio stream.
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
            key for key in ['parameter']
            if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Interface(**dict_object)

    def to_dict(self):
        """ Returns the `Interface` object as a `dict`.
        """
        return {
            'format': self.format,
            'rate': self.rate,
            'channels': self.channels,
            'chunk': self.chunk
        }

    def __repr__(self):
        """ Returns the `Interface` object as a json-formatted `str`.
        """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
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
    """ A `class` that represents an audio device.

    Attributes
    ----------
    index : `int`
        The hardware index of the audio device.
    """
    index: int = field(default=DEVICE_INDEX)

    def from_dict(dict_object: dict) -> Device:
        """ Returns a `Device` object from a `dict`.

        Parameters
        ----------
        dict_object : `dict`
            The dictionary object to convert to a `Device` object.
        """

        # Assert object type
        if not isinstance(dict_object, dict):
            raise TypeError('Object must be a `dict`.')

        # Assert keys
        missing_keys = [
            key for key in ['parameter']
            if key not in dict_object
        ]
        if missing_keys:
            raise KeyError(
                'Missing keys. The `dict` object is missing the following required keys [%s].' % (
                    ','.join(["'%s'" % (key) for key in missing_keys])
                )
            )

        return Device(**dict_object)

    def to_dict(self):
        """ Returns the `Device` object as a `dict`.
        """
        return {
            'index': self.index
        }

    def __repr__(self):
        """ Returns the `Device` object as a json-formatted `str`.
        """
        return json.dumps(self.to_dict(), indent=2)

    def __eq__(self, compare):
        if isinstance(compare, Device):
            return (
                self.index == compare.index
            )
        return False


class Input():
    """ A `class` that represents an audio device input.

    Parameters
    ----------
    interface: `audera.Interface`
        An `audera.Interface` object.
    device: `audera.Device`
        An `audera.Device` object.
    """

    def __init__(
        self,
        interface: Interface,
        device: Device
    ):
        """ Initializes an instance of an audio input.

        Parameters
        ----------
        interface: `audera.Interface`
            An `audera.Interface` object.
        device: `audera.Device`
            An `audera.Device` object.
        """

        # Initialize the audio stream
        self.interface = interface
        self.device = device
        self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(
            format=interface.format,
            rate=interface.rate,
            channels=interface.channels,
            frames_per_buffer=interface.chunk,
            input=True,
            input_device_index=device.index
        )

    def __eq__(self, compare):
        if isinstance(compare, Input):
            return (
                self.interface.format == compare.interface.format
                and self.interface.rate == compare.interface.rate
                and self.interface.channels == compare.interface.channels
                and self.interface.chunk == compare.interface.chunk
                and self.device.index == compare.device.index
            )
        return False

    def update(self, new: Input) -> Input:
        """ Opens a new audio stream with updated interface and device settings. """

        if not self == new:

            # Manage / close the audio stream
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()

            # Update the input interface
            if not self.interface == new.interface:
                self.interface = copy.deepcopy(new.interface)
                print('Updating the audio interface.')

            # Update the input device
            if not self.device == new.device:
                self.device = copy.deepcopy(new.device)
                print('Updating the audio device {%s}.' % (self.device.index))

            # Open a new audio stream with the latest settings
            self.stream = self.audio.open(
                format=self.interface.format,
                rate=self.interface.rate,
                channels=self.interface.channels,
                frames_per_buffer=self.interface.chunk,
                input=True,
                input_device_index=self.device.index
            )

            return self
