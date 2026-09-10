"""Integration tests for the streamer dashboard UI."""

import asyncio
import os
import subprocess
import time
from types import SimpleNamespace
from typing import Callable, TypeVar

import pytest
from nicegui import core, ui
from nicegui.client import Client
from nicegui.testing import User

import audera.ui.streamer.pages._plex as streamer_plex
from audera.cli import conf
from audera.clients import CamillaDSPClient, SnapserverClient
from audera.dal import balance as balance_dal
from audera.dal import dsp as dsp_dal
from audera.dal import presets as presets_dal
from audera.dal import settings as settings_dal
from audera.dal import sources as sources_dal
from audera.dal import volume as volume_dal
from audera.domains.sources import CATALOG, SourceDefinition, default_source
from audera.errors import ServiceError, Unreachable
from audera.models.balance import ReferenceBalance
from audera.models.dsp import Band, DSPConfig, Preset
from audera.models.player import Group, Player
from audera.models.settings import Settings
from audera.services import system
from audera.ui import components, features
from audera.ui.streamer import broker, commands
from audera.ui.streamer.pages import Page, current, index
from audera.ui.streamer.pages import dsp as dsp_page
from audera.ui.streamer.pages.dsp import _band_summary

_ElementT = TypeVar('_ElementT', bound=ui.element)


def _unreachable(self, *args, **kwargs):
    raise ConnectionRefusedError()


def _seed_hub(
    monkeypatch,
    players: list[Player] | None = None,
    groups: list[Group] | None = None,
    stream_status: dict[str, str] | None = None,
    volumes: dict[str, int | None] | None = None,
) -> broker.EventBroker:
    """Injects a pre-seeded Hub singleton without starting its async tasks.

    Also mocks ``SnapserverClient.get_status`` from the hub cache so ``broker.reseed()``
    (called after source toggles) refreshes from the same seeded state instead of opening
    a real socket. Stream status is read live from the cache dict so readiness tests that
    mutate ``mock_stream_status`` during the wait still reseed correctly.
    """
    h = broker.EventBroker.__new__(broker.EventBroker)
    h._host = 'localhost'
    h._port = 1780
    h._url = 'ws://localhost:1780/jsonrpc'
    h.cache = broker.Cache()
    h._callbacks = []
    h._prev_snapshot = ()
    h._reader_task = None
    h._debounce_handle = None
    h._stopped = True
    h.cache.clients = list(players or [])
    h.cache.groups = list(groups or [])
    h.cache.stream_status = stream_status if stream_status is not None else {}
    h.cache.volumes = volumes if volumes is not None else {p.id: 80 for p in (players or []) if p.connected}
    h._prev_snapshot = h.cache.snapshot()
    monkeypatch.setattr(broker, '_broker', h)

    def _get_status(self) -> dict:
        groups_payload = []
        for group in h.cache.groups:
            clients_payload = []
            for client in h.cache.clients:
                if client.group_id != group.id:
                    continue
                clients_payload.append(
                    {
                        'id': client.id,
                        'connected': client.connected,
                        'host': {'ip': client.host, 'port': client.port, 'name': client.name},
                        'config': {
                            'name': client.name,
                            'volume': {'percent': client.volume, 'muted': client.muted},
                            'latency': client.latency_ms,
                        },
                    }
                )
            groups_payload.append(
                {
                    'id': group.id,
                    'name': group.name,
                    'stream_id': group.stream_id,
                    'muted': group.muted,
                    'clients': clients_payload,
                    'volume': {'percent': group.volume},
                }
            )
        streams_payload = [{'id': stream_id, 'status': status} for stream_id, status in h.cache.stream_status.items()]
        return {'server': {'groups': groups_payload, 'streams': streams_payload}}

    monkeypatch.setattr(SnapserverClient, 'get_status', _get_status)
    return h


def _drag_slider(slider: ui.slider, value: int) -> None:
    """Simulates a user dragging a slider to `value` by firing the Quasar `update:model-value` event.

    Setting `slider.value` programmatically fires `on_change` but NOT `update:model-value`, which
    is the event the volume controls use for persistence (so a broker push cannot echo back). This
    helper fires the right event for tests that assert on persistence.
    """
    # Select the app's persistence listener over NiceGUI's own built-in value-sync handler. Both sit
    # on `update:modelValue`; the built-in is a closure defined inside NiceGUI's `ValueElement`,
    # while the app handler lives in the `audera` package. Discriminate by the handler's defining
    # module rather than its literal name, so an internal rename of NiceGUI's handler cannot silently
    # break the match.
    for listener in slider._event_listeners.values():
        if listener.type != 'update:modelValue':
            continue
        if not (getattr(listener.handler, '__module__', '') or '').startswith('nicegui'):
            slider._handle_event({'listener_id': listener.id, 'args': value})
            return
    raise AssertionError('no update:model-value listener found on slider')


async def _settled(condition: Callable[[], bool], *, timeout: float = 5.0, interval: float = 0.01) -> None:
    """Yields to the event loop until `condition()` holds, or until `timeout` passes.

    NiceGUI schedules a click's handler and a `@ui.refreshable`'s rebuild as tasks the caller does
    not await, so an assertion on the line after a click reads the pre-click state.

    Returns rather than raises at the deadline, so the caller's own assertion reports what it read.

    Parameters
    ----------
    condition: `Callable[[], bool]`
        What the click is expected to have produced. Called on the event loop, so it must not
        block.
    timeout: `float`
        How long to wait before giving up.
    interval: `float`
        The retry interval.
    """
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return
        await asyncio.sleep(interval)


async def _stable(read: Callable[[], object], *, timeout: float = 5.0, interval: float = 0.01) -> object:
    """Returns `read()` once two consecutive readings agree, or the last one at the deadline.

    `_settled`'s counterpart for an element identity, which a pending rebuild changes to a value
    nothing can name in advance. Agreement means no pending rebuild changed the identity between
    readings.

    Parameters
    ----------
    read: `Callable[[], object]`
        The identity to sample. Called on the event loop, so it must not block.
    timeout: `float`
        How long to wait for two readings to agree.
    interval: `float`
        The gap between readings, which also gives a scheduled rebuild room to run.
    """
    deadline = time.monotonic() + timeout
    previous = read()
    while True:
        await asyncio.sleep(interval)
        current = read()
        if current == previous or time.monotonic() >= deadline:
            return current
        previous = current


# Every snapserver fixture mocks the full read set a render performs: stream status always, and
# CamillaDSP wherever a player is served, whether or not the test under it reads either. Both
# clients are reached synchronously from the render with a 5 s `open_timeout`, so an unmocked
# method opens a real socket on the event loop and blocks for the full timeout once per call site
# per render. `_stream_status` connects to `settings.snapserver_host`, which a repo-root `.env`
# points at a real streamer, and `_build_player_card` connects to the player's own host.
# `_stream_status` swallows the failure into `{}`, so the empty map these fixtures return matches
# what the timeout would have produced.
@pytest.fixture(autouse=True)
async def _command_queue(monkeypatch):
    """Starts a command queue for each test and tears it down afterwards."""
    q = commands.CommandQueue()
    q.start()
    monkeypatch.setattr(commands, '_queue', q)
    yield
    await q.stop()


@pytest.fixture
def mock_snapserver_empty(monkeypatch, mock_stream_status):
    _seed_hub(monkeypatch, players=[], groups=[], stream_status=mock_stream_status, volumes={})
    monkeypatch.setattr(SnapserverClient, 'get_clients', _unreachable)


@pytest.fixture
def mock_snapserver_with_client(monkeypatch, mock_camilladsp, mock_stream_status):
    player = Player(id='abc123', host='192.168.1.50', port=1704, connected=True, volume=80, name='Living Room')

    _seed_hub(monkeypatch, players=[player], groups=[], stream_status=mock_stream_status)
    monkeypatch.setattr(SnapserverClient, 'get_clients', lambda self: [player])
    monkeypatch.setattr(SnapserverClient, 'get_groups', _unreachable)
    return player


@pytest.fixture
def mock_snapserver_with_muted_client(monkeypatch, mock_camilladsp, mock_stream_status):
    player = Player(id='abc123', host='192.168.1.50', port=1704, connected=True, volume=80, muted=True, name='Living Room')

    _seed_hub(monkeypatch, players=[player], groups=[], stream_status=mock_stream_status)
    monkeypatch.setattr(SnapserverClient, 'get_clients', lambda self: [player])
    monkeypatch.setattr(SnapserverClient, 'get_groups', _unreachable)
    return player


def _two_clients(*group_ids: str) -> list[Player]:
    """Returns two connected players, one per supplied group id."""
    names = [('abc123', '192.168.1.50', 'Living Room'), ('def456', '192.168.1.51', 'Kitchen')]
    return [
        Player(id=id, host=host, port=1704, connected=True, volume=80, group_id=group_id, name=name)
        for (id, host, name), group_id in zip(names, group_ids)
    ]


