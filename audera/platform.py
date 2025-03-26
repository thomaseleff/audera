""" Operating-system management """

from typing import Callable, Literal
import os
import dotenv
import platform

# Load the dietpi os environment
dotenv.load_dotenv('/boot/dietpi/.version')

NAME = 'dietpi' if os.getenv('G_DIETPI_VERSION_CORE') else platform.system().strip().lower()
VERSION = '.'.join(
    os.getenv('G_DIETPI_VERSION_CORE', '0'),
    os.getenv('G_DIETPI_VERSION_SUB', '0'),
    os.getenv('G_DIETPI_VERSION_RC', '0')
) if os.getenv('G_DIETPI_VERSION_CORE') else platform.version().strip().lower()


# Decorator function(s)
def requires(
    platform_: Literal['any', 'dietpi', 'windows', 'linux', 'darwin'] = 'any'
) -> Callable:
    """ Raises an exception when the function is called on an unsupported platform.

    Parameters
    ----------
    platform_: `Literal['any', 'dietpi', 'windows', 'linux', 'darwin'] = 'dietpi'`
        The required platform. Default='dietpi'.
    """

    if platform_.strip().lower() not in ['any', 'dietpi', 'windows', 'linux', 'darwin']:
        raise ValueError(
            "Invalid platform {%s}. Platform must be either ['dietpi', 'windows', 'linux', 'darwin']." % (
                platform_.strip().lower()
            )
        )

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):

            # Check the platform
            if platform_.strip().lower() != 'any':
                if NAME.strip().lower() != platform_.strip().lower():
                    raise RuntimeError(
                        "Invalid platform {%s}. %s() requires {%s}." % (
                            NAME.strip().lower(),
                            func.__name__,
                            platform_.strip().lower()
                        )
                    )

            return func(*args, **kwargs)
        return wrapper

    return decorator
