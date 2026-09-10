"""Integration tests for the event broker against a real Snapserver container."""

import asyncio
import time

import pytest

from audera.clients import CamillaDSPClient, SnapserverClient
from audera.dal import dsp as dsp_dal
from audera.dal import volume as volume_dal
from audera.models.dsp import Band, DSPConfig
from audera.ui.streamer import commands
from audera.ui.streamer.broker import EventBroker


async def _poll(predicate, *, timeout=5.0, interval=0.05):
    """Polls until ``predicate()`` holds or ``timeout`` elapses.

    Returns rather than raises at the deadline, so the caller's own assertion reports what it found.
    """
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return
        await asyncio.sleep(interval)


@pytest.fixture
def snap_client(snapserver_container):
    host, port = snapserver_container
    return SnapserverClient(host, port)


@pytest.fixture
async def broker_instance(snapserver_container, monkeypatch):
    host, port = snapserver_container
    monkeypatch.setattr(CamillaDSPClient, 'get_percent_volume', lambda self: None)
    b = EventBroker(host, port)
    b.start()
    await _poll(lambda: len(b.cache.clients) > 0, timeout=10.0)
    yield b
    await b.stop()


async def test_seed_populates_cache(broker_instance):
    assert len(broker_instance.cache.clients) >= 1
    assert len(broker_instance.cache.groups) > 0
    assert len(broker_instance.cache.stream_status) >= 1
    assert all(isinstance(v, str) and v for v in broker_instance.cache.stream_status.values())


async def test_seed_volumes_without_dal_fall_back_to_none(audera_home, broker_instance):
    connected = [c for c in broker_instance.cache.clients if c.connected]
    for c in connected:
        assert broker_instance.cache.volumes[c.id] is None
    disconnected_ids = {c.id for c in broker_instance.cache.clients if not c.connected}
    for did in disconnected_ids:
        assert did not in broker_instance.cache.volumes


async def test_seed_volumes_with_dal_uses_cached_value(audera_home, broker_instance, snap_client):
    """When the DAL holds a volume and a notification arrives, the broker reads from the DAL."""
    client_id = broker_instance.cache.clients[0].id
    volume_dal.set(client_id, 42)
    await asyncio.to_thread(snap_client.set_client_volume, client_id, 75)
    await _poll(lambda: broker_instance.cache.volumes.get(client_id) == 42)
    assert broker_instance.cache.volumes[client_id] == 42


async def test_notification_updates_volume(broker_instance, snap_client):
    client_id = broker_instance.cache.clients[0].id
    original = broker_instance.cache.clients[0].volume
    new_vol = 30 if original != 30 else 50
    await asyncio.to_thread(snap_client.set_client_volume, client_id, new_vol)
    await _poll(lambda: broker_instance.cache.clients[0].volume == new_vol)
    assert broker_instance.cache.clients[0].volume == new_vol


async def test_notification_fires_dirty_callback(broker_instance, snap_client):
    dirty = asyncio.Event()
    broker_instance.on_dirty(lambda: dirty.set())
    client_id = broker_instance.cache.clients[0].id
    original = broker_instance.cache.clients[0].volume
    new_vol = 25 if original != 25 else 55
    await asyncio.to_thread(snap_client.set_client_volume, client_id, new_vol)
    await asyncio.wait_for(dirty.wait(), timeout=2.0)
    assert dirty.is_set()


async def test_notification_name_change(broker_instance, snap_client):
    client_id = broker_instance.cache.clients[0].id
    await asyncio.to_thread(snap_client.set_client_name, client_id, 'Test Name')
    await _poll(lambda: broker_instance.cache.clients[0].name == 'Test Name')
    assert broker_instance.cache.clients[0].name == 'Test Name'


async def test_client_reconnect_reapplies_saved_dsp_pipeline(audera_home, broker_instance, monkeypatch):
    """`Client.OnConnect` re-pushes a saved, enabled DSP config onto the reconnecting player.

    Regression: a re-provisioned player's daemon boots with an empty pipeline (ADR 003 decision 3),
    wiping any previously-pushed filters; without a reconnect resync the saved config was only
    re-applied when someone opened the DSP page and hit Save.
    """
    client_id = broker_instance.cache.clients[0].id
    dsp_dal.save(DSPConfig(player_id=client_id, preamp_db=-3.0, bands=[Band(id='b1', freq=1000.0, gain=3.0)]))

    calls: list[str] = []
    applied: dict = {}

    monkeypatch.setattr(CamillaDSPClient, 'get_config', lambda self: {'filters': {}, 'pipeline': []})

    def _validate_config(self, config):
        calls.append('validate_config')

    def _set_config(self, config):
        calls.append('set_config')
        applied.update(config)

    monkeypatch.setattr(CamillaDSPClient, 'validate_config', _validate_config)
    monkeypatch.setattr(CamillaDSPClient, 'set_config', _set_config)

    commands.start()
    try:
        await broker_instance._handle_notification('Client.OnConnect', {'client': {'id': client_id}})
        await _poll(lambda: calls == ['validate_config', 'set_config'])
    finally:
        await commands.stop()

    assert calls == ['validate_config', 'set_config']
    assert any(name.startswith('audera_peq_') for name in applied.get('filters', {}))


