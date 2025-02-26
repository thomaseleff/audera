""" Playback session configuration-layer """

from typing import Union, List
import os
import copy
from pytensils import config, utils
from audera.struct import session, player
from audera.dal import path, players, groups


PATH: Union[str, os.PathLike] = os.path.join(path.HOME, 'sessions')
DTYPES: dict = {
    'session': {
        'name': 'str',
        'uuid': 'str',
        'mac_address': 'str',
        'address': 'str',
        'group': 'str',
        'players': 'list',
        'provider': 'str',
        'volume': 'float'
    }
}


def exists(uuid: str) -> bool:
    """ Returns `True` when the session configuration file exists.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
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


def create(session_: session.Session) -> config.Handler:
    """ Creates the session configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    session_: `audera.struct.session.Session`
        An instance of a `audera.struct.session.Session` object.
    """

    # Create the session configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([session_.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict({'session': session_.to_dict()})

    return config_


def get(uuid: str) -> config.Handler:
    """ Returns the contents of the session configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    """

    # Read the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([uuid, 'json'])
    )

    # Validate
    config_.validate(DTYPES)

    return config_


def get_or_create(session_: session.Session) -> config.Handler:
    """ Creates or reads the session player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    session_: `audera.struct.session.Session`
        An instance of an `audera.struct.session.Session` object.
    """
    if exists(session_.uuid):
        return get(session_.uuid)
    else:
        return create(session_)


def save(session_: session.Session) -> config.Handler:
    """ Saves the session player configuration to `~/.audera/sessions/{session.uuid}.json`.

    Parameters
    ----------
    session_: `audera.struct.session.Session`
        An instance of an `audera.struct.session.Session` object.
    """

    # Create the session configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    config_ = config.Handler(
        path=PATH,
        file_name='.'.join([session_.uuid, 'json']),
        create=True
    )
    config_ = config_.from_dict({'session': session_.to_dict()})

    return config_


def update(new: session.Session) -> session.Session:
    """ Updates the session player configuration file `~/.audera/sessions/{session.uuid}.json`.

    Parameters
    ----------
    new: `audera.struct.session.Session`
        An instance of an `audera.struct.session.Session` object.
    """

    # Read the configuration file
    config_ = get_or_create(new)

    # Convert the config to a playback session object
    session_ = session.Session.from_config(config=config_)

    # Compare and update
    if not session_ == new:

        # Update the session configuration object and write to the configuration file
        config_ = config_.from_dict({'session': new.to_dict()})
        return new

    else:
        return session_


def delete(uuid: str):
    """ Deletes the configuration file associated with a `audera.struct.session.Session` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    """
    if exists(uuid):
        os.remove(os.path.join(PATH, '.'.join([uuid, 'json'])))


def get_session(uuid: str) -> session.Session:
    """ Returns the playback session as an `audera.struct.session.Session` object. """
    return session.Session.from_config(get(uuid))


def rename(uuid: str, name: str) -> session.Session:
    """ Renames a session by setting `name` = {name}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    name: `str`
        The new name of the playback session.
    """

    session_ = get_session(uuid)

    if session_.name == name:
        return session_

    session_.name = utils.as_type(name, 'str')
    return update(session_)


def update_volume(uuid: str, volume: float) -> session.Session:
    """ Updates the volume for a session by setting `volume` = {volume}.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """

    session_ = get_session(uuid)

    if session_.volume == volume:
        return session_

    session_.volume = utils.as_type(volume, 'float')
    return update(session_)


def _generate_name(
    session_: session.Session
) -> str:
    """ Generates a session name from the names of the attached players.

    Parameters
    ----------
    session_: `audera.struct.session.Session`
        An instance of an `audera.struct.session.Session` object.
    """

    # Return the session name if the current session has a group player attached
    if session_.group:
        return session_.name

    # Return an empty name if no players are attached
    if not session_.players:
        return ''

    # Create a new name for the playback session
    name = players.get_player(session_.players[0]).name

    if len(session_.players) > 1:
        name = '%s + %s' % (
            name,
            int(len(session_.players) - 1)
        )

    return name


def attach_players(
    uuid: str,
    player_or_players: Union[str, List[str]]
) -> session.Session:
    """ Attaches an audio player or a list of audio players to a playback session.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    player_or_players: `Union[str, List[str]]`
        A unique universal identifier or a list of unique universal identifiers
            of `audera.struct.player.Player` objects.
    """

    # Get the playback session
    session_ = get_session(uuid)

    # Manage / handle parameter types
    if not isinstance(player_or_players, list):
        player_or_players = [player_or_players]

    # Return the session if the player(s) is(are) unavailable
    available_players = players.get_all_available_player_uuids()
    player_or_players = [
        player_uuid for player_uuid in player_or_players
        if player_uuid in available_players
    ]
    if not player_or_players:
        return session_

    # Return the session if the player(s) is(are) already attached
    extended_players = copy.deepcopy(session_.players)
    extended_players.extend(player_or_players)
    extended_players = set(extended_players)

    if extended_players == set(session_.players):
        return session_

    # Play the new player(s) to attach to the session
    for player_uuid in player_or_players:
        if player_uuid in available_players:
            players.play(player_uuid)

    # Update the playback session with the new player(s)
    session_.group = ''
    session_.players = sorted(list(extended_players))
    session_.name = _generate_name(session_)

    return update(session_)


def detach_players(
    uuid: str,
    player_or_players: Union[str, List[str]]
) -> session.Session:
    """ Detaches an audio player or a list of audio players from a playback session.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    player_or_players: `Union[str, List[str]]`
        A unique universal identifier or a list of unique universal identifiers
            of `audera.struct.player.Player` objects.
    """

    # Get the playback session
    session_ = get_session(uuid)

    # Manage / handle parameter types
    if not isinstance(player_or_players, list):
        player_or_players = [player_or_players]

    # Return the session if the player(s) is(are) not attached
    reduced_players = copy.deepcopy(session_.players)
    reduced_players = [
        player_uuid for player_uuid in reduced_players
        if player_uuid not in player_or_players
    ]
    reduced_players = set(reduced_players)

    if reduced_players == set(session_.players):
        return session_

    # Stop the player(s) detached from the session
    for player_uuid in player_or_players:
        if (
            player_uuid not in reduced_players
            and player_uuid in players.get_all_available_player_uuids()
        ):
            players.stop(player_uuid)

    # Update the playback session
    session_.group = ''
    session_.players = sorted(list(reduced_players))
    session_.name = _generate_name(session_)

    return update(session_)


def attach_group(session_uuid: str, group_uuid: str) -> session.Session:
    """ Attaches a group player to a playback session.

    Parameters
    ----------
    session_uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    group_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    # Get the playback session
    session_ = get_session(session_uuid)

    # Return the session if the group player is unavailable
    available_groups = groups.get_all_available_group_uuids()
    if group_uuid not in available_groups:
        return session_

    # Return the session if the group player is already attached
    group = groups.get_group(group_uuid)
    if (
        group.name == session_.name
        and group.players == session_.players
    ):
        return session_

    # Stop the current group player attached to the session
    #   if the current playback session is assigned a group player
    if session_.group in available_groups:
        groups.stop(session_.group)

    # Play the new group player to attach to the session
    groups.play(group_uuid)

    # Update the playback session
    session_.name = group.name
    session_.group = group.uuid
    session_.players = copy.deepcopy(group.players)
    session_.volume = group.volume

    return update(session_)


