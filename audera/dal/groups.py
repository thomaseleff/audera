""" Group player configuration-layer """

from typing import Union, List
import os
import duckdb
from pytensils import config, utils
from audera.struct import player
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


def exists(uuid: str) -> bool:
    """ Returns `True` when the group player configuration file exists.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
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


def create(group: player.Group) -> config.Handler:
    """ Creates the group player configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    group: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """

    # Create the group player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([group.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict({'group': group.to_dict()})

    return config_


def get(uuid: str) -> config.Handler:
    """ Returns the contents of the group player configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    # Read the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([uuid, 'json'])
    )

    # Validate
    config_.validate(DTYPES)

    return config_


def get_or_create(group: player.Group) -> config.Handler:
    """ Creates or reads the group player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    group: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """
    if exists(group.uuid):
        return get(group.uuid)
    else:
        return create(group)


def save(group: player.Group) -> config.Handler:
    """ Saves the group player configuration to `~/.audera/groups/{group.uuid}.json`.

    Parameters
    ----------
    player: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """

    # Create the group player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([group.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict({'group': group.to_dict()})

    return config_


def update(new: player.Group) -> player.Group:
    """ Updates the group player configuration file `~/.audera/groups/{group.uuid}.json`.

    Parameters
    ----------
    new: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """

    # Read the configuration file
    config_ = get_or_create(new)

    # Convert the config to an audio group player object
    group = player.Group.from_config(config=config_)

    # Compare and update
    if not group == new:

        # Update the group player configuration object and write to the configuration file
        config_ = config_.from_dict({'group': new.to_dict()})

        return new

    else:
        return group


def delete(uuid: str):
    """ Deletes the configuration file associated with a `audera.struct.player.Group` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """
    if exists(uuid):
        os.remove(os.path.join(PATH, '.'.join([uuid, 'json'])))


def get_group(uuid: str) -> player.Group:
    """ Returns the group player as an `audera.struct.player.Group` object. """
    return player.Group.from_config(get(uuid))


def rename(uuid: str, name: str) -> player.Group:
    """ Renames a group player by setting `name` = {name}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    name: `str`
        The new name of the group player.
    """

    group = get_group(uuid)

    if group.name == name:
        return group

    group.name = utils.as_type(name, 'str')
    return update(group)


def play(uuid: str) -> player.Group:
    """ Starts audio playback to a group player by setting `playing` = `True`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    group = get_group(uuid)

    if not (group.enabled and not group.playing):
        return group

    available_players = players.get_all_available_player_uuids()
    for player_ in group.players:
        if player_ in available_players:
            players.play(player_)

    group.playing = True
    return update(group)


def stop(uuid: str) -> player.Group:
    """ Stops audio playback to a group player by setting `playing` = `False`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    group = get_group(uuid)

    if not (group.playing):
        return group

    available_players = players.get_all_available_player_uuids()
    for player_ in group.players:
        if player_ in available_players:
            players.stop(player_)

    group.playing = False
    return update(group)


def enable(uuid: str) -> player.Group:
    """ Enables a group player by setting `enabled` = `True`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    group = get_group(uuid)

    if (group.enabled):
        return group

    group.enabled = True
    return update(group)


def disable(uuid: str) -> player.Group:
    """ Disables a group player by setting `enabled` = `False`.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    group = get_group(uuid)

    if not (group.enabled):
        return group

    group.enabled = False
    return player.Group.from_config(stop(uuid))  # A group player cannot be playing if it is disabled


def update_volume(uuid: str, volume: float) -> player.Group:
    """ Updates the volume for a group player by setting `volume` = {volume}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """

    group = get_group(uuid)

    if group.volume == volume:
        return group

    group.volume = utils.as_type(volume, 'float')
    return update(group)


def attach_player(group_uuid: str, player_uuid: str) -> player.Group:
    """ Attaches a new player to a group player.

    Parameters
    ----------
    group_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    player_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    group = get_group(group_uuid)
    player_ = players.get_player(player_uuid)

    if player_uuid in group.players or not (player_.enabled and player_.connected):
        return group

    group.players.append(player_uuid)
    return update(group)


def detach_player(group_uuid: str, player_uuid: str) -> player.Group:
    """ Detaches a player from a group player.

    Parameters
    ----------
    group_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    player_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Player` object.
    """

    group = get_group(group_uuid)

    if player_uuid not in group.players:
        return group

    group.players.remove(player_uuid)
    return update(group)


def connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect().execute(
        'CREATE TABLE groups AS SELECT "group".* FROM read_json_auto(?)',
        (os.path.join(PATH, '*.json'),)
    )


def query_to_groups(cursor: duckdb.DuckDBPyConnection) -> List[player.Group]:
    columns = [desc[0] for desc in cursor.description]
    return [player.Group.from_dict(dict(zip(columns, row))) for row in cursor.fetchall()]


def get_all_groups() -> List[player.Group]:
    """ Returns all group players as a list of `audera.struct.player.Group` objects. """
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
    """ Returns all available group players as a list of `audera.struct.player.Group` objects. An
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


def get_all_available_group_uuids() -> List[str]:
    """ Returns the uuid of all available group players as a list. An
    available group player is enabled.
    """
    with connection() as conn:
        return [
            uuid[0] for uuid in conn.execute(
                """
                SELECT uuid
                FROM groups
                WHERE enabled = True
                """
            ).fetchall()
        ]


def get_all_playing_groups() -> List[player.Group]:
    """ Returns all currently playing players as a list of `audera.struct.player.Group` objects. """
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
    """ Returns all players from a group as a list of `audera.struct.player.Player` objects.

    Parameters
    ----------
    group: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """
    with players.connection() as conn:
        return players.query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                WHERE uuid IN (%s)
                """ % (", ".join(["'%s'" % (uuid) for uuid in group.players]))
            )
        )


def get_all_available_group_players(group: player.Group) -> List[player.Player]:
    """ Returns all available players from a group as a list of `audera.struct.player.Player` objects.

    Parameters
    ----------
    group: `audera.struct.player.Group`
        An instance of an `audera.struct.player.Group` object.
    """
    with players.connection() as conn:
        return players.query_to_players(
            conn.execute(
                """
                SELECT *
                FROM players
                WHERE uuid IN (%s)
                """ % (
                    ", ".join(
                        [
                            "'%s'" % (uuid) for uuid in group.players
                            if uuid in players.get_all_available_player_uuids()
                        ]
                    )
                )
            )
        )
