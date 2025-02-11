""" Player configuration-layer """

from typing import Union, List
import os
import duckdb
from pytensils import config, utils
from audera.struct import identity, player
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


def create(identity_: identity.Identity) -> config.Handler:
    """ Creates the player configuration file from a player identity
    and returns the contents as a `pytensils.config.Handler` object.

    Parameters
    ----------
    identity_: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([identity_.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict(
        {
            'player': player.Player(
                name=identity_.name,
                uuid=identity_.uuid,
                mac_address=identity_.mac_address,
                address=identity_.address
            ).to_dict()
        }
    )

    return config_


def get(uuid: str) -> config.Handler:
    """ Returns the contents of the player configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    # Read the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([uuid, 'json'])
    )

    # Validate
    config_.validate(DTYPES)

    return config_


def get_or_create(identity_: identity.Identity) -> config.Handler:
    """ Creates or reads the player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    identity_: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """
    if exists(identity_.uuid):
        return get(identity_.uuid)
    else:
        return create(identity_)


def save(player: player.Player) -> config.Handler:
    """ Saves the player configuration to `~/.audera/players/{player.uuid}.json`.

    Parameters
    ----------
    player: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([player.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict({'player': player.to_dict()})

    return config_


def update(new: player.Player) -> player.Player:
    """ Updates the player configuration file `~/.audera/players/{player.uuid}.json`.

    Parameters
    ----------
    new: `audera.struct.player.Player`
        An instance of an `audera.struct.player.Player` object.
    """

    # Read the configuration file
    config_ = get_or_create(
        identity.Identity(
            name=new.name,
            uuid=new.uuid,
            mac_address=new.mac_address,
            address=new.address
        )
    )

    # Convert the config to an audio player object
    player_ = player.Player.from_config(config=config_)

    # Compare and update
    if not player_ == new:

        # Update the player configuration object and write to the configuration file
        config_ = config_.from_dict({'player': new.to_dict()})

        return new

    else:
        return player_


def delete(uuid: str):
    """ Deletes the configuration file associated with a `audera.struct.player.Player` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """
    if exists(uuid):
        os.remove(os.path.join(PATH, '.'.join([uuid, 'json'])))


def get_player(uuid: str) -> player.Player:
    """ Returns the player as an `audera.struct.player.Player` object. """
    return player.Player.from_config(get(uuid))


def rename(uuid: str, name: str) -> player.Player:
    """ Renames a player by setting `name` = {name}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    name: `str`
        The new name of the audio player.
    """

    player_ = get_player(uuid)

    if player_.name == name:
        return player_

    player_.name = utils.as_type(name, 'str')
    return update(player_)


def play(uuid: str) -> player.Player:
    """ Starts audio playback to a player by setting `playing` = `True`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if not (player_.enabled and player_.connected and not player_.playing):
        return player_

    player_.playing = True
    return update(player_)


def stop(uuid: str) -> player.Player:
    """ Stops audio playback to a player by setting `playing` = `False`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if not (player_.playing):
        return player_

    player_.playing = False
    return update(player_)


def enable(uuid: str) -> player.Player:
    """ Enables a player by setting `enabled` = `True`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if (player_.enabled):
        return player_

    player_.enabled = True
    return update(player_)


def disable(uuid: str) -> player.Player:
    """ Disables a player by setting `enabled` = `False`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if not (player_.enabled):
        return player_

    player_.enabled = False
    player_.playing = False  # A player cannot be playing if it is disabled
    return update(player_)


def connect(uuid: str) -> player.Player:
    """ Connects a player by setting `connected` = `True`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if (player_.connected):
        return player_

    player_.connected = True
    return update(player_)


def disconnect(uuid: str) -> player.Player:
    """ Disconnects a player by setting `connected` = `False`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if not (player_.connected):
        return player_

    player_.connected = False
    player_.playing = False  # A player cannot be playing if it is disconnected
    return update(player_)


def update_volume(uuid: str, volume: float) -> player.Player:
    """ Updates the volume for a player by setting `volume` = {volume}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """

    player_ = get_player(uuid)

    if player_.volume == volume:
        return player_

    player_.volume = utils.as_type(volume, 'float')
    return update(player_)


def update_channels(uuid: str, channels: int) -> player.Player:
    """ Updates the playback channels for a player by setting `channels` = {channels}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    player_ = get_player(uuid)

    if player_.channels == channels:
        return player_

    player_.channels = utils.as_type(channels, 'int')
    return update(player_)


def connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect().execute(
        "CREATE TABLE players AS SELECT player.* FROM read_json_auto(?)",
        (os.path.join(PATH, '*.json'),)
    )


def query_to_players(cursor: duckdb.DuckDBPyConnection) -> List[player.Player]:
    columns = [desc[0] for desc in cursor.description]
    return [player.Player.from_dict(dict(zip(columns, row))) for row in cursor.fetchall()]


def get_player_by_address(address: str) -> player.Player:
    """ Returns the player associated with the ip-address on the local network as an
    `audera.struct.player.Player` object.

    Parameters
    ----------
    address: `str`
        The ip-address of the player.
    """
    try:
        with connection() as conn:
            return query_to_players(
                conn.execute(
                    """
                    SELECT *
                    FROM players
                    WHERE address = '%s'
                    """ % (str(address))
                )
            )[0]
    except duckdb.IOException:
        return None


def get_all_players() -> List[player.Player]:
    """ Returns all players as a list of `audera.struct.player.Player` objects. """
    try:
        with connection() as conn:
            return query_to_players(
                conn.execute(
                    """
                    SELECT *
                    FROM players
                    """
                )
            )
    except duckdb.IOException:
        return []


def get_all_available_players() -> List[player.Player]:
    """ Returns all available players as a list of `audera.struct.player.Player` objects. An
    available player is enabled and connected to the network.
    """
    try:
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
    except duckdb.IOException:
        return []


def get_all_available_player_uuids() -> List[str]:
    """ Returns the uuid of all available players as a list. An
    available player is enabled and connected to the network.
    """
    try:
        with connection() as conn:
            return [
                str(uuid[0]) for uuid in conn.execute(
                    """
                    SELECT uuid
                    FROM players
                    WHERE enabled = True
                        AND connected = True
                    """
                ).fetchall()  # Duckdb converts uuid-like objects into `uuid.UUID` objects.
            ]
    except duckdb.IOException:
        return []


def get_all_playing_players() -> List[player.Player]:
    """ Returns all currently playing players as a list of `audera.struct.player.Player` objects."""
    try:
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
    except duckdb.IOException:
        return []
