""" Audio I / O device manager """

from __future__ import annotations
import asyncio
import time
import copy
import json
import numpy as np
import pyaudio
import samplerate

from audera import struct


class Input():
    """ A `class` that represents an audio device input.

    Parameters
    ----------
    interface: `audera.struct.audio.Interface`
        An `audera.struct.audio.Interface` object.
    device: `audera.struct.audio.Device`
        An `audera.struct.audio.Device` object that represents an audio input.
    """

    def __init__(
        self,
        interface: struct.audio.Interface,
        device: struct.audio.Device
    ):
        """ Initializes an instance of an audio input.

        Parameters
        ----------
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object that represents an audio input.
        """

        # Initialize the audio stream
        self.interface: struct.audio.Interface = interface
        self.device: struct.audio.Device = device
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
            'type': self.device.type,
            'format': self.interface.format,
            'bit_rate': self.interface.bit_rate,
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
        compare: `audera.device_manager.Input`
            An instance of an `audera.device_manager.Input` object.
        """
        if isinstance(compare, Input):
            return (
                self.interface.format == compare.interface.format
                and self.interface.rate == compare.interface.rate
                and self.interface.channels == compare.interface.channels
                and self.interface.chunk == compare.interface.chunk
                and self.device.index == compare.device.index
                and self.device.type == compare.device.type
            )
        return False

    def update(self, interface: struct.audio.Interface, device: struct.audio.Device):
        """ Opens a new audio stream with an updated interface and device settings and
        returns `True` when the stream is updated.

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


class Output():
    """ A `class` that represents an audio device output.

    Parameters
    ----------
    interface: `audera.struct.audio.Interface`
        An `audera.struct.audio.Interface` object.
    device: `audera.struct.audio.Device`
        An `audera.struct.audio.Device` object that represents an audio output.
    """

    def __init__(
        self,
        interface: struct.audio.Interface,
        device: struct.audio.Device
    ):
        """ Initializes an instance of an audio input.

        Parameters
        ----------
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object that represents an audio output.
        """

        # Initialize the audio stream
        self.interface: struct.audio.Interface = interface
        self.device: struct.audio.Device = device
        self.port = pyaudio.PyAudio()
        self.stream = self.port.open(
            format=interface.format,
            rate=interface.rate,
            channels=interface.channels,
            frames_per_buffer=interface.chunk,
            output=True,
            output_device_index=device.index
        )

    @property
    def silent_chunk(self) -> bytes:
        """ A silent audio chunk. """
        return (
            b'\x00'
            * (
                self.interface.chunk,
                self.interface.channels
                * 2
            )
        )

    def to_dict(self):
        """ Returns the `audera.struct.audio.Input` object as a `dict`. """
        return {
            'state': 'active' if self.stream.is_active() else 'stopped',
            'type': self.device.type,
            'format': self.interface.format,
            'bit_rate': self.interface.bit_rate,
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
        compare: `audera.device_manager.Input`
            An instance of an `audera.device_manager.Input` object.
        """
        if isinstance(compare, Input):
            return (
                self.interface.format == compare.interface.format
                and self.interface.rate == compare.interface.rate
                and self.interface.channels == compare.interface.channels
                and self.interface.chunk == compare.interface.chunk
                and self.device.index == compare.device.index
                and self.device.type == compare.device.type
            )
        return False

    def update(
        self,
        interface: struct.audio.Interface,
        device: struct.audio.Device
    ):
        """ Opens a new audio stream with an updated interface and device settings and
        returns `True` when the stream is updated.

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
                output=True,
                output_device_index=self.device.index
            )

            return True

        else:
            return False

    async def play(
        self,
        chunk: bytes,
        target_playback_time: float,
        resample: bool = False
    ):
        """ Play the audio stream data, resampling the audio data chunk based on latency
        drift to ensure multi-player synchronization is maintained adaptively over-time.

        Parameters
        ----------
        chunk: `bytes`
            The audio data chunk as bytes.
        target_playback_time: `float`
            The target playback time of the audio data chunk in reference to the current local
                time.
        resample: `bool`
            `True` or `False` whether to resample the audio data chunk.
        """
        if resample:
            await asyncio.to_thread(self.stream.write, self.resample(chunk, target_playback_time))
        else:
            await asyncio.to_thread(self.stream.write, chunk)

    def resample(
        self,
        chunk: bytes,
        target_playback_time: float
    ) -> bytes:
        """ Resample the audio data chunk based on latency drift to ensure multi-player
        synchronization is maintained adaptively over-time.

        Parameters
        ----------
        chunk: `bytes`
            The audio data chunk as bytes.
        target_playback_time: `float`
            The target playback time of the audio data chunk in reference to the current local
                time.
        """

        # Calculate speed adjustment factor
        latency = target_playback_time - time.time()
        if latency < 0:
            speed_factor = min(1.05, 1.0 + abs(latency) * 0.05)  # Increase playback speed
        elif latency > 0:
            speed_factor = max(0.95, 1.0 - latency * 0.05)  # Decrease playback speed

        # Skip resampling when there is no playback latency
        else:
            return chunk

        # Select NumPy dtype based on the audio stream format
        dtype_ = struct.audio.format_to_numpy_dtype(self.interface.format)

        # Convert the audio data chunk to a NumPy array
        sample_audio: np.typing.NDArray = np.frombuffer(chunk, dtype_)

        # Reshape the NumPy array for multi-channel audio
        if self.interface.channels > 1:
            sample_audio = sample_audio.reshape(-1, self.interface.channels)

        # Normalize the audio data to float32 for processing
        if dtype_ == np.uint8:  # 8-bit
            sample_audio = (sample_audio - 128) / 128.0
        elif dtype_ == np.int16:  # 16-bit
            sample_audio = sample_audio.astype(np.float32) / 32768.0
        elif dtype_ == np.int32:  # 24-bit
            sample_audio = (sample_audio.astype(np.float32) / 8388608.0)
        elif dtype_ == np.float32:  # 32-bit
            pass  # Already float32

        # Resample
        resampled_audio: np.typing.NDArray = samplerate.resample(sample_audio, speed_factor, "sinc_best")

        # Convert the audio data back to the original bit depth
        if dtype_ == np.uint8:  # 8-bit
            resampled_audio = np.clip((resampled_audio * 128) + 128, 0, 255).astype(np.uint8)
        elif dtype_ == np.int16:  # 16-bit
            resampled_audio = np.clip(resampled_audio * 32768, -32768, 32767).astype(np.int16)
        elif dtype_ == np.int32:  # 24-bit
            resampled_audio = np.clip(resampled_audio * 8388608, -8388608, 8388607).astype(np.int32)
        elif dtype_ == np.float32:  # 32-bit
            pass  # Already float32

        # Convert the audio data sample back into bytes
        return resampled_audio.tobytes()
