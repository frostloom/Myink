"""Fixed local bridge transport; no network proxy, retries or caller-chosen URLs."""
import json
from pathlib import Path
import httpx
import pytest


@pytest.fixture
def service_token(tmp_path):
    path=tmp_path/'client-token';path.write_text('fixture-service-token-at-least-32-characters');path.chmod(0o640);return path


def test_fixed_transport_sends_only_local_credential_and_can_read_rotation(service_token):
    from myink.pi_console import PiConsoleClient
    seen=[]
    def handle(request):seen.append(request);return httpx.Response(200,json={'schema_version':1})
    client=PiConsoleClient('/private/tmp/not-connected.sock',service_token,transport=httpx.MockTransport(handle))
    assert client.call('GET','/v1/status')=={'schema_version':1}
    service_token.write_text('rotated-service-token-at-least-32-characters');client.call('GET','/v1/status')
    assert seen[0].headers['X-Pi-Console-Token'].startswith('fixture') and seen[1].headers['X-Pi-Console-Token'].startswith('rotated')
    assert all(request.url.host=='pi-console' and 'authorization' not in request.headers for request in seen)


@pytest.mark.parametrize('path',['https://external.invalid','/v1/arbitrary','/v1/operations/../../etc/passwd'])
def test_transport_rejects_arbitrary_urls_and_paths(service_token,path):
    from myink.pi_console import PiConsoleClient
    seen=[];client=PiConsoleClient('/private/tmp/not-connected.sock',service_token,transport=httpx.MockTransport(lambda r:seen.append(r)))
    with pytest.raises(ValueError):client.call('GET',path)
    assert seen==[]


@pytest.mark.parametrize('status,error',[(409,'PiConsoleConflict'),(404,'PiConsoleNotFound'),(401,'PiConsoleUnavailable'),(503,'PiConsoleUnavailable')])
def test_host_errors_are_projected_without_credentials_or_private_error_body(service_token,status,error):
    from myink import pi_console
    client=pi_console.PiConsoleClient('/private/tmp/not-connected.sock',service_token,transport=httpx.MockTransport(lambda r:httpx.Response(status,json={'private_path':'/private/secret','token':'PRIVATE'})))
    with pytest.raises(getattr(pi_console,error)) as caught:client.call('GET','/v1/status')
    assert 'PRIVATE' not in str(caught.value) and '/private/secret' not in str(caught.value)


def test_malformed_or_oversized_host_payload_is_unavailable(service_token):
    from myink.pi_console import PiConsoleClient,PiConsoleUnavailable
    for response in (httpx.Response(200,text='not-json'),httpx.Response(200,content=b'x'*8388609)):
        client=PiConsoleClient('/private/tmp/not-connected.sock',service_token,transport=httpx.MockTransport(lambda r:response))
        with pytest.raises(PiConsoleUnavailable):client.call('GET','/v1/status')


def test_readable_to_the_world_or_symlinked_service_credentials_are_rejected(service_token,tmp_path):
    from myink.pi_console import PiConsoleClient,PiConsoleUnavailable
    service_token.chmod(0o644);client=PiConsoleClient('/private/tmp/not-connected.sock',service_token,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))
    with pytest.raises(PiConsoleUnavailable):client.call('GET','/v1/status')
    service_token.chmod(0o640);link=tmp_path/'link';link.symlink_to(service_token);client=PiConsoleClient('/private/tmp/not-connected.sock',link,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))
    with pytest.raises(PiConsoleUnavailable):client.call('GET','/v1/status')
