""" Audio I / O device manager """

from __future__ import annotations
from typing import Union
import logging
import asyncio
import time
import struct
import copy
import json
import pyaudio

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
    """

    def __init__(
        self,
        logger: logging.Logger,
        interface: struct_.audio.Interface,
        device: struct_.audio.Device,
        buffer_size: int = 5,
        time_offset: float = 0.0,
        playback_timing_tolerance: float = 0.005,
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
        playback_timing_tolerance: `float`
            The tolerance in seconds for determining playback timing.
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
            stream_callback=self.audio_playback_callback_v2
        )

        # Initialize the audio buffer and time offset
        self.buffer: asyncio.Queue = asyncio.Queue(buffer_size)
        self.time_offset: float = time_offset
        self.playback_timing_tolerance: float = playback_timing_tolerance

        # Initialize the audio stream chunk
        self.current_chunk: Union[bytes, None] = None
        self.current_target_playback_time: Union[float, None] = None
        self.current_position: int = 0

    @property
    def chunk_length(self) -> int:
        """ The number of bytes in the audio data chunk. """
        return (
            self.interface.chunk
            * self.interface.channels
            * self.interface.bit_rate // 8
        )

    @property
    def frame_size(self) -> int:
        """ The number of bytes in a single frame of audio data. """
        return self.interface.channels * self.interface.bit_rate // 8

    @property
    def bytes_per_second(self) -> int:
        """ The number of bytes in a second of audio data. """
        return self.interface.rate * self.frame_size

    @property
    def chunk_duration(self) -> float:
        """ The duration of the audio data chunk in seconds. """
        return self.interface.chunk / self.interface.rate

    def silent_chunk(self, length: int) -> bytes:
        """ A silent audio data chunk. """
        return b'\x00' * length

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
                stream_callback=self.audio_playback_callback_v2
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

        # Calculate the digital-to-analog converter (dac) offset
        dac_offset = time.time() - time_info['current_time']

        # Convert the digital-to-analog converter output time to local-time
        dac_playback_time = time_info['output_buffer_dac_time'] + dac_offset

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
            if target_playback_time < dac_playback_time:

                # Logging
                self.logger.warning(
                    'Late packet %.7f [sec.] with playback time %.7f [sec.].' % (
                        target_playback_time - dac_playback_time,
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

        # Create a silent audio stream chunk when the buffer queue is empty
        except asyncio.QueueEmpty:
            chunk = self.silent_chunk(length=self.chunk_length)

        # Return the audio stream chunk
        return (chunk, pyaudio.paContinue)

    def audio_playback_callback_v2(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: dict,
        status: int
    ) -> tuple[bytes, int]:
        """ Returns the next audio stream packet from the playback buffer, discarding incomplete
        or late packets and propagating the audio data into the return audio stream chunk.
        This is a more advanced version of the audio playback callback function that manages early
        packets.

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

        # Calculate the digital-to-analog converter (dac) offset
        dac_offset = time.time() - time_info['current_time']

        # Convert the digital-to-analog converter output time to local-time
        dac_playback_time = time_info['output_buffer_dac_time'] + dac_offset

        # Construct the audio stream chunk
        out_data = b''

        while len(out_data) < self.chunk_length:

            # Get the next audio stream packet from the buffer queue
            if self.current_chunk is None:
                try:
                    packet = self.buffer.get_nowait()

                    # Parse the playback time and audio data from the packet
                    playback_time = struct.unpack("d", packet[4:12])[0]
                    chunk = packet[12:-12]

                    # Calculate the target playback time in the player local time
                    target_playback_time = playback_time - self.time_offset

                    # Discard late packets
                    if dac_playback_time - target_playback_time > self.playback_timing_tolerance:

                        # Logging
                        self.logger.warning(
                            'Late packet %.7f [sec.] with playback time %.7f [sec.].' % (
                                target_playback_time - dac_playback_time,
                                playback_time
                            )
                        )

                        continue

                    # Retain the audio data packet
                    self.current_chunk = chunk
                    self.current_target_playback_time = target_playback_time
                    self.current_position = 0

                # Create a silent audio stream chunk when the buffer queue is empty
                except asyncio.QueueEmpty:
                    out_data += self.silent_chunk(length=(self.chunk_length - len(out_data)))
                    break

            # Determine how much time has elapsed since the target playback time
            elapsed = dac_playback_time - self.current_target_playback_time

            # Pad the return audio stream chunk with silence when the chunk arrives early
            if elapsed < -self.playback_timing_tolerance:

                # Logging
                self.logger.warning(
                    'Early packet %.7f [sec.] with playback time %.7f [sec.].' % (
                        target_playback_time - dac_playback_time,
                        playback_time
                    )
                )

                # Calculate the number of bytes to pad with silence
                silent_bytes = min(
                    int(abs(elapsed) * self.bytes_per_second),
                    self.chunk_length - len(out_data)
                )
                remaining_space = self.chunk_length - len(out_data)

                # Pad the remaining bytes of the return audio stream chunk with silence
                if silent_bytes >= remaining_space:
                    out_data += self.silent_chunk(length=remaining_space)
                    break

                # Pad only up to the target playback time with silence
                out_data += self.silent_chunk(length=silent_bytes)

            # Propagate data into the return audio stream chunk
            start_byte = self.current_position
            end_byte = min(start_byte + (self.chunk_length - len(out_data)), len(self.current_chunk))
            out_data += self.current_chunk[start_byte:end_byte]
            self.current_position = end_byte

            # Get the next audio stream packet from the buffer queue
            if self.current_position >= len(self.current_chunk):
                self.current_chunk = None

        # Check if the return audio stream chunk contains silent bytes
        silent_sample = self.silent_chunk(length=1)
        has_silence = silent_sample in out_data
        all_silence = out_data == self.silent_chunk(length=self.chunk_length)

        if has_silence and not all_silence:

            # Logging
            self.logger.warning(
                'Audio stream chunk with playback time %.7f [sec.] contains silent bytes adjusting for playback timing.' % (
                    playback_time
                )
            )

        # Check if the return audio stream chunk is the wrong size
        if len(out_data) != self.chunk_length:

            # Logging
            self.logger.error(
                'Audio stream chunk with playback time %.7f [sec.] is the wrong size.' % (
                    playback_time
                )
            )

        return (out_data, pyaudio.paContinue)

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
