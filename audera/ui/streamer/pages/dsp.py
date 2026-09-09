"""Remote audio device parametric-EQ editor page"""

import asyncio
import uuid
from typing import TYPE_CHECKING, Literal, get_args

from nicegui import ui

import audera
from audera.dal import dsp as dsp_dal
from audera.dal import presets as presets_dal
from audera.domains.dsp import apply_pipeline, auto_preamp_db, clone_bands, format_rew, loudness_preset, parse_rew
from audera.errors import CommandError
from audera.models.dsp import PASS_TYPES, Band, DSPConfig, Preset
from audera.ui import components, features
from audera.ui.streamer import commands
from audera.ui.streamer.pages._clients import _camilladsp, _snapserver

if TYPE_CHECKING:
    from audera.ui.streamer.pages import Page

# Derived from the model literal so the editor's type choices can never drift from
# `audera.models.dsp.Band`. Pass filters carry no gain, so their gain field is disabled
# (their membership is tested against the shared `PASS_TYPES` taxonomy).
_BAND_TYPES = list(get_args(Band.model_fields['type'].annotation))


def _band_summary(band: Band) -> str:
    """One-line band description for compact rows; omits gain for pass filters."""
    parts = [band.type, f'{band.freq:.0f} Hz']
    if band.type not in PASS_TYPES:
        parts.append(f'{band.gain:.1f} dB')
    parts.append(f'Q {band.q:.3f}')
    return ' · '.join(parts)