def detach_group(session_uuid: str, group_uuid: str) -> session.Session:
    """ Detaches a group player from a playback session.

    Parameters
    ----------
    session_uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    group_uuid: `str`
        A unique universal identifier of an `audera.struct.player.Group` object.
    """

    # Get the playback session and group player
    session_ = get_session(session_uuid)

    # Return the session if the group player is not attached
    group = groups.get_group(group_uuid)
    if not (
        group.name == session_.name
        and group.players == session_.players
    ):
        return session_

    # Stop the group player detached from the session
    #   if the current playback session is assigned a group player
    if group_uuid in groups.get_all_available_group_uuids():
        groups.stop(group_uuid)

    # Update the playback session
    session_.name = ''
    session_.group = ''
    session_.players = []

    return update(session_)


def attach_players_or_group(
    uuid: str,
    players_or_group: Union[player.Player, List[player.Player], player.Group]
) -> session.Session:
    """ Attaches an `audera.struct.player.Player` object, a list of
    `audera.struct.player.Player` objects, or an `audera.struct.player.Group` object to a playback session.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    players_or_group: `Union[audera.player.Player, List[audera.player.Player], audera.player.Group]`
        An `audera.struct.player.Player` object, a list of `audera.struct.player.Player` objects, or an
            `audera.struct.player.Group` object.
    """

    if isinstance(players_or_group, player.Group):
        return attach_group(uuid, players_or_group.uuid)
    else:
        if isinstance(players_or_group, player.Player):
            players_or_group = [players_or_group]

        return attach_players(uuid, [player_.uuid for player_ in players_or_group])


def detach_players_or_group(
    uuid: str,
    players_or_group: Union[player.Player, List[player.Player], player.Group]
) -> session.Session:
    """ Detaches an `audera.struct.player.Player` object, a list of
    `audera.struct.player.Player` objects, or an `audera.struct.player.Group` object to a playback session.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    players_or_group: `Union[audera.player.Player, List[audera.player.Player], audera.player.Group]`
        An `audera.struct.player.Player` object, a list of `audera.struct.player.Player` objects, or an
            `audera.struct.player.Group` object.
    """

    if isinstance(players_or_group, player.Group):
        return detach_group(uuid, players_or_group.uuid)
    else:
        if isinstance(players_or_group, player.Player):
            players_or_group = [players_or_group]

        return detach_players(uuid, [player_.uuid for player_ in players_or_group])


def get_session_players(uuid: str) -> list[player.Player]:
    """ Returns the session players as a list of `audera.struct.player.Player` objects.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.struct.session.Session` object.
    """

    session_ = get_session(uuid)
    return [players.get_player(player_) for player_ in session_.players]
