""" Data-access layer """

import os
from audera.dal import devices
from audera.dal import players

__all__ = ['devices', 'players']

PATH = os.path.abspath(os.path.join(os.path.expanduser('~'), '.audera'))
