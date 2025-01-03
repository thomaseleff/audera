""" Playback session configuration-layer """

from typing import Union, List
import os
import copy
from pytensils import config, utils
from audera.struct import player
from audera.dal import path, players


PATH: Union[str, os.PathLike] = os.path.join(path.HOME, 'sessions')
DTYPES: dict = {
    'session': {
        'name': 'str',
        'uuid': 'str',
        'group_uuid': 'str',
        'players': 'list',
        'provider': 'str',
        'volume': 'float'
    }
}


def exists(session: player.Session) -> bool:
    """ Returns `True` when the session configuration file exists.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """
    if os.path.isfile(
        os.path.abspath(
            os.path.join(
                PATH,
                '.'.join([session.uuid, 'json'])
            )
        )
    ):
        return True
    else:
        return False


def create(session: player.Session) -> config.Handler:
    """ Creates the session configuration file and returns the contents
    as a `pytensils.config.Handler` object.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of a `audera.player.Session` object.
    """

    # Create the player configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([session.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict({'session': session.to_dict()})

    return Config


def get(uuid: str) -> config.Handler:
    """ Returns the contents of the session configuration as a
    `pytensils.config.Handler` object.

    Parameters
    ----------
    uuid: `str`
        A unique universal identifier of an `audera.player.Session` object.
    """

    # Read the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([uuid, 'json'])
    )

    # Validate
    Config.validate(DTYPES)

    return Config


def get_or_create(session: player.Session) -> config.Handler:
    """ Creates or reads the session player configuration file and returns the contents as
    a `pytensils.config.Handler` object.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """
    if exists(session):
        return get(session.uuid)
    else:
        return create(session)


def save(session: player.Session) -> config.Handler:
    """ Saves the session player configuration to `~/.audera/sessions/{session.uuid}.json`.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """

    # Create the session configuration-layer directory
    if not os.path.isdir(PATH):
        os.makedirs(PATH)

    # Create the configuration file
    Config = config.Handler(
        path=PATH,
        file_name='.'.join([session.uuid, 'json']),
        create=True
    )
    Config = Config.from_dict({'session': session.to_dict()})

    return Config


def update(new: player.Session) -> config.Handler:
    """ Updates the session player configuration file `~/.audera/sessions/{session.uuid}.json`.

    Parameters
    ----------
    new: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """

    # Read the configuration file
    Config = get_or_create(new)

    # Convert the config to an audio player object
    Player = player.Session.from_config(config=Config)

    # Compare and update
    if not Player == new:

        # Update the player configuration object and write to the configuration file
        Config = Config.from_dict({'session': new.to_dict()})
        return Config

    else:
        return Config


def delete(session: player.Session):
    """ Deletes the configuration file associated with a `audera.struct.player.Session` object.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """
    if exists():
        os.remove(os.path.join(PATH, '.'.join([session.uuid, 'json'])))


def rename(session: player.Session, name: str) -> player.Session:
    """ Renames a session by setting `name` = {name}.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    """

    if session.name == name:
        return session

    session.name = utils.as_type(name, 'str')
    return player.Session.from_config(update(session))


def update_volume(session: player.Session, volume: float) -> player.Session:
    """ Updates the volume for a session by setting `volume` = {volume}.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    volume: `float`
        A float value from 0 to 100 that sets the loudness of playback. A value of
            0 is muted.
    """

    if session.volume == volume:
        return session

    session.volume = utils.as_type(volume, 'float')
    return player.Session.from_config(update(session))


def attach_players(
    session: player.Session,
    player_or_players: Union[player.Player, List[player.Player]]
) -> player.Session:
    """ Attaches an `audera.player.Player` object or a list of
    `audera.player.Player` objects to a session.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    player_or_players: `Union[player.Player, List[player.Player]]`
        An `audera.player.Player` object or a list of `audera.player.Player` objects.
    """

    # Update the session with the new players
    if isinstance(player_or_players, player.Player):
        player_or_players = [player_or_players]

    extended_players = copy.deepcopy(session.players)
    extended_players.extend([player_.uuid for player_ in player_or_players])
    extended_players = set(extended_players)

    if extended_players == set(session.players):
        return session

    session.players = sorted(list(extended_players))

    # Rename
    if len(session.players) == 1:
        only_player: player.Player = session.players[0]
        session.name = players.get(only_player).data['player']['name']
    else:
        first_player: player.Player = session.players[0]
        session.name = '%s + %s' % (
            players.get(first_player).data['player']['name'],
            int(len(session.players) - 1)
        )

    # Remove the session group-id
    session.group_uuid = ''

    return player.Session.from_config(update(session))


def attach_group(
    session: player.Session,
    group: player.Group
) -> player.Session:
    """ Attaches an `audera.player.Group` object to a session.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    group: `audera.player.Group`
        An instance of an `audera.player.Group` object.
    """

    if (
        group.name == session.name
        and group.players == session.players
    ):
        return session

    session.name = str(group.name)
    session.group_uuid = str(group.uuid)
    session.players = copy.deepcopy(group.players)
    session.volume = utils.as_type(group.volume, 'float')

    return player.Session.from_config(update(session))


def attach_players_or_group(
    session: player.Session,
    players_or_group: Union[player.Player, List[player.Player], player.Group]
) -> player.Session:
    """ Attaches an `audera.player.Player` object, a list of
    `audera.player.Player` objects, or an `audera.player.Group` object to a session.

    Parameters
    ----------
    session: `audera.player.Session`
        An instance of an `audera.player.Session` object.
    players_or_group: `Union[audera.player.Player, List[audera.player.Player], audera.player.Group]`
        An `audera.player.Player` object, a list of `audera.player.Player` objects, or an
            `audera.player.Group` object.
    """

    if isinstance(players_or_group, player.Group):
        return attach_group(session, players_or_group)
    else:
        return attach_players(session, players_or_group)


def get_session_players(uuid: str) -> list:
    """ Returns the session players as a `list`. """

    # Read the configuration file
    session: player.Session = player.Session.from_config(get(uuid))
    return session.players
