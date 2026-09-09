"""Audera app index"""

import asyncio
import time
from typing import TYPE_CHECKING, Callable, NamedTuple

from nicegui import ui

import audera
from audera.dal import balance as balance_dal
from audera.dal import settings as settings_dal
from audera.dal import sources as sources_dal
from audera.dal import volume as volume_dal
from audera.domains.sources import CATALOG, SourceDefinition, default_source, toggle
from audera.errors import CommandError
from audera.models.balance import ReferenceBalance
from audera.models.player import Player
from audera.models.settings import Settings
from audera.ui import components, features
from audera.ui.streamer import broker, commands
from audera.ui.streamer.pages import _plex
from audera.ui.streamer.pages._clients import _camilladsp, _snapserver

if TYPE_CHECKING:
    from audera.ui.streamer.pages import Page

# `sources_dal` is imported as a module so that `sources_dal.PATH` resolves at call time, which
# lets the tests redirect it. `domains.sources.toggle` carries the same convention for
# `conf.SNAPSERVER_CONF` and `system.systemctl`.

# `ui.tabs.on_value_change` reports the tab name rather than the `ui.tab` element, so the handler
# and the constructor must agree on the string.
_PLAYERS_TAB = 'Players'
_SOURCES_TAB = 'Sources'
_SETTINGS_TAB = 'Settings'

# How long to keep asking a restarted Snapserver for its stream status before rendering the
# Sources tab anyway, and how long to sleep between asks.
_READY_TIMEOUT = 20.0
_READY_INTERVAL = 0.5

_LAST_SOURCE_MESSAGE = 'At least one audio source must stay enabled.'
_INTERRUPTION_MESSAGE = 'Applying this will briefly interrupt playback on all players.'

_NO_GROUP_MESSAGE = 'This player is not in a Snapcast group yet.'
_NO_DESTINATION_MESSAGE = 'There is nowhere else to move this player.'
_NO_LIVE_DESTINATION_MESSAGE = 'No other enabled source is running, so Snapserver will reassign these players itself.'

# The by-stream layout's section for players whose stream Snapserver did not name. A marker
# suffix has to be non-empty, and no catalog entry can collide with `''`.
_UNASSIGNED_SECTION = 'unassigned'

# What both layouts call a player whose stream Snapserver did not name.
_UNASSIGNED_LABEL = 'Unassigned'
_UNASSIGNED_MESSAGE = 'Snapserver has not said what this player is listening to.'


# What the chip reads for a flow that exists but raised when queried.
_SETUP_REQUIRED = 'setup required'

# The catalog's only post-enable configuration flow, keyed on `SourceDefinition.setup`. Inlined
# rather than tabled: one discriminator, one pair of `_plex` handlers.
_SETUP_FLOW = 'plex_claim'


def _close_dialog(page: 'Page') -> None:
    """Clears ``_dialog_open`` and replays deferred tab refreshes if any were queued."""
    page._dialog_open = False
    tabs = page._deferred_tabs
    if not tabs:
        return
    page._deferred_tabs = set()
    if 'sources' in tabs:
        page._build_sources_tab.refresh()
    if 'settings' in tabs:
        page._build_settings_tab.refresh()
    if 'players' in tabs:
        page._build_players_tab.refresh()


async def render(page: 'Page') -> None:
    """Renders the main dashboard page.

    The Players tab reads from the broker cache, so no async I/O is needed for the initial build.
    The broker's dirty callback drives subsequent rebuilds.
    """
    components.header.render(audera.NAME.capitalize())

    with ui.tabs().classes('w-full') as tabs:
        players_tab = ui.tab(_PLAYERS_TAB)
        sources_tab = ui.tab(_SOURCES_TAB)
        settings_tab = ui.tab(_SETTINGS_TAB)

    with ui.tab_panels(tabs, value=players_tab).classes('w-full'):
        with ui.tab_panel(players_tab):
            page._build_players_tab()  # type: ignore
        with ui.tab_panel(sources_tab):
            page._build_sources_tab()  # type: ignore
        with ui.tab_panel(settings_tab):
            page._build_settings_tab()  # type: ignore

    entered_sources = False

    def _on_tab_change(e) -> None:
        nonlocal entered_sources
        if e.value != _SOURCES_TAB:
            return
        if not entered_sources:
            entered_sources = True
            return
        if page._claim_in_flight:
            return
        page._build_sources_tab.refresh()

    tabs.on_value_change(_on_tab_change)


def adopt_running_sources(page: 'Page') -> None:
    """Seeds the enabled source set from the streams Snapserver is serving, once, when nothing has
    been recorded yet.

    Called once from `Page.load()` rather than from a render path.

    `dal.sources.get_enabled()` degrades an absent `sources.json` to `DEFAULT_ENABLED`, which is
    only correct for a flashed device. An in-place upgrade inherits a conf naming sources this code
    never recorded, and since the enabled set is the only input to the conf rewrite, the first
    toggle of any source would truncate those streams out of `/etc/snapserver.conf` without the
    disable path's reassignment safeguard firing.

    Writes only on a successful, non-empty intersection with `CATALOG`. An unreachable Snapserver,
    or one naming no catalogued stream, leaves the file absent so the next load retries.
    `dal.sources.adopt` re-checks both preconditions.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    """
    if sources_dal.is_recorded():
        return
    status = _stream_status(page)
    sources_dal.adopt([source.id for source in CATALOG if source.id in status])


def build_sources_tab(page: 'Page') -> None:
    """Renders the Sources tab: one card per catalogued audio source, with a live status chip and
    an enable/disable toggle.

    Called by `Page._build_sources_tab`, the `@ui.refreshable` method that owns the refresh
    target (so refreshes are keyed per `Page` instance).

    Not polled: `render()`'s 10 s timer refreshes the Players tab only, since polling here would
    cancel the claim flow's own timers every tick. The chips are refreshed at load, after each
    toggle, and at claim completion.
    """
    enabled = _enabled_ids()
    status = _stream_status(page)
    for source in CATALOG:
        _build_source_card(page, source, enabled, status)


def _enabled_ids() -> list[str]:
    """Returns the enabled source ids that name a catalog entry, in catalog order.

    Intersected with `CATALOG` at the point of use because `dal.sources` stores whatever was
    toggled and does not filter: an id left behind by a removed catalog entry renders no card and
    must not count toward the "at least one enabled" guard.
    """
    stored = set(sources_dal.get_enabled())
    return [source.id for source in CATALOG if source.id in stored]


def _remaining_ids(source_id: str) -> list[str]:
    """Returns the enabled source ids that would survive disabling `source_id`.

    Parameters
    ----------
    source_id: `str`
        The source id about to be disabled.
    """
    return [id for id in _enabled_ids() if id != source_id]


def _stream_status(page: 'Page') -> dict[str, str]:
    """Returns Snapserver's own status word per stream id, or `{}` when it is unreachable.

    Prefers the broker cache when the broker is running. Falls back to a direct Snapserver call for
    callers that run before the broker starts (``adopt_running_sources``).

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    """
    try:
        return broker.get().cache.stream_status
    except Exception:
        pass
    try:
        return _snapserver(page.settings).get_stream_status()
    except Exception:
        return {}


