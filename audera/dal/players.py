""" Player configuration-layer """

from typing import Union, List
import os
import coolname
import duckdb
from pytensils import config, utils
from audera.struct import player
from audera.dal import path


PATH: Union[str, os.PathLike] = os.path.join(path.HOME, 'players')
DTYPES: dict = {
    'player': {
        'name': 'str',
        'uuid': 'str',
        'mac_address': 'str',
        'address': 'str',
        'provider': 'str',
        'volume': 'float',
        'channels': 'int',
        'enabled': 'bool',
        'connected': 'bool',
        'playing': 'bool'
    }
}


def exists(uuid: str) -> bool:
    """ Returns `True` when the player configuration file exists.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """
    if os.path.isfile(
        os.path.abspath(
            os.path.join(
                PATH,
                '.'.join([uuid, 'json'])
            )
        )
    ):
        return True
    else:
        return False


def create(network_interface: player.NetworkInterface) -> config.Handler:
    """ Creates the player configuration file from a network interface
    and returns the contents as a `pytensils.config.Handler` object.

    Parameters
    ----------
    network_interface: `audera.struct.player.NetworkInterface`
        An instance of an `audera.struct.player.NetworkInterface` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([network_interface.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict(
        {
            'player': player.Player(
                name=coolname.generate_slug(2),
                uuid=network_interface.uuid,
                mac_address=network_interface.mac_address,
                address=network_interface.address
            ).to_dict()
        }
    )

    return Config


def get(uuid: str) -> config.Handler:
    """ Returns the contents of the player configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([uuid, 'json'])
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create(network_interface: player.NetworkInterface) -> config.Handler:
    """ Creates or reads the player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    network_interface: `audera.struct.player.NetworkInterface`
        An instance of an `audera.struct.player.NetworkInterface` object.
    """
    if exists(network_interface.uuid):
        return get(network_interface.uuid)
    else:
        return create(network_interface)


def save(player: player.Player) -> config.Handler:
    """ Saves the player configuration to `~/.audera/playerss/{player.uuid}.json`.

    Parameters
    ----------
    player: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([player.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict({'player': player.to_dict()})

    return Config


def update(new: player.Player) -> config.Handler:
    """ Updates the player configuration file `~/.audera/players/{player.uuid}.json`.

    Parameters
    ----------
    new: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    # Read the configuration file
    Config = get_or_create(
        player.NetworkInterface(
            uuid=new.uuid,
            mac_address=new.mac_address,
            address=new.address
        )
    )

    # Convert the config to an audio player object
    Player = player.Player.from_config(config=Config)

    # Compare and update
    if not Player == new:

        # Update the player configuration object and write to the configuration file
        Config = Config.from_dict({'player': new.to_dict()})

        return Config

    else:
        return Config


def delete(player_: player.Player):
    """ Deletes the configuration file associated with a `audera.struct.player.Player` object.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """
    if exists():
        os.remove(os.path.join(PATH, '.'.join([player_.uuid, 'json'])))


def connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect().execute(
        "CREATE TABLE players AS SELECT player.* FROM read_json_auto(?)",
        (os.path.join(PATH, '*.json'),)
    )


def query_to_players(cursor: duckdb.DuckDBPyConnection) -> List[player.Player]:
    columns = [desc[0] for desc in cursor.description]
    return [player.Player.from_dict(dict(zip(columns, row))) for row in cursor.fetchall()]


def get_all_players() -> List[player.Player]:
    """ Returns all players as a list of `audera.struct.player.Player` objects. """
    with connection() as conn:
        return query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                """
            )
        )


def get_all_available_players() -> List[player.Player]:
    """ Returns all available players as a list of `audera.struct.player.Player` objects. An
    available player is enabled and connected to the network.
    """
    with connection() as conn:
        return query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                WHERE enabled = True
                    AND connected = True
                """
            )
        )


def get_all_playing_players() -> List[player.Player]:
    """ Returns all currently playing players as a list of `audera.struct.player.Player` objects."""
    with connection() as conn:
        return query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                WHERE playing = True
                """
            )
        )


def play(player_: player.Player) -> player.Player:
    """ Starts audio playback to a player by setting `playing` = `True`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if not (player_.enabled and player_.connected and not player_.playing):
        return player_

    player_.playing = True
    return player.Player.from_config(update(player_))


def stop(player_: player.Player) -> player.Player:
    """ Stops audio playback to a player by setting `playing` = `False`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if not (player_.playing):
        return player_

    player_.playing = False
    return player.Player.from_config(update(player_))


def enable(player_: player.Player) -> player.Player:
    """ Enables a player by setting `enabled` = `True`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if (player_.enabled):
        return player_

    player_.enabled = True
    return player.Player.from_config(update(player_))


def disable(player_: player.Player) -> player.Player:
    """ Disables a player by setting `enabled` = `False`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if not (player_.enabled):
        return player_

    player_.enabled = False
    return player.Player.from_config(stop(player_))  # A player cannot be playing if it is disabled


def connect(player_: player.Player) -> player.Player:
    """ Connects a player by setting `connected` = `True`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if (player_.connected):
        return player_

    player_.connected = True
    return player.Player.from_config(update(player_))


def disconnect(player_: player.Player) -> player.Player:
    """ Disconnects a player by setting `connected` = `False`.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if not (player_.connected):
        return player_

    player_.connected = False
    return player.Player.from_config(player(player_))  # A player cannot be playing if it is disconnected


def rename(player_: player.Player, name: str) -> player.Player:
    """ Renames a player by setting `name` = {name}.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    name: `str`
        The new name of the audio player.
    """

    if player_.name == name:
        return player_

    player_.name = utils.as_type(name, 'str')
    return player.Player.from_config(update(player_))


def update_volume(player_: player.Player, volume: float) -> player.Player:
    """ Updates the volume for a player by setting `volume` = {volume}.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """

    if player_.volume == volume:
        return player_

    player_.volume = utils.as_type(volume, 'float')
    return player.Player.from_config(update(player_))


def update_channels(player_: player.Player, channels: int) -> player.Player:
    """ Updates the playback channels for a player by setting `channels` = {channels}.

    Parameters
    ----------
    player_: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    if player_.channels == channels:
        return player_

    player_.channels = utils.as_type(channels, 'int')
    return player.Player.from_config(update(player_))