def _bare_broker() -> EventBroker:
    """An EventBroker with no reader task, for unit-testing signal/debounce paths."""
    from audera.ui.streamer.broker import Cache

    b = EventBroker.__new__(EventBroker)
    b._host = 'localhost'
    b._port = 1780
    b._url = 'ws://localhost:1780/jsonrpc'
    b.cache = Cache()
    b._callbacks = []
    b._prev_snapshot = ()
    b._reader_task = None
    b._debounce_handle = None
    b._stopped = True
    return b


async def test_seed_signals_dirty_when_cache_changes_from_empty():
    """The seed handler must fire dirty when the cache changes from empty.

    Regression: the seed handler set ``_prev_snapshot`` before calling ``_maybe_signal``,
    so the comparison always found them equal and never signalled dirty.
    """
    from audera.ui.streamer.broker import _DEBOUNCE_SECONDS

    b = _bare_broker()
    b.cache.stream_status = {'AirPlay': 'idle'}

    dirty = asyncio.Event()
    b.on_dirty(lambda: dirty.set())

    b._maybe_signal()

    await asyncio.wait_for(dirty.wait(), timeout=_DEBOUNCE_SECONDS + 1.0)
    assert dirty.is_set()
    assert b._prev_snapshot == b.cache.snapshot()


async def test_identical_full_status_does_not_drop_pending_dirty():
    """A full-status apply that cancels the debounce must not strand an undelivered change.

    Regression: ``_maybe_signal`` used to commit ``_prev_snapshot`` at schedule time, so
    ``_apply_full_status`` cancelling the timer left cache == prev and dirty never fired.
    """
    from unittest.mock import patch

    from audera.models.player import Player
    from audera.ui.streamer.broker import _DEBOUNCE_SECONDS

    b = _bare_broker()
    b.cache.clients = [
        Player(id='c1', host='10.0.0.2', port=1704, connected=True, volume=50, muted=False, group_id='g1', name='A')
    ]
    b.cache.groups = []
    b.cache.stream_status = {'AirPlay': 'idle'}
    b.cache.volumes = {'c1': 50}
    b._prev_snapshot = b.cache.snapshot()

    dirty = asyncio.Event()
    b.on_dirty(lambda: dirty.set())

    b.cache.clients[0].muted = True
    b._maybe_signal()
    assert b._debounce_handle is not None

    status = {
        'server': {
            'groups': [
                {
                    'id': 'g1',
                    'name': '',
                    'muted': False,
                    'stream_id': 'AirPlay',
                    'clients': [
                        {
                            'id': 'c1',
                            'connected': True,
                            'host': {'ip': '10.0.0.2', 'name': 'A', 'port': 1704},
                            'config': {
                                'name': 'A',
                                'latency': 0,
                                'volume': {'percent': 50, 'muted': True},
                            },
                        }
                    ],
                }
            ],
            'streams': [{'id': 'AirPlay', 'status': 'idle'}],
        }
    }

    async def _load_volumes():
        b.cache.volumes = {'c1': 50}

    with patch.object(b, '_load_volumes', _load_volumes):
        await b._apply_full_status(status)
        b._maybe_signal()

    await asyncio.wait_for(dirty.wait(), timeout=_DEBOUNCE_SECONDS + 1.0)
    assert dirty.is_set()
    assert b.cache.clients[0].muted is True
    assert b._prev_snapshot == b.cache.snapshot()