def _mock_groups(
    monkeypatch,
    players: list[Player],
    groups: list[Group],
    stream_status: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Serves `players` and `groups`, and writes a move through to `groups`.

    Returns the ordered `(group_id, stream_id)` move log. Under the by-stream grouping the card's
    position is its assignment, so a read-only `set_group_stream` mock would re-render the card
    where it started.
    """
    moves: list[tuple[str, str]] = []

    def _set_group_stream(self, group_id: str, stream_id: str) -> dict:
        moves.append((group_id, stream_id))
        for group in groups:
            if group.id == group_id:
                group.stream_id = stream_id
        h = broker.get()
        for g in h.cache.groups:
            if g.id == group_id:
                g.stream_id = stream_id
        return {}

    _seed_hub(monkeypatch, players=players, groups=groups, stream_status=stream_status)
    monkeypatch.setattr(SnapserverClient, 'get_clients', lambda self: list(players))
    monkeypatch.setattr(SnapserverClient, 'get_groups', lambda self: list(groups))
    monkeypatch.setattr(SnapserverClient, 'set_group_stream', _set_group_stream)
    return moves


@pytest.fixture
def mock_snapserver_two_players(monkeypatch, mock_camilladsp, mock_stream_status):
    """Two connected players, in separate groups, listening to different streams."""
    return _mock_groups(
        monkeypatch,
        _two_clients('g1', 'g2'),
        [
            Group(id='g1', name='', client_ids=['abc123'], stream_id='Spotify'),
            Group(id='g2', name='', client_ids=['def456'], stream_id='AirPlay'),
        ],
        stream_status=mock_stream_status,
    )


@pytest.fixture
def mock_snapserver_shared_group(monkeypatch, mock_camilladsp, mock_stream_status):
    """Two connected players in one group, a state Snapweb can create and Audera cannot."""
    return _mock_groups(
        monkeypatch,
        _two_clients('g1', 'g1'),
        [Group(id='g1', name='', client_ids=['abc123', 'def456'], stream_id='Spotify')],
        stream_status=mock_stream_status,
    )


@pytest.fixture
def mock_snapserver_orphan_stream(monkeypatch, mock_camilladsp, mock_stream_status):
    """One connected player whose group is parked on an uncatalogued stream."""
    return _mock_groups(
        monkeypatch,
        _two_clients('g1', 'g2')[:1],
        [Group(id='g1', name='', client_ids=['abc123'], stream_id='Ghost')],
        stream_status=mock_stream_status,
    )


@pytest.fixture
def mock_camilladsp(monkeypatch):
    # Stateful, like the real daemon: get returns the last-set percent, seeded at 80.
    calls = {}
    state = {'volume': 80}

    def _set_percent_volume(self, percent: int) -> None:
        calls['set_percent_volume'] = percent
        state['volume'] = percent

    def _get_percent_volume(self) -> int:
        calls['get_percent_volume'] = True
        return state['volume']

    def _set_volume(self, level: float) -> None:
        calls['set_volume'] = level

    monkeypatch.setattr(CamillaDSPClient, 'set_percent_volume', _set_percent_volume)
    monkeypatch.setattr(CamillaDSPClient, 'get_percent_volume', _get_percent_volume)
    monkeypatch.setattr(CamillaDSPClient, 'set_volume', _set_volume)
    return calls


@pytest.fixture
def mock_camilladsp_unreadable(monkeypatch, mock_camilladsp):
    """Serves a player whose CamillaDSP volume read fails.

    Layered over `mock_camilladsp`, which the snapserver fixtures depend on, so the rest of the
    render's read set stays served.
    """

    def _get_percent_volume(self) -> int:
        raise OSError('unreachable')

    monkeypatch.setattr(CamillaDSPClient, 'get_percent_volume', _get_percent_volume)
    return mock_camilladsp


@pytest.fixture
def mock_camilladsp_dsp(monkeypatch):
    """Mocks the CamillaDSP client for the Advanced DSP editor page.

    Records the Save choreography (get/validate/set config, reset clipped samples) and
    keeps the last-set config so a re-open would see the compiled pipeline. Keeps the
    tests daemon-free while `response_peak_db` still runs the real `camilladsp_plot`.
    """
    calls = {}
    state = {'config': {'devices': {'samplerate': 48000}, 'filters': {}, 'pipeline': []}}

    def _get_config(self) -> dict:
        calls['get_config'] = True
        return state['config']

    def _validate_config(self, config: dict) -> None:
        calls['validate_config'] = config

    def _set_config(self, config: dict) -> None:
        calls['set_config'] = config
        state['config'] = config

    def _get_clipped_samples(self) -> int:
        return 0

    def _reset_clipped_samples(self) -> None:
        calls['reset_clipped_samples'] = True

    monkeypatch.setattr(CamillaDSPClient, 'get_config', _get_config)
    monkeypatch.setattr(CamillaDSPClient, 'validate_config', _validate_config)
    monkeypatch.setattr(CamillaDSPClient, 'set_config', _set_config)
    monkeypatch.setattr(CamillaDSPClient, 'get_clipped_samples', _get_clipped_samples)
    monkeypatch.setattr(CamillaDSPClient, 'reset_clipped_samples', _reset_clipped_samples)
    return calls


@pytest.fixture
def mock_snapserver_volume(monkeypatch):
    calls = {}

    def _set_client_volume(self, client_id: str, percent: int, muted: bool = False):
        calls['set_client_volume'] = (client_id, percent, muted)

    monkeypatch.setattr(SnapserverClient, 'set_client_volume', _set_client_volume)
    return calls


@pytest.fixture
def db_volume_mode(audera_home):
    """Seeds settings so the volume control renders in dB mode (rather than percent)."""
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.VOLUME_KEY: features.FF_VOLUME_PERC_OR_DB},
        )
    )


async def test_index_renders_tabs(audera_home, mock_snapserver_empty, monkeypatch, user: User):
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'inactive')
    Page().load()
    await user.open('/')
    await user.should_see('Players')
    await user.should_see('Sources')
    await user.should_see('Settings')


async def test_players_tab_shows_empty_state(audera_home, mock_snapserver_empty, user: User):
    Page().load()
    await user.open('/')
    await user.should_see('No Snapcast clients found.')


async def test_players_tab_shows_connected_client(audera_home, mock_snapserver_with_client, user: User):
    Page().load()
    await user.open('/')
    await user.should_see('Living Room')
    await user.should_see('Mute')
    # The Sources tab renders one `ui.switch` per catalogued source, so the default Player
    # Selection experience is asserted as a switch count rather than as an absence.
    assert len(user.find(kind=ui.switch).elements) == len(CATALOG)


@pytest.mark.parametrize('marker', ['player-dsp', 'player-settings'])
async def test_players_tab_per_client_controls_are_addressable_individually(
    audera_home, mock_snapserver_with_client, user: User, marker
):
    """A per-card control carries the client id as well as the shared marker.

    `UserInteraction.click()` fires on every match, so a shared marker would act on every card.
    """
    Page().load()
    await user.open('/')
    await user.should_see(marker=marker)
    await user.should_see(marker=f'{marker}-abc123')


async def test_players_tab_shows_latency_control(audera_home, mock_snapserver_with_client, user: User):
    Page().load()
    await user.open('/')
    user.find(marker='player-settings').click()
    await user.should_see('Latency (ms)')


async def test_players_tab_disabled_experience_shows_switch_and_hides_mute(audera_home, mock_snapserver_with_client, user: User):
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE},
        )
    )
    Page().load()
    await user.open('/')
    await user.should_see(kind=ui.switch)
    await user.should_not_see(kind=ui.checkbox)


async def test_players_tab_disabled_experience_minimizes_muted_client(
    audera_home, mock_snapserver_with_muted_client, user: User
):
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE},
        )
    )
    Page().load()
    await user.open('/')
    await user.should_see(kind=ui.switch)
    await user.should_see(marker='player-settings')
    await user.should_not_see(kind=ui.slider)


async def test_players_tab_disabled_experience_toggle_off_mutes_client(
    audera_home, mock_snapserver_with_client, mock_snapserver_volume, user: User
):
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE},
        )
    )
    Page().load()
    await user.open('/')
    # Found by marker rather than `kind=ui.switch`: `UserInteraction.click()` clicks every match,
    # and the Sources tab renders one switch per catalogued source.
    user.find(marker='player-toggle-abc123').click()
    await _settled(lambda: mock_snapserver_volume.get('set_client_volume') is not None)
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 100, True)


async def test_players_tab_disabled_experience_toggle_on_unmutes_client(
    audera_home, mock_snapserver_with_muted_client, mock_snapserver_volume, user: User
):
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE},
        )
    )
    Page().load()
    await user.open('/')
    user.find(marker='player-toggle-abc123').click()
    await _settled(lambda: mock_snapserver_volume.get('set_client_volume') is not None)
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 100, False)


# --- Sources tab -------------------------------------------------------------------------


@pytest.fixture
def snapserver_conf(tmp_path, monkeypatch):
    """Redirects the conf the Sources tab writes into `tmp_path`.

    Patched on `audera.cli.conf`, which `domains.sources.toggle` reads the constant from at call
    time, so nothing writes to the device's real `/etc/snapserver.conf`.
    """
    path = tmp_path / 'snapserver.conf'
    monkeypatch.setattr(conf, 'SNAPSERVER_CONF', str(path))
    return path


@pytest.fixture
def mock_stream_status(monkeypatch):
    """A mutable `{stream_id: status}` backing the status chips, seeded before `user.open()`."""
    status: dict[str, str] = {}
    monkeypatch.setattr(SnapserverClient, 'get_stream_status', lambda self: dict(status))
    return status


@pytest.fixture
def mock_snapserver_listener(monkeypatch, mock_camilladsp, mock_stream_status):
    """One connected player, in group `g1`, listening to the `Spotify` stream.

    Returns the group, and serves the move write-through as well as the reads, so a test asserts
    where a listener ended up by reading the group's own `stream_id` rather than a call log.
    """
    player = Player(id='abc123', host='192.168.1.50', port=1704, connected=True, volume=80, group_id='g1', name='Living Room')
    group = Group(id='g1', name='', client_ids=['abc123'], stream_id='Spotify')

    _mock_groups(monkeypatch, [player], [group], stream_status=mock_stream_status)
    return group


@pytest.fixture
def stub_systemctl(monkeypatch):
    """Makes the Sources tab's toggle handlers runnable off-device.

    A developer's machine has no systemd and `@platform.requires('dietpi')` raises at call time, so
    the seam is replaced with a no-op that reports success. Patched at `audera.services.system`,
    which keeps the gate out of the path without patching `platform.NAME` or `subprocess`.
    `system.is_active` is left alone, since PlexAmp's state comes from
    `streamer_plex._plexamp_state`, the level `index._SETUP_FLOWS` captured at import time.

    Everything either side of the seam runs for real, so the enabled set these tests read back and
    the conf bytes they read off disk are the ones the page produced. What the seam's argv does is
    asserted in `tests/systemd/inside/test_index.py`, against real units.

    `_READY_TIMEOUT` is set to zero: nothing was started, so a test using this fixture would
    otherwise spend the readiness budget waiting on a `mock_stream_status` that stays empty. The
    wait's own behaviour is asserted by the tests that re-patch it.
    """
    monkeypatch.setattr(index, '_READY_TIMEOUT', 0.0)

    def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(['systemctl', *args], 0, '', '')

    monkeypatch.setattr(system, 'systemctl', _systemctl)


def _seed_sources(*ids: str) -> None:
    """Persists the enabled source ids before the page loads.

    Writes through the private saver rather than `set_enabled`, so an uncatalogued id can be
    seeded verbatim.
    """
    sources_dal._save(list(ids))


def _live(status: dict[str, str], *ids: str) -> None:
    """Marks `ids` as streams Snapserver is feeding, so they are attachable destinations.

    Uses `'idle'` rather than `'playing'`, since a destination is normally idle when picked.

    Parameters
    ----------
    status: `dict[str, str]`
        The `mock_stream_status` fixture's mutable backing dict.
    ids: `str`
        The stream ids to mark live.
    """
    status.update({id: 'idle' for id in ids})


def _definition(source_id: str) -> SourceDefinition:
    """Returns a catalog entry by id."""
    return next(source for source in CATALOG if source.id == source_id)


def _page(user: User) -> Page:
    """Returns the `Page` this user's client rendered against.

    One is built per client, so the instance a test constructs to call `load()` is not the one the
    render path holds; only this one carries that client's `_dialog_open` and `_claim_in_flight`.
    """
    with user:
        return current()


def _elements(user: User, **kwargs) -> list:
    """Returns the matching elements in creation order, or `[]` when nothing matches.

    `user.find()` raises when nothing matches and returns an unordered `set` when it does;
    both are the wrong shape for asserting on render order and on absence.
    """
    try:
        found = user.find(**kwargs).elements
    except AssertionError:
        return []
    return sorted(found, key=lambda element: element.id)


def _entity_markers(user: User, marker: str, prefix: str) -> list[str]:
    """Per-entity markers for elements carrying `marker`, in render order.

    Resolves each element's entity marker by `prefix` rather than a positional `_markers[1]`, so
    the assertion doesn't depend on how many markers NiceGUI attaches or in what order.
    """
    return [next(m for m in element._markers if m.startswith(prefix)) for element in _elements(user, marker=marker)]


def _only(user: User, kind: type[_ElementT], marker: str) -> _ElementT:
    """Returns the one element of `kind` carrying `marker`.

    `kind` is passed even where the marker is already unique, since it narrows `user.find()`'s
    return type from `ui.element` to the element's own class.
    """
    elements = user.find(kind=kind, marker=marker).elements
    assert len(elements) == 1
    return elements.pop()


def _chip(user: User, source_id: str) -> str:
    """Returns a source card's status-chip text."""
    return _only(user, ui.label, f'source-status-{source_id}').text


async def test_sources_tab_renders_a_card_per_catalog_entry(audera_home, mock_snapserver_empty, mock_stream_status, user: User):
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    for source in CATALOG:
        await user.should_see(source.label)
        await user.should_see(source.description)
    # Render order is catalog order, which puts AirPlay, the bootstrap source, first.
    assert _entity_markers(user, marker='source-card', prefix='source-card-') == [
        f'source-card-{source.id}' for source in CATALOG
    ]


async def test_sources_tab_fresh_device_enables_exactly_one_source(
    audera_home, mock_snapserver_empty, mock_stream_status, user: User
):
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    on = [source.id for source in CATALOG if _only(user, ui.switch, f'source-toggle-{source.id}').value]
    # No `sources.json` has been written, so the tab renders the bootstrap set the flashed
    # image's systemd state already mirrors.
    assert on == list(sources_dal.DEFAULT_ENABLED)
    assert len(on) == 1


async def test_sources_tab_adopts_the_running_streams_on_first_load(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    """An in-place upgrade inherits a conf this code never recorded.

    Without adoption `get_enabled()` reports `DEFAULT_ENABLED` while Snapserver serves something
    else, so one page load renders `PlexAmp: disabled` here and `PlexAmp: playing` on the Players
    tab.
    """
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'claimed')
    mock_stream_status['PlexAmp'] = 'playing'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert sources_dal.get_enabled() == ['PlexAmp']
    assert _chip(user, 'PlexAmp') == 'playing'


async def test_sources_tab_adoption_precedes_the_next_conf_render(
    audera_home, mock_snapserver_empty, mock_stream_status, stub_systemctl, snapserver_conf, monkeypatch, user: User
):
    """The enabled set is the sole input to the conf rewrite, so an unadopted set loses data.

    Without adoption this toggle renders a conf naming AirPlay and Spotify. That truncates the
    inherited PlexAmp stream out of the conf, restarts Snapserver, and reassigns every group
    parked on PlexAmp, without the disable path's safeguard firing.
    """
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'claimed')
    mock_stream_status['PlexAmp'] = 'playing'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Spotify Connect enabled')
    written = snapserver_conf.read_text(encoding='utf-8')
    assert 'name=PlexAmp' in written
    assert 'name=AirPlay' not in written


