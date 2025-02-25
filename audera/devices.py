""" Audio I / O device manager """

from __future__ import annotations
import logging
import asyncio
import time
import struct
import copy
import json
import numpy as np
import pyaudio
import samplerate

from audera import struct as struct_


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
        interface: struct_.audio.Interface,
        device: struct_.audio.Device
    ):
        """ Initializes an instance of an audio device input.

        Parameters
        ----------
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object that represents an audio input.
        """

        # Initialize the audio stream
        self.interface: struct_.audio.Interface = interface
        self.device: struct_.audio.Device = device
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

    def update(self, interface: struct_.audio.Interface, device: struct_.audio.Device):
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
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    interface: `audera.struct.audio.Interface`
        An `audera.struct.audio.Interface` object.
    device: `audera.struct.audio.Device`
        An `audera.struct.audio.Device` object that represents an audio output.
    buffer_size: `int`
        The number of audio packets to buffer before playback.
    time_offset: `float`
        The time offset in seconds between the local time on the remote audio
        output player and the audio streamer for synchronizing the audio playback stream.
    resample: `bool`
        `True` or `False` whether to resample the audio data chunk.
    """

    def __init__(
        self,
        logger: logging.Logger,
        interface: struct_.audio.Interface,
        device: struct_.audio.Device,
        buffer_size: int = 5,
        time_offset: float = 0.0,
        resample: bool = False
    ):
        """ Initializes an instance of an audio device output.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object that represents an audio output.
        buffer_size: `int`
            The number of audio packets to buffer before playback.
        time_offset: `float`
            The time offset in seconds between the local time on the remote audio
            output player and the audio streamer for synchronizing the audio playback stream.
        resample: `bool`
            `True` or `False` whether to resample the audio data chunk.
        """

        # Logging
        self.logger = logger

        # Initialize the audio stream
        self.interface: struct_.audio.Interface = interface
        self.device: struct_.audio.Device = device
        self.port = pyaudio.PyAudio()
        self.stream = self.port.open(
            format=interface.format,
            rate=interface.rate,
            channels=interface.channels,
            frames_per_buffer=interface.chunk,
            output=True,
            output_device_index=device.index,
            stream_callback=self.audio_playback_callback
        )
        self.resample_: bool = resample

        # Initialize the audio buffer and time offset
        self.buffer: asyncio.Queue = asyncio.Queue(buffer_size)
        self.time_offset: float = time_offset

    @property
    def chunk_length(self) -> int:
        """ The number of bytes in the audio data chunk. """
        return (
            self.interface.chunk
            * self.interface.channels
            * self.interface.bit_rate // 8
        )

    @property
    def silent_chunk(self) -> bytes:
        """ A silent audio data chunk. """
        return b'\x00' * self.chunk_length

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
        interface: struct_.audio.Interface,
        device: struct_.audio.Device
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
                output_device_index=self.device.index,
                stream_callback=self.audio_playback_callback
            )

            return True
        else:
            return False

    def audio_playback_callback(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict,
        status: int
    ) -> tuple[bytes, int]:
        """ Returns the next audio stream packet from the playback buffer, discarding incomplete
        or late packets.

        Parameters
        ----------
        in_data: `bytes`
            The audio data chunk as bytes.
        frame_count: `int`
            The number of frames in the audio data chunk.
        time_info: `dict`
            A dictionary containing the current time and the input buffer time.
        status: `int`
            The status of the audio stream.
        """

        # Discard invalid packets
        while not self.buffer.empty():

            # Peak at the next audio stream packet from the buffer queue
            next_packet = self.buffer._queue[0]

            # Peak at the playback time and length of the next packet
            playback_time = struct.unpack("d", next_packet[4:12])[0]
            length = struct.unpack(">I", next_packet[:4])[0]

            # Discard incomplete packets
            if length != self.chunk_length:

                # Logging
                self.logger.warning(
                    'Incomplete packet with playback time %.7f [sec.].' % (
                        playback_time
                    )
                )

                # Remove the incomplete packet from the buffer queue
                _ = self.buffer.get_nowait()

                continue

            # Calculate the target playback time in the player local time
            target_playback_time = playback_time - self.time_offset

            # Discard late packets
            if target_playback_time < time.time():

                # Logging
                self.logger.warning(
                    'Late packet %.7f [sec.] with playback time %.7f [sec.].' % (
                        target_playback_time - time.time(),
                        playback_time
                    )
                )

                # Remove the late packet from the buffer queue
                _ = self.buffer.get_nowait()

                continue

            # Exit the loop only when a valid packet is available
            break

        # Get the next audio stream packet from the buffer queue
        try:
            packet = self.buffer.get_nowait()

            # Parse the playback time and audio data from the packet
            playback_time = struct.unpack("d", packet[4:12])[0]
            chunk = packet[12:-12]

            # Calculate the target playback time in the player local time
            target_playback_time = playback_time - self.time_offset

            # Sleep until the target playback time, ensuring that no unnecessary delay
            #   is introduced when sleep time becomes very small

            while time.time() < target_playback_time:
                if target_playback_time - time.time() > 0.001:
                    time.sleep(target_playback_time - time.time())
                else:
                    break

            # Resample the audio data chunk based on latency drift to ensure multi-player
            #   synchronization is maintained adaptively over-time

            if self.resample_:
                chunk = self.resample(chunk, target_playback_time)

        # Create a silent audio stream chunk when the buffer queue is empty
        except asyncio.QueueEmpty:
            chunk = self.silent_chunk

        # Return the audio stream chunk
        return (chunk, pyaudio.paContinue)

    def play(self):
        """ Starts the audio playback stream. """
        if not self.stream.is_active():
            self.stream.start_stream()

    def clear_buffer(self):
        """ Clears any / all unplayed audio stream packets from the buffer. """
        while not self.buffer.empty():
            try:
                self.buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

    def stop(self):
        """ Stops the audio playback stream. """

        # Stop the audio stream
        if self.stream.is_active():
            self.stream.stop_stream()

        # Close the audio services
        self.stream.close()
        self.port.terminate()

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

        # Skip resampling when there is no playback latency
        if (target_playback_time - time.time()) == 0:
            return chunk

        # Select NumPy dtype based on the audio stream format
        dtype_ = struct_.audio.format_to_numpy_dtype(self.interface.format)

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

        # Calculate speed adjustment factor
        if target_playback_time - time.time() < 0:
            speed_factor = min(1.05, 1.0 + abs(target_playback_time - time.time()) * 0.05)

        if target_playback_time - time.time() >= 0:
            speed_factor = max(0.95, 1.0 - (target_playback_time - time.time()) * 0.05)

        # Resample
        resampled_audio: np.typing.NDArray = samplerate.resample(sample_audio, speed_factor, 'sinc_fastest')

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
