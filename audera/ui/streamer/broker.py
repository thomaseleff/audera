"""Event broker between device state and the UI.

Receives events from two sources: Snapserver notifications over a persistent WebSocket, and
player volumes from the volume DAL. Caches clients, groups, stream status, and volumes, parsing
status frames via `clients.snapserver`'s shared frame parsers. Signals registered callbacks when
the cached state changes.

Writes use short-lived connections via ``SnapserverClient._call`` because Snapserver's
``excludeSession`` excludes the writing socket from notifications.

Connected players missing from the volume DAL fall back to a one-shot CamillaDSP read
(first boot / migration) and seed the DAL with the result.
"""

import asyncio
import json
import logging
from typing import Callable

import websockets.asyncio.client

import audera
from audera.clients import CamillaDSPClient, SnapserverClient
from audera.clients.snapserver import groups_from_status, players_from_status, stream_status_from_status
from audera.dal import dsp as dsp_dal
from audera.dal import volume as volume_dal
from audera.domains.dsp import apply_pipeline
from audera.models.player import Group, Player
from audera.ui.streamer import commands

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS: float = 0.25
_RECONNECT_MIN: float = 1.0
_RECONNECT_MAX: float = 30.0


class Cache:
    """Mutable cache of Snapserver clients, groups, stream status, and player volumes.

    All fields are written by the broker's reader task and read by UI builds. The UI never writes here.
    """

    __slots__ = ('clients', 'groups', 'stream_status', 'volumes')

    def __init__(self):
        self.clients: list[Player] = []
        self.groups: list[Group] = []
        self.stream_status: dict[str, str] = {}
        self.volumes: dict[str, int | None] = {}

    def snapshot(self) -> tuple:
        """Change-detection key over every cached field.

        Each model is serialized via `dict(model)`, which on a pydantic v2 model yields **all**
        fields (including `exclude=True` ones like `Player.name`/`latency_ms` and group `volume`),
        so a newly added field is always in change detection. The result is only ever compared with
        `==` (never hashed), so a list-valued field such as `Group.client_ids` is fine.
        """
        return (
            tuple(tuple(sorted(dict(c).items())) for c in self.clients),
            tuple(tuple(sorted(dict(g).items())) for g in self.groups),
            tuple(sorted(self.stream_status.items())),
            tuple(sorted(self.volumes.items())),
        )