@pytest.mark.parametrize(
    ('streams', 'expected'),
    [
        # An unreachable Snapserver, or one that raced the load. Recording `[]` would freeze a
        # wrong answer onto disk and render a zero-stream conf; leaving the file absent lets the
        # next load retry.
        pytest.param({}, [], id='unreachable'),
        # `render_snapserver()` only ever emits `CATALOG` sources, so a hand-edited stream cannot
        # survive a conf rewrite whether it is adopted or not.
        pytest.param({'Ghost': 'playing'}, [], id='uncatalogued'),
        pytest.param({'Ghost': 'playing', 'PlexAmp': 'idle'}, ['PlexAmp'], id='partly-catalogued'),
    ],
)
async def test_sources_tab_adoption_records_nothing_it_cannot_serve(
    audera_home, mock_snapserver_empty, mock_stream_status, user: User, streams, expected
):
    mock_stream_status.update(streams)
    Page().load()
    await user.open('/')
    assert sources_dal.is_recorded() is bool(expected)
    assert sources_dal.get_enabled() == (expected or list(sources_dal.DEFAULT_ENABLED))


async def test_sources_tab_adoption_never_overwrites_a_recorded_set(
    audera_home, mock_snapserver_empty, mock_stream_status, user: User
):
    _seed_sources('AirPlay')
    mock_stream_status['PlexAmp'] = 'playing'
    Page().load()
    await user.open('/')
    # A recorded set is the operator's intent and takes precedence over anything inferred from
    # the server.
    assert sources_dal.get_enabled() == ['AirPlay']


@pytest.mark.parametrize(
    ('seeded', 'plexamp_state', 'streams', 'source_id', 'expected'),
    [
        pytest.param(('AirPlay',), 'inactive', {}, 'Spotify', 'disabled', id='not-enabled'),
        pytest.param(('AirPlay', 'PlexAmp'), 'unclaimed', {}, 'PlexAmp', 'setup required', id='setup-incomplete'),
        # A unit systemd has started but that has not bound its port yet gets its own word;
        # `setup required` would be false on a claimed device.
        pytest.param(('AirPlay', 'PlexAmp'), 'starting', {}, 'PlexAmp', 'starting', id='setup-starting'),
        # A unit that is not running shares `unclaimed`'s word, since both leave the operator the
        # same next action. Every row here is a device with no recorded setup; once one is
        # recorded the ladder never reaches the probe, which is
        # `test_sources_tab_a_recorded_setup_outranks_the_live_probe` below.
        pytest.param(('AirPlay', 'PlexAmp'), 'inactive', {}, 'PlexAmp', 'setup required', id='setup-inactive'),
        pytest.param(('AirPlay',), 'inactive', {'AirPlay': 'playing'}, 'AirPlay', 'playing', id='playing'),
        pytest.param(('AirPlay',), 'inactive', {'AirPlay': 'idle'}, 'AirPlay', 'idle', id='idle'),
        # Snapserver's word for "the backend feeding this stream is not running", the same text
        # step 1 renders for "the operator turned this source off".
        pytest.param(('AirPlay',), 'inactive', {'AirPlay': 'disabled'}, 'AirPlay', 'disabled', id='stream-disabled'),
        pytest.param(('AirPlay',), 'inactive', {}, 'AirPlay', 'not running', id='no-stream'),
    ],
)
async def test_sources_tab_chip_ladder(
    audera_home,
    mock_snapserver_empty,
    mock_stream_status,
    monkeypatch,
    user: User,
    seeded,
    plexamp_state,
    streams,
    source_id,
    expected,
):
    _seed_sources(*seeded)
    mock_stream_status.update(streams)
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: plexamp_state)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, source_id) == expected


def test_plex_records_its_completion_against_the_catalogued_source():
    """The id the claim flow records under is the id the card reads back.

    `_plex` states the id and `index._setup_state` keys on `source.id`, so a mismatch records a
    completion nothing reads and re-offers the claim forever. `setup='plex_claim'` ties the flow
    to the entry, so it is read from there rather than restated.
    """
    claims = [source for source in CATALOG if source.setup == 'plex_claim']
    assert [source.id for source in claims] == [streamer_plex.SOURCE_ID]


async def test_sources_tab_a_recorded_setup_outranks_the_live_probe(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    """A recorded setup outranks the live probe, whatever the unit is doing.

    The probe answers what the device does now, so a reprovision, which stops PlexAmp's units,
    would make a claimed device read `setup required` and re-offer a completed claim flow. The
    ladder consults the record first, so the probe is not called at all.
    """
    probes: list[int] = []

    def _plexamp_state() -> str:
        probes.append(1)
        return 'unclaimed'

    monkeypatch.setattr(streamer_plex, '_plexamp_state', _plexamp_state)
    _seed_sources('AirPlay', 'PlexAmp')
    sources_dal.set_setup_complete('PlexAmp', True)
    mock_stream_status['PlexAmp'] = 'idle'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, 'PlexAmp') == 'idle'
    assert probes == []
    assert _elements(user, marker='plex-connect') == []


async def test_sources_tab_disabling_a_source_discards_its_setup_record(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    """Disabling is the one action that discards a setup record.

    Kept across a disable, the record would outrank every probe on a later re-enable and report a
    source as set up without anything having checked.
    """
    _seed_sources('AirPlay', 'PlexAmp')
    sources_dal.set_setup_complete('PlexAmp', True)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    # The one connected player is listening to Spotify, so nothing is attached to PlexAmp and the
    # disable runs without the destination dialog.
    user.find(marker='source-toggle-PlexAmp').click()
    await user.should_see('PlexAmp disabled')
    assert sources_dal.get_enabled() == ['AirPlay']
    assert sources_dal.get_setup('PlexAmp') == {}


async def test_sources_tab_unclaimed_plexamp_shows_setup_required_and_the_claim_flow(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    _seed_sources('AirPlay', 'PlexAmp')
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'unclaimed')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, 'PlexAmp') == 'setup required'
    await user.should_see(marker='plex-connect')


async def test_claim_flow_releases_in_flight_when_a_rebuild_deletes_the_panel(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    """A mid-claim Sources rebuild that deletes the claim panel must release `_claim_in_flight`.

    Regression: the poll's `is_deleted` branches only cancelled their timer, so the flag stayed
    `True` forever. With the Sources tab's activation repaint suppressed while a claim is in flight,
    that wedged the tab until a full page reload. Deletion is a terminal path and must clear it.
    """
    _seed_sources('AirPlay', 'PlexAmp')
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'unclaimed')
    monkeypatch.setattr(streamer_plex, '_create_plex_pin', lambda: (123, 'CODE'))
    monkeypatch.setattr(streamer_plex, '_poll_plex_pin', lambda pin_id: None)  # never authorizes
    # The harness swaps `ui.navigate` for its own `user.navigate` on nearly every attribute access,
    # and that stub opens a string target as a page — so a real click would drive the simulated
    # browser to the external Plex auth URL and 404. Stub the object the code actually reaches.
    monkeypatch.setattr(user.navigate, 'to', lambda *args, **kwargs: None)

    Page().load()
    await user.open('/')
    page = _page(user)
    user.find('Sources').click()
    await user.should_see(marker='plex-connect')

    user.find(marker='plex-connect').click()
    await _settled(lambda: page._claim_in_flight is True)

    # Delete the status label the poll writes to, standing in for the fan-out Sources rebuild that
    # the claim's own PlexAmp restart triggers. The next poll tick must treat it as terminal.
    with user:
        labels = [el for el in _elements(user, kind=ui.label) if el.text == 'Waiting for Plex authorization…']
        assert len(labels) == 1
        labels[0].delete()

    await _settled(lambda: page._claim_in_flight is False)
    assert page._claim_in_flight is False


async def test_sources_tab_claimed_plexamp_without_a_claim_conf_shows_its_stream_status(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, tmp_path, user: User
):
    """The chip is not derived from `PLEXAMP_CLAIM_CONF`.

    The drop-in is deleted on success and on timeout, so its absence is also the steady state for
    a claimed device, and a file predicate would report every claimed device as `setup required`.
    """
    monkeypatch.setattr(streamer_plex, 'PLEXAMP_CLAIM_CONF', str(tmp_path / 'absent' / 'claim.conf'))
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'claimed')
    _seed_sources('AirPlay', 'PlexAmp')
    mock_stream_status['PlexAmp'] = 'idle'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert not os.path.exists(streamer_plex.PLEXAMP_CLAIM_CONF)
    assert _chip(user, 'PlexAmp') == 'idle'
    await user.should_see('Open PlexAmp')


async def test_sources_tab_starting_plexamp_offers_no_claim_button(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    """Inside the startup window a closed port is not evidence of an unclaimed device, so the card
    offers no re-claim button while the device is still booting.
    """
    _seed_sources('AirPlay', 'PlexAmp')
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'starting')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, 'PlexAmp') == 'starting'
    await user.should_see('PlexAmp is starting')
    assert _elements(user, marker='plex-connect') == []


async def test_sources_tab_starting_plexamp_repaints_once_the_port_opens(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    """The starting panel polls; nothing else on the Sources tab does.

    Without it a device that came up after the page loaded would read `starting` until the tab was
    left and re-entered.
    """
    _seed_sources('AirPlay', 'PlexAmp')
    mock_stream_status['PlexAmp'] = 'idle'
    state = {'value': 'starting'}
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: state['value'])
    monkeypatch.setattr(streamer_plex, '_STARTING_POLL', 0.05)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, 'PlexAmp') == 'starting'

    state['value'] = 'claimed'
    await _settled(lambda: _chip(user, 'PlexAmp') == 'idle')
    assert _chip(user, 'PlexAmp') == 'idle'
    await user.should_see('Open PlexAmp')


def test_plexamp_active_seconds_measures_against_the_shared_monotonic_epoch(monkeypatch):
    """systemd's monotonic timestamps and `time.monotonic()` are both `CLOCK_MONOTONIC` on Linux.

    They share the boot epoch, so the microsecond field subtracts directly. `_active_seconds`
    reads the monotonic property rather than the wall-clock `ActiveEnterTimestamp`.
    """
    started = int((time.monotonic() - 10) * 1_000_000)
    monkeypatch.setattr(system, 'systemctl', lambda *args, check=True: subprocess.CompletedProcess(args, 0, f'{started}\n', ''))
    elapsed = streamer_plex._active_seconds()
    assert elapsed is not None and 9 < elapsed < 12


@pytest.mark.parametrize(
    'stdout',
    [
        # `systemctl show` exits 0 for a unit that has never been active and answers `0`, so the
        # exit status is not what separates a reading from a non-reading.
        pytest.param('0', id='never-active'),
        pytest.param('', id='empty'),
        pytest.param('[not set]', id='not-set'),
        pytest.param('n/a', id='unparsable'),
    ],
)
def test_plexamp_active_seconds_withholds_what_systemd_will_not_say(monkeypatch, stdout):
    monkeypatch.setattr(system, 'systemctl', lambda *args, check=True: subprocess.CompletedProcess(args, 0, stdout, ''))
    assert streamer_plex._active_seconds() is None


