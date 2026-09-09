"""Systemd unit management"""

import logging
import subprocess

from audera.errors import ServiceError, Unreachable
from audera.services import platform

# Bounds every call. A `systemctl` verb that has not returned in 15 seconds is hung.
TIMEOUT: float = 15

# `CalledProcessError.__str__` carries the argv and the exit status but never `stderr`, so a
# failure's reason is logged here, into the `audera-streamer` journal.
LOGGER = logging.getLogger(__name__)


@platform.requires('dietpi')
def systemctl(*args: str, check: bool = True, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    """Runs `systemctl` with `args` and returns the completed process.

    Output is always captured, since `is_active()` reads `stdout`.

    Parameters
    ----------
    *args: `str`
        The `systemctl` arguments, e.g. `'restart', 'snapserver'`.
    check: `bool`
        Whether a non-zero exit status raises `subprocess.CalledProcessError`.
    timeout: `float`
        Seconds before the call is treated as hung. Defaults to `TIMEOUT`; raise it for a verb
        that legitimately runs longer on slow hardware, e.g. a synchronous `NetworkManager`
        restart on a Pi Zero W (armv6), which waits for the wifi driver to load.
    """
    try:
        return subprocess.run(
            ['systemctl', *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.error(f'systemctl {" ".join(args)} failed: {(exc.stderr or "").strip()}')
        raise ServiceError((exc.stderr or '').strip() or str(exc)) from exc
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise Unreachable(str(exc)) from exc


@platform.requires('dietpi')
def reboot() -> None:
    """Reboots the device via systemd.

    Routes through `systemctl()` for the `TIMEOUT`, the `stderr` logging, and the exception
    translation. `systemctl reboot` runs unprivileged on-device, so no `sudo` is needed.
    """
    systemctl('reboot')


@platform.requires('dietpi')
def is_active(unit: str) -> bool:
    """Returns `True` when the systemd unit is active.

    Parameters
    ----------
    unit: `str`
        The systemd unit name, e.g. `'plexamp'`.
    """
    try:
        # `check=False`: `systemctl is-active` exits 3 for an inactive unit, which is an expected
        # outcome here and must not raise.
        result = systemctl('is-active', unit, check=False)
        return result.stdout.strip() == 'active'
    except (Unreachable, ServiceError, RuntimeError):
        return False
