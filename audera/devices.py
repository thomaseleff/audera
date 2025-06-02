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
    logger: `audera.logging.Logger`
        An instance of `audera.logging.Logger`.
    interface: `audera.struct.audio.Interface`
        An `audera.struct.audio.Interface` object.
    device: `audera.struct.audio.Device`
        An `audera.struct.audio.Device` object that represents an audio input.
    playback_delay: `float`
        The time in seconds to apply to the playback time of each audio packet.
    time_offset: `float`
        The time offset in seconds between the local time on the streamer and network time.
    """

    def __init__(
        self,
        logger: logging.Logger,
        interface: struct_.audio.Interface,
        device: struct_.audio.Device,
        playback_delay: float,
        time_offset: float = 0.0
    ):
        """ Initializes an instance of an audio device input.

        Parameters
        ----------
        logger: `audera.logging.Logger`
            An instance of `audera.logging.Logger`.
        interface: `audera.struct.audio.Interface`
            An `audera.struct.audio.Interface` object.
        device: `audera.struct.audio.Device`
            An `audera.struct.audio.Device` object that represents an audio input.
        playback_delay: `float`
            The time in seconds to apply to the playback time of each audio packet.
        time_offset: `float`
            The time offset in seconds between the local time on the streamer and network time.
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
            input=True,
            input_device_index=device.index
        )

        # Initialize the audio buffer and time offset
        self.playback_delay: float = playback_delay
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
    playback_timing_tolerance: `float`
        The tolerance in seconds for determining on-time packets.
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
            The tolerance in seconds for determining on-time packets.
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
            start=False,
            stream_callback=self.audio_playback_callback
        )
        self.stream_start_time: Union[float, None] = None

        # Initialize the audio buffer and time offset
        self.buffer: asyncio.Queue = asyncio.Queue(buffer_size)
        self.time_offset: float = time_offset
        self.playback_timing_tolerance: float = playback_timing_tolerance

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
                start=False,
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

        # Get the next audio stream packet from the buffer queue
        try:
            packet = self.buffer.get_nowait()

            # Parse the audio data from the packet
            chunk = packet[12:-12]

            # Debug
            # self.logger.info(
            #     'Streaming audio stream packet with playback time %.7f [sec.].' % (
            #         struct.unpack("d", packet[4:12])[0]
            #     )
            # )

        # Create a silent audio stream chunk when the buffer queue is empty
        except asyncio.QueueEmpty:
            chunk = self.silent_chunk(length=self.chunk_length)

        # Return the audio stream chunk
        return (chunk, pyaudio.paContinue)

    def synchronize(self):
        """ Synchronizes the startup of the playback stream with the playback time of the
        next early or on-time packet from the buffer.
        """

        # Discard invalid packets
        while not self.buffer.empty():

            # Peak at the next audio stream packet from the buffer queue
            next_packet = self.buffer._queue[0]

            # Peak at the length of the next packet and the playback time
            length = struct.unpack(">I", next_packet[:4])[0]
            playback_time = struct.unpack("d", next_packet[4:12])[0]

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
            time_difference = target_playback_time - time.time()

            # Discard late packets
            if time_difference < -self.playback_timing_tolerance:

                # Logging
                self.logger.warning(
                    'Late packet %.7f [sec.] with playback time %.7f [sec.].' % (
                        time_difference,
                        playback_time
                    )
                )

                # Remove the late packet from the buffer queue
                _ = self.buffer.get_nowait()

                continue

            # Discard early packets
            # if time_difference > self.playback_timing_tolerance:

            #     # Logging
            #     self.logger.warning(
            #         'Early packet %.7f [sec.] with playback time %.7f [sec.].' % (
            #             time_difference,
            #             playback_time
            #         )
            #     )
            #     # Remove the late packet from the buffer queue
            #     _ = self.buffer.get_nowait()

            #     continue

            # Exit the loop only when a valid packet is available
            break

        # Sleep until the target playback time
        target_playback_clock_time = time.monotonic() + time_difference
        while True:
            remaining = target_playback_clock_time - time.monotonic()

            if (
                remaining < self.playback_timing_tolerance
                and remaining > -self.playback_timing_tolerance
            ):
                break

            if remaining > 0.1:
                time.sleep(
                    target_playback_clock_time - time.monotonic() - (2 * self.playback_timing_tolerance)
                )
            else:
                time.sleep(
                    max(
                        min(
                            target_playback_clock_time - time.monotonic(),
                            0.001
                        ),
                        0
                    )
                )

        # Logging
        self.logger.info(
            "".join([
                "The synchronized audio playback stream was opened at %.7f [sec.]" % (
                    playback_time
                ),
                " within %.7f [sec.] of the target playback time." % (
                    target_playback_clock_time - time.monotonic()
                )
            ])
        )

    def start(self):
        """ Starts the audio playback stream. """
        self.synchronize()

        if not self.stream.is_active():
            self.stream.start_stream()

            # Retain the start time of the audio playback stream
            self.stream_start_time = time.time()

    def stop(self):
        """ Stops the audio playback stream. """
        if self.stream.is_active():
            self.stream.stop_stream()

    def restart(self):
        """ Restarts the audio playback stream. """
        self.stop()
        self.start()

    def clear_buffer(self):
        """ Clears any / all unplayed audio stream packets from the buffer. """
        while not self.buffer.empty():
            try:
                self.buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

    def close(self):
        """ Closes the audio playback stream. """
        self.stop()
        self.stream.close()
        self.port.terminate()