def _await_snapserver(page: 'Page') -> None:
    """Blocks until a restarted Snapserver answers `Server.GetStatus` again, or the deadline passes.

    `systemctl restart snapserver` returns once systemd has forked the process, not once it is
    serving, so the JSON-RPC socket refuses connections for seconds afterwards and a refresh inside
    that window renders every enabled source `not running`.

    A non-empty status is the readiness signal, which is sound because of `CATALOG`'s rule 2: the
    conf this restart just loaded always names at least one stream, so `{}` means unreachable.

    Returns rather than raises on timeout, since `not running` is then the correct chip.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    """
    deadline = time.monotonic() + _READY_TIMEOUT
    while True:
        try:
            if _snapserver(page.settings).get_stream_status():
                return
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return
        time.sleep(_READY_INTERVAL)


def _attachable(source_id: str, status: dict[str, str]) -> bool:
    """Returns whether a player's group may be pointed at `source_id`.

    A source is attachable when Snapserver names it and its status word is not `'disabled'`.
    `'playing'` and `'idle'` are both attachable. Absence and Snapserver's own `'disabled'` both
    mean its backend is not feeding the stream, and an assignment made there produces silence with
    no error.

    Fails open: a word this build does not know stays attachable, since refusing a live source
    reads as a broken control.

    Parameters
    ----------
    source_id: `str`
        The source id being offered as a destination.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    return status.get(source_id, '') not in ('', 'disabled')


def _label(source_id: str) -> str:
    """Returns a source id's display label, falling back to the id itself.

    Parameters
    ----------
    source_id: `str`
        The source id.
    """
    for source in CATALOG:
        if source.id == source_id:
            return source.label
    return source_id


def _setup_state(source: SourceDefinition) -> str | None:
    """Returns `source`'s pending-setup chip label, or `None` when nothing is pending.

    The only seam through which the render path queries a setup flow. Reached only for enabled
    sources, so a device whose only enabled source is AirPlay makes no systemd calls to render this
    tab.

    Parameters
    ----------
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being rendered.
    """
    if not source.setup:
        return None
    if sources_dal.get_setup(source.id).get('complete'):
        # A recorded completion outranks the flow, whose probes read what the device does now. A
        # reprovision stops the source's units, which makes every live probe report the setup as
        # undone. The record is discarded when the source is disabled.
        return None
    if source.setup != _SETUP_FLOW:
        # Fail open: this build has no flow for the discriminator, so the card shows the stream's
        # real status rather than staying in `setup required`.
        return None
    try:
        return _plex.setup_state()
    except Exception:
        # Fail closed: a flow that raised reports nothing about whether it is done.
        return _SETUP_REQUIRED


def _source_status(
    source: SourceDefinition,
    enabled: list[str],
    status: dict[str, str],
    pending: str | None,
) -> tuple[str, str]:
    """Returns the status chip's `(text, classes)` for one source.

    Parameters
    ----------
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being rendered.
    enabled: `list[str]`
        The enabled source ids.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    pending: `str | None`
        The source's pending-setup label, or `None` when nothing is pending. `_setup_state(source)`,
        resolved by the caller so the chip and the panel below it agree within a render.
    """
    if source.id not in enabled:
        return 'disabled', 'text-sm text-gray-500'
    if pending:
        return pending, 'text-sm text-amber-500'
    if source.id in status:
        # Snapserver's own vocabulary: `'playing'`, `'idle'`, or `'disabled'`, the last meaning its
        # backend process is not feeding the stream. That is a different `'disabled'` from the one
        # above, which means the operator turned the source off.
        state = status[source.id]
        return state, 'text-sm text-green-500' if state == 'playing' else 'text-sm text-gray-500'
    return 'not running', 'text-sm text-red-500'


def _build_source_card(
    page: 'Page',
    source: SourceDefinition,
    enabled: list[str],
    status: dict[str, str],
) -> None:
    """Renders one audio source's card.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being rendered.
    enabled: `list[str]`
        The enabled source ids.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    is_enabled = source.id in enabled
    pending = _setup_state(source) if is_enabled else None
    text, classes = _source_status(source, enabled, status, pending)
    # The "at least one enabled" guard as an affordance: the last switch is disabled before the
    # click rather than refused afterwards. `_toggle_source` and `_disable_source` re-check it.
    is_last = is_enabled and len(enabled) == 1

    # Two markers: the per-source one addresses a single card, and the shared one lets a test
    # subtract the whole tab (`.not_within(marker='source-card')`).
    with ui.card().classes('w-full mb-2').mark(f'source-card source-card-{source.id}'):
        with ui.row().classes('items-center justify-between w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.label(source.label).classes('font-medium')
                ui.label(text).classes(classes).mark(f'source-status-{source.id}')
            with ui.row().classes('items-center gap-2'):
                spinner = ui.spinner(size='sm')
                spinner.set_visibility(False)
                switch = ui.switch(value=is_enabled).mark(f'source-toggle-{source.id}')
                if is_last:
                    switch.set_enabled(False)
                    switch.tooltip(_LAST_SOURCE_MESSAGE)

        ui.label(source.description).classes('text-sm text-gray-500')

        if is_enabled and source.setup == _SETUP_FLOW:
            _plex.build_setup_panel(page, pending)

    async def _on_change(e) -> None:
        # The claim-in-flight refusal below reverts the switch, which re-enters here; a change back
        # to the rendered state is never a click.
        if e.value == is_enabled:
            return
        if page._claim_in_flight:
            ui.notify(
                'Finish or cancel the PlexAmp setup before changing sources.',
                type='warning',
                position='top-right',
            )
            # Revert rather than refresh, because refreshing would delete the claim flow's
            # elements and cancel its timers.
            switch.set_value(is_enabled)
            return
        # The busy state is never restored; every terminal path below refreshes the tab, rebuilding
        # this card from the state that landed.
        switch.set_enabled(False)
        spinner.set_visibility(True)
        await _toggle_source(page, source, e.value)

    # Registered after construction rather than passed to `ui.switch(on_change=…)`: the handler
    # closes over `switch` and `spinner`, and post-construction registration keeps the initial
    # value from firing it.
    switch.on_value_change(_on_change)


async def _toggle_source(page: 'Page', source: SourceDefinition, enable: bool) -> None:
    """Routes a source toggle to the enable or disable choreography.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being toggled.
    enable: `bool`
        The switch's new value.
    """
    if enable:
        await _enable_source(page, source)
        return

    # Stops the disable dialog from opening with an empty destination list. It is racy against a
    # second browser tab, so `_disable_source_write` re-reads it inside the queue; only that
    # re-read enforces the invariant.
    if len(_remaining_ids(source.id)) == 0:
        ui.notify(_LAST_SOURCE_MESSAGE, type='warning', position='top-right')
        page._build_sources_tab.refresh()
        return

    players = await asyncio.to_thread(_attached_players, page, source.id)
    if not players:
        await _disable_source(page, source, None)
        return

    # Read here rather than in the dialog builder, which is synchronous. The dialog needs it to
    # withhold a destination Snapserver is not feeding, which would mis-route the listeners
    # silently.
    status = await asyncio.to_thread(_stream_status, page)
    _open_disable_dialog(page, source, players, _remaining_ids(source.id), status)


def _enable_source_write(source: SourceDefinition) -> None:
    """DAL write + toggle.apply, atomic in one callable through the command queue."""
    enabled = sources_dal.set_enabled(source.id, True)
    toggle.apply(source, True, enabled)


async def _enable_source(page: 'Page', source: SourceDefinition) -> None:
    """Enables a source: records the intent, re-renders the conf, starts its units, restarts Snapserver.

    The data-access layer goes first because the enabled set is the intent and everything
    `toggle.apply` writes is derived from it. The set it returns is passed through rather than read
    back, so the conf cannot be rendered from a set other than the one just recorded.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being enabled.
    """
    ui.notify(f'Enabling {source.label}. {_INTERRUPTION_MESSAGE}', type='warning', position='top-right')

    try:
        await commands.get().submit(_enable_source_write, source)
    except (CommandError, RuntimeError) as exc:
        if source.id in sources_dal.get_enabled():
            _notify_failure(f'{source.label} is enabled, but applying it failed', exc)
        else:
            _notify_failure(f'Could not enable {source.label}', exc)
        page._build_sources_tab.refresh()
        return

    await asyncio.to_thread(_await_snapserver, page)
    # Readiness used a direct Snapserver call; the Sources tab reads stream_status from the
    # broker cache. Reseed so the success refresh does not paint pre-restart chips.
    await broker.reseed()

    ui.notify(f'{source.label} enabled', type='positive', position='top-right')
    page._build_sources_tab.refresh()


def _disable_source_write(
    source: SourceDefinition,
    destination: str | None,
    settings: Settings,
) -> bool:
    """Re-check invariants, reassign groups, DAL write + toggle.apply, through the command queue."""
    enabled = _enabled_ids()
    if source.id not in enabled:
        return False
    if len(enabled) == 1:
        raise RuntimeError(_LAST_SOURCE_MESSAGE)

    if destination is not None:
        snap = _snapserver(settings)
        for group in snap.get_groups():
            if group.stream_id == source.id:
                snap.set_group_stream(group.id, destination)

    remaining = _record_disabled(source.id)
    toggle.apply(source, False, remaining)
    return True


async def _disable_source(page: 'Page', source: SourceDefinition, destination: str | None) -> None:
    """Disables a source: moves its listeners, records the intent, re-renders the conf, stops its units.

    In order: reassign listeners, record the intent, re-render the conf, `disable --now` the units,
    restart Snapserver. Reassignment is the only abort point, since after the conf is written the
    stream no longer exists to reassign anyone off; every step from there on rolls forward.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being disabled.
    destination: `str | None`
        The source id to move this stream's groups to, or `None` when nothing is listening.
    """
    enabled = _enabled_ids()
    if source.id not in enabled:
        page._build_sources_tab.refresh()
        return
    if len(enabled) == 1:
        ui.notify(_LAST_SOURCE_MESSAGE, type='warning', position='top-right')
        page._build_sources_tab.refresh()
        return

    ui.notify(f'Disabling {source.label}. {_INTERRUPTION_MESSAGE}', type='warning', position='top-right')

    try:
        did_work = await commands.get().submit(_disable_source_write, source, destination, page.settings)
    except (CommandError, RuntimeError) as exc:
        if source.id not in sources_dal.get_enabled():
            _notify_failure(f'{source.label} is disabled, but applying it failed', exc)
        else:
            _notify_failure(f'Could not disable {source.label}', exc)
        page._build_sources_tab.refresh()
        return

    if not did_work:
        page._build_sources_tab.refresh()
        return

    await asyncio.to_thread(_await_snapserver, page)
    await broker.reseed()

    ui.notify(f'{source.label} disabled', type='positive', position='top-right')
    page._build_sources_tab.refresh()


def _record_disabled(source_id: str) -> list[str]:
    """Records a source as disabled, discards its setup record, and returns the remaining ids.

    The record outranks the live probes while a source is enabled, so keeping it across a disable
    would let a re-enabled source render as set up without anything having checked. Both writes
    happen in one call, on the near side of the choreography's single abort point.

    Blocking, and called through `asyncio.to_thread`.

    Parameters
    ----------
    source_id: `str`
        The source id being disabled.
    """
    remaining = sources_dal.set_enabled(source_id, False)
    sources_dal.clear_setup(source_id)
    return remaining


def _attached_players(page: 'Page', source_id: str) -> list[Player]:
    """Returns the connected Snapcast clients currently listening to `source_id`.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source_id: `str`
        The source being disabled.
    """
    snap = _snapserver(page.settings)
    try:
        group_ids = {group.id for group in snap.get_groups() if group.stream_id == source_id}
        clients = snap.get_clients()
    except Exception:
        # An unreachable Snapserver has no listeners to strand, so the disable proceeds without
        # the dialog.
        return []
    return [client for client in clients if client.connected and client.group_id in group_ids]


def _open_disable_dialog(
    page: 'Page',
    source: SourceDefinition,
    players: list[Player],
    remaining: list[str],
    status: dict[str, str],
) -> None:
    """Asks where to move a source's listeners before disabling it.

    Only running survivors are offered, since a destination Snapserver is not feeding routes the
    listeners into silence. When none is running the dialog says so and the disable proceeds
    without an explicit reassignment; Snapserver then moves the groups to `default_source` at the
    next client connect.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    source: `audera.domains.sources.SourceDefinition`
        The catalog entry being disabled.
    players: `list[audera.models.player.Player]`
        The connected clients listening to the source.
    remaining: `list[str]`
        The source ids that survive the disable.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    page._dialog_open = True
    # Latched by whichever path closes the dialog first, so the `hide` the browser emits on a
    # programmatic close does not re-run the decision.
    state = {'handled': False}

    with ui.dialog() as dialog, ui.card().classes('w-96'):
        ui.label(f'Disable {source.label}').classes('font-medium text-lg mb-2')

        names = ', '.join(player.name for player in players)
        verb = 'is' if len(players) == 1 else 'are'
        ui.label(f'{names} {verb} listening to {source.label}.').classes('text-sm')

        live = [id for id in remaining if _attachable(id, status)]
        destination = None
        if live:
            ui.label('Move to').classes('text-xs text-gray-500 mt-2')
            destination = (
                ui.select(
                    # Maps id -> label and submits the id. The two differ for Spotify, so
                    # `set_group_stream(gid, 'Spotify Connect')` mis-routes silently.
                    {id: _label(id) for id in live},
                    # The destination Snapserver would pick on its own. Derived from the live
                    # subset, since a value absent from the options renders blank.
                    value=default_source(live),
                )
                .classes('w-full')
                .mark('disable-destination')
            )
        else:
            ui.label(_NO_LIVE_DESTINATION_MESSAGE).classes('text-sm text-amber-500 mt-2').mark('disable-no-destination')

        ui.label(_INTERRUPTION_MESSAGE).classes('text-xs text-gray-500 mt-2')

        def _dismiss():
            if state['handled']:
                return
            state['handled'] = True
            _close_dialog(page)
            page._build_sources_tab.refresh()

        with ui.row().classes('justify-between w-full mt-4'):

            def _on_cancel():
                # Closed first, then dismissed, so the `hide` this raises in the browser arrives
                # after `state['handled']` is latched and the refresh happens only once.
                dialog.close()
                _dismiss()

            async def _on_confirm():
                state['handled'] = True
                _close_dialog(page)
                dialog.close()
                await _disable_source(page, source, destination.value if destination is not None else None)

            ui.button('Cancel', on_click=_on_cancel).props('flat dense')
            (ui.button('Disable', on_click=_on_confirm).props('dense').mark('disable-confirm'))

    dialog.on('hide', _dismiss)
    dialog.open()


def _notify_failure(message: str, exc: Exception) -> None:
    """Notifies a failed host mutation, preferring a service's own reason.

    `getattr` rather than `exc.stderr` because `@platform.requires('dietpi')` raises
    `RuntimeError`, which has no `stderr`.

    Parameters
    ----------
    message: `str`
        What was being attempted.
    exc: `Exception`
        The exception raised.
    """
    detail = (getattr(exc, 'stderr', '') or str(exc)).strip()
    ui.notify(f'{message}: {detail}', type='negative', position='top-right')


class _Assignment(NamedTuple):
    """A `class` that represents one player's stream assignment, projected for its card.

    Built once per render by `_assignment`, which is pure, so a card never issues I/O of its own.

    Attributes
    ----------
    stream_id: `str`
        The stream the player's group is listening to, or `''` when Snapserver did not say.
    destinations: `dict[str, str]`
        The move destinations, mapping source id -> display label: the current stream first, then
        the enabled set in catalog order. A `dict` because a move renders the label and sends the
        id to `Group.SetStream`; the two differ (`Spotify` vs. `Spotify Connect`), and sending the
        label mis-routes with no error.
    siblings: `int`
        The other connected players sharing this player's group. Always `0` for anything Audera
        creates; non-zero only where Snapweb merged clients into one group.
    """

    stream_id: str
    destinations: dict[str, str]
    siblings: int


def _group_streams_from_hub() -> dict[str, str]:
    """Returns the stream id each Snapcast group is listening to, from the broker cache."""
    try:
        return {group.id: group.stream_id for group in broker.get().cache.groups}
    except Exception:
        return {}


def _assignment(
    client: Player,
    clients: list[Player],
    streams: dict[str, str],
    enabled: list[str],
) -> _Assignment:
    """Returns one player's `_Assignment`. Pure; every input is already fetched.

    Parameters
    ----------
    client: `audera.models.player.Player`
        The Snapcast client being rendered.
    clients: `list[audera.models.player.Player]`
        Every Snapcast client, from `get_clients()`.
    streams: `dict[str, str]`
        The stream id per group id, from `_group_streams`.
    enabled: `list[str]`
        The enabled source ids, from `_enabled_ids`.
    """
    stream_id = streams.get(client.group_id, '') if client.group_id else ''

    # The current stream leads, so a group parked on a stream outside the enabled set still has its
    # own value among the options. A `ui.select` whose value is absent from its options renders
    # blank, which reads as "unassigned".
    destinations = {stream_id: _label(stream_id)} if stream_id else {}
    for id in enabled:
        destinations.setdefault(id, _label(id))

    # Connected only, matching the tab's own contents, so the caption does not name a player that
    # appears nowhere on screen.
    siblings = sum(1 for other in clients if other.connected and other.id != client.id and other.group_id == client.group_id)
    return _Assignment(stream_id, destinations, siblings if client.group_id else 0)


def _stream_caption(siblings: int) -> str:
    """Returns the stream control's caption, naming the players a move would affect.

    Shared by both groupings so the wording cannot drift. `siblings` is non-zero only where Snapweb
    merged clients into one group, in which case moving one player moves all of them.

    Parameters
    ----------
    siblings: `int`
        The other connected players sharing this player's group.
    """
    if siblings == 0:
        return 'Stream'
    return f'Stream (shared with {siblings} other player{"" if siblings == 1 else "s"})'


def _stream_state(stream_id: str, status: dict[str, str]) -> tuple[str, str]:
    """Returns a stream header's status `(text, classes)`, or `('', '')` for the unassigned
    section.

    The last two rungs of the Sources chip ladder. Not shared with `_source_status`, which also
    answers "is it enabled" and "is setup done", neither of which this tab can act on.

    Parameters
    ----------
    stream_id: `str`
        The section's stream id, or `''` for the unassigned section.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    if not stream_id:
        # Nothing is running at unassigned, so there is no status word to report.
        return '', ''
    if stream_id in status:
        state = status[stream_id]
        return state, 'text-sm text-green-500' if state == 'playing' else 'text-sm text-gray-500'
    return 'not running', 'text-sm text-red-500'


def _stream_tint(source_id: str, status: dict[str, str]) -> str:
    """Returns the assignment chip's colour classes: a text colour and a 10 % tint of the same
    hue.

    `_stream_state`'s three rungs in the chip's own idiom, plus a fourth for the unassigned case,
    which only the by-player layout can render. The tint makes liveness readable down a stack of
    cards without a second word on every row.

    Spelled out rather than derived from `_stream_state`'s class string, which would couple the
    chip to the spelling of a colour token; `test_players_tab_chip_tint_tracks_the_status` holds
    the two in agreement.

    Parameters
    ----------
    source_id: `str`
        The stream the player's group is listening to, or `''` when Snapserver did not say.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    if not source_id:
        # Nothing is running at unassigned, and red would report a fault where there is none.
        return 'text-gray-500 bg-gray-500/10'
    if source_id not in status:
        return 'text-red-500 bg-red-500/10'
    if status[source_id] == 'playing':
        return 'text-green-500 bg-green-500/10'
    return 'text-gray-500 bg-gray-500/10'


def _stream_summary(source_id: str, status: dict[str, str]) -> str:
    """Returns the assignment chip's tooltip: the status word its tint stands for.

    The chip spends its one line of text on the stream's label, so the word behind the tint is
    reachable only from a tooltip.

    Parameters
    ----------
    source_id: `str`
        The stream the player's group is listening to, or `''` when Snapserver did not say.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    if not source_id:
        return _UNASSIGNED_MESSAGE
    text, _ = _stream_state(source_id, status)
    return f'{_label(source_id)} — {text}'


def _move_destinations(assignment: _Assignment) -> dict[str, str]:
    """Returns a move menu's rows: every destination but the one the player is already on.

    The current stream is omitted, since the section header or the chip doing the opening already
    names it.

    Parameters
    ----------
    assignment: `audera.ui.streamer.pages.index._Assignment`
        The client's stream assignment, from `_assignment`.
    """
    return {id: label for id, label in assignment.destinations.items() if id != assignment.stream_id}


def _move_refusal(client: Player, destinations: dict[str, str], status: dict[str, str]) -> str:
    """Returns why a move trigger must be disabled, or `''` when the move may be offered.

    Both triggers refuse on the same two grounds, so the grounds live here and only the rendering
    is per-layout.

    Parameters
    ----------
    client: `audera.models.player.Player`
        The Snapcast client whose group would be moved.
    destinations: `dict[str, str]`
        The menu's rows, from `_move_destinations`.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    if not client.group_id:
        # `set_group_stream('', …)` is an RPC with no target.
        return _NO_GROUP_MESSAGE
    if not any(_attachable(id, status) for id in destinations):
        # An attachable destination rather than any destination: a menu of nothing but greyed rows
        # offers no move.
        return _NO_DESTINATION_MESSAGE
    return ''


def _sections(
    connected_clients: list[Player],
    assignments: dict[str, _Assignment],
    enabled: list[str],
) -> dict[str, list[Player]]:
    """Returns the by-stream layout's sections, mapping stream id -> its connected players.

    Seeded from `enabled` so an empty stream keeps its header, then extended per player via
    `setdefault` so a group parked on a stream outside that set gets its own section. Dict
    insertion order is the rendering order: the enabled ids in catalog order, then any other stream
    a group is parked on, then `''`.

    Parameters
    ----------
    connected_clients: `list[audera.models.player.Player]`
        The connected Snapcast clients.
    assignments: `dict[str, audera.ui.streamer.pages.index._Assignment]`
        Each client's stream assignment, keyed by client id.
    enabled: `list[str]`
        The enabled source ids, from `_enabled_ids`.
    """
    sections: dict[str, list[Player]] = {id: [] for id in enabled}
    for client in connected_clients:
        sections.setdefault(assignments[client.id].stream_id, []).append(client)
    return sections


def build_players_tab(page: 'Page') -> None:
    """Renders the Players tab from the broker cache. Synchronous — no I/O.

    Called by ``Page._build_players_tab``, the ``@ui.refreshable`` method that owns the refresh
    target (so refreshes are keyed per ``Page`` instance).

    All data comes from ``broker.get().cache``. The broker's dirty callback drives rebuilds when the
    cache changes.
    """
    try:
        state = broker.get().cache
    except Exception:
        ui.label('No Snapcast clients found.').classes('text-gray-500')
        return

    clients = state.clients
    connected_clients = [c for c in clients if c.connected]
    if not connected_clients:
        ui.label('No Snapcast clients found.').classes('text-gray-500')
        return

    streams = _group_streams_from_hub()
    status = state.stream_status
    volumes = {c.id: state.volumes.get(c.id) for c in connected_clients}

    FF_GROUPING_BY_STREAM = features.flag_enabled(page.settings, features.PLAYER_GROUPING_KEY, features.FF_GROUPING_BY_STREAM)
    enabled = _enabled_ids()
    assignments = {c.id: _assignment(c, clients, streams, enabled) for c in connected_clients}

    if not FF_GROUPING_BY_STREAM:
        for client in connected_clients:
            _build_player_card(page, client, assignments[client.id], status, volumes[client.id], by_stream=False)
        return

    for stream_id, members in _sections(connected_clients, assignments, enabled).items():
        _build_stream_section(page, stream_id, members, assignments, status, volumes)


def _build_stream_section(
    page: 'Page',
    stream_id: str,
    members: list[Player],
    assignments: dict[str, _Assignment],
    status: dict[str, str],
    volumes: dict[str, int | None],
) -> None:
    """Renders one stream's header and the cards of the players listening to it.

    Empty streams are shown rather than hidden, since an enabled source with nothing pointed at it
    is still a destination the move menu names.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    stream_id: `str`
        The section's stream id, or `''` for the unassigned section.
    members: `list[audera.models.player.Player]`
        The connected players listening to the stream.
    assignments: `dict[str, audera.ui.streamer.pages.index._Assignment]`
        Each client's stream assignment, keyed by client id.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    volumes: `dict[str, int]`
        Each client's CamillaDSP percent volume, keyed by client id, from `_volumes`. `None`
        where the daemon could not be read.
    """
    section_id = stream_id or _UNASSIGNED_SECTION
    with ui.column().classes('w-full gap-2 mb-4'):
        with ui.row().classes('items-center gap-3 w-full'):
            (
                ui.label(_label(stream_id) if stream_id else _UNASSIGNED_LABEL)
                .classes('font-medium')
                .mark(f'stream-header stream-header-{section_id}')
            )
            text, classes = _stream_state(stream_id, status)
            if text:
                ui.label(text).classes(classes).mark(f'stream-status-{section_id}')
            (
                ui.label(f'{len(members)} player{"" if len(members) == 1 else "s"}')
                .classes('text-sm text-gray-500')
                .mark(f'stream-count-{section_id}')
            )

        if not members:
            with ui.card().classes('w-full mb-2'):
                ui.label('No players assigned').classes('text-gray-500').mark(f'stream-empty-{section_id}')
            return

        for client in members:
            _build_player_card(page, client, assignments[client.id], status, volumes[client.id], by_stream=True)


def _build_player_card(
    page: 'Page',
    client: Player,
    assignment: _Assignment,
    status: dict[str, str],
    volume: int | None,
    by_stream: bool,
) -> None:
    """Renders one player's card, identical under both groupings but for its assignment
    affordance.

    `by_stream` is consulted at two points: the header row takes the move button, the card body
    takes the stream chip. Both open the same menu, and everything else is single-copy.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    client: `audera.models.player.Player`
        The Snapcast client being rendered.
    assignment: `audera.ui.streamer.pages.index._Assignment`
        The client's stream assignment, from `_assignment`.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`. Alongside `assignment`
        rather than inside it, because the assignment affordance needs the word itself to explain a
        destination it refuses.
    volume: `int`
        This client's CamillaDSP percent volume, from `_volumes`, seeding the slider. `None`
        where the daemon could not be read, which renders the slider disabled and unlabelled.
    by_stream: `bool`
        Whether the card sits under a stream header. The chip and the move button are two triggers
        for one menu, and never both at once.
    """
    # Named after the feature-flag constant so flag-gated UI is obvious to the reader.
    FF_DISABLED_VS_MUTE = features.flag_enabled(page.settings, features.PLAYER_SELECTION_KEY, features.FF_DISABLED_VS_MUTE)
    minimized = FF_DISABLED_VS_MUTE and client.muted

    # Two markers: the shared one lets a test count the whole tab, the per-client one addresses a
    # single card.
    with ui.card().classes('w-full mb-2').mark(f'player-card player-card-{client.id}'):
        mute_cb = None
        with ui.row().classes('items-center justify-between w-full'):
            with ui.row().classes('items-center gap-2'):
                if FF_DISABLED_VS_MUTE:
                    # Marked so a test can address this switch alone: the Sources tab renders one
                    # switch per catalogued source, and `user.find(kind=ui.switch)` clicks every
                    # match.
                    ui.switch(value=not client.muted, on_change=lambda e: _on_enabled_change(page, client, e.value)).mark(
                        f'player-toggle-{client.id}'
                    )
                # A disabled player's name is grayed out to reinforce the "disabled" state; its
                # controls stay live since muting is an audio-output decision, not a configuration
                # lock — the player still needs to be configurable for when it's re-enabled.
                name_label = ui.label(client.name).classes('font-medium')
                if minimized:
                    name_label.classes('text-gray-400')
            with ui.row().classes('items-center gap-2'):
                if not FF_DISABLED_VS_MUTE:
                    mute_cb = ui.checkbox(
                        'Mute', value=client.muted, on_change=lambda e: _on_mute_change(page, client.id, e.value)
                    )
                # DSP first (left), then settings (right), both plain material icons. An icon reads
                # as clickable on its own (like the gear), and dropping the bordered circle avoids
                # the sub-pixel oval it rendered at some viewport widths. As two icon buttons with
                # identical props they are the same size by construction — no pixel pinning needed.
                # `sym_o_airwave` (a Material Symbol — hence the `sym_o_` prefix) reads as sound
                # waves, fitting the DSP page.
                # Two markers: the shared one addresses the control on every card, the per-client
                # one a single card. `UserInteraction.click()` fires on every match, and
                # `Element.mark()` splits on whitespace while `ElementFilter` matches any one
                # marker.
                if by_stream:
                    _build_move_button(page, client, assignment, status)
                # DSP and settings stay live on a disabled player: muting is an audio-output
                # decision, not a configuration lock, and the player still needs to be
                # configurable for when it's re-enabled.
                (
                    ui.button(on_click=lambda: ui.navigate.to(f'/player/{client.id}/dsp'))
                    .props('icon=sym_o_airwave flat dense round size=sm')
                    .mark(f'player-dsp player-dsp-{client.id}')
                )
                (
                    ui.button(on_click=lambda: _open_settings_dialog(page, client))
                    .props('icon=settings flat dense round size=sm')
                    .mark(f'player-settings player-settings-{client.id}')
                )

        # Stream reassignment stays available on a disabled card; only the volume slider row
        # (meaningless for a muted player) is skipped below.
        if not by_stream:
            _build_stream_chip(page, client, assignment, status)

        if minimized:
            return

        with ui.row(wrap=False).classes('items-center gap-4 w-full'):
            slider = _build_volume_controls(page, client.id, volume, client.host)
            # Not bound when the volume is unknown: `bind_enabled_from` would re-enable the slider
            # as soon as the player reads unmuted, undoing the `set_enabled(False)` that
            # `_build_volume_controls` applied.
            if mute_cb is not None and volume is not None:
                slider.bind_enabled_from(mute_cb, 'value', backward=lambda v: not v)


def _build_stream_chip(page: 'Page', client: Player, assignment: _Assignment, status: dict[str, str]) -> None:
    """Renders the `Stream ( AirPlay 2 ⌄ )` row, the by-player grouping's assignment affordance.

    Rendered unconditionally (unlike the volume slider row below it), so stream reassignment
    stays available on a player the operator switched off.

    The chip opens the same menu the by-stream layout opens rather than a `ui.select` of its own,
    since a select over a `dict[id, label]` cannot grey a single option: it either offers a dead
    destination or hides it. The chip's tint carries the current stream's liveness and its tooltip
    states it in words.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    client: `audera.models.player.Player`
        The Snapcast client being rendered.
    assignment: `audera.ui.streamer.pages.index._Assignment`
        The client's stream assignment, from `_assignment`.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    tint = _stream_tint(assignment.stream_id, status)
    refusal = _move_refusal(client, _move_destinations(assignment), status)

    async def _on_move(source_id: str) -> None:
        # By player the card does not move, so the tab is not re-laid-out: a refresh would reseed
        # every volume slider from CamillaDSP and cancel a live drag on another card. The chip
        # repaints itself instead, and only on success, since a failure has already refreshed the
        # tab and deleted these elements.
        nonlocal tint
        if not await _on_stream_change(page, client, source_id, refresh=False):
            return
        text.set_text(_label(source_id))
        moved = _stream_tint(source_id, status)
        # Removed by name rather than replaced wholesale, so the chip's shape classes survive.
        chip.classes(remove=tint, add=moved)
        tint = moved
        tip.set_text(_stream_summary(source_id, status))

    with ui.row(wrap=False).classes('items-center gap-4 w-full'):
        (
            ui.label(_stream_caption(assignment.siblings))
            .classes('text-xs text-gray-500 shrink-0 whitespace-nowrap')
            .mark(f'player-stream-label-{client.id}')
        )
        # A `ui.button` rather than a bare `div`, so the refusal below can use `set_enabled(False)`
        # rather than a hand-rolled pointer-events class. `color=None` because the default
        # `'primary'` renders as Quasar's `text-primary`, which sits on the same element as the
        # tint's text colour at equal specificity and wins on stylesheet order.
        chip = (
            ui.button(color=None)
            .props('flat dense no-caps')
            .classes(f'rounded-full px-3 py-1 {tint}')
            .mark(f'player-stream player-stream-{client.id}')
        )
        with chip:
            with ui.row(wrap=False).classes('items-center gap-1'):
                text = (
                    ui.label(_label(assignment.stream_id) if assignment.stream_id else _UNASSIGNED_LABEL)
                    .classes('text-sm')
                    .mark(f'player-stream-value-{client.id}')
                )
                ui.icon('expand_more').classes('text-base')
            # Constructed rather than `chip.tooltip(…)`, which appends another tooltip on every
            # call and so cannot be updated in place.
            tip = ui.tooltip(refusal or _stream_summary(assignment.stream_id, status))
            _build_move_menu(page, client, assignment, status, _on_move)

    if refusal:
        chip.set_enabled(False)


def _build_move_button(
    page: 'Page',
    client: Player,
    assignment: _Assignment,
    status: dict[str, str],
) -> None:
    """Renders the move button, the by-stream grouping's assignment affordance.

    A header-row button, beside its DSP and settings neighbours; a switched-off player still
    appears under its stream header and keeps its move button live, since muting is an
    audio-output decision, not a configuration lock. It is disabled only on `_move_refusal`'s
    grounds (destination validity), never on the player's disabled state.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    client: `audera.models.player.Player`
        The Snapcast client being rendered.
    assignment: `audera.ui.streamer.pages.index._Assignment`
        The client's stream assignment, from `_assignment`.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    """
    with ui.button().props('icon=swap_horiz flat dense round size=sm').mark(f'player-move player-move-{client.id}') as move_btn:
        # By stream a card's position is its assignment, so a move that did not re-lay-out would
        # leave it under the wrong header for up to 10 s.
        _build_move_menu(page, client, assignment, status, lambda id: _on_stream_change(page, client, id, refresh=True))

    refusal = _move_refusal(client, _move_destinations(assignment), status)
    if refusal:
        move_btn.set_enabled(False)
        move_btn.tooltip(refusal)


def _build_move_menu(
    page: 'Page',
    client: Player,
    assignment: _Assignment,
    status: dict[str, str],
    on_move: Callable[[str], object],
) -> None:
    """Renders the move menu, inside whichever element opens it.

    One menu for both groupings, so their destinations, their wording, and their poll latch cannot
    drift. No confirmation step, since the move is a single live RPC and is reversible by another.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    client: `audera.models.player.Player`
        The Snapcast client whose group the menu would move.
    assignment: `audera.ui.streamer.pages.index._Assignment`
        The client's stream assignment, from `_assignment`.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    on_move: `Callable[[str], object]`
        What a row does with the destination it was clicked for. Awaited by NiceGUI's own event
        dispatch, so a coroutine function belongs here.
    """
    with ui.menu() as menu:
        # `ui.label` rather than `ui.item`: the caption is not clickable, and `ui.item` inside a
        # menu reads as clickable.
        ui.label(_stream_caption(assignment.siblings)).classes('px-4 py-2 text-xs text-gray-500')
        for id, label in _move_destinations(assignment).items():
            _build_move_menu_item(client, id, label, status, on_move)

    # The menu's own open state, so the 10 s poll cannot destroy an open menu mid-interaction. One
    # event covers both open and close. Every path that refreshes must clear the flag first: left
    # latched by an element the refresh deleted, it freezes the poll for the life of the page.
    def _on_menu_change(e):
        if e.value:
            page._dialog_open = True
        else:
            _close_dialog(page)

    menu.on_value_change(_on_menu_change)


def _build_move_menu_item(
    client: Player,
    source_id: str,
    label: str,
    status: dict[str, str],
    on_move: Callable[[str], object],
) -> None:
    """Renders one destination row of a move menu.

    A source Snapserver is not feeding is rendered disabled beside its own status word rather than
    dropped, so a row reading `not running` states why it cannot be picked. The row carries no
    click handler, so the refusal does not rest on `set_enabled(False)` being honoured.

    Parameters
    ----------
    client: `audera.models.player.Player`
        The Snapcast client whose group the row would move.
    source_id: `str`
        The destination source id.
    label: `str`
        The destination's display label.
    status: `dict[str, str]`
        Snapserver's status word per stream id, from `_stream_status`.
    on_move: `Callable[[str], object]`
        What the row does with `source_id` when clicked, from `_build_move_menu`.
    """
    if _attachable(source_id, status):
        ui.menu_item(label, on_click=lambda: on_move(source_id)).mark(f'player-move-{client.id}-{source_id}')
        return

    with ui.menu_item().mark(f'player-move-{client.id}-{source_id}') as item:
        with ui.row(wrap=False).classes('items-center justify-between gap-4 w-full'):
            ui.label(label)
            text, classes = _stream_state(source_id, status)
            ui.label(text).classes(classes).mark(f'player-move-status-{client.id}-{source_id}')
    item.set_enabled(False)


async def _on_stream_change(page: 'Page', client: Player, stream_id: str, refresh: bool) -> bool:
    """Moves a player's group onto `stream_id`, and returns whether the move landed.

    Snapcast owns the assignment, persisting it in its own `server.json`, so this writes through to
    Snapserver and Audera keeps no replica.

    Parameters
    ----------
    page: `audera.ui.streamer.pages.Page`
        An instance of the streamer dashboard app.
    client: `audera.models.player.Player`
        The Snapcast client whose group is being moved.
    stream_id: `str`
        The stream to move the group onto.
    refresh: `bool`
        Whether to re-lay-out the tab afterwards, decided by the caller per grouping. By stream a
        card's position is its assignment, so it must re-render; by player the card stays put and
        repaints its own chip, since a refresh would reseed every volume slider from CamillaDSP and
        cancel a live drag on a different card.

    Returns
    -------
    `bool`
        Whether the move landed. `False` also means the tab has already been refreshed, so a caller
        that repaints in place must not touch its own elements afterwards.
    """
    _close_dialog(page)
    try:
        await commands.get().submit(_snapserver(page.settings).set_group_stream, client.group_id, stream_id)
    except CommandError as exc:
        _notify_failure(f'Could not move {client.name}', exc)
        page._build_players_tab.refresh()
        return False

    ui.notify(f'{client.name} moved to {_label(stream_id)}', type='positive', position='top-right')
    if refresh:
        page._build_players_tab.refresh()
    return True


async def _on_mute_change(page: 'Page', client_id: str, muted: bool) -> None:
    """Handles the Mute checkbox in the card header for the default Player Selection experience.

    Does not refresh the Players tab afterward, so the volume slider keeps its live
    drag state — see `_reset_snap_volume` for the same rationale.
    """
    try:
        await commands.get().submit(_snapserver(page.settings).set_client_volume, client_id, 100, muted=muted)
    except CommandError:
        ui.notify('Could not update mute state', type='negative', position='top-right')


async def _on_enabled_change(page: 'Page', client, enabled: bool) -> None:
    """Handles the 'disabled' Player Selection experience's enable/disable switch.

    Toggling off mutes the Snapcast client (the minimized-card state is derived from
    `client.muted` on the next render); toggling on unmutes it.
    """
    try:
        await commands.get().submit(_snapserver(page.settings).set_client_volume, client.id, 100, muted=not enabled)
    except CommandError:
        ui.notify('Could not update player state', type='negative', position='top-right')
    page._build_players_tab.refresh()


def _open_settings_dialog(page: 'Page', client) -> None:
    """Opens a settings popup for renaming, latency, and Snapcast volume reset."""
    page._dialog_open = True

    with ui.dialog() as dialog, ui.card().classes('w-96'):
        ui.label('Settings').classes('font-medium text-lg mb-2')

        name_input = ui.input('Name', value=client.name).classes('w-full')
        latency_input = (
            ui.number('Latency (ms)', value=client.latency_ms, min=-500, max=500, step=1)
            .classes('w-full')
            .props('hint="Adds playback delay."')
        )

        # Snapcast volume is a sidecar kept at 100/0; CamillaDSP controls actual loudness.
        snap_vol = client.volume
        with ui.row().classes('w-full items-start justify-between mt-2'):
            with ui.column().classes('gap-0'):
                ui.label('Snapcast Volume').classes('text-xs')
                current_vol_label = ui.label(f'Current Volume {snap_vol}%').classes('text-xs text-gray-500')
            ui.button('Reset', on_click=lambda c=client, lbl=current_vol_label: _reset_snap_volume(page, c, lbl)).props('dense')

        ui.separator().classes('mt-4 mb-2')
        # No group id: it is an opaque uuid that changes over time, and the stream it identified is
        # already shown on the card.
        with ui.column().classes('text-xs text-gray-500 gap-1'):
            ui.label(f'ID      {client.id}')
            ui.label(f'Host    {client.host}')

        with ui.row().classes('justify-between w-full mt-4'):

            def _on_cancel():
                _close_dialog(page)
                dialog.close()

            async def _on_save(c=client, ni=name_input, li=latency_input):
                snap = _snapserver(page.settings)
                try:
                    if ni.value and ni.value != c.name:
                        await commands.get().submit(snap.set_client_name, c.id, ni.value)
                        ui.notify(f'Renamed to "{ni.value}"', type='positive', position='top-right')
                    if li.value is not None and int(li.value) != c.latency_ms:
                        await commands.get().submit(snap.set_client_latency, c.id, int(li.value))
                        ui.notify(f'Latency set to {int(li.value)} ms', type='positive', position='top-right')
                except CommandError as exc:
                    _notify_failure('Save failed', exc)

                _close_dialog(page)
                dialog.close()
                page._build_players_tab.refresh()

            ui.button('Cancel', on_click=_on_cancel).props('flat dense')
            ui.button('Save', on_click=_on_save).props('dense')

    dialog.on('hide', lambda: _close_dialog(page))
    dialog.open()


async def _reset_snap_volume(page: 'Page', client, vol_label=None) -> None:
    """Resets the Snapcast client volume to 100% / unmuted.

    If vol_label is provided (from the settings dialog), its text is updated to
    reflect the new value. The players tab is *not* refreshed so that the CamillaDSP
    volume sliders retain their current visual state.
    """
    try:
        await commands.get().submit(_snapserver(page.settings).set_client_volume, client.id, 100, muted=False)
    except CommandError as exc:
        _notify_failure('Could not reset Snapcast volume', exc)
        return
    if vol_label is not None:
        vol_label.set_text('Current Volume 100%')
    ui.notify('Snapcast volume reset to 100%', type='positive', position='top-right')


def _apply_volume(settings: Settings, camilla, client_id: str, percent: int) -> None:
    """Writes one player's volume through the triad: CamillaDSP (the real loudness), the volume
    DAL, and the Snapcast 0/100 mute sidecar. The slider and Save/Restore share this path so the
    three writes never drift.
    """
    camilla.set_percent_volume(percent)
    volume_dal.set(client_id, percent)
    muted = percent <= 0
    _snapserver(settings).set_client_volume(client_id, 0 if muted else 100, muted=muted)


def _build_volume_controls(
    page: 'Page',
    client_id: str,
    initial_volume: float | None,
    client_host: str = '',
) -> ui.slider:
    """Renders a volume icon, slider, and live value label (routed through CamillaDSP).

    Volume is owned by the CamillaDSP daemon, which persists it durably via its
    ``--statefile``; the slider seeds from the broker cache and writes through CamillaDSP
    via ``update:model-value`` — a Quasar event that fires only on user interaction, not
    on programmatic ``set_value()``, so a broker push cannot echo back to the device.

    The slider's value is bound from ``broker.get().cache.volumes[client_id]`` via NiceGUI's
    binding system (100 ms propagation). Every pushed value is step-aligned via
    ``int(round(…))`` so Quasar does not snap the slider and emit a phantom
    ``update:model-value``.

    Returns the ``ui.slider`` element so the caller can bind its enabled state to the
    Mute checkbox built alongside it in the card header.
    """
    camilla = _camilladsp(client_host) if client_host else _camilladsp('localhost')
    FF_VOLUME_PERC_OR_DB = features.flag_enabled(page.settings, features.VOLUME_KEY, features.FF_VOLUME_PERC_OR_DB)

    async def _persist_and_sync(e) -> None:
        percent = int(e.args)
        try:
            await commands.get().submit(
                _apply_volume, page.settings, camilla, client_id, percent, coalesce_key=('volume', client_id)
            )
        except CommandError:
            pass

    unknown = initial_volume is None

    ui.icon('volume_off' if unknown else 'volume_up').classes('text-gray-400')
    slider = (
        ui.slider(min=0, max=100, step=1, value=0 if unknown else int(round(initial_volume)))
        .classes('grow')
        .mark(f'player-volume player-volume-{client_id}')
    )
    slider.on('update:model-value', _persist_and_sync)
    if unknown:
        slider.set_enabled(False)

    def _step_aligned(vol):
        if vol is None:
            return 0
        return int(round(vol))

    try:
        h = broker.get()
        slider.bind_value_from(h.cache.volumes, client_id, backward=_step_aligned)
    except Exception:
        pass

    value_label = ui.label().classes('text-xs text-gray-500 shrink-0 whitespace-nowrap text-right w-16')

    def _text(value: float) -> str:
        if unknown:
            return '—'
        if FF_VOLUME_PERC_OR_DB:
            return f'{camilla.percent_to_db(value):.1f} dB'
        return f'{int(value)}%'

    value_label.bind_text_from(slider, 'value', backward=_text)

    return slider


def _at_reference() -> bool:
    """Whether every connected player currently sits at its recorded reference volume.

    ``False`` when no balance is saved, when no player is connected, or when any connected player
    is missing from the balance or off its recorded percent.
    """
    if not balance_dal.exists():
        return False
    try:
        ref = balance_dal.get().volumes
    except CommandError:
        return False
    cache = broker.get().cache
    connected = [player for player in cache.clients if player.connected]
    if not connected:
        return False
    return all(player.id in ref and cache.volumes.get(player.id) == ref[player.id] for player in connected)


def build_settings_tab(page: 'Page') -> None:
    """Renders the Settings tab — a reference-balance section, then one single-select button group
    per registered UX feature."""
    ui.label('Reference balance').classes('text-lg font-medium mb-2')
    ui.label('Save and restore the current volume balance across all connected players.').classes('text-sm text-gray-500 mb-2')
    # Indicator left, Save/Restore right, on one fixed-height row so the buttons stay put whether
    # or not the indicator is lit.
    with ui.row().classes('mb-4 w-full items-center justify-between h-9'):
        with ui.row().classes('gap-1 items-center').mark('reference-status'):
            if _at_reference():
                ui.icon('circle').classes('text-green-500 text-xs')
                ui.label('Listening at reference').classes('text-sm text-gray-500')
        with ui.row().classes('gap-2'):
            ui.button('Save', on_click=lambda: _on_save_reference_balance(page)).mark('save-reference')
            restore = ui.button('Restore', on_click=lambda: _on_restore_reference_balance(page)).mark('restore-reference')
            restore.set_enabled(balance_dal.exists())

    ui.label('Features').classes('text-lg font-medium mb-2')
    for feature in features.FEATURES:
        ui.label(feature.label).classes('text-sm text-gray-500')
        ui.toggle(
            {option.value: option.label for option in feature.options},
            value=features.selected(page.settings, feature.key),
            on_change=lambda e, key=feature.key: _on_feature_change(page, key, e.value),
        ).classes('mb-4')


async def _on_feature_change(page: 'Page', key: str, value: str) -> None:
    """Persists a feature-flag selection and refreshes the Players tab to reflect it."""
    updated = page.settings.model_copy(deep=True)
    updated.features[key] = value
    try:
        await commands.get().submit(settings_dal.save, updated)
    except CommandError:
        ui.notify('Could not save settings', type='negative', position='top-right')
        page._build_players_tab.refresh()
        return
    page.settings = updated
    page._build_players_tab.refresh()


async def _on_save_reference_balance(page: 'Page') -> None:
    """Snapshots the current per-player volume balance and persists it as the reference balance."""
    volumes = {player_id: percent for player_id, percent in broker.get().cache.volumes.items() if percent is not None}
    ref = ReferenceBalance(volumes=volumes)
    try:
        await commands.get().submit(balance_dal.save, ref)
    except CommandError:
        ui.notify('Could not save reference balance', type='negative', position='top-right')
        return
    ui.notify('Saved reference balance', type='positive', position='top-right')
    page._build_settings_tab.refresh()


async def _on_restore_reference_balance(page: 'Page') -> None:
    """Re-applies the saved reference balance to every connected player it names, skipping the rest."""
    try:
        ref = await asyncio.to_thread(balance_dal.get)
    except CommandError:
        ui.notify('Could not read reference balance', type='negative', position='top-right')
        return

    connected = [player for player in broker.get().cache.clients if player.connected]
    restored = 0
    for player in connected:
        percent = ref.volumes.get(player.id)
        if percent is None:
            continue
        try:
            await commands.get().submit(
                _apply_volume,
                page.settings,
                _camilladsp(player.host),
                player.id,
                percent,
                coalesce_key=('volume', player.id),
            )
        except CommandError:
            continue
        restored += 1

    page._build_players_tab.refresh()
    ui.notify(
        f'Restored balance for {restored} player{"" if restored == 1 else "s"}',
        type='positive',
        position='top-right',
    )