async def test_full_status_prunes_volumes_for_removed_clients():
    """A client dropped by a full ``Server.GetStatus`` must not leak a stale ``cache.volumes`` entry.

    Regression: ``_load_volumes`` merged into ``cache.volumes`` without pruning, so a client removed
    by a wholesale status refresh (as opposed to a ``Client.OnDisconnect``) left its entry behind.
    """
    from unittest.mock import patch

    from audera.ui.streamer import broker as bmod

    b = _bare_broker()

    def _status_with(ids):
        return {
            'server': {
                'groups': [
                    {
                        'id': 'g1',
                        'clients': [
                            {
                                'id': i,
                                'connected': True,
                                'host': {'ip': 'x'},
                                'config': {'name': '', 'volume': {'percent': 50, 'muted': False}},
                            }
                            for i in ids
                        ],
                    }
                ],
                'streams': [],
            }
        }

    with patch.object(bmod.volume_dal, 'get_all', return_value={'a': 10, 'b': 20}):
        await b._apply_full_status(_status_with(['a', 'b']))
    assert set(b.cache.volumes) == {'a', 'b'}

    with patch.object(bmod.volume_dal, 'get_all', return_value={'a': 10}):
        await b._apply_full_status(_status_with(['a']))

    assert 'b' not in b.cache.volumes
    assert set(b.cache.volumes) == {'a'}
    assert [p.id for p in b.cache.clients] == ['a']


async def test_partial_client_frame_degrades_instead_of_raising():
    """A client frame missing ``config``/``volume`` must degrade to a defaulted entry, not ``KeyError``.

    Regression: the broker used to re-parse status frames with hard subscripts, so a partial frame
    the client tolerates raised and dropped the socket into a silent reconnect loop.
    """
    from unittest.mock import patch

    from audera.ui.streamer import broker as bmod

    b = _bare_broker()

    status = {
        'server': {
            'groups': [
                {
                    'id': 'g1',
                    'clients': [
                        {'id': 'c1', 'connected': True, 'host': {'ip': '10.0.0.2'}},
                    ],
                }
            ],
            'streams': [],
        }
    }

    with patch.object(bmod.volume_dal, 'get_all', return_value={}):
        await b._apply_full_status(status)

    assert [p.id for p in b.cache.clients] == ['c1']
    player = b.cache.clients[0]
    assert player.volume == 0
    assert player.muted is False
    assert player.host == '10.0.0.2'


async def test_group_volume_change_triggers_dirty():
    """A change to only a group's volume must fire the dirty callback.

    Regression: the hand-maintained snapshot omitted group ``volume``, so a group-volume change
    left the UI stale with no error. The model-derived snapshot includes it.
    """
    from unittest.mock import patch

    from audera.ui.streamer import broker as bmod
    from audera.ui.streamer.broker import _DEBOUNCE_SECONDS

    b = _bare_broker()

    def _status_with_group_volume(vol):
        return {
            'server': {
                'groups': [
                    {
                        'id': 'g1',
                        'name': 'Living Room',
                        'stream_id': 'AirPlay',
                        'muted': False,
                        'volume': {'percent': vol},
                        'clients': [
                            {
                                'id': 'c1',
                                'connected': True,
                                'host': {'ip': '10.0.0.2'},
                                'config': {'name': '', 'volume': {'percent': 50, 'muted': False}},
                            }
                        ],
                    }
                ],
                'streams': [{'id': 'AirPlay', 'status': 'idle'}],
            }
        }

    with patch.object(bmod.volume_dal, 'get_all', return_value={'c1': 50}):
        await b._apply_full_status(_status_with_group_volume(80))
    b._maybe_signal()
    b._signal_dirty()  # flush the seed change so the next change is isolated to group volume

    dirty = asyncio.Event()
    b.on_dirty(lambda: dirty.set())

    with patch.object(bmod.volume_dal, 'get_all', return_value={'c1': 50}):
        await b._apply_full_status(_status_with_group_volume(40))
    b._maybe_signal()

    await asyncio.wait_for(dirty.wait(), timeout=_DEBOUNCE_SECONDS + 1.0)
    assert dirty.is_set()
    assert b.cache.groups[0].volume == 40


async def test_dirty_not_delivered_when_change_reverts_during_debounce():
    """If the cache returns to the last delivered snapshot before the timer fires, skip callbacks."""
    from audera.ui.streamer.broker import _DEBOUNCE_SECONDS

    b = _bare_broker()
    b.cache.stream_status = {'AirPlay': 'idle'}
    b._prev_snapshot = b.cache.snapshot()

    dirty = asyncio.Event()
    b.on_dirty(lambda: dirty.set())

    b.cache.stream_status = {'AirPlay': 'playing'}
    b._maybe_signal()
    b.cache.stream_status = {'AirPlay': 'idle'}
    # Timer still armed; delivery must observe the reverted snapshot and no-op.
    assert b._debounce_handle is not None

    await asyncio.sleep(_DEBOUNCE_SECONDS + 0.15)
    assert not dirty.is_set()
    assert b._prev_snapshot == b.cache.snapshot()
