""" Audio stream / playback session manager """

from __future__ import annotations
from typing import Union, Dict
import asyncio

from audera import struct, dal


class PlayerConnection():
    """ A `class` that represents a remote audio output player stream connection.

    Parameters
    ----------
    player: `audera.struct.player.Player`
        An `audera.struct.player.Player` object.
    stream_writer: `asyncio.StreamWriter`
        The asynchronous network stream writer registered to the player used to write the
            audio stream to the player over a TCP connection.
    """

    def __init__(
        self,
        player: struct.player.Player,
        stream_writer: Union[asyncio.StreamWriter, None] = None
    ):
        """  Initializes an instance of a remote audio output player stream connection.

        Parameters
        ----------
        player: `audera.struct.player.Player`
            An `audera.struct.player.Player` object.
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the player used to write the
                audio stream to the player over a TCP connection.
        """
        self.player: struct.player.Player = player
        self.stream_writer: Union[asyncio.StreamWriter, None] = stream_writer

    def connect(self, stream_writer: asyncio.StreamWriter) -> PlayerConnection:
        """ Attaches the asynchronous network stream writer.

        Parameters
        ----------
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the player used to write the
                audio stream to the player over a TCP connection.
        """
        self.stream_writer = stream_writer
        self.player = dal.players.connect(self.player.uuid)

        return self

    async def disconnect(self):
        """ Detaches the asynchronous network stream writer. """

        # Close the connection
        if self.stream_writer:
            self.stream_writer.close()
            try:
                await self.stream_writer.wait_closed()
            except (
                ConnectionResetError,  # Player disconnected
                ConnectionAbortedError  # Player aborted the connection
            ):
                pass

        # Disconnect the player
        self.player = dal.players.disconnect(self.player.uuid)


class Stream():
    """ A `class` that represents an audio stream session.

    Parameters
    ----------
    session: `audera.struct.session.Session`
        An `audera.struct.session.Session` object.
    """

    def __init__(
        self,
        session: struct.session.Session
    ):
        """ Initializes an instance of an audio stream session.

        Parameters
        ----------
        session: `audera.struct.session.Session`
            An `audera.struct.session.Session` object.
        """
        self.session: struct.session.Session = session
        self.player_connections: Dict[str, PlayerConnection] = {}

    @property
    def num_players(self) -> int:
        """ Returns the number of attached remote audio output players as an `int`. """
        return len(self.player_connections.keys())

    def attach_player(
        self,
        player: struct.player.Player,
        stream_writer: asyncio.StreamWriter = None
    ):
        """ Attaches a player from the audio stream session.

        Parameters
        ----------
        player: `audera.struct.player.Player`
            An `audera.struct.player.Player` object.
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the player used to write the
                audio stream to the player over a TCP connection.
        """

        # Attach the remote audio output player to the stream session
        self.session = dal.sessions.attach_players_or_group(
            self.session.uuid,
            player
        )

        # Attach / retain the remote audio output player connection
        self.player_connections[player.address] = PlayerConnection(player, stream_writer)

    async def detach_player(
        self,
        player: struct.player.Player
    ):
        """ Detaches a player from the audio stream session and closes the asynchronous
        network stream writer.

        Parameters
        ----------
        player: `audera.struct.player.Player`
            An `audera.struct.player.Player` object.
        """

        try:
            if player.address in self.player_connections:

                # Detach the remote audio output player from the stream session
                self.session = dal.sessions.detach_players_or_group(
                    self.session.uuid,
                    self.player_connections.get(player.address).player
                )

                # Close the remote audio output player connection
                await asyncio.gather(self.player_connections.get(player.address).disconnect())

                # Remove the remote audio output player connection
                del self.player_connections[player.address]

        except KeyError:  # The remote audio output player has already been detached
            pass

    async def close(self):
        """ Detaches all players from the audio stream session and closes all asynchronous
        network stream writers concurrently.
        """

        # Detach all remote audio output players from the stream session
        self.session = dal.sessions.detach_players_or_group(
            self.session.uuid,
            [player_connection.player for player_connection in self.player_connections.values()]
        )

        # Close all remote audio output player connections
        await asyncio.gather(
            *[
                player_connection.disconnect()
                for player_connection in self.player_connections.values()
            ]
        )

        # Reset remote audio output player connections
        self.player_connections = {}

        # Remove the stream session
        dal.sessions.delete(self.session.uuid)


class StreamerConnection():
    """ A `class` that represents a streamer connection.

    Parameters
    ----------
    streamer_address: `str`
        The ip-address of the audio streamer.
    stream_writer: `asyncio.StreamWriter`
        The asynchronous network stream writer registered to the streamer.
    """

    def __init__(
        self,
        streamer_address: Union[str, None] = None,
        stream_writer: Union[asyncio.StreamWriter, None] = None
    ):
        """ Initializes an instance of a streamer connection.

        Parameters
        ----------
        streamer_address: `str`
            The ip-address of the audio streamer.
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the streamer.
        """
        self.streamer_address: Union[str, None] = streamer_address
        self.stream_writer: Union[asyncio.StreamWriter, None] = stream_writer

    def connect(self, stream_writer: asyncio.StreamWriter) -> StreamerConnection:
        """ Attaches the asynchronous network stream writer.

        Parameters
        ----------
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the streamer.
        """
        self.stream_writer = stream_writer

        return self

    async def disconnect(self):
        """ Detaches the asynchronous network stream writer. """

        # Close the connection
        if self.stream_writer:
            self.stream_writer.close()
            try:
                await self.stream_writer.wait_closed()
            except (
                ConnectionResetError,  # Streamer disconnected
                ConnectionAbortedError  # Streamer aborted the connection
            ):
                pass


class Playback():
    """ A `class` that represents an audio playback session. """

    def __init__(self):
        """ Initializes an instance of an audio playback session. """
        self.streamer_connection: StreamerConnection = StreamerConnection()

    async def attach_streamer(
        self,
        streamer_address: str
    ):
        """ Attaches a streamer to the audio stream session.

        Parameters
        ----------
        streamer_address: `str`
            The ip-address of the audio streamer.
        """

        # Clear any / all existing playback session
        await self.clear()

        # Retain the streamer address
        self.streamer_connection = StreamerConnection(streamer_address)

    async def attach_stream_writer(
        self,
        streamer_address: str,
        stream_writer: asyncio.StreamWriter = None
    ):
        """ Attaches a stream writer to the audio stream session.

        Parameters
        ----------
        streamer_address: `str`
            The ip-address of the audio streamer.
        stream_writer: `asyncio.StreamWriter`
            The asynchronous network stream writer registered to the streamer.
        """

        # Attach / retain the streamer connection
        if self.streamer_connection.streamer_address == streamer_address:
            self.streamer_connection = self.streamer_connection.connect(stream_writer=stream_writer)
        else:
            self.attach_streamer(streamer_address, stream_writer)

    async def detach_streamer(
        self,
        streamer_address: str
    ):
        """ Detaches a streamer from the playback session and closes the asynchronous
        network stream writer.

        Parameters
        ----------
        streamer_address: `str`
            The ip-address of the audio streamer.
        """

        if self.streamer_connection.streamer_address == streamer_address:

            # Close and reset the streamer connection
            await self.close()

    async def clear(self):
        """ Clears the streamers from the playback session and closes the asynchronous
        network stream writer.
        """
        await self.streamer_connection.disconnect()

    async def close(self):
        """ Detaches the streamer from the audio playback session and closes the asynchronous
        network stream writer.
        """

        # Close the streamer connection
        await self.clear()

        # Reset the streamer connection
        self.streamer_connection = StreamerConnection()