class EventBroker:
    """Event broker between device state and the UI."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._url = 'ws://%s:%d/jsonrpc' % (host, port)
        self.cache = Cache()
        self._callbacks: list[Callable[[], None]] = []
        self._prev_snapshot: tuple = ()
        self._reader_task: asyncio.Task | None = None
        self._debounce_handle: asyncio.TimerHandle | None = None
        self._stopped = False

    def on_dirty(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def _signal_dirty(self) -> None:
        """Delivers dirty callbacks and commits the delivered snapshot.

        Snapshot is committed here, not in ``_maybe_signal``, so cancelling a pending
        debounce (e.g. ``_apply_full_status``) cannot strand an undelivered change: the
        next ``_maybe_signal`` still sees cache != last delivered snapshot.
        """
        self._debounce_handle = None
        snap = self.cache.snapshot()
        if snap == self._prev_snapshot:
            # Reverted during the quiet period; nothing to deliver.
            return
        self._prev_snapshot = snap
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                logger.exception('broker dirty callback failed')

    def _maybe_signal(self) -> None:
        """Schedules a dirty delivery when the cache differs from the last delivered snapshot."""
        if self.cache.snapshot() == self._prev_snapshot:
            return
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
        loop = asyncio.get_event_loop()
        self._debounce_handle = loop.call_later(_DEBOUNCE_SECONDS, self._signal_dirty)

    def _snap_client(self) -> SnapserverClient:
        return SnapserverClient(host=self._host, port=self._port)

    async def _load_volumes(self) -> None:
        """Populates ``cache.volumes`` from the volume DAL, falling back to a one-shot
        CamillaDSP read for connected players missing from the DAL (first boot / migration)."""
        dal_volumes: dict[str, int | None] = dict(await asyncio.to_thread(volume_dal.get_all))
        connected = [c for c in self.cache.clients if c.connected]
        missing = [p for p in connected if p.id not in dal_volumes]

        async def _seed_one(p: Player) -> tuple[str, int | None]:
            try:
                vol = await asyncio.to_thread(CamillaDSPClient(host=p.host).get_percent_volume)
                if vol is not None:
                    await asyncio.to_thread(volume_dal.set, p.id, vol)
                return p.id, vol
            except Exception:
                return p.id, None

        if missing:
            results = await asyncio.gather(*(_seed_one(p) for p in missing))
            for client_id, vol in results:
                dal_volumes[client_id] = vol

        # Rebuild rather than merge: a full `Server.GetStatus` replaces `clients` wholesale, so a
        # dropped client would otherwise leave a stale entry.
        self.cache.volumes = {p.id: dal_volumes.get(p.id) for p in connected}

    async def _apply_full_status(self, status: dict) -> None:
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        self.cache.clients = players_from_status(status)
        self.cache.groups = groups_from_status(status)
        self.cache.stream_status = stream_status_from_status(status)
        await self._load_volumes()

    async def _reseed_via_short_lived(self) -> None:
        """Full reseed using a short-lived connection, used when the persistent socket
        cannot carry a request (e.g. after Client.OnConnect)."""
        await self.reseed()

    async def reseed(self) -> None:
        """Pulls ``Server.GetStatus`` over a short-lived connection and refreshes the cache.

        Used after a source toggle restarts Snapserver so Sources/Players reads see the
        post-restart streams before the persistent socket's next notification.

        Failures are logged and swallowed: the caller already waited for readiness, and a
        later notification or reconnect still reseeds. Raising would abort the toggle's
        success path after the host write already landed.
        """
        try:
            status = await asyncio.to_thread(self._snap_client().get_status)
        except Exception:
            logger.warning('broker reseed failed', exc_info=True)
            return
        await self._apply_full_status(status)
        self._maybe_signal()

    def _find_player(self, client_id: str) -> Player | None:
        for p in self.cache.clients:
            if p.id == client_id:
                return p
        return None

    def _find_group(self, group_id: str) -> Group | None:
        for g in self.cache.groups:
            if g.id == group_id:
                return g
        return None

    async def _resync_dsp(self, player: Player) -> None:
        """Re-pushes a player's saved DSP pipeline after it reconnects.

        A re-provisioned player's daemon re-renders `/etc/camilladsp/config.yml` with an empty
        pipeline (ADR 003 decision 3), wiping any previously-pushed `audera_`-managed filters; the
        saved config is otherwise only re-applied when someone opens the DSP page and hits Save.
        The read and apply run in one queued command so the config can't be captured stale ahead of
        an in-flight Save's persist, and `coalesce_key` collapses a flapping client's repeated
        reconnects into a single apply. Failures are logged and swallowed, matching `reseed()`'s
        pattern: a background resync must not crash the reader loop or block other players.
        """

        def _resync() -> None:
            if not dsp_dal.exists(player.id):
                return
            apply_pipeline(CamillaDSPClient(host=player.host), dsp_dal.get(player.id))

        try:
            await commands.get().submit(_resync, coalesce_key=('dsp-resync', player.id))
        except Exception:
            logger.warning('broker DSP resync failed for player %s', player.id, exc_info=True)

    async def _handle_notification(self, method: str, params: dict) -> None:
        if method == 'Client.OnVolumeChanged':
            client_id = params.get('id', '')
            vol_data = params.get('volume', {})
            p = self._find_player(client_id)
            if p is not None:
                p.volume = vol_data.get('percent', p.volume)
                p.muted = vol_data.get('muted', p.muted)
                vol = await asyncio.to_thread(volume_dal.get, client_id)
                if vol is not None:
                    self.cache.volumes[client_id] = vol

        elif method == 'Client.OnConnect':
            await self._reseed_via_short_lived()
            client_data = params.get('client', params)
            p = self._find_player(client_data.get('id', ''))
            if p is not None:
                await self._resync_dsp(p)

        elif method == 'Client.OnDisconnect':
            client_data = params.get('client', params)
            client_id = client_data.get('id', '')
            p = self._find_player(client_id)
            if p is not None:
                p.connected = False
            self.cache.volumes.pop(client_id, None)

        elif method == 'Client.OnNameChanged':
            client_id = params.get('id', '')
            p = self._find_player(client_id)
            if p is not None:
                p.name = params.get('name', p.name)

        elif method == 'Client.OnLatencyChanged':
            client_id = params.get('id', '')
            p = self._find_player(client_id)
            if p is not None:
                p.latency_ms = params.get('latency', p.latency_ms)

        elif method == 'Group.OnStreamChanged':
            group_id = params.get('id', '')
            g = self._find_group(group_id)
            if g is not None:
                g.stream_id = params.get('stream_id', g.stream_id)

        elif method == 'Group.OnMute':
            group_id = params.get('id', '')
            g = self._find_group(group_id)
            if g is not None:
                g.muted = params.get('mute', g.muted)

        elif method == 'Stream.OnUpdate':
            stream = params.get('stream', params)
            stream_id = stream.get('id', '')
            if stream_id:
                self.cache.stream_status[stream_id] = stream.get('status', 'unknown')

        elif method == 'Server.OnUpdate':
            server_data = params.get('server', params)
            await self._apply_full_status({'server': server_data})

        self._maybe_signal()

    async def _reader_loop(self) -> None:
        backoff = _RECONNECT_MIN
        while not self._stopped:
            try:
                async with websockets.asyncio.client.connect(self._url) as ws:
                    backoff = _RECONNECT_MIN
                    logger.info('broker connected to %s', self._url)

                    status_msg = json.dumps(
                        {
                            'id': 'broker-seed',
                            'jsonrpc': '2.0',
                            'method': 'Server.GetStatus',
                        }
                    )
                    await ws.send(status_msg)

                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)

                        if msg.get('id') == 'broker-seed':
                            await self._apply_full_status(msg.get('result', {}))
                            self._maybe_signal()
                            continue

                        method = msg.get('method', '')
                        if method:
                            await self._handle_notification(method, msg.get('params', {}))

            except asyncio.CancelledError:
                return
            except Exception:
                if self._stopped:
                    return
                logger.warning('broker connection lost, reconnecting in %.0fs', backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX)

    def start(self) -> None:
        self._stopped = False
        loop = asyncio.get_event_loop()
        self._reader_task = loop.create_task(self._reader_loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass


_broker: EventBroker | None = None


def get() -> EventBroker:
    assert _broker is not None, 'broker not started'
    return _broker


def start(host: str, port: int = audera.SNAPSERVER_PORT) -> None:
    global _broker
    _broker = EventBroker(host, port)
    _broker.start()


async def stop() -> None:
    global _broker
    if _broker is not None:
        await _broker.stop()
        _broker = None


async def reseed() -> None:
    """Reseeds the process broker when it is running; no-op before startup."""
    if _broker is not None:
        await _broker.reseed()
