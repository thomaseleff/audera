"""DSP compiler"""

import copy
import math
from typing import Literal

from audera.clients import CamillaDSPClient
from audera.models.dsp import PASS_TYPES, Band, DSPConfig

_MANAGED_PREFIX = 'audera_'
_PREAMP_KEY = 'audera_preamp'
_PEQ_PREFIX = 'audera_peq_'
_MIXER_KEY = 'audera_mixer'
_BALANCE_L_KEY = 'audera_balance_l'
_BALANCE_R_KEY = 'audera_balance_r'

# The standard clip-safe mono-sum weighting: correlated/centered content nets to ~0 dB, only
# drops toward -3 dB as content decorrelates, and never clips even at full correlation. No
# compensating makeup gain is added after the mixer, and `headroom.auto_preamp_db` stays purely
# band-driven — a fixed makeup term would guess at content correlation and be wrong exactly when
# it matters most (correlated content at unity gain, where positive makeup reopens clipping risk).
_MONO_MIX_GAIN_DB = 20 * math.log10(0.5)


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
    """Returns `True` when a pipeline step references any managed filter or mixer.

    Filter steps name their targets via `names` (plural); Mixer steps via `name` (singular).

    Parameters
    ----------
    step: `dict`
        A CamillaDSP pipeline step.
    """
    if any(name.startswith(_MANAGED_PREFIX) for name in step.get('names', [])):
        return True
    return step.get('name', '').startswith(_MANAGED_PREFIX)


def _balance_gain_db(balance: float, side: Literal['left', 'right']) -> float:
    """Returns a channel's balance attenuation in dB, 0 dB on its favored side.

    Linear taper to `CamillaDSPClient.MIN_DB` on the attenuated side, mirroring the volume
    attenuation range.

    Parameters
    ----------
    balance: `float`
        The L/R balance, from -1.0 (full left) to 1.0 (full right).
    side: `Literal['left', 'right']`
        Which channel's gain to compute.
    """
    taper = -CamillaDSPClient.MIN_DB
    if side == 'left':
        return 0.0 if balance <= 0 else -balance * taper
    return 0.0 if balance >= 0 else balance * taper


def compile_pipeline(current_config: dict, config: DSPConfig) -> dict:
    """Returns a new CamillaDSP config compiled from `mono` + `stereo_balance` + `preamp_db` + `bands`.

    The returned `dict` is a deep copy of `current_config` with every managed
    (`audera_`-prefixed) filter, mixer, and pipeline step replaced by a fresh mono downmix
    Mixer (when `config.mono`), L/R balance Gain filters, a pre-amp Gain, and one Biquad per
    band, in that signal-flow order. Foreign filters, foreign pipeline steps, and
    device/resampler settings are preserved untouched. The caller's `current_config` is never
    mutated.

    Parameters
    ----------
    current_config: `dict`
        The current CamillaDSP pipeline configuration to compile into.
    config: `audera.models.dsp.DSPConfig`
        An instance of an `audera.models.dsp.DSPConfig` object.
    """
    compiled = copy.deepcopy(current_config)

    # CamillaDSP's own config carries these keys as explicit `null`, not omitted, when empty —
    # `.get(key, {})`'s default only kicks in when the key is absent, so a plain `or` is needed.
    filters = {
        name: filter_ for name, filter_ in (compiled.get('filters') or {}).items() if not name.startswith(_MANAGED_PREFIX)
    }
    mixers = {name: mixer for name, mixer in (compiled.get('mixers') or {}).items() if not name.startswith(_MANAGED_PREFIX)}
    pipeline = [step for step in (compiled.get('pipeline') or []) if not _is_managed_step(step)]

    # Re-add the managed steps, in signal-flow order: mono mixer, then balance, then pre-amp,
    # then one Biquad per band.
    if config.mono:
        mixers[_MIXER_KEY] = {
            'channels': {'in': 2, 'out': 2},
            'mapping': [
                {
                    'dest': dest,
                    'sources': [{'channel': src, 'gain': _MONO_MIX_GAIN_DB, 'inverted': False} for src in (0, 1)],
                }
                for dest in (0, 1)
            ],
        }
        pipeline.append({'type': 'Mixer', 'name': _MIXER_KEY})

    filters[_BALANCE_L_KEY] = {'type': 'Gain', 'parameters': {'gain': _balance_gain_db(config.stereo_balance, 'left')}}
    filters[_BALANCE_R_KEY] = {'type': 'Gain', 'parameters': {'gain': _balance_gain_db(config.stereo_balance, 'right')}}
    pipeline.append({'type': 'Filter', 'channels': [0], 'names': [_BALANCE_L_KEY], 'bypassed': False})
    pipeline.append({'type': 'Filter', 'channels': [1], 'names': [_BALANCE_R_KEY], 'bypassed': False})

    filters[_PREAMP_KEY] = {'type': 'Gain', 'parameters': {'gain': config.preamp_db}}
    pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': [_PREAMP_KEY], 'bypassed': False})
    for band in config.bands:
        name = _PEQ_PREFIX + band.id
        filters[name] = _band_to_biquad(band)
        pipeline.append({'type': 'Filter', 'channels': [0, 1], 'names': [name], 'bypassed': not band.enabled})

    compiled['filters'] = filters
    compiled['mixers'] = mixers
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
