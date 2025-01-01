""" Group player configuration-layer """

from typing import Union, List
import os
import duckdb
from pytensils import config, utils
from audera import player
from audera.dal import path, players


PATH: Union[str, os.PathLike] = os.path.join(path.HOME, 'groups')
DTYPES: dict = {
    'group': {
        'name': 'str',
        'uuid': 'str',
        'players': 'list',
        'provider': 'str',
        'volume': 'float',
        'enabled': 'bool',
        'playing': 'bool'
    }
}


def exists(group: player.Group) -> bool:
    """ Returns `True` when the group player configuration file exists.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """
    if os.path.isfile(
        os.path.abspath(
            os.path.join(
                PATH,
                '.'.join([group.uuid, 'json'])
            )
        )
    ):
        return True
    else:
        return False


def create(group: player.Group) -> config.Handler:
    """ Creates the group player configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    group: `player.Group`
        An instance of an `player.Group` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([group.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict({'group': group.to_dict()})

    return Config


def get(group: player.Group) -> config.Handler:
    """ Returns the contents of the group player configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([group.uuid, 'json'])
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create(group: player.Group) -> config.Handler:
    """ Creates or reads the group player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """
    if exists(group):
        return get(group)
    else:
        return create(group)


def save(group: player.Group) -> config.Handler:
    """ Saves the group player configuration to `~/.audera/groups/{group.uuid}.json`.

    Parameters
    ----------
    player: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.mkdir(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([group.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict({'group': group.to_dict()})

    return Config


def update(new: player.Group) -> config.Handler:
    """ Updates the group player configuration file `~/.audera/group/{group.uuid}.json`.

    Parameters
    ----------
    new: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    # Read the configuration file
    Config = get_or_create(new)

    # Convert the config to an audio player object
    Player = player.Group.from_config(config=Config)

    # Compare and update
    if not Player == new:

        # Update the player configuration object and write to the configuration file
        Config = Config.from_dict({'group': new.to_dict()})

        return Config

    else:
        return Config


def delete(group: player.Group):
    """ Deletes the configuration file associated with a `player.Group` object.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """
    if exists():
        os.remove(os.path.join(PATH, '.'.join([group.uuid, 'json'])))


def connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect().execute(
        'CREATE TABLE groups AS SELECT "group".* FROM read_json_auto(?)',
        (os.path.join(PATH, '*.json'),)
    )


def query_to_groups(cursor: duckdb.DuckDBPyConnection) -> List[player.Group]:
    columns = [desc[0] for desc in cursor.description]
    return [player.Group.from_dict(dict(zip(columns, row))) for row in cursor.fetchall()]


def get_all_groups() -> List[player.Group]:
    """ Returns all group players as a list of `player.Group` objects. """
    with connection() as conn:
        return query_to_groups(
            conn.execute(
                """
                SELECT *
                FROM groups
                """
            )
        )


def get_all_available_groups() -> List[player.Group]:
    """ Returns all available group players as a list of `player.Group` objects. An
    available group player is enabled.
    """
    with connection() as conn:
        return query_to_groups(
            conn.execute(
                """
                SELECT *
                FROM groups
                WHERE enabled = True
                """
            )
        )


def get_all_playing_groups() -> List[player.Group]:
    """ Returns all currently playing players as a list of `player.Group` objects. """
    with connection() as conn:
        return query_to_groups(
            conn.execute(
                """
                SELECT *
                FROM groups
                WHERE playing = True
                """
            )
        )


def get_all_group_players(group: player.Group) -> List[player.Player]:
    """ Returns all players from a group as a list of `player.Player` objects.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """
    with players.connection() as conn:
        return players.query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                WHERE uuid in (%s)
                """ % (", ".join(["'%s'" % (uuid) for uuid in group.players]))
            )
        )


def play(group: player.Group) -> player.Group:
    """ Starts audio playback to a group player by setting `playing` = `True`.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if not (group.enabled and not group.playing):
        return group

    group.playing = True
    return player.Group.from_config(update(group))


def stop(group: player.Group) -> player.Group:
    """ Stops audio playback to a group player by setting `playing` = `False`.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if not (group.playing):
        return group

    group.playing = False
    return player.Group.from_config(update(group))


def enable(group: player.Group) -> player.Group:
    """ Enables a group player by setting `enabled` = `True`.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if (group.enabled):
        return group

    group.enabled = True
    return player.Group.from_config(update(group))


def disable(group: player.Group) -> player.Group:
    """ Disables a group player by setting `enabled` = `False`.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if not (group.enabled):
        return group

    group.enabled = False
    return player.Group.from_config(stop(group))  # A player cannot be playing if it is disabled


def rename(group: player.Group, name: str) -> player.Group:
    """ Renames a group player by setting `name` = {name}.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if group.name == name:
        return group

    group.name = utils.as_type(name, 'str')
    return player.Group.from_config(update(group))


def update_volume(group: player.Group, volume: float) -> player.Group:
    """ Updates the volume for a group player by setting `volume` = {volume}.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if group.volume == volume:
        return group

    group.volume = utils.as_type(volume, 'float')
    return player.Group.from_config(update(group))


def add_player(group: player.Group, player_: player.Player) -> player.Group:
    """ Adds a new player to a group player.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    player_: `audera.player.Player`
        An instance of an `audera.player.Player` object.
    """

    if player_.uuid in group.players:
        return group

    group.players.append(player_.uuid)
    return player.Group.from_config(update(group))


def remove_player(group: player.Group, player_: player.Player) -> player.Group:
    """ Removes a player from a group player.

    Parameters
    ----------
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    player_: `audera.player.Player`
        An instance of an `audera.player.Player` object.
    """

    if player_.uuid not in group.players:
        return group

    group.players.remove(player_.uuid)
    return player.Group.from_config(update(group))