def test_plexamp_active_seconds_withholds_a_reading_off_device(monkeypatch):
    """`@platform.requires('dietpi')` raises rather than returning, and this tab renders on a dev box."""

    def _off_device(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        raise RuntimeError("audera: `dietpi` is required, found 'Windows'")

    monkeypatch.setattr(system, 'systemctl', _off_device)
    assert streamer_plex._active_seconds() is None


@pytest.mark.parametrize(
    ('elapsed', 'expected'),
    [
        pytest.param(0.0, 'starting', id='just-activated'),
        pytest.param(streamer_plex.STARTUP_GRACE - 1, 'starting', id='inside-the-window'),
        pytest.param(streamer_plex.STARTUP_GRACE, 'unclaimed', id='window-elapsed'),
        # No reading is not evidence of a boot in progress, so the window does not open.
        pytest.param(None, 'unclaimed', id='no-reading'),
    ],
)
def test_plexamp_state_separates_starting_from_unclaimed_by_elapsed_time(monkeypatch, elapsed, expected):
    """A closed port 32500 is what both states look like; the time since activation tells them apart.

    `_unreachable` stands in for the OS refusing a closed loopback port immediately rather than
    waiting out the probe's timeout.
    """
    monkeypatch.setattr(system, 'is_active', lambda unit: True)
    monkeypatch.setattr(streamer_plex, 'socket', SimpleNamespace(create_connection=_unreachable))
    monkeypatch.setattr(streamer_plex, '_active_seconds', lambda: elapsed)
    assert streamer_plex._plexamp_state() == expected


async def test_sources_tab_uncatalogued_id_renders_no_card(audera_home, mock_snapserver_empty, mock_stream_status, user: User):
    _seed_sources('AirPlay', 'Ghost')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _elements(user, marker='source-card-Ghost') == []
    assert len(_elements(user, marker='source-card')) == len(CATALOG)


async def test_sources_tab_render_does_not_probe_a_disabled_source(
    audera_home, mock_snapserver_empty, mock_stream_status, monkeypatch, user: User
):
    probes: list[int] = []

    def _plexamp_state() -> str:
        probes.append(1)
        return 'inactive'

    monkeypatch.setattr(streamer_plex, '_plexamp_state', _plexamp_state)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    # The chip ladder reaches the setup probe only for an enabled source. PlexAmp ships disabled,
    # so a freshly flashed device renders this tab with no `systemctl is-active`.
    assert probes == []


async def test_sources_tab_last_enabled_source_cannot_be_switched_off(
    audera_home, mock_snapserver_empty, mock_stream_status, user: User
):
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert not _only(user, ui.switch, 'source-toggle-AirPlay').enabled
    assert [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)] == [index._LAST_SOURCE_MESSAGE]


async def test_sources_tab_uncatalogued_id_does_not_count_toward_the_guard(
    audera_home, mock_snapserver_empty, mock_stream_status, user: User
):
    _seed_sources('AirPlay', 'Ghost')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    # 'Ghost' is stored but renders nothing and feeds nothing, so AirPlay is still the last
    # source Snapserver would have and its switch stays locked.
    assert not _only(user, ui.switch, 'source-toggle-AirPlay').enabled


