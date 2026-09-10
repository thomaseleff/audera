"""DSP domain layer

The `dsp` sub-package compiles bands into a CamillaDSP pipeline (`compiler`), derives
the combined magnitude response, its peak, and the clip-safe pre-amp ceiling for headroom
safety (`headroom`), and mints editable preset bands (`presets`).
"""

from audera.domains.dsp.compiler import apply_pipeline, compile_pipeline
from audera.domains.dsp.headroom import auto_preamp_db, response_curve, response_peak_db
from audera.domains.dsp.presets import clone_bands, loudness_preset
from audera.domains.dsp.rew import format_rew, parse_rew

__all__ = [
    'compile_pipeline',
    'apply_pipeline',
    'auto_preamp_db',
    'response_curve',
    'response_peak_db',
    'clone_bands',
    'loudness_preset',
    'format_rew',
    'parse_rew',
]
