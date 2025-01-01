""" Data-access layer """

import os
from audera.dal import devices
from audera.dal import players
from audera.dal import groups

__all__ = ['devices', 'players', 'groups']

PATH = os.path.abspath(os.path.join(os.path.expanduser('~'), '.audera'))