async def test_sources_tab_disabling_a_stale_last_source_never_renders_a_conf(
    audera_home, mock_snapserver_empty, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    # The card rendered with two sources enabled, so its switch is live. Another tab disabled
    # Spotify in the meantime; re-reading the enabled set keeps this click from reaching
    # `render_snapserver()`'s `ValueError`.
    _seed_sources('AirPlay')
    user.find(marker='source-toggle-AirPlay').click()
    await user.should_see(index._LAST_SOURCE_MESSAGE)
    assert sources_dal.get_enabled() == ['AirPlay']
    assert not snapserver_conf.exists()


async def test_sources_tab_enable_writes_the_rendered_conf(
    audera_home, mock_snapserver_empty, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Spotify Connect enabled')
    written = snapserver_conf.read_text(encoding='utf-8')
    assert '\nsource = process:///usr/local/bin/go-librespot?name=Spotify' in written
    # AirPlay leads the catalog, so it stays the default even though Spotify was added after.
    assert '\ndefault_source = AirPlay\n' in written


async def test_sources_tab_enable_waits_for_snapserver_before_repainting_the_chips(
    audera_home, mock_snapserver_empty, stub_systemctl, snapserver_conf, mock_stream_status, monkeypatch, user: User
):
    """`systemctl restart` returns once systemd has forked snapserver, before it is serving."""
    _seed_sources('AirPlay')

    monkeypatch.setattr(index, '_READY_TIMEOUT', 5.0)
    monkeypatch.setattr(index, '_READY_INTERVAL', 0.01)

    Page().load()
    await user.open('/')
    user.find('Sources').click()

    # The readiness wait polls SnapserverClient.get_stream_status until it is non-empty. Model
    # Snapserver still coming up after a restart on that probe — the operation the loop actually
    # polls — rather than on the wait primitive: refuse (empty) twice, then serve. This holds
    # whether the loop sleeps via time.sleep, asyncio.sleep, or a monotonic spin.
    stub = system.systemctl
    state = {'refusals': 0}

    def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        if args[:2] == ('restart', 'snapserver'):
            mock_stream_status.clear()
            state['refusals'] = 2
        return stub(*args, check=check)

    original_get_stream_status = SnapserverClient.get_stream_status

    def _refusing_get_stream_status(self) -> dict[str, str]:
        if state['refusals'] > 0:
            state['refusals'] -= 1
            if state['refusals'] == 0:
                mock_stream_status.update({'AirPlay': 'idle', 'Spotify': 'playing'})
            return {}
        return original_get_stream_status(self)

    monkeypatch.setattr(system, 'systemctl', _systemctl)
    monkeypatch.setattr(SnapserverClient, 'get_stream_status', _refusing_get_stream_status)

    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Spotify Connect enabled')
    assert _chip(user, 'Spotify') == 'playing'
    assert _chip(user, 'AirPlay') == 'idle'


async def test_sources_tab_repaints_on_activation(audera_home, mock_snapserver_empty, mock_stream_status, user: User):
    _seed_sources('AirPlay')
    mock_stream_status['AirPlay'] = 'idle'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    assert _chip(user, 'AirPlay') == 'idle'

    # NiceGUI builds every tab panel eagerly at page load, so without a repaint on activation
    # this still reads the word the tab was built with.
    mock_stream_status['AirPlay'] = 'playing'
    user.find('Players').click()
    user.find('Sources').click()
    # `refresh()` returns an `AwaitableResponse`, which defers the rebuild to a background task, so
    # an un-yielded assertion here reads the old chip whether or not the repaint was requested.
    await _settled(lambda: _chip(user, 'AirPlay') == 'playing')
    assert _chip(user, 'AirPlay') == 'playing'


async def test_sources_tab_activation_repaints_nothing_during_a_claim(
    audera_home, mock_snapserver_empty, monkeypatch, user: User
):
    reads: list[int] = []
    original = index._stream_status

    def _counting_stream_status(page):
        reads.append(1)
        return original(page)

    monkeypatch.setattr(index, '_stream_status', _counting_stream_status)
    _seed_sources('AirPlay')
    Page().load()
    await user.open('/')
    page = _page(user)
    user.find('Sources').click()

    page._claim_in_flight = True
    before = len(reads)
    user.find('Players').click()
    user.find('Sources').click()

    page._claim_in_flight = False
    user.find('Players').click()
    user.find('Sources').click()
    await _settled(lambda: len(reads) > before)
    assert len(reads) == before + 1


async def test_sources_tab_disable_without_listeners_opens_no_dialog(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    # The one connected player is listening to Spotify, so nothing is attached to AirPlay.
    user.find(marker='source-toggle-AirPlay').click()
    await user.should_see('AirPlay 2 disabled')
    assert _elements(user, marker='disable-destination') == []
    # The dialog is skipped; the disable still applies.
    assert sources_dal.get_enabled() == ['Spotify']
    assert 'name=AirPlay' not in snapserver_conf.read_text(encoding='utf-8')


async def test_sources_tab_disable_with_listeners_names_them_and_offers_a_destination(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Living Room is listening to Spotify Connect.')
    await user.should_see(marker='disable-destination')
    # Opening the dialog applies nothing; the operator has not confirmed yet.
    assert sources_dal.get_enabled() == ['AirPlay', 'Spotify']
    assert not snapserver_conf.exists()


async def test_sources_tab_disable_moves_the_listener_to_the_chosen_destination(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    """The destination the dialog offered is the one `Group.SetStream` receives.

    The select's value is a source id where everything else the dialog renders is a display label.
    The two differ for Spotify, and `set_group_stream(gid, 'AirPlay 2')` mis-routes with no error.
    `tests/systemd/inside/test_index.py` covers the reassignment itself, with a destination of its
    own rather than one the operator picked.
    """
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    user.find(marker='disable-confirm').click()
    await user.should_see('Spotify Connect disabled')
    assert mock_snapserver_listener.stream_id == 'AirPlay'


async def test_sources_tab_disable_destination_defaults_to_the_snapserver_fallback(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, user: User
):
    _seed_sources('AirPlay', 'Spotify', 'PlexAmp')
    _live(mock_stream_status, 'AirPlay', 'PlexAmp')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    # The destination Snapserver would pick on its own, stated in the dialog rather than left to
    # a server-side fallback.
    assert _only(user, ui.select, 'disable-destination').value == default_source(['AirPlay', 'PlexAmp'])


async def test_sources_tab_disable_destination_options_exclude_uncatalogued_ids(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, user: User
):
    _seed_sources('AirPlay', 'Spotify', 'Ghost')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    # 'Ghost' feeds no stream, so offering it as a destination would strand the group.
    assert _only(user, ui.select, 'disable-destination').options == {'AirPlay': 'AirPlay 2'}


async def test_sources_tab_disable_destination_options_exclude_sources_that_are_not_running(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, user: User
):
    _seed_sources('AirPlay', 'Spotify', 'PlexAmp')
    _live(mock_stream_status, 'PlexAmp')
    mock_stream_status['AirPlay'] = 'disabled'
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    # Enabled does not imply running. AirPlay is enabled but Snapserver is not feeding it, so
    # moving the listener there would be a silent mis-route.
    assert _only(user, ui.select, 'disable-destination').options == {'PlexAmp': 'PlexAmp'}


async def test_sources_tab_disable_without_a_live_destination_says_so_and_proceeds(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see(marker='disable-no-destination')
    assert _elements(user, marker='disable-destination') == []
    user.find(marker='disable-confirm').click()
    await user.should_see('Spotify Connect disabled')
    # Nothing is running to move onto, so the group is left where it was and Snapserver's own
    # `default_source` fallback applies. The dialog says so, and the disable is not blocked.
    assert mock_snapserver_listener.stream_id == 'Spotify'
    assert sources_dal.get_enabled() == ['AirPlay']


async def test_sources_tab_failed_reassignment_aborts_before_the_dal_write(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, monkeypatch, user: User
):
    def _set_group_stream(self, group_id: str, stream_id: str) -> dict:
        raise Unreachable('Snapserver error [Group.SetStream]: timed out')

    monkeypatch.setattr(SnapserverClient, 'set_group_stream', _set_group_stream)
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    user.find(marker='disable-confirm').click()
    await user.should_see('Could not disable Spotify Connect')
    # Reassignment is the sole abort point: nothing past it ran.
    assert sources_dal.get_enabled() == ['AirPlay', 'Spotify']
    assert not snapserver_conf.exists()


async def test_sources_tab_cancelling_the_disable_dialog_restores_the_toggle(
    audera_home, mock_snapserver_listener, mock_stream_status, stub_systemctl, snapserver_conf, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Disable Spotify Connect')
    user.find('Cancel').click()
    await _settled(lambda: _only(user, ui.switch, 'source-toggle-Spotify').value is True)
    # A dismissal is treated as a cancellation, and the switch has already flipped, so the tab
    # refreshes back to the recorded state.
    assert _only(user, ui.switch, 'source-toggle-Spotify').value is True
    assert sources_dal.get_enabled() == ['AirPlay', 'Spotify']
    assert not snapserver_conf.exists()


async def test_sources_tab_restart_failure_leaves_the_new_state_in_place(
    audera_home, mock_snapserver_empty, mock_stream_status, stub_systemctl, snapserver_conf, monkeypatch, user: User
):
    def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        if args[0] == 'restart':
            raise ServiceError('Job for snapserver.service failed.')
        return subprocess.CompletedProcess(['systemctl', *args], 0, '', '')

    monkeypatch.setattr(system, 'systemctl', _systemctl)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-Spotify').click()
    await user.should_see('Spotify Connect is enabled, but applying it failed')
    # The failure rolls forward: the intent and the conf stay at the new state, and the chip on
    # the next render reports what is actually running.
    assert sources_dal.get_enabled() == ['AirPlay', 'Spotify']
    assert 'name=Spotify' in snapserver_conf.read_text(encoding='utf-8')


async def test_sources_tab_failure_surfaces_stderr_not_the_exit_status(
    audera_home, mock_snapserver_empty, mock_stream_status, stub_systemctl, snapserver_conf, monkeypatch, user: User
):
    def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        if not check:
            return subprocess.CompletedProcess(['systemctl', *args], 0, '', '')
        raise ServiceError('Job for plexamp.service failed.')

    monkeypatch.setattr(system, 'systemctl', _systemctl)
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'unclaimed')
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker='source-toggle-PlexAmp').click()
    await user.should_see('Job for plexamp.service failed.')
    await user.should_not_see('non-zero exit status')


@pytest.mark.parametrize(
    ('seeded', 'source_id'),
    [
        pytest.param(('AirPlay',), 'Spotify', id='enable'),
        pytest.param(('AirPlay', 'Spotify'), 'AirPlay', id='disable'),
    ],
)
async def test_sources_tab_toggle_warns_that_playback_is_interrupted(
    audera_home,
    mock_snapserver_listener,
    mock_stream_status,
    stub_systemctl,
    snapserver_conf,
    user: User,
    seeded,
    source_id,
):
    _seed_sources(*seeded)
    Page().load()
    await user.open('/')
    user.find('Sources').click()
    user.find(marker=f'source-toggle-{source_id}').click()
    await user.should_see(index._INTERRUPTION_MESSAGE)


# --- Players tab: stream assignment ------------------------------------------------------


def _seed_grouping(mode: str, **extra: str) -> None:
    """Persists settings selecting the Players tab grouping before the page loads."""
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_GROUPING_KEY: mode, **extra},
        )
    )


def _stream_chip(user: User, client_id: str) -> ui.button:
    """Returns a player card's assignment chip, the by-player grouping's move trigger."""
    return _only(user, ui.button, f'player-stream-{client_id}')


def _stream_value(user: User, client_id: str) -> str:
    """Returns the assignment chip's text, which is a source's display label, not its id."""
    return _only(user, ui.label, f'player-stream-value-{client_id}').text


async def test_players_tab_defaults_to_the_by_player_grouping(
    audera_home, mock_snapserver_listener, mock_camilladsp, user: User
):
    Page().load()
    await user.open('/')
    # The by-player trigger is the body-row chip; the by-stream one is the header-row move
    # button. Both open the same menu, and only one of them renders at a time.
    await user.should_see(marker='player-stream-abc123')
    assert _elements(user, marker='player-move-abc123') == []


async def test_players_tab_card_is_addressable_per_client(audera_home, mock_snapserver_two_players, mock_camilladsp, user: User):
    Page().load()
    await user.open('/')
    assert _entity_markers(user, marker='player-card', prefix='player-card-') == ['player-card-abc123', 'player-card-def456']


async def test_players_tab_chip_shows_the_current_stream(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # The chip renders the display label, where the select it replaced held the id.
    assert _stream_value(user, 'abc123') == 'Spotify Connect'


async def test_players_tab_chip_menu_offers_the_enabled_set(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify', 'Ghost')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    # The chip opens the same menu the by-stream trigger opens, so its rows are the enabled set
    # intersected with `CATALOG`, less the current stream. 'Ghost' feeds no stream.
    assert _elements(user, marker='player-move-abc123-Ghost') == []
    assert _elements(user, marker='player-move-abc123-Spotify') == []
    await user.should_see(marker='player-move-abc123-AirPlay')


async def test_players_tab_chip_repaints_without_relayouting(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    # The poll's own rebuild has to land before taking the identity the move is measured against.
    before = await _stable(lambda: _stream_chip(user, 'abc123').id)
    user.find(marker='player-move-abc123-AirPlay').click()
    await _settled(lambda: mock_snapserver_two_players != [])
    # The client's own group, and Snapcast's stream id, which is the source id rather than its
    # display label. `set_group_stream(gid, 'AirPlay 2')` would mis-route silently.
    assert mock_snapserver_two_players == [('g1', 'AirPlay')]
    # No re-layout: a refresh would reseed every volume slider from CamillaDSP, cancelling a live
    # drag on a different card. The chip repaints its own label and tint in place. 'Spotify' is
    # absent from the status (red), 'AirPlay' is idle (grey).
    assert _stream_chip(user, 'abc123').id == before
    assert _stream_value(user, 'abc123') == 'AirPlay 2'
    assert 'bg-gray-500/10' in _stream_chip(user, 'abc123')._classes
    assert 'bg-red-500/10' not in _stream_chip(user, 'abc123')._classes


@pytest.mark.parametrize(
    ('word', 'hue'),
    [
        pytest.param('playing', 'green', id='playing'),
        pytest.param('idle', 'gray', id='idle'),
        pytest.param(None, 'red', id='not-running'),
    ],
)
async def test_players_tab_chip_tint_tracks_the_status(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, word, hue, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    if word is not None:
        mock_stream_status['Spotify'] = word
    Page().load()
    await user.open('/')
    # A text colour and a 10 % tint of the same hue, matching the by-stream header's hue for the
    # same word. `_stream_tint` spells its rungs out rather than parsing `_stream_state`'s class
    # string, so this assertion keeps the two in agreement.
    chip = _stream_chip(user, 'abc123')
    assert f'text-{hue}-500' in chip._classes
    assert f'bg-{hue}-500/10' in chip._classes
    assert f'text-{hue}-500' in index._stream_state('Spotify', mock_stream_status)[1]
    # No Quasar colour on the same element. `ui.button`'s default `'primary'` renders as
    # `text-primary` at equal specificity, wins on stylesheet order, and leaves the chip
    # grey-navy on a coloured ground.
    assert 'color' not in chip._props


async def test_players_tab_chip_tooltip_names_the_status_word(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # The chip's one line of text is the label, so the status word behind the tint is only
    # reachable through the tooltip.
    assert 'Spotify Connect — idle' in [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)]


async def test_players_tab_chip_is_disabled_without_a_group(
    audera_home, mock_snapserver_with_client, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    # Covers both the empty `group_id` and the raising `get_groups`; `set_group_stream('', …)`
    # is an RPC with no target either way.
    assert not _stream_chip(user, 'abc123').enabled
    assert _stream_value(user, 'abc123') == 'Unassigned'
    assert index._NO_GROUP_MESSAGE in [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)]


async def test_players_tab_chip_is_disabled_without_a_running_destination(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    mock_stream_status['AirPlay'] = 'disabled'
    Page().load()
    await user.open('/')
    # Both triggers refuse on the same two grounds, via `_move_refusal`, so the chip is disabled
    # wherever the by-stream button would be.
    assert not _stream_chip(user, 'abc123').enabled
    assert index._NO_DESTINATION_MESSAGE in [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)]


async def test_players_tab_unreachable_groups_still_offer_the_enabled_set(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, monkeypatch, user: User
):
    monkeypatch.setattr(SnapserverClient, 'get_groups', _unreachable)
    broker.get().cache.groups = []
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # A move is legitimate even when the current stream is unknown, and this client is in a
    # group, so the chip renders enabled and unassigned over the whole enabled set.
    assert _stream_chip(user, 'abc123').enabled
    assert _stream_value(user, 'abc123') == 'Unassigned'
    await user.should_see(marker='player-move-abc123-AirPlay')
    await user.should_see(marker='player-move-abc123-Spotify')


async def test_players_tab_orphan_stream_keeps_its_own_label(
    audera_home, mock_snapserver_orphan_stream, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    # A group parked on a stream outside the enabled set still names it, and the menu still omits
    # it as the current stream. A chip reading 'Unassigned' would be false.
    assert _stream_value(user, 'abc123') == 'Ghost'
    assert _elements(user, marker='player-move-abc123-Ghost') == []
    await user.should_see(marker='player-move-abc123-AirPlay')


@pytest.mark.parametrize(
    ('fixture', 'expected'),
    [
        pytest.param('mock_snapserver_two_players', 'Stream', id='alone'),
        pytest.param('mock_snapserver_shared_group', 'Stream (shared with 1 other player)', id='shared'),
    ],
)
async def test_players_tab_stream_caption_names_the_blast_radius(
    audera_home, mock_camilladsp, request, user: User, fixture, expected
):
    request.getfixturevalue(fixture)
    Page().load()
    await user.open('/')
    # Audera never merges clients into a group; a shared group comes from Snapweb. Moving one
    # player then moves all, and the caption states that rather than the code preventing it.
    assert _only(user, ui.label, 'player-stream-label-abc123').text == expected


async def test_players_tab_minimized_card_keeps_the_stream_chip_but_hides_the_slider(
    audera_home, mock_snapserver_with_muted_client, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_PLAYER, **{features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE})
    Page().load()
    await user.open('/')
    # Muting is an audio-output decision, not a configuration lock: stream reassignment stays
    # available on a disabled card, but the volume slider (meaningless for a muted player) is gone.
    await user.should_see(marker='player-card-abc123')
    await user.should_see(marker='player-stream-abc123')
    assert _elements(user, kind=ui.slider) == []


async def test_players_tab_minimized_card_keeps_dsp_and_settings_enabled(
    audera_home, mock_snapserver_with_muted_client, user: User
):
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE},
        )
    )
    Page().load()
    await user.open('/')
    assert _only(user, ui.button, 'player-dsp-abc123').enabled
    assert _only(user, ui.button, 'player-settings-abc123').enabled


async def test_players_tab_reads_from_hub_cache_not_snapserver(
    audera_home, mock_snapserver_shared_group, mock_camilladsp, monkeypatch, user: User
):
    reads: list[str] = []

    def _get_groups(self) -> list[Group]:
        reads.append('groups')
        return []

    def _get_clients(self) -> list[Player]:
        reads.append('clients')
        return []

    monkeypatch.setattr(SnapserverClient, 'get_groups', _get_groups)
    monkeypatch.setattr(SnapserverClient, 'get_clients', _get_clients)
    Page().load()
    await user.open('/')
    # The Players tab reads from the broker cache, not from SnapserverClient, so the patched
    # methods are never called during render.
    await user.should_see('Living Room')
    assert reads.count('groups') == 0
    assert reads.count('clients') == 0


async def test_players_tab_by_player_reads_stream_status_from_hub(
    audera_home, mock_snapserver_listener, mock_camilladsp, mock_stream_status, monkeypatch, user: User
):
    reads: list[int] = []
    monkeypatch.setattr(SnapserverClient, 'get_stream_status', lambda self: reads.append(1) or {})
    _live(mock_stream_status, 'Spotify')
    Page().load()
    # Adoption reads from the broker, which falls back to the client if the broker is not started.
    # Cleared here so the count measures only the per-render calls.
    reads.clear()
    await user.open('/')
    # Stream status comes from the broker cache, not from SnapserverClient.get_stream_status.
    assert reads.count(1) == 0
    await user.should_see('Living Room')


async def test_players_tab_open_chip_menu_suppresses_and_releases_the_poll(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    page = _page(user)
    menu = _elements(user, kind=ui.menu)[0]
    with user:
        menu.value = True
    # A broker dirty signal refreshes the Players tab, which would destroy an open menu.
    assert page._dialog_open is True
    user.find(marker='player-move-abc123-AirPlay').click()
    await _settled(lambda: page._dialog_open is False)
    # Under the by-player grouping nothing refreshes, so the handler itself clears the flag. A
    # latch left set by an element no refresh replaces would freeze the signal for the life of the
    # page.
    assert page._dialog_open is False


async def test_players_tab_failed_move_notifies_and_refreshes(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, monkeypatch, user: User
):
    def _set_group_stream(self, group_id: str, stream_id: str) -> dict:
        raise Unreachable('Snapserver error [Group.SetStream]: timed out')

    monkeypatch.setattr(SnapserverClient, 'set_group_stream', _set_group_stream)
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    before = _stream_chip(user, 'abc123').id
    user.find(marker='player-move-abc123-AirPlay').click()
    await user.should_see('Could not move Living Room')
    # Refreshed regardless of the grouping, so the chip returns to the recorded assignment rather
    # than repainting onto a destination the move never reached.
    assert _stream_chip(user, 'abc123').id != before
    assert _stream_value(user, 'abc123') == 'Spotify Connect'


def _headers(user: User) -> list[str]:
    """Returns the by-stream section headers' per-stream markers, in render order."""
    return _entity_markers(user, marker='stream-header', prefix='stream-header-')


@pytest.mark.parametrize(
    'mode',
    [
        pytest.param(features.FF_GROUPING_BY_PLAYER, id='by-player'),
        pytest.param(features.FF_GROUPING_BY_STREAM, id='by-stream'),
    ],
)
async def test_players_tab_renders_the_same_card_under_both_groupings(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User, mode
):
    _seed_grouping(mode)
    Page().load()
    await user.open('/')
    # One card with one of every control on it; only the assignment affordance moves.
    await user.should_see('Living Room')
    await user.should_see(marker='player-card-abc123')
    await user.should_see(marker='player-dsp-abc123')
    await user.should_see(marker='player-settings-abc123')
    assert len(_elements(user, kind=ui.slider)) == 1


async def test_players_tab_by_stream_replaces_the_select_with_a_move_action(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    Page().load()
    await user.open('/')
    # Only one of the two assignment affordances renders at a time.
    await user.should_see(marker='player-move-abc123')
    assert _elements(user, marker='player-stream-abc123') == []


async def test_players_tab_by_stream_headers_follow_catalog_order(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('Spotify', 'AirPlay')
    Page().load()
    await user.open('/')
    # `_enabled_ids` returns catalog order rather than toggle order, and the sections inherit it
    # through the dict `_sections` seeds from it.
    assert _headers(user) == [f'stream-header-{id}' for id in index._enabled_ids()]


async def test_players_tab_by_stream_shows_empty_streams(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # An enabled source with nothing pointed at it still renders a section, which is the drop
    # target the move menu names.
    assert 'stream-header-AirPlay' in _headers(user)
    assert _only(user, ui.label, 'stream-count-AirPlay').text == '0 players'
    await user.should_see(marker='stream-empty-AirPlay')


async def test_players_tab_by_stream_menu_omits_the_current_stream(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # The section the card sits in already says where it is.
    assert _elements(user, marker='player-move-abc123-Spotify') == []
    await user.should_see(marker='player-move-abc123-AirPlay')


async def test_players_tab_by_stream_move_submits_the_stream_id(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    user.find(marker='player-move-abc123-AirPlay').click()
    await _settled(lambda: mock_snapserver_two_players != [])
    # The client's own group, and the source id rather than its display label.
    assert mock_snapserver_two_players == [('g1', 'AirPlay')]


@pytest.mark.parametrize(
    ('word', 'attachable'),
    [
        pytest.param('playing', True, id='playing'),
        pytest.param('idle', True, id='idle'),
        pytest.param('kUnknown', True, id='unrecognised-fails-open'),
        pytest.param('disabled', False, id='disabled'),
        pytest.param(None, False, id='absent'),
    ],
)
async def test_players_tab_by_stream_menu_offers_only_running_destinations(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, word, attachable, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    if word is not None:
        mock_stream_status['AirPlay'] = word
    Page().load()
    await user.open('/')
    # `idle` is attachable, since a speaker is routinely pointed at a source before playback
    # starts. Absence and Snapserver's own `disabled` both mean the backend is not feeding it. An
    # unrecognised word fails open, matching `_SETUP_FLOWS`.
    assert _only(user, ui.menu_item, 'player-move-abc123-AirPlay').enabled is attachable


async def test_players_tab_by_stream_menu_names_a_dead_destinations_status(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # Shown disabled rather than dropped, so the row states why it cannot be picked.
    assert _only(user, ui.label, 'player-move-status-abc123-AirPlay').text == 'not running'


async def test_players_tab_by_stream_clicking_a_dead_destination_moves_nothing(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify', 'PlexAmp')
    _live(mock_stream_status, 'PlexAmp')
    Page().load()
    await user.open('/')
    # The row carries no click handler, so the refusal does not depend on `set_enabled(False)`
    # being honoured by whatever dispatches the event.
    user.find(marker='player-move-abc123-AirPlay').click()

    # Polling cannot prove a move did not happen, so a live destination is clicked behind the dead
    # one and waited for. Both would dispatch in the same tick and the dead row's task was created
    # first, so a dead row that did move somebody leaves two entries rather than one.
    user.find(marker='player-move-abc123-PlexAmp').click()
    await _settled(lambda: mock_snapserver_two_players != [])
    assert mock_snapserver_two_players == [('g1', 'PlexAmp')]


async def test_players_tab_by_stream_relayouts_on_assignment(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    assert _only(user, ui.label, 'stream-count-AirPlay').text == '1 player'
    user.find(marker='player-move-abc123-AirPlay').click()
    await _settled(lambda: _only(user, ui.label, 'stream-count-AirPlay').text == '2 players')
    # Under the by-stream grouping the card's position is its assignment, so without a re-layout
    # it would sit under the wrong header for up to 10 s.
    assert _only(user, ui.label, 'stream-count-AirPlay').text == '2 players'
    assert _only(user, ui.label, 'stream-count-Spotify').text == '0 players'


@pytest.mark.parametrize(
    ('seeded', 'expected'),
    [
        pytest.param({'Spotify': 'playing'}, 'playing', id='playing'),
        pytest.param({'Spotify': 'idle'}, 'idle', id='idle'),
        pytest.param({}, 'not running', id='absent'),
    ],
)
async def test_players_tab_by_stream_header_shows_snapservers_own_status_word(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User, seeded, expected
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('Spotify')
    mock_stream_status.update(seeded)
    Page().load()
    await user.open('/')
    # The last two rungs of the Sources chip ladder. 'disabled' and 'setup required' are not
    # rendered here, since this tab cannot act on them.
    assert _only(user, ui.label, 'stream-status-Spotify').text == expected


async def test_players_tab_by_stream_lists_every_connected_player_once(
    audera_home, mock_snapserver_orphan_stream, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay')
    Page().load()
    await user.open('/')
    # `_sections`' `setdefault` is what makes this hold: a group parked outside the enabled set
    # gets its own section rather than the player disappearing from the tab.
    assert _entity_markers(user, marker='player-card', prefix='player-card-') == ['player-card-abc123']
    assert _headers(user) == ['stream-header-AirPlay', 'stream-header-Ghost']


async def test_players_tab_by_stream_unassigned_section_carries_no_status_word(
    audera_home, mock_snapserver_with_client, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay')
    Page().load()
    await user.open('/')
    # Nothing is running at 'unassigned', so a status word there would report a state that does
    # not exist.
    assert _headers(user) == ['stream-header-AirPlay', 'stream-header-unassigned']
    assert _elements(user, marker='stream-status-unassigned') == []


async def test_players_tab_by_stream_move_button_is_disabled_without_a_group(
    audera_home, mock_snapserver_with_client, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay')
    Page().load()
    await user.open('/')
    button = _only(user, ui.button, 'player-move-abc123')
    assert not button.enabled
    assert index._NO_GROUP_MESSAGE in [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)]


async def test_players_tab_by_stream_move_button_is_disabled_without_a_running_destination(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    mock_stream_status['AirPlay'] = 'disabled'
    Page().load()
    await user.open('/')
    # A menu of only greyed rows offers no destination, so the button reports that instead of
    # requiring the menu to be opened.
    button = _only(user, ui.button, 'player-move-abc123')
    assert not button.enabled
    assert index._NO_DESTINATION_MESSAGE in [tooltip.text for tooltip in _elements(user, kind=ui.tooltip)]


async def test_players_tab_by_stream_minimized_card_keeps_a_disabled_move_button(
    audera_home, mock_snapserver_with_muted_client, mock_stream_status, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM, **{features.PLAYER_SELECTION_KEY: features.FF_DISABLED_VS_MUTE})
    Page().load()
    await user.open('/')
    # A header-row button rather than a body row like the by-player chip, which is dropped. A
    # switched-off player is still assigned, so its card still appears under its stream header.
    await user.should_see(marker='player-card-abc123')
    assert not _only(user, ui.button, 'player-move-abc123').enabled


async def test_players_tab_by_stream_menu_names_the_blast_radius(
    audera_home, mock_snapserver_shared_group, mock_stream_status, mock_camilladsp, user: User
):
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    Page().load()
    await user.open('/')
    # The same caption as the by-player select, from the same helper, so the wording cannot
    # drift between the two layouts.
    await user.should_see(index._stream_caption(1))


async def test_players_tab_by_stream_reads_stream_status_from_hub(
    audera_home, mock_snapserver_listener, mock_camilladsp, mock_stream_status, monkeypatch, user: User
):
    reads: list[int] = []
    monkeypatch.setattr(SnapserverClient, 'get_stream_status', lambda self: reads.append(1) or {})
    _live(mock_stream_status, 'Spotify')
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    Page().load()
    reads.clear()
    await user.open('/')
    # Stream status comes from the broker cache, not from SnapserverClient.get_stream_status.
    assert reads.count(1) == 0
    await user.should_see('Living Room')


async def test_players_tab_by_stream_open_menu_suppresses_and_releases_the_poll(
    audera_home, mock_snapserver_two_players, mock_stream_status, mock_camilladsp, user: User
):
    # Seeded before the page is opened: the client's `Page` reads the settings once, at construction.
    _seed_grouping(features.FF_GROUPING_BY_STREAM)
    _seed_sources('AirPlay', 'Spotify')
    _live(mock_stream_status, 'AirPlay')
    Page().load()
    await user.open('/')
    page = _page(user)
    menu = _elements(user, kind=ui.menu)[0]
    with user:
        menu.value = True
    # A broker dirty signal refreshes the Players tab, which would destroy an open menu.
    assert page._dialog_open is True
    user.find(marker='player-move-abc123-AirPlay').click()
    await _settled(lambda: page._dialog_open is False)
    # Cleared by the move it triggered. This grouping does refresh, so a latched flag would
    # freeze the signal for the life of the page.
    assert page._dialog_open is False


async def test_settings_tab_switching_the_grouping_relayouts_the_players_tab(
    audera_home, mock_snapserver_listener, mock_stream_status, mock_camilladsp, user: User
):
    Page().load()
    await user.open('/')
    await user.should_see(marker='player-stream-abc123')
    user.find('Settings').click()
    with user:
        user.find(kind=ui.toggle, content='By stream').elements.pop().value = features.FF_GROUPING_BY_STREAM
    await _settled(lambda: _elements(user, marker='player-move-abc123') != [])
    assert settings_dal.get().features[features.PLAYER_GROUPING_KEY] == features.FF_GROUPING_BY_STREAM
    # `_on_feature_change` already refreshes the Players tab, so the new layout needs no extra code.
    assert _elements(user, marker='player-stream-abc123') == []
    assert _elements(user, marker='player-move-abc123') != []


async def test_settings_dialog_no_longer_shows_the_group_id(audera_home, mock_snapserver_listener, mock_camilladsp, user: User):
    Page().load()
    await user.open('/')
    user.find(marker='player-settings-abc123').click()
    await user.should_see('Snapcast Volume')
    # Asserted on the value rather than the word 'Group', since the Settings tab renders
    # `Player Grouping` on the same page.
    await user.should_not_see('g1')


async def test_settings_tab_shows_feature_groups(audera_home, mock_snapserver_empty, user: User):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    for feature in features.FEATURES:
        await user.should_see(feature.label)
        for option in feature.options:
            await user.should_see(option.label)
    await user.should_not_see('PlexAmp Host')
    await user.should_not_see('Snapserver Host')


async def test_settings_tab_selecting_option_persists_to_dal(audera_home, mock_snapserver_empty, user: User):
    """ui.toggle renders as a single q-btn-toggle group; the test harness's generic
    click() doesn't know how to target one button within it (unlike ui.radio/ui.select,
    which it special-cases), so the option is selected the same way the harness selects
    those: by assigning the element's `value` directly, which drives the same on_change
    path a real button click would.
    """
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    with user:
        user.find(kind=ui.toggle, content='Disabled toggle').elements.pop().value = 'disabled'
    await _settled(lambda: settings_dal.get().features['player_selection'] == 'disabled')
    assert settings_dal.get().features['player_selection'] == 'disabled'
    with user:
        user.find(kind=ui.toggle, content='Decibels').elements.pop().value = 'db'
    await _settled(lambda: settings_dal.get().features['volume'] == 'db')
    assert settings_dal.get().features['volume'] == 'db'


async def test_settings_first_load_seeds_default_features(audera_home, mock_snapserver_empty, user: User):
    Page().load()
    await user.open('/')
    assert settings_dal.get().features == features.default_selections()


async def test_settings_tab_restore_disabled_until_a_balance_is_saved(audera_home, mock_snapserver_two_players, user: User):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    assert not user.find(kind=ui.button, marker='restore-reference').elements.pop().enabled


async def test_settings_tab_save_reference_balance_captures_current_volumes(
    audera_home, mock_snapserver_two_players, user: User
):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    user.find(marker='save-reference').click()
    await _settled(balance_dal.exists)
    assert balance_dal.get().volumes == {'abc123': 80, 'def456': 80}


async def test_settings_tab_save_enables_restore(audera_home, mock_snapserver_two_players, user: User):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    user.find(marker='save-reference').click()
    await _settled(lambda: user.find(kind=ui.button, marker='restore-reference').elements.pop().enabled)
    assert user.find(kind=ui.button, marker='restore-reference').elements.pop().enabled


async def test_settings_tab_restore_applies_to_connected_players_and_skips_the_rest(
    audera_home, mock_snapserver_two_players, mock_camilladsp, monkeypatch, user: User
):
    """`ghost` is absent from the cache (never restored) and `def456` is absent from the saved
    balance (skipped); only the connected, named `abc123` is written back."""
    balance_dal.save(ReferenceBalance(volumes={'abc123': 30, 'ghost': 55}))

    applied: list[tuple[str, int, bool]] = []

    def _set_client_volume(self, client_id: str, percent: int, muted: bool = False):
        applied.append((client_id, percent, muted))

    monkeypatch.setattr(SnapserverClient, 'set_client_volume', _set_client_volume)

    Page().load()
    await user.open('/')
    user.find('Settings').click()
    user.find(marker='restore-reference').click()
    await _settled(lambda: bool(applied))
    assert applied == [('abc123', 100, False)]
    assert mock_camilladsp.get('set_percent_volume') == 30
    assert volume_dal.get('abc123') == 30


async def test_settings_tab_indicator_lights_when_players_match_the_reference(
    audera_home, mock_snapserver_two_players, user: User
):
    balance_dal.save(ReferenceBalance(volumes={'abc123': 80, 'def456': 80}))
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    await user.should_see('Listening at reference')


async def test_settings_tab_indicator_dark_when_a_player_diverges(audera_home, mock_snapserver_two_players, user: User):
    balance_dal.save(ReferenceBalance(volumes={'abc123': 80, 'def456': 80}))
    broker.get().cache.volumes['abc123'] = 55
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    await user.should_not_see('Listening at reference')


async def test_settings_tab_indicator_dark_without_a_saved_reference(audera_home, mock_snapserver_two_players, user: User):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    await user.should_not_see('Listening at reference')


async def test_settings_tab_save_lights_the_indicator(audera_home, mock_snapserver_two_players, user: User):
    Page().load()
    await user.open('/')
    user.find('Settings').click()
    await user.should_not_see('Listening at reference')
    user.find(marker='save-reference').click()
    await user.should_see('Listening at reference')


async def test_run_preamble_does_not_set_script_mode(audera_home, monkeypatch, user: User):
    """Page.load() followed by apply_defaults() must not set core.script_mode=True.

    In production Client.instances is empty when run() executes.  If apply_defaults()
    created a NiceGUI Element (e.g. ui.colors()), NiceGUI would activate script_mode and
    ui.run() would raise: RuntimeError: ui.page cannot be used in NiceGUI scripts when
    UI is defined in the global scope. apply_defaults() only registers static files and
    sets Quasar's slots via CSS, so it must stay element-free.
    """
    monkeypatch.setattr(streamer_plex, '_plexamp_state', lambda: 'inactive')
    Page().load()
    Client.instances.clear()  # replicate production: no pre-existing clients
    components.theme.apply_defaults()
    assert not core.script_mode, (
        'apply_defaults() triggered script_mode by creating a NiceGUI Element. '
        'Keep it to app-level calls (app.add_static_files) and CSS.'
    )


# One `Page` per client. Every assertion below fails against a shared instance, because
# `@ui.refreshable` filters its render targets by instance alone: one `refresh()` clears every
# client's tab.
async def _rendered(*users: User) -> None:
    """Waits for every user's Players tab to show the player card."""
    await _settled(lambda: all(_sees_player(user) for user in users))


def _sees_player(user: User) -> bool:
    """Whether this user's element tree carries the player card's name label."""
    return 'Living Room' in [label.text for label in _elements(user, kind=ui.label)]


async def test_a_second_client_does_not_blank_the_first(audera_home, mock_snapserver_with_client, create_user):
    Page().load()
    first, second = create_user(), create_user()
    await first.open('/')
    await second.open('/')
    await _rendered(first, second)

    assert _sees_player(first), 'the first client blanked when the second one opened'
    assert _sees_player(second)


async def test_concurrent_clients_both_render_players(audera_home, mock_snapserver_with_client, create_user):
    Page().load()
    first, second = create_user(), create_user()
    await asyncio.gather(first.open('/'), second.open('/'))
    await _rendered(first, second)

    assert _sees_player(first)
    assert _sees_player(second)


async def test_one_clients_poll_leaves_another_clients_players_tab(audera_home, mock_snapserver_with_client, create_user):
    """A refresh on one client's `Page` does not blank another client's tab."""
    Page().load()
    first, second = create_user(), create_user()
    await first.open('/')
    await second.open('/')
    await _rendered(first, second)

    _page(first)._build_players_tab.refresh()
    await _rendered(first, second)

    assert _sees_player(first), 'the refreshing client did not come back'
    assert _sees_player(second), "another client's poll cleared this tab"


async def test_volume_slider_seeded_from_hub(
    audera_home,
    mock_snapserver_with_client,
    mock_camilladsp,
    user: User,
):
    Page().load()
    await user.open('/')
    # Volume seeds from the broker cache — no set_percent_volume on render.
    sliders = list(user.find(kind=ui.slider).elements)
    assert len(sliders) == 1
    assert sliders[0].value == 80
    assert mock_camilladsp.get('set_percent_volume') is None


async def test_players_tab_volume_percent_mode_shows_icon_and_label(
    audera_home, mock_snapserver_with_client, mock_camilladsp, user: User
):
    Page().load()
    await user.open('/')
    await user.should_see(kind=ui.icon, content='volume_up')
    await user.should_see('80%')  # seeded from the daemon's get_percent_volume


async def test_players_tab_volume_db_mode_shows_icon_and_label(
    audera_home, mock_snapserver_with_client, mock_camilladsp, db_volume_mode, user: User
):
    Page().load()
    await user.open('/')
    await user.should_see(kind=ui.icon, content='volume_up')
    await user.should_see('-1.9 dB')  # percent_to_db(80) == -1.938...


async def test_players_tab_unreadable_volume_withholds_a_value_and_disables_the_slider(
    audera_home, mock_snapserver_with_client, mock_camilladsp_unreadable, user: User
):
    broker.get().cache.volumes['abc123'] = None
    Page().load()
    await user.open('/')
    # An unreadable daemon used to seed the slider at `DEFAULT_PERCENT_VOLUME`, rendering `25%`,
    # which is indistinguishable from a player genuinely set to 25% and is the base a drag would
    # write its edit against. The reading is withheld instead.
    await user.should_see('—')
    await user.should_not_see('25%')
    await user.should_see(kind=ui.icon, content='volume_off')
    assert _only(user, kind=ui.slider, marker='player-volume').enabled is False


async def test_players_tab_volume_percent_slider_change_persists_and_updates_label(
    audera_home, mock_snapserver_with_client, mock_camilladsp, mock_snapserver_volume, user: User
):
    Page().load()
    await user.open('/')
    slider = _only(user, kind=ui.slider, marker='player-volume')
    with user:
        _drag_slider(slider, 60)
    await _settled(lambda: mock_camilladsp.get('set_percent_volume') is not None)
    assert mock_camilladsp.get('set_percent_volume') == 60
    assert mock_camilladsp.get('set_volume') is None
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 100, False)
    assert volume_dal.get('abc123') == 60


async def test_players_tab_volume_db_slider_change_persists_percent_and_shows_db(
    audera_home, mock_snapserver_with_client, mock_camilladsp, mock_snapserver_volume, db_volume_mode, user: User
):
    Page().load()
    await user.open('/')
    slider = _only(user, kind=ui.slider, marker='player-volume')
    with user:
        _drag_slider(slider, 50)
    await _settled(lambda: mock_camilladsp.get('set_percent_volume') is not None)
    assert mock_camilladsp.get('set_percent_volume') == 50
    assert mock_camilladsp.get('set_volume') is None
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 100, False)


async def test_players_tab_volume_db_slider_floor_mutes_via_snapcast(
    audera_home, mock_snapserver_with_client, mock_camilladsp, mock_snapserver_volume, db_volume_mode, user: User
):
    Page().load()
    await user.open('/')
    slider = _only(user, kind=ui.slider, marker='player-volume')
    with user:
        _drag_slider(slider, 0)
    await _settled(lambda: mock_snapserver_volume.get('set_client_volume') is not None)
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 0, True)


async def test_players_tab_volume_db_slider_is_percent_scaled(
    audera_home, mock_snapserver_with_client, mock_camilladsp, db_volume_mode, user: User
):
    Page().load()
    await user.open('/')
    # dB mode keeps the percent (0-100) scale so the handle position matches percent mode.
    slider = user.find(kind=ui.slider).elements.pop()
    assert slider._props['min'] == 0
    assert slider._props['max'] == 100


async def test_reset_snap_volume_calls_snapserver(
    audera_home,
    mock_snapserver_with_client,
    mock_snapserver_volume,
    user: User,
):
    Page().load()
    await user.open('/')
    user.find(marker='player-settings').click()
    user.find('Reset').click()
    await user.should_see('Snapcast volume reset to 100%')
    assert mock_snapserver_volume.get('set_client_volume') == ('abc123', 100, False)


async def test_reset_snap_volume_button(audera_home, mock_snapserver_with_client, monkeypatch, user: User):
    """Player settings dialog contains Snapcast Volume control with Reset button."""
    Page().load()
    await user.open('/')
    user.find(marker='player-settings').click()
    await user.should_see('Snapcast Volume')


async def test_settings_dialog_no_longer_shows_loudness(audera_home, mock_snapserver_with_client, user: User):
    Page().load()
    await user.open('/')
    user.find(marker='player-settings').click()
    await user.should_see('Snapcast Volume')
    await user.should_not_see('Loudness')
    await user.should_not_see('Reference level (dB)')


# --- Advanced DSP editor -----------------------------------------------------------------


async def test_players_tab_shows_dsp_icon(audera_home, mock_snapserver_with_client, mock_camilladsp, user: User):
    Page().load()
    await user.open('/')
    await user.should_see(marker='player-dsp')


async def test_dsp_page_renders(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('Living Room')  # breadcrumb player segment
    await user.should_see('DSP')  # breadcrumb tail segment
    await user.should_see('Pre-amp (dB)')
    await user.should_see('Presets')
    await user.should_see('Save')
    await user.should_see('Reset')
    await user.should_see('Bands (0)')


async def test_dsp_page_unknown_player_shows_message(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/nope/dsp')
    await user.should_see('Player not found or unreachable.')


async def test_dsp_page_offloads_the_snapserver_read_off_the_event_loop(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, monkeypatch, user: User
):
    """The DSP page must not block the shared event loop on the Snapserver read.

    Regression: `render` was a synchronous builder calling `get_clients()` inline, so a slow or
    unreachable Snapserver froze every connected browser for the client's open/read timeout. The
    render path (and its route) is now async and the read is offloaded via `asyncio.to_thread`.
    """
    assert asyncio.iscoroutinefunction(dsp_page.render)
    assert asyncio.iscoroutinefunction(Page.dsp)

    offloaded: list = []
    real_to_thread = asyncio.to_thread

    async def _tracking(func, *args, **kwargs):
        offloaded.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', _tracking)
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('Bands (0)')

    # `get_clients` is patched onto the class by the fixture, so match the bound method by its
    # underlying function rather than by name.
    assert any(getattr(func, '__func__', None) is SnapserverClient.get_clients for func in offloaded)


@pytest.mark.parametrize(
    'steps',
    [
        # Each step is (find-kwargs, expected footer label), applied in order. The
        # intermediate `Bands (2)` on the flat/reset cases is load-bearing: their end state
        # (0 bands) equals the initial state, so without it a silently no-op loudness click
        # would let the test pass vacuously.
        pytest.param([({'marker': 'preset-loudness'}, 'Bands (2)')], id='loudness-seeds-two'),
        pytest.param(
            [({'marker': 'preset-loudness'}, 'Bands (2)'), ({'marker': 'preset-flat'}, 'Bands (0)')],
            id='flat-clears',
        ),
        pytest.param([({'content': '+ Add band'}, 'Bands (1)')], id='add-appends-one'),
        pytest.param(
            [({'marker': 'preset-loudness'}, 'Bands (2)'), ({'content': 'Reset'}, 'Bands (0)')],
            id='reset-discards',
        ),
    ],
)
async def test_dsp_band_count_reflects_actions(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User, steps):
    Page().load()
    await user.open('/player/abc123/dsp')
    for find_kwargs, expected in steps:
        user.find(**find_kwargs).click()
        await user.should_see(expected)


def _seed_dsp(config: DSPConfig) -> None:
    """Persists a DSP config keyed by player 'abc123' (the page's load path).

    The config is keyed by the player id (`dsp/abc123.json` is the link), so persisting it
    under that key is all `get_or_create` needs to open it instead of a fresh empty one.
    """
    dsp_dal.save(config.model_copy(update={'player_id': 'abc123'}))


async def test_dsp_bandless_shows_chart_message_and_hides_chart(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('Load a preset')  # the empty-state tip
    await user.should_not_see(kind=ui.echart)


async def test_dsp_adding_band_reveals_chart(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_not_see(kind=ui.echart)
    user.find(content='+ Add band').click()
    await user.should_see(kind=ui.echart)


async def test_dsp_preamp_rises_when_band_removed(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    # The pre-amp is fully derived from the bands: removing the boost that lowered it must
    # return it to 0 (regression: the old min() clamp only ratcheted down, never up).
    band = Band(id='b1', type='Peaking', freq=1000.0, gain=5.0, q=0.707)
    _seed_dsp(DSPConfig(player_id='cfg1', preamp_db=-5.0, bands=[band]))
    Page().load()
    await user.open('/player/abc123/dsp')
    with user:
        user.find(marker='dsp-band-delete').click()

    def _preamp() -> float:
        return user.find(kind=ui.number, content='auto-protected').elements.pop().value

    await _settled(lambda: _preamp() == pytest.approx(0.0, abs=0.05))
    assert _preamp() == pytest.approx(0.0, abs=0.05)


async def test_dsp_saved_config_opens_clean(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    # The pre-amp is fully derived from the bands and normalized on load, so a saved config's
    # seeded pre-amp is replaced by the recomputed clip-safe ceiling; the editor opens without
    # a false "Unsaved changes" flag.
    _seed_dsp(DSPConfig(player_id='cfg1', preamp_db=-6.0, bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=6.0, q=1.0)]))
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see(kind=ui.echart)
    await user.should_not_see('Unsaved changes')


async def test_dsp_protect_button_removed(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='preset-loudness').click()
    await user.should_see('Bands (2)')
    await user.should_not_see('protect headroom')


async def test_dsp_save_applies_and_persists(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='preset-loudness').click()
    await user.should_see('Bands (2)')
    user.find('Save').click()
    await user.should_see('Saved')

    # The compiled pipeline is both validated and pushed, and carries `audera_peq_*` filters.
    assert 'validate_config' in mock_camilladsp_dsp
    compiled = mock_camilladsp_dsp['set_config']
    assert any(name.startswith('audera_peq_') for name in compiled['filters'])
    assert 'reset_clipped_samples' in mock_camilladsp_dsp

    # The config is persisted keyed by the player id, carrying the two bands.
    assert dsp_dal.exists('abc123')
    assert len(dsp_dal.get('abc123').bands) == 2


# --- CamillaDSP YAML import/export via Config ▾ ------------------------------------------


async def test_dsp_config_menu_exposes_import_and_export(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    Page().load()
    await user.open('/player/abc123/dsp')
    assert user.find(marker='config-import').elements
    assert user.find(marker='config-export').elements


async def test_dsp_import_appends_bands(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('Bands (0)')
    user.find(marker='config-import').click()
    yaml_text = (
        'filters:\n'
        '  band_1: {type: Biquad, parameters: {type: Peaking, freq: 1000, q: 1.41, gain: -3.0}}\n'
        '  band_2: {type: Biquad, parameters: {type: Lowshelf, freq: 90, q: 0.7, gain: 4.0}}\n'
    )
    with user:
        user.find(kind=ui.textarea).elements.pop().value = yaml_text
    user.find(marker='config-import-run').click()
    await user.should_see('Bands (2)')
    await user.should_see('Imported 2 band(s)')


async def test_dsp_import_notifies_skipped_filters(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='config-import').click()
    yaml_text = (
        'filters:\n'
        '  band_1: {type: Biquad, parameters: {type: Peaking, freq: 1000, q: 1.41, gain: -3.0}}\n'
        '  band_2: {type: Biquad, parameters: {type: Notch, freq: 60, q: 5.0, gain: 0}}\n'
    )
    with user:
        user.find(kind=ui.textarea).elements.pop().value = yaml_text
    user.find(marker='config-import-run').click()
    await user.should_see('Bands (1)')
    await user.should_see('Imported 1 band(s), skipped 1 filter(s)')


async def test_dsp_export_renders_saved_config_yaml(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    _seed_dsp(DSPConfig(player_id='cfg1', preamp_db=-6.0, bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=6.0, q=1.0)]))
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='config-export').click()
    await user.should_see('filters:')  # the CamillaDSP tag REW requires to import
    await user.should_see('Peaking')


async def test_dsp_export_banner_absent_on_clean_open(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    _seed_dsp(DSPConfig(player_id='cfg1', preamp_db=-6.0, bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=6.0, q=1.0)]))
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='config-export').click()
    await user.should_see('filters:')
    await user.should_not_see(marker='export-unsaved-banner')


async def test_dsp_export_banner_shown_after_edit(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    _seed_dsp(DSPConfig(player_id='cfg1', preamp_db=-6.0, bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=6.0, q=1.0)]))
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(content='+ Add band').click()  # stage an edit so staged ≠ saved
    await user.should_see('Bands (2)')
    user.find(marker='config-export').click()
    await user.should_see(marker='export-unsaved-banner')


# --- Named user presets ------------------------------------------------------------------


async def test_dsp_saved_preset_appears_and_appends(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    presets_dal.save_preset(
        Preset(
            id='p1',
            name='Bass Boost',
            bands=[
                Band(id='b1', type='Lowshelf', freq=90.0, gain=6.0, q=0.7),
                Band(id='b2', type='Peaking', freq=1000.0, gain=-3.0, q=2.0),
            ],
        )
    )
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('Bands (0)')
    await user.should_see('Bass Boost')  # the saved preset lists in the menu by name
    user.find(marker='preset-saved').click()
    await user.should_see('Bands (2)')  # apply = append cloned bands


async def test_dsp_save_current_as_preset_persists(audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User):
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='preset-loudness').click()  # stage two bands to capture
    await user.should_see('Bands (2)')
    user.find(marker='preset-save-as').click()
    with user:
        user.find(kind=ui.input).elements.pop().value = 'My Loudness'  # the dialog's only input
    user.find(marker='preset-save-run').click()
    await user.should_see('Saved preset')

    saved = presets_dal.get_all_presets()
    assert len(saved) == 1
    assert saved[0].name == 'My Loudness'
    assert len(saved[0].bands) == 2


async def test_dsp_save_preset_name_collision_replace_overwrites(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    # A trimmed, case-insensitive name match prompts a confirm; Replace overwrites the same
    # preset (reusing its id) rather than appending a duplicate.
    presets_dal.save_preset(
        Preset(id='p1', name='My Preset', bands=[Band(id='b0', type='Peaking', freq=500.0, gain=2.0, q=1.0)])
    )
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='preset-loudness').click()  # stage two bands to capture
    await user.should_see('Bands (2)')
    user.find(marker='preset-save-as').click()
    with user:
        user.find(kind=ui.input, marker='preset-save-name').elements.pop().value = 'my preset'  # differs only by case
    user.find(marker='preset-save-run').click()
    await user.should_see('already exists')  # the collision confirm
    user.find(marker='preset-replace-confirm').click()
    await user.should_see('Replaced preset')

    saved = presets_dal.get_all_presets()
    assert len(saved) == 1  # overwrote in place — no duplicate
    assert saved[0].id == 'p1'  # reused the existing id so references stay stable
    assert len(saved[0].bands) == 2  # bands swapped to the staged loudness set


async def test_dsp_save_preset_name_collision_cancel_keeps_original(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    # Cancel on the confirm leaves the existing preset untouched (and the save dialog open).
    presets_dal.save_preset(
        Preset(id='p1', name='My Preset', bands=[Band(id='b0', type='Peaking', freq=500.0, gain=2.0, q=1.0)])
    )
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(marker='preset-loudness').click()
    await user.should_see('Bands (2)')
    user.find(marker='preset-save-as').click()
    with user:
        user.find(kind=ui.input, marker='preset-save-name').elements.pop().value = 'My Preset'
    user.find(marker='preset-save-run').click()
    await user.should_see('already exists')
    user.find(marker='preset-replace-cancel').click()

    saved = presets_dal.get_all_presets()
    assert len(saved) == 1
    assert saved[0].id == 'p1'
    assert len(saved[0].bands) == 1  # original bands untouched


def test_response_plot_options_axes():
    # Max is fixed display headroom (the auto pre-amp keeps the curve ≤ 0 dB); min floors at
    # -18 dB but auto-extends downward when a deep cut dips below it.
    flat = DSPConfig(player_id='cfg1', bands=[])
    flat_axis = components.response_plot.options(flat)['yAxis']
    assert flat_axis['max'] == 5
    assert flat_axis['min'] == -18  # floor holds with no deep cut
    deep = DSPConfig(player_id='cfg1', bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=-24.0, q=1.0)])
    assert components.response_plot.options(deep)['yAxis']['min'] < -18


# --- DSP band-editor UX (full / expand / dialog) -----------------------------------------


def test_band_summary_omits_gain_for_pass_types():
    # `dB` also appears in the `Pre-amp (dB)` label, so the pass-type omission is asserted on
    # the pure helper rather than page-level DOM matching.
    assert 'dB' not in _band_summary(Band(id='x', type='Highpass', freq=80.0, gain=0.0, q=0.7))
    assert 'dB' in _band_summary(Band(id='y', type='Peaking', freq=1000.0, gain=-3.0, q=0.707))


def _seed_band_editor(mode: str) -> None:
    """Persists settings selecting the DSP band-editor mode before the page loads."""
    settings_dal.create(
        Settings(
            plexamp_host='localhost',
            snapserver_host='localhost',
            features={features.DSP_BAND_EDITOR_KEY: mode},
        )
    )


# Discriminator for collapsed-vs-revealed controls: the DSP editor has no `ui.select` anywhere
# except the band Type control, so its presence cleanly signals whether controls are showing.
def _one_band() -> DSPConfig:
    return DSPConfig(player_id='cfg1', bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=-3.0, q=0.707)])


async def test_dsp_band_editor_full_shows_inline_controls(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    _seed_band_editor(features.FF_DSP_BAND_EDITOR_FULL)
    _seed_dsp(_one_band())
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see(kind=ui.select)  # full mode renders the type/freq/gain/q controls inline


async def test_dsp_band_editor_expand_reveals_controls_on_edit(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    _seed_band_editor(features.FF_DSP_BAND_EDITOR_EXPAND)
    _seed_dsp(_one_band())
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('1000 Hz')  # the compact summary row
    await user.should_not_see(kind=ui.select)  # controls stay collapsed until the ✏ edit
    user.find(marker='dsp-band-edit').click()
    await user.should_see(kind=ui.select)  # accordion revealed the controls inline


async def test_dsp_band_editor_dialog_opens_modal_on_edit(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    _seed_band_editor(features.FF_DSP_BAND_EDITOR_DIALOG)
    _seed_dsp(_one_band())
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_see('1000 Hz')  # the compact summary row
    await user.should_not_see(kind=ui.select)  # controls live in the modal, not the row
    user.find(marker='dsp-band-edit').click()
    await user.should_see('Edit band')  # the modal title
    await user.should_see(marker='dsp-band-close')
    await user.should_see(kind=ui.select)  # controls render inside the modal


async def test_dsp_band_editor_expand_add_band_reveals_controls(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    _seed_band_editor(features.FF_DSP_BAND_EDITOR_EXPAND)
    Page().load()
    await user.open('/player/abc123/dsp')
    await user.should_not_see(kind=ui.select)
    user.find(content='+ Add band').click()
    await user.should_see(kind=ui.select)  # the new band's editor auto-reveals — no second click


async def test_dsp_band_editor_dialog_add_band_opens_modal(
    audera_home, mock_snapserver_with_client, mock_camilladsp_dsp, user: User
):
    _seed_band_editor(features.FF_DSP_BAND_EDITOR_DIALOG)
    Page().load()
    await user.open('/player/abc123/dsp')
    user.find(content='+ Add band').click()
    await user.should_see('Edit band')  # the new band's editor auto-opens as a modal
