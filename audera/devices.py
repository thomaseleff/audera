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
    buffer_size: `int`
        The number of audio packets to buffer before streaming.
    playback_delay: `float`
        The time in seconds to apply to the playback time of each audio packet.
    terminator: `bytes`
        The bytes suffix that indicates the end of a packet.
    time_offset: `float`
        The time offset in seconds between the local time on the streamer and network time.
    """

    def __init__(
        self,
        logger: logging.Logger,
        interface: struct_.audio.Interface,
        device: struct_.audio.Device,
        buffer_size: int,
        playback_delay: float,
        terminator: bytes,
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
        buffer_size: `int`
            The number of audio packets to buffer before streaming.
        playback_delay: `float`
            The time in seconds to apply to the playback time of each audio packet.
        terminator: `bytes`
            The bytes suffix that indicates the end of a packet.
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
            # output=True,  # Forces time-info in the callback
            input_device_index=device.index,
            # stream_callback=self.audio_capture_callback
        )

        # Initialize the audio buffer and time offset
        self.buffer: asyncio.Queue = asyncio.Queue(buffer_size)
        self.playback_delay: float = playback_delay
        self.terminator: bytes = terminator
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
                # output=True,  # Forces time-info in the callback
                input_device_index=self.device.index,
                # stream_callback=self.audio_capture_callback
            )

            return True
        else:
            return False

    # def audio_capture_callback(
    #     self,
    #     in_data: bytes,
    #     frame_count: int,
    #     time_info: dict,
    #     status: int
    # ) -> tuple[bytes, int]:
    #     """ Adds the next audio stream packet to the playback buffer, discarding old / stale
    #     audio packets.

    #     Parameters
    #     ----------
    #     in_data: `bytes`
    #         The audio data chunk as bytes.
    #     frame_count: `int`
    #         The number of frames in the audio data chunk.
    #     time_info: `dict`
    #         A dictionary containing the current time and the input buffer time.
    #     status: `int`
    #         The status of the audio stream.
    #     """

    #     # Get playback time
    #     playback_time = (
    #         time.time()
    #         - self.stream.get_input_latency()
    #         + time_info["output_buffer_dac_time"] - time_info["current_time"]
    #         + self.time_offset
    #         + self.playback_delay
    #     )

    #     # Logging
    #     self.logger.info(
    #         'Capturing audio stream packet with est. capture time %.7f [sec.] and playback time %.7f [sec.].' % (
    #             time.time() + self.time_offset - self.stream.get_input_latency(),
    #             playback_time
    #         )
    #     )

    #     # Convert the audio data chunk to a timestamped packet, including the length of
    #     #   the packet as well as the packet terminator. Assign the timestamp as the target
    #     #   playback time accounting for a fixed playback delay from the current time on
    #     #   the streamer.

    #     length = struct.pack(">I", len(in_data))
    #     playback_time = struct.pack(
    #         "d",
    #         playback_time
    #     )
    #     packet = (
    #         length  # 4 bytes
    #         + playback_time  # 8 bytes
    #         + in_data
    #         + self.terminator
    #     )

    #     # Put the next audio stream packet into the buffer queue
    #     try:
    #         self.buffer.put_nowait(packet)

    #     # When the buffer queue is full, remove the oldest / stale packet and add the next audio stream packet
    #     except asyncio.QueueFull:
    #         try:
    #             _ = self.buffer.get_nowait()
    #             self.buffer.put_nowait(packet)

    #         except asyncio.QueueEmpty:  # Rare condition
    #             self.buffer.put_nowait(packet)

    #     return (in_data, pyaudio.paContinue)


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
            stream_callback=self.audio_playback_callback
        )

        # Initialize the audio buffer and time offset
        self.buffer: asyncio.Queue = asyncio.Queue(buffer_size)
        self.time_offset: float = time_offset
        self.playback_timing_tolerance: float = playback_timing_tolerance

        # Initialize the audio stream chunk
        self.current_chunk: Union[bytes, None] = None
        self.current_playback_time: Union[float, None] = None
        self.current_target_playback_time: Union[float, None] = None
        self.current_position: int = 0
        self.current_num_silent_bytes: int = 0
        self.time_until_target_playback_time: float = 0.0
        self.silent_sample: int = self.silent_chunk(length=1)

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

        # Convert the digital-to-analog converter output time to local-time
        dac_playback_time = (
            time_info['output_buffer_dac_time']
            + (time.time() - time_info['current_time'])
        )

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
            if dac_playback_time - target_playback_time > self.playback_timing_tolerance:

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

        # Convert the digital-to-analog converter output time to local-time
        dac_playback_time = (
            time_info['output_buffer_dac_time']
            + (time.time() - time_info['current_time'])
        )

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

                    # Logging
                    self.logger.info(
                        'Parsing audio stream packet for chunk with dac playback time %.7f [sec.] from packet with playback time %.7f [sec.].' % (
                            dac_playback_time,
                            target_playback_time
                        )
                    )

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
                    self.current_playback_time = playback_time
                    self.current_target_playback_time = target_playback_time
                    self.current_position = 0
                    self.current_num_silent_bytes = 0
                    self.time_until_target_playback_time = dac_playback_time - self.current_target_playback_time

                # Create a silent audio stream chunk when the buffer queue is empty
                except asyncio.QueueEmpty:
                    out_data += self.silent_chunk(length=int(self.chunk_length - len(out_data)))
                    break

            # Determine how much time has elapsed since the target playback time
            # time_until_target_playback_time

            # Pad the return audio stream chunk with silence when the chunk arrives early,
            #   accounting for any audio data already propagated into the chunk

            if (
                self.time_until_target_playback_time
                + int(len(out_data) / self.bytes_per_second)
             ) < -self.playback_timing_tolerance:

                # Logging
                self.logger.warning(
                    'Early packet %.7f [sec.] with playback time %.7f [sec.].' % (
                        self.current_target_playback_time - dac_playback_time,
                        self.current_playback_time
                    )
                )

                # Calculate the number of bytes to pad with silence
                self.current_num_silent_bytes = max(
                    min(
                        int(self.time_until_target_playback_time * self.bytes_per_second),
                        int(self.chunk_length - len(out_data))
                    ),
                    0
                )

                # Pad the audio stream chunk with silence
                out_data += self.silent_chunk(length=self.current_num_silent_bytes)

            # Propagate data into the return audio stream chunk
            start_byte = self.current_position
            end_byte = min(int(start_byte + self.chunk_length - len(out_data)), self.chunk_length)
            out_data += self.current_chunk[start_byte:end_byte]
            self.current_position = end_byte

            # Get the next audio stream packet from the buffer queue
            if self.current_position >= self.chunk_length:
                self.current_chunk = None

            # Logging
            self.logger.info(
                'Constructing audio stream chunk with dac playback time %.7f [sec.] from packet with playback time %.7f [sec.], adjusted time until playback time %.7f [sec.], num. silent bytes {%d} and current position {%d} / {%d}.' % (
                    dac_playback_time,
                    self.current_target_playback_time,
                    self.time_until_target_playback_time + int(len(out_data) / self.bytes_per_second),
                    self.current_num_silent_bytes,
                    self.current_position,
                    self.chunk_length
                )
            )

        # Logging
        self.logger.info(
            'Played constructed audio stream chunk with dac playback time %.7f [sec.].' % (
                dac_playback_time
            )
        )

        # Check if the return audio stream chunk contains silent bytes
        if self.silent_sample in out_data and not out_data == self.silent_chunk(length=self.chunk_length):

            # Logging
            self.logger.warning(
                'Audio stream chunk with playback time %.7f [sec.] contains silent bytes adjusting for playback timing.' % (
                    self.current_playback_time
                )
            )

        # Check if the return audio stream chunk is the wrong size
        if len(out_data) != self.chunk_length:

            # Logging
            self.logger.error(
                'Audio stream chunk with playback time %.7f [sec.] is the wrong size %f, expected %f.' % (
                    self.current_playback_time,
                    len(out_data),
                    self.chunk_length
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
