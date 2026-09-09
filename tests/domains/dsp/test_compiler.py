from audera.domains.dsp import apply_pipeline, compile_pipeline
from audera.domains.dsp.compiler import _PEQ_PREFIX, _PREAMP_KEY
from audera.models.dsp import Band, DSPConfig


def _empty_config() -> dict:
    return {'filters': {}, 'pipeline': []}


def _foreign_config() -> dict:
    """A base config carrying a foreign filter, its step, and device settings."""
    return {
        'devices': {'samplerate': 48000},
        'filters': {'user_filter': {'type': 'Gain', 'parameters': {'gain': -2.0}}},
        'pipeline': [{'type': 'Filter', 'channels': [0, 1], 'names': ['user_filter']}],
    }


def test_preamp_and_peq_filters_exist():
    config = DSPConfig(
        player_id='x',
        preamp_db=-6.0,
        bands=[
            Band(id='b1', type='Peaking', freq=1000.0, gain=3.0),
            Band(id='b2', type='Lowshelf', freq=90.0, gain=10.0),
        ],
    )
    compiled = compile_pipeline(_empty_config(), config)
    assert _PREAMP_KEY in compiled['filters']
    assert _PEQ_PREFIX + 'b1' in compiled['filters']
    assert _PEQ_PREFIX + 'b2' in compiled['filters']
    assert compiled['filters'][_PREAMP_KEY] == {'type': 'Gain', 'parameters': {'gain': -6.0}}


def test_each_managed_filter_has_own_stereo_step():
    config = DSPConfig(
        player_id='x',
        bands=[
            Band(id='b1', type='Peaking', freq=1000.0, gain=3.0),
            Band(id='b2', type='Peaking', freq=2000.0, gain=3.0),
        ],
    )
    compiled = compile_pipeline(_empty_config(), config)
    steps = compiled['pipeline']
    assert len(steps) == 3  # preamp + one per band
    for step in steps:
        assert step['type'] == 'Filter'
        assert step['channels'] == [0, 1]
        assert len(step['names']) == 1
    assert steps[0]['names'] == [_PREAMP_KEY]
    assert steps[1]['names'] == [_PEQ_PREFIX + 'b1']
    assert steps[2]['names'] == [_PEQ_PREFIX + 'b2']


def test_shelf_type_passes_through_to_camilladsp():
    # `Band.type` already carries CamillaDSP's own casing, so the compiler emits it verbatim.
    config = DSPConfig(
        player_id='x',
        bands=[
            Band(id='low', type='Lowshelf', freq=90.0, gain=10.0),
            Band(id='high', type='Highshelf', freq=8000.0, gain=6.0),
        ],
    )
    compiled = compile_pipeline(_empty_config(), config)
    assert compiled['filters'][_PEQ_PREFIX + 'low']['parameters']['type'] == 'Lowshelf'
    assert compiled['filters'][_PEQ_PREFIX + 'high']['parameters']['type'] == 'Highshelf'


def test_disabled_band_step_is_bypassed():
    config = DSPConfig(
        player_id='x',
        bands=[
            Band(id='on', type='Peaking', freq=1000.0, gain=3.0, enabled=True),
            Band(id='off', type='Peaking', freq=2000.0, gain=3.0, enabled=False),
        ],
    )
    compiled = compile_pipeline(_empty_config(), config)
    by_name = {step['names'][0]: step for step in compiled['pipeline']}
    assert by_name[_PEQ_PREFIX + 'on']['bypassed'] is False
    assert by_name[_PEQ_PREFIX + 'off']['bypassed'] is True
    assert by_name[_PREAMP_KEY]['bypassed'] is False


def test_pass_filters_omit_gain_shelves_include_it():
    config = DSPConfig(
        player_id='x',
        bands=[
            Band(id='lp', type='Lowpass', freq=12000.0, q=0.7),
            Band(id='hp', type='Highpass', freq=40.0, q=0.7),
            Band(id='pk', type='Peaking', freq=1000.0, gain=3.0),
        ],
    )
    compiled = compile_pipeline(_empty_config(), config)
    assert 'gain' not in compiled['filters'][_PEQ_PREFIX + 'lp']['parameters']
    assert 'gain' not in compiled['filters'][_PEQ_PREFIX + 'hp']['parameters']
    assert compiled['filters'][_PEQ_PREFIX + 'pk']['parameters']['gain'] == 3.0


def test_foreign_filters_and_steps_are_preserved():
    config = DSPConfig(player_id='x', bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=3.0)])
    compiled = compile_pipeline(_foreign_config(), config)
    assert compiled['devices'] == {'samplerate': 48000}
    assert 'user_filter' in compiled['filters']
    assert {'type': 'Filter', 'channels': [0, 1], 'names': ['user_filter']} in compiled['pipeline']


def test_does_not_mutate_caller_config():
    base = _empty_config()
    config = DSPConfig(player_id='x', bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=3.0)])
    compile_pipeline(base, config)
    assert base == {'filters': {}, 'pipeline': []}


def test_idempotency():
    config = DSPConfig(
        player_id='x',
        preamp_db=-4.0,
        bands=[
            Band(id='b1', type='Lowshelf', freq=90.0, gain=10.0),
            Band(id='b2', type='Peaking', freq=1000.0, gain=3.0, enabled=False),
        ],
    )
    once = compile_pipeline(_foreign_config(), config)
    twice = compile_pipeline(once, config)
    assert twice == once


def test_empty_base_config_compiles_cleanly():
    config = DSPConfig(player_id='x')
    compiled = compile_pipeline(_empty_config(), config)
    assert compiled['filters'] == {_PREAMP_KEY: {'type': 'Gain', 'parameters': {'gain': 0.0}}}
    assert compiled['pipeline'] == [{'type': 'Filter', 'channels': [0, 1], 'names': [_PREAMP_KEY], 'bypassed': False}]


class _FakeCamillaClient:
    """Records calls in order; no I/O. `get_config` returns the same dict every time."""

    def __init__(self, current: dict):
        self._current = current
        self.calls: list[str] = []
        self.validated: dict | None = None
        self.applied: dict | None = None

    def get_config(self) -> dict:
        self.calls.append('get_config')
        return self._current

    def validate_config(self, config: dict) -> None:
        self.calls.append('validate_config')
        self.validated = config

    def set_config(self, config: dict) -> None:
        self.calls.append('set_config')
        self.applied = config


def test_apply_pipeline_compiles_validates_and_sets_in_order():
    config = DSPConfig(player_id='x', bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=3.0)])
    client = _FakeCamillaClient(_empty_config())
    result = apply_pipeline(client, config)  # ty: ignore[invalid-argument-type]
    assert client.calls == ['get_config', 'validate_config', 'set_config']
    assert client.validated == result
    assert client.applied == result
    assert _PEQ_PREFIX + 'b1' in result['filters']