async def render(page: 'Page', player_id: str) -> None:
    """Renders the full-page parametric-EQ editor for a single player.

    Bands are the source of truth; they are compiled to a live CamillaDSP pipeline
    on Save. Per-page edit state lives in closures rather than on `page`, which holds
    only what the tabs share: `state['saved']` mirrors the persisted config and
    `state['staged']` is the working copy that is compiled, validated, and pushed on
    Save. Scalar field edits mutate a band in place and only recompute the dirty
    indicator, derived pre-amp, and live response chart; structural changes
    (add/delete/type/preset/reset) refresh the band table.
    """
    components.header.render(audera.NAME.capitalize())
    components.layout.fill_viewport()  # page fills the viewport; the editor's `grow` column owns the scroll region

    snap = _snapserver(page.settings)
    try:
        # Off-thread so a slow/unreachable Snapserver can't freeze the single NiceGUI event
        # loop (and every other connected browser) for the client's open/read timeout.
        clients = await asyncio.to_thread(snap.get_clients)
    except Exception:
        clients = []
    live = next((client for client in clients if client.id == player_id), None)

    if live is None:
        with ui.column().classes('w-full gap-2 p-4'):
            ui.link('‹ Players', '/')
            ui.label('Player not found or unreachable.').classes('text-gray-500')
        return

    # The config is keyed by the player's own id (`dsp/{player_id}.json` is the link),
    # so `live.id` is all that's needed to resolve it.
    saved = dsp_dal.get_or_create(DSPConfig(player_id=live.id))
    # The pre-amp is fully derived; normalize any legacy value so the editor opens clean.
    saved.preamp_db = auto_preamp_db(saved.bands)
    state = {'saved': saved, 'staged': saved.model_copy(deep=True)}
    dsp_band_editor = features.selected(page.settings, features.DSP_BAND_EDITOR_KEY)
    # `expand` mode reveals one band's controls at a time (single id ⇒ one-open-at-a-time).
    expanded = {'id': None}

    def _dirty() -> bool:
        return state['staged'] != state['saved']

    def _mark_changed() -> None:
        """Recomputes the auto pre-amp from the bands, then refreshes dirty state, chart, count."""
        auto = auto_preamp_db(state['staged'].bands)
        if auto != state['staged'].preamp_db:
            state['staged'].preamp_db = auto
            preamp_field.value = auto
        dirty_label.set_visibility(_dirty())
        has_bands = bool(state['staged'].bands)  # chart only once a band exists
        chart.set_visibility(has_bands)
        chart_message.set_visibility(not has_bands)
        if header_row is not None:  # full mode only; column headers show only above real rows
            header_row.set_visibility(has_bands)
        if has_bands:
            # `EChart.options` is a read-only view onto the live props dict; swap its
            # contents in place (the documented "change the options" push) and redraw.
            chart.options.clear()
            chart.options.update(components.response_plot.options(state['staged']))
            chart.update()
        count_label.set_text(f'Bands ({len(state["staged"].bands)})')

    def _on_enabled(band: Band, value: bool) -> None:
        band.enabled = bool(value)
        _mark_changed()

    def _on_type(band: Band, value: str, refresh) -> None:
        # `value` is constrained to `_BAND_TYPES` by the select; the assignment is
        # unvalidated (Band sets no `validate_assignment`), so the literal narrows fine.
        band.type = value  # type: ignore
        refresh()  # re-render the tree owning the gain field (its enabled state depends on the type)
        _mark_changed()

    def _on_freq(band: Band, value) -> None:
        if value is not None:
            band.freq = float(value)
        _mark_changed()

    def _on_gain(band: Band, value) -> None:
        if value is not None:
            band.gain = float(value)
        _mark_changed()

    def _on_q(band: Band, value) -> None:
        if value is not None:
            band.q = float(value)
        _mark_changed()

    def _add_band() -> None:
        # A default Peaking band can't be edited from a compact row alone, so the
        # compact modes auto-reveal its editor (accordion for expand, modal for dialog).
        band = Band(id=uuid.uuid4().hex, type='Peaking', freq=1000.0, gain=0.0, q=0.707)
        # Prepend, not append: biquads cascade so their order doesn't change the response, and a
        # new band at the top is always in view and ready to edit — appended it would land below
        # the fold of the scroll area once several bands exist.
        state['staged'].bands.insert(0, band)
        if dsp_band_editor == features.FF_DSP_BAND_EDITOR_EXPAND:
            expanded['id'] = band.id
        _band_table.refresh()
        _mark_changed()
        if dsp_band_editor == features.FF_DSP_BAND_EDITOR_DIALOG:
            _open_band_dialog(band)

    def _remove_band(band: Band) -> None:
        state['staged'].bands = [b for b in state['staged'].bands if b.id != band.id]
        if expanded['id'] == band.id:  # tidy; a dangling id is otherwise harmless (matches no row)
            expanded['id'] = None
        _band_table.refresh()
        _mark_changed()

    def _apply_preset(kind: Literal['loudness', 'flat']) -> None:
        if kind == 'loudness':
            state['staged'].bands.extend(loudness_preset())
        else:
            state['staged'].bands = []
        _band_table.refresh()
        _mark_changed()

    def _apply_saved_preset(preset: Preset) -> None:
        """Appends fresh clones of a saved preset's bands onto the staged config.

        Apply = append + clone (never replace); the clones carry fresh ids so their
        `audera_peq_<id>` filter names can't collide. Routing through `_mark_changed`
        re-clamps the pre-amp and redraws the chart over the merged set — same wiring
        as REW import.
        """
        state['staged'].bands.extend(clone_bands(preset.bands))
        _band_table.refresh()
        _mark_changed()

    def _delete_preset(preset: Preset) -> None:
        presets_dal.delete_preset(preset.id)
        _presets_menu.refresh()
        ui.notify(f'Deleted preset "{preset.name}"', type='positive', position='top-right')

    def _open_save_preset_dialog() -> None:
        """Opens a dialog to capture the current bands as a named, reusable preset."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Save preset').classes('font-medium text-lg mb-1')
            ui.label('Capture the current bands as a reusable preset you can append to any player.').classes(
                'text-xs text-gray-500 mb-2'
            )
            name_field = (
                ui.input('Preset name', placeholder='My preset')
                .props('outlined dense')
                .classes('w-full')
                .mark('preset-save-name')
            )

            def _save_preset(preset: Preset, notice: str) -> None:
                presets_dal.save_preset(preset)
                _presets_menu.refresh()
                ui.notify(notice, type='positive', position='top-right')
                dialog.close()

            def _on_save_preset() -> None:
                name = (name_field.value or '').strip() or 'Untitled'
                bands = clone_bands(state['staged'].bands)
                # Case-insensitive, trimmed name match against the same source the menu reads.
                existing = next(
                    (preset for preset in presets_dal.get_all_presets() if preset.name.strip().lower() == name.lower()),
                    None,
                )
                if existing is None:
                    _save_preset(Preset(id=uuid.uuid4().hex, name=name, bands=bands), f'Saved preset "{name}"')
                    return

                # A preset with this name already exists — confirm before overwriting it.
                with ui.dialog() as confirm, ui.card().classes('w-96'):
                    ui.label(f'Preset "{name}" already exists.').classes('font-medium mb-1')
                    ui.label('Replace the existing preset with the current bands?').classes('text-xs text-gray-500 mb-2')

                    def _on_replace() -> None:
                        # Reuse the existing id so save_preset overwrites the same {id}.json and any
                        # references to the preset stay stable.
                        _save_preset(Preset(id=existing.id, name=name, bands=bands), f'Replaced preset "{name}"')
                        confirm.close()

                    with ui.row().classes('justify-between w-full mt-2'):
                        # Cancel dismisses only the confirm, leaving the save dialog open to rename.
                        ui.button('Cancel', on_click=confirm.close).props('flat dense').mark('preset-replace-cancel')
                        ui.button('Replace', on_click=_on_replace).props('dense').mark('preset-replace-confirm')

                confirm.open()

            with ui.row().classes('justify-between w-full mt-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat dense')
                ui.button('Save', on_click=_on_save_preset).props('dense').mark('preset-save-run')

        dialog.open()

    @ui.refreshable
    def _presets_menu() -> None:
        ui.menu_item('Loudness', on_click=lambda: _apply_preset('loudness')).mark('preset-loudness')
        ui.menu_item('Clear', on_click=lambda: _apply_preset('flat')).mark('preset-flat')
        saved = presets_dal.get_all_presets()
        if saved:
            ui.separator()
            for preset in saved:
                with ui.menu_item(on_click=lambda p=preset: _apply_saved_preset(p)).mark('preset-saved'):
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.label(preset.name)
                        (
                            ui.button(icon='delete', on_click=lambda p=preset: _delete_preset(p))
                            .props('flat dense round size=sm')
                            .classes('text-gray-400')
                            .on('click.stop')  # .stop: delete doesn't also fire append
                        )
        ui.separator()
        ui.menu_item('New preset', on_click=_open_save_preset_dialog).mark('preset-save-as')

    def _open_import_dialog() -> None:
        """Opens a paste-import dialog that appends CamillaDSP YAML filters as bands.

        REW (v5.20.14+) exports its parametric EQ as CamillaDSP YAML — the same
        `filters:` shape our compiler emits — so its exports paste in directly. Import is
        append-only (it never replaces existing bands) and routes through `_mark_changed`,
        so the auto-ceiling re-clamps the pre-amp and the chart redraws over the merged
        band set. Unsupported filter types are surfaced in the notification rather than
        dropped.
        """
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Import CamillaDSP YAML').classes('font-medium text-lg mb-1')
            ui.label(
                'Paste a CamillaDSP YAML export (e.g. from REW). Biquad filters are appended to the current '
                'configuration; the pre-amp stays auto-protected.'
            ).classes('text-xs text-gray-500 mb-2')
            text = (
                ui.textarea(
                    placeholder='filters:\n  band_1:\n    type: Biquad\n    parameters:'
                    '\n      type: Peaking\n      freq: 1000\n      q: 1.41\n      gain: -3.0'
                )
                .props('outlined autogrow')
                .classes('w-full font-mono')
            )

            def _on_import() -> None:
                result = parse_rew(text.value or '')
                state['staged'].bands.extend(result.bands)
                _band_table.refresh()
                _mark_changed()  # re-clamps pre-amp + redraws chart over the merged bands
                message = f'Imported {len(result.bands)} band(s)'
                if result.skipped:
                    message += f', skipped {len(result.skipped)} filter(s)'
                ui.notify(message, type='positive', position='top-right')
                dialog.close()

            with ui.row().classes('justify-between w-full mt-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat dense')
                ui.button('Import', on_click=_on_import).props('dense').mark('config-import-run')

        dialog.open()

    def _open_export_dialog() -> None:
        """Opens a dialog showing the *saved* configuration as CamillaDSP YAML.

        The YAML carries the `filters:` tag REW (v5.20.14+) requires to re-import, so a
        round-trip out to REW and back is lossless. The text is always the saved config
        (never the staged edits): a partial edit would export a config that never
        clip-guarded, so Save is the gate. When the editor is dirty a banner spells this
        out; Copy and Download surface the same text.
        """
        yaml_text = format_rew(state['saved'].preamp_db, state['saved'].bands)
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Export CamillaDSP YAML').classes('font-medium text-lg mb-1')
            if _dirty():
                ui.label(
                    'There are unsaved changes. Export downloads only the saved configuration — '
                    'Save first to export the current editor contents.'
                ).classes('text-xs text-amber-500 mb-2').mark('export-unsaved-banner')
            ui.textarea(value=yaml_text).props('outlined readonly autogrow').classes('w-full font-mono')

            def _on_copy() -> None:
                ui.clipboard.write(yaml_text)  # synchronous in NiceGUI 3.11.1
                ui.notify('Copied to clipboard', type='positive', position='top-right')

            def _on_download() -> None:
                ui.download.content(yaml_text, f'{live.name}-dsp.yml')

            with ui.row().classes('justify-between w-full mt-2'):
                ui.button('Close', on_click=dialog.close).props('flat dense')
                ui.button('Copy', on_click=_on_copy).props('dense')
                ui.button('Download .yml', on_click=_on_download).props('dense')

        dialog.open()

    def _on_reset() -> None:
        state['staged'] = state['saved'].model_copy(deep=True)
        preamp_field.value = state['staged'].preamp_db
        _band_table.refresh()
        _mark_changed()

    async def _on_save() -> None:
        """Compiles → validates → pushes the live pipeline, then persists the config.

        Pattern B (live apply, no restart): the daemon owns volume and `SetConfigJson`
        leaves the fader untouched, so no volume snapshot/restore is needed. The config
        is keyed by the player id (`dsp/{id}.json`), so Save only updates that one file.

        The CamillaDSP push and the local persist are separate commands so a StorageError
        on the DAL write cannot mask a successful hardware apply.
        """
        camilla = _camilladsp(live.host)
        try:
            await commands.get().submit(apply_pipeline, camilla, state['staged'])
        except CommandError as exc:
            ui.notify(f'Save failed: {exc}', type='negative', position='top-right')
            return
        try:
            await commands.get().submit(dsp_dal.update, state['staged'])
        except CommandError as exc:
            ui.notify(f'Applied but could not save to disk: {exc}', type='negative', position='top-right')
            return
        try:
            await commands.get().submit(camilla.reset_clipped_samples)
        except CommandError:
            pass
        state['saved'] = state['staged'].model_copy(deep=True)
        _mark_changed()
        ui.notify('Saved', type='positive', position='top-right')

    async def _poll_clips() -> None:
        try:
            count = await asyncio.to_thread(_camilladsp(live.host).get_clipped_samples)
        except Exception:
            return
        if count:
            clip_label.set_text(f'⚠ {count} clipped samples')
            clip_label.set_visibility(True)
        else:
            clip_label.set_visibility(False)

    def _band_controls(band: Band, refresh, labeled: bool = False, full_width: bool = False) -> None:
        """Renders the Type / Freq / Gain / Q editors — shared by all three variants.

        Excludes the On checkbox and delete button (those live on the row and are never
        duplicated in the editor). `refresh` re-renders the tree that owns the gain field,
        whose enabled state flips with the type — the table body in full/expand, the dialog
        body in dialog mode (a separate tree `_band_table.refresh()` can't reach).

        `labeled` adds floating field labels for the header-less compact modes (full mode
        keeps its own column-header row instead). `full_width` stretches every field to fill
        its container, for the dialog's vertical stack on narrow phone screens.
        """
        type_w = 'w-full' if full_width else 'w-32'
        num_w = 'w-full' if full_width else 'w-24'
        q_w = 'w-full' if full_width else 'w-20'
        ui.select(
            _BAND_TYPES,
            value=band.type,
            label='Type' if labeled else None,
            on_change=lambda e, b=band: _on_type(b, e.value, refresh),
        ).props('dense outlined').classes(type_w)
        ui.number(
            'Freq (Hz)' if labeled else None,
            value=band.freq,
            step=1,
            format='%.0f',
            on_change=lambda e, b=band: _on_freq(b, e.value),
        ).props('dense outlined debounce=200').classes(num_w)
        gain_field = (
            ui.number(
                'Gain (dB)' if labeled else None,
                value=band.gain,
                step=0.1,
                format='%.1f',
                on_change=lambda e, b=band: _on_gain(b, e.value),
            )
            .props('dense outlined debounce=200')
            .classes(num_w)
        )
        gain_field.set_enabled(band.type not in PASS_TYPES)
        ui.number(
            'Q' if labeled else None,
            value=band.q,
            step=0.001,
            format='%.3f',
            on_change=lambda e, b=band: _on_q(b, e.value),
        ).props('dense outlined debounce=200').classes(q_w)

    def _compact_row(band: Band, on_edit) -> None:
        """Renders a one-line band row (On · summary · ✏ edit · 🗑 delete) for expand + dialog.

        The two compact modes differ only in the ✏ handler passed as `on_edit`.
        """
        with ui.row(wrap=False).classes('items-center gap-2 w-full'):
            ui.checkbox(value=band.enabled, on_change=lambda e, b=band: _on_enabled(b, e.value)).classes('w-10')
            ui.label(_band_summary(band)).classes('grow text-sm')
            (
                ui.button(icon='edit', on_click=lambda b=band: on_edit(b))
                .props('flat dense round size=sm')
                .classes('text-gray-400')
                .mark('dsp-band-edit')
            )
            (
                ui.button(icon='delete', on_click=lambda b=band: _remove_band(b))
                .props('flat dense round size=sm')
                .classes('text-gray-400')
                .mark('dsp-band-delete')
            )

    def _toggle_expand(band: Band) -> None:
        expanded['id'] = None if expanded['id'] == band.id else band.id
        _band_table.refresh()  # rebuilds every summary from live band values

    def _open_band_dialog(band: Band) -> None:
        """Raises a modal with the band controls; edits apply live (chart previews behind it).

        The dialog body is its own nested refreshable so a type-change re-renders the dialog
        (not the table). Single Close button — no snapshot; the table refreshes on close so
        the compact summary reflects the live edits.
        """
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Edit band').classes('font-medium text-lg mb-1')

            @ui.refreshable
            def _dialog_body() -> None:
                # Vertical stack — phones have the vertical room, and full-width labeled
                # fields read far more clearly than a cramped horizontal row.
                with ui.column().classes('w-full gap-3'):
                    _band_controls(band, refresh=_dialog_body.refresh, labeled=True, full_width=True)

            _dialog_body()

            def _close() -> None:
                _band_table.refresh()  # summary line now reflects the live edits
                dialog.close()

            with ui.row().classes('justify-end w-full mt-2'):
                (ui.button('Close', on_click=_close).props('dense').mark('dsp-band-close'))

        dialog.open()

    @ui.refreshable
    def _band_table() -> None:
        # Only the band rows live here — the full-mode column headers and the '+ Add band'
        # button sit in the fixed region above so they stay put while these rows scroll.
        for band in state['staged'].bands:
            if dsp_band_editor == features.FF_DSP_BAND_EDITOR_FULL:
                with ui.row(wrap=False).classes('items-center gap-2 w-full'):
                    ui.checkbox(value=band.enabled, on_change=lambda e, b=band: _on_enabled(b, e.value)).classes('w-10')
                    _band_controls(band, refresh=_band_table.refresh)
                    (
                        ui.button(icon='delete', on_click=lambda b=band: _remove_band(b))
                        .props('flat dense round size=sm')
                        .classes('text-gray-400')
                        .mark('dsp-band-delete')
                    )
            elif dsp_band_editor == features.FF_DSP_BAND_EDITOR_EXPAND:
                # Each band is its own card; the ✏ edit grows the card downward to reveal
                # the labeled controls inline (one card open at a time).
                with ui.card().classes('w-full p-3 gap-2'):
                    _compact_row(band, on_edit=_toggle_expand)
                    if expanded['id'] == band.id:
                        with ui.row().classes('items-center gap-2 w-full pl-10'):
                            _band_controls(band, refresh=_band_table.refresh, labeled=True)
            else:  # FF_DSP_BAND_EDITOR_DIALOG
                # Each band is its own card (matching the expanded view); the ✏ edit raises
                # the modal rather than growing the card inline.
                with ui.card().classes('w-full p-3 gap-2'):
                    _compact_row(band, on_edit=_open_band_dialog)

    # One flex column owns the whole editor: the breadcrumb and everything above the band table keep
    # their natural height, and the `grow` scroll area beneath them flexes to fill the rest — so the
    # band list always sizes to the screen with no per-element height math. `components.layout.
    # fill_viewport()` (called at the top of `render`) bounds this column to the viewport minus the
    # fixed header, so `grow min-h-0` here just claims that leftover height — no `dvh`/`6rem` constant.
    with ui.column().classes('w-full gap-3 flex flex-col grow min-h-0'):
        # Breadcrumb leads the column at its natural height; the current segment ("DSP") is bolded.
        with ui.row().classes('items-center justify-between w-full'):
            with ui.row().classes('items-center gap-2 text-sm'):
                ui.link('Players', '/').classes('text-gray-500 no-underline hover:text-gray-700')
                ui.label('›').classes('text-gray-400')
                ui.label(live.name).classes('text-gray-500')
                ui.label('›').classes('text-gray-400')
                ui.label('DSP').classes('text-gray-800 font-medium')  # the current segment leads
            ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat dense round size=sm').mark('dsp-back')

        # --- Fixed region: presets, pre-amp, chart, info line, headers all stay put ---
        # Presets and Config are the two "sources" that build a pipeline, so they lead on their
        # own row; the pre-amp and the Reset/Save actions sit in line beneath them.
        with ui.row().classes('items-center gap-2 w-full'):
            with ui.button('Presets').props('flat dense icon-right=arrow_drop_down'):
                with ui.menu():
                    _presets_menu()
            with ui.button('Config').props('flat dense icon-right=arrow_drop_down'):
                with ui.menu():
                    ui.menu_item('Import', on_click=_open_import_dialog).mark('config-import')
                    ui.menu_item('Export', on_click=_open_export_dialog).mark('config-export')

        # wrap=False keeps Reset/Save on the pre-amp's line: the widened field would
        # otherwise push Save onto a second row at narrower window widths.
        with ui.row(wrap=False).classes('items-center gap-4 w-full'):
            preamp_field = (
                ui.number('Pre-amp (dB) · auto-protected', value=state['staged'].preamp_db, format='%.1f')
                .props('dense outlined readonly')
                .classes('w-64')
            )
            ui.space()
            ui.button('Reset', on_click=_on_reset).props('flat dense')
            ui.button('Save', on_click=_on_save).props('dense')

        # Persistent handle + empty-state tip, both toggled by the forward-closure
        # `_mark_changed`: the chart shows only once a band exists, the tip otherwise.
        chart = components.response_plot.render(state['staged'])
        with (
            ui.column()
            .classes('w-full gap-1 border-l-4 border-blue-500 rounded px-3 py-2')
            .style('background-color: rgba(59, 130, 246, 0.1)') as chart_message
        ):
            with ui.row().classes('items-center gap-1.5'):
                ui.icon('info').classes('text-blue-600 text-base')
                ui.label('Info').classes('text-sm font-semibold text-gray-800')
            ui.html('Load a preset or click <b>+ ADD BAND</b> to build a DSP pipeline.').classes('text-sm text-gray-700')

        # Band info (left) and Add band (right) share one fixed row above the scrolling table:
        # right-aligning the button favours one-handed phone use, and merging the two rows leaves
        # more height for the band list below.
        with ui.row(wrap=False).classes('items-center justify-between w-full gap-4'):
            with ui.row().classes('items-center gap-4 text-xs text-gray-500 min-w-0'):
                count_label = ui.label()
                dirty_label = ui.label('Unsaved changes ●').classes('text-amber-500')
                clip_label = ui.label('').classes('text-red-500')
                clip_label.set_visibility(False)  # hidden until the clip poll reports a nonzero count
            ui.button('+ Add band', on_click=_add_band).props('flat dense').classes('shrink-0 whitespace-nowrap')

        # Full mode's column headers stay pinned above the scrolling rows; their visibility
        # tracks `has_bands` in `_mark_changed` (mode is fixed per page, so only that can change).
        header_row = None
        if dsp_band_editor == features.FF_DSP_BAND_EDITOR_FULL:
            with ui.row(wrap=False).classes('items-center gap-2 w-full text-xs text-gray-500') as header_row:
                ui.label('On').classes('w-10 text-center')
                ui.label('Type').classes('w-32')
                ui.label('Freq (Hz)').classes('w-24')
                ui.label('Gain (dB)').classes('w-24')
                ui.label('Q').classes('w-20')
                ui.label('').classes('w-10')

        # --- Scrollable region: only the band rows scroll; `grow` claims the leftover height ---
        # `grow min-h-0` lets this box shrink below its content and claim the column's leftover
        # height; `relative` + the scroll area's `absolute inset-0` give QScrollArea a concrete
        # box to fill (it collapses to nothing at short viewports when sized by flex alone).
        # `height: auto` is required: NiceGUI's `.nicegui-scroll-area` hard-codes `height: 16rem`,
        # which — being a real `height` — otherwise wins over `inset-0`'s `bottom: 0` and pins the
        # scroll area to 256px, leaving the rest of this box empty. Clearing it lets `inset-0`
        # stretch the scroll area to fill the wrapper.
        with ui.element('div').classes('w-full grow min-h-0 relative'):
            with ui.scroll_area().classes('absolute inset-0').style('height: auto'):
                _band_table()

    _mark_changed()
    ui.timer(3.0, _poll_clips)
