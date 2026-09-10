import pytest
import websockets.sync.client

from audera.clients import CamillaDSPClient
from audera.domains.dsp import compile_pipeline
from audera.errors import ServiceError, Unreachable
from audera.models.dsp import Band, DSPConfig


def test_call_reads_with_a_deadline_and_maps_timeout(monkeypatch):
    """A peer that accepts the socket but never replies must raise `Unreachable`, not hang.

    Pure test (no container): the connection is stubbed so `recv` sees the read deadline the fix
    adds. Without a `timeout` argument `recv` would block forever; the stub asserts one is passed
    and simulates the silent-socket timeout, which `_call` must translate to `Unreachable`.
    """

    class _StalledWS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send(self, _payload):
            pass

        def recv(self, timeout=None):
            assert timeout is not None, 'ws.recv must be called with a read deadline'
            raise TimeoutError('peer accepted the socket but never replied')

    monkeypatch.setattr(websockets.sync.client, 'connect', lambda *a, **k: _StalledWS())

    client = CamillaDSPClient(host='127.0.0.1', port=1234)
    with pytest.raises(Unreachable):
        client.get_volume()


@pytest.fixture(scope='session')
def client(camilladsp_container):
    host, port = camilladsp_container
    return CamillaDSPClient(host, port)


def test_get_config(client):
    config = client.get_config()
    assert isinstance(config, dict)


def test_set_config(client):
    original = client.get_config()
    new_config = {**original, 'filters': {}, 'pipeline': []}
    client.set_config(new_config)
    result = client.get_config()
    assert result['filters'] == {}
    assert result['pipeline'] == []


def test_get_volume(client):
    volume = client.get_volume()
    assert isinstance(volume, float)


def test_set_volume(client):
    client.set_volume(-20.0)
    result = client.get_volume()
    assert result == -20.0


def test_error_response_raises(client):
    with pytest.raises(ServiceError):
        client._call('UnknownCommand')


def test_percent_to_db():
    c = CamillaDSPClient('localhost', 0)
    assert c.percent_to_db(100) == 0.0
    assert c.percent_to_db(50) == pytest.approx(-6.021, abs=1e-3)
    assert c.percent_to_db(0) == -50.0


def test_db_to_percent():
    c = CamillaDSPClient('localhost', 0)
    assert c.db_to_percent(0.0) == pytest.approx(100.0)
    assert c.db_to_percent(-6.0) == pytest.approx(50.12, abs=1e-2)
    assert c.db_to_percent(-50.0) == 0.0
    assert c.db_to_percent(-80.0) == 0.0


def test_set_percent_volume(client):
    client.set_percent_volume(75)
    result = client.get_volume()
    assert result == pytest.approx(-2.499, abs=1e-3)


def test_get_percent_volume(client):
    client.set_volume(-6.0)
    assert client.get_percent_volume() == 50


def test_validate_config_valid(client):
    config = {
        **client.get_config(),
        'filters': {
            'peak_1': {
                'type': 'Biquad',
                'parameters': {'type': 'Peaking', 'freq': 1000, 'q': 1.0, 'gain': 3.0},
            }
        },
        'pipeline': [{'type': 'Filter', 'channels': [0, 1], 'names': ['peak_1']}],
    }
    assert client.validate_config(config) is None
    client.set_config(config)
    result = client.get_config()
    assert result['filters']['peak_1']['parameters']['type'] == 'Peaking'
    assert result['pipeline'][0]['names'] == ['peak_1']
    assert result['pipeline'][0]['channels'] == [0, 1]


@pytest.mark.parametrize(
    'overrides',
    [
        # a pipeline step referencing a filter name absent from `filters`
        {'filters': {}, 'pipeline': [{'type': 'Filter', 'channels': [0, 1], 'names': ['does_not_exist']}]},
        # a Biquad with an invalid `parameters.type`
        {
            'filters': {'bad_1': {'type': 'Biquad', 'parameters': {'type': 'NotARealType', 'freq': 1000}}},
            'pipeline': [{'type': 'Filter', 'channels': [0, 1], 'names': ['bad_1']}],
        },
    ],
    ids=['missing-filter-name', 'invalid-biquad-type'],
)
def test_validate_config_invalid_raises(client, overrides):
    config = {**client.get_config(), **overrides}
    with pytest.raises(ServiceError):
        client.validate_config(config)


def test_validate_and_set_mono_balance_mixer(client):
    """The compiler's `Mixer`/balance schema, unverified against any repo precedent, must be
    accepted by the real daemon — a shape mismatch here would only surface as a live 400 on Save.
    """
    config = DSPConfig(
        player_id='x',
        mono=True,
        stereo_balance=0.5,
        preamp_db=-3.0,
        bands=[Band(id='b1', type='Peaking', freq=1000.0, gain=3.0)],
    )
    # Start from a clean pipeline — other tests in this module leave foreign filters/steps on
    # the shared daemon, and a Mixer step is only first among *managed* steps, not absolutely.
    current = {**client.get_config(), 'filters': {}, 'mixers': {}, 'pipeline': []}
    compiled = compile_pipeline(current, config)
    assert client.validate_config(compiled) is None
    client.set_config(compiled)
    result = client.get_config()
    assert result['pipeline'][0]['type'] == 'Mixer'


def test_get_clipped_samples(client):
    clipped = client.get_clipped_samples()
    assert isinstance(clipped, int)
    assert clipped >= 0


def test_reset_clipped_samples(client):
    assert client.reset_clipped_samples() is None
    assert client.get_clipped_samples() == 0
