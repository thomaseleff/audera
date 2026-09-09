"""DSP compiler"""

import copy

from audera.clients import CamillaDSPClient
from audera.models.dsp import PASS_TYPES, Band, DSPConfig

_MANAGED_PREFIX = 'audera_'
_PREAMP_KEY = 'audera_preamp'
_PEQ_PREFIX = 'audera_peq_'


def _band_to_biquad(band: Band) -> dict:
    """Returns a CamillaDSP Biquad filter `dict` for a single `Band`.

    Shared by the compiler and the headroom evaluator so that the shape compiled
    into the pipeline and the shape evaluated for the magnitude peak can never
    drift apart.

    Parameters
    ----------
    band: `audera.models.dsp.Band`
        An instance of an `audera.models.dsp.Band` object.
    """
    parameters = {
        'type': band.type,
        'freq': band.freq,
        'q': band.q,
    }
    if band.type not in PASS_TYPES:
        parameters['gain'] = band.gain
    return {'type': 'Biquad', 'parameters': parameters}


def _is_managed_step(step: dict) -> bool:
    """Returns `True` when a pipeline step references any managed filter.

    Parameters
    ----------
    step: `dict`
        A CamillaDSP pipeline step.
    """
    return any(name.startswith(_MANAGED_PREFIX) for name in step.get('names', []))


def compile_pipeline(current_config: dict, config: DSPConfig) -> dict:
    """Returns a new CamillaDSP config compiled from `preamp_db` + `bands`.

    The returned `dict` is a deep copy of `current_config` with every managed
    (`audera_`-prefixed) filter and pipeline step replaced by a fresh pre-amp Gain
    followed by one Biquad per band, in `bands` order. Foreign filters, foreign
    pipeline steps, and device/resampler settings are preserved untouched. The
    caller's `current_config` is never mutated.

    Parameters
    ----------
    current_config: `dict`
        The current CamillaDSP pipeline configuration to compile into.
    config: `audera.models.dsp.DSPConfig`
        An instance of an `audera.models.dsp.DSPConfig` object.
    """
    compiled = copy.deepcopy(current_config)

    # Strip previously-managed filters and steps; keep everything foreign.
    filters = {name: filter_ for name, filter_ in compiled.get('filters', {}).items() if not name.startswith(_MANAGED_PREFIX)}
    pipeline = [step for step in compiled.get('pipeline', []) if not _is_managed_step(step)]

    # Re-add the pre-amp Gain, then one Biquad per band, in a stable order.
    filters[_PREAMP_KEY] = {'type': 'Gain', 'parameters': {'gain': config.preamp_db}}
    pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': [_PREAMP_KEY], 'bypassed': False})
    for band in config.bands:
        name = _PEQ_PREFIX + band.id
        filters[name] = _band_to_biquad(band)
        pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': [name], 'bypassed': not band.enabled})

    compiled['filters'] = filters
    compiled['pipeline'] = pipeline
    return compiled


def apply_pipeline(client: CamillaDSPClient, config: DSPConfig) -> dict:
    """Compiles `config` against the daemon's current pipeline and pushes it live.

    Shared by the DSP editor's Save action and the broker's reconnect resync, so the two
    apply paths can never drift.

    Parameters
    ----------
    client: `audera.clients.CamillaDSPClient`
        A CamillaDSP client bound to the target player's host.
    config: `audera.models.dsp.DSPConfig`
        An instance of an `audera.models.dsp.DSPConfig` object.
    """
    current = client.get_config()
    compiled = compile_pipeline(current, config)
    client.validate_config(compiled)
    client.set_config(compiled)
    return compiled
