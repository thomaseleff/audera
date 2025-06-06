""" Data-access layer """

import os
from audera.dal import interfaces
from audera.dal import devices
from audera.dal import identities
from audera.dal import players
from audera.dal import groups
from audera.dal import sessions

__all__ = ['interfaces', 'devices', 'identities', 'players', 'groups', 'sessions']

PATH = os.path.abspath(os.path.join(os.path.expanduser('~'), '.audera'))
