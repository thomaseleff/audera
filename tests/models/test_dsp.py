from audera.models.dsp import DSPConfig


def test_dsp_config_legacy_dict_drops_retired_keys():
    """A config written by an earlier release loads and re-serializes without its retired keys.

    Deployed devices carry `~/.audera/dsp/{player_id}.json` files from before the parametric-EQ
    rewrite. A `model_dump()` that echoed the unknown keys would keep re-writing a `pipeline` the
    compiler no longer reads.
    """
    legacy = {
        'player_id': 'player-1',
        'id': 'dsp-1',
        'dsp_id': 'dsp-1',
        'pipeline': {'filters': {}, 'pipeline': []},
        'loudness_enabled': True,
        'loudness_reference_level': -30.0,
        'volume': 40.0,
        'enabled': True,
    }
    result = DSPConfig.model_validate(legacy).model_dump()
    assert set(result.keys()) == {'player_id', 'preamp_db', 'bands', 'enabled', 'mono', 'stereo_balance'}
    for retired in ('id', 'dsp_id', 'pipeline', 'loudness_enabled', 'loudness_reference_level', 'volume'):
        assert retired not in result
