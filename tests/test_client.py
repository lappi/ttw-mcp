import httpx
import pytest

from ttw_mcp.client import TtwClient
from ttw_mcp.errors import NotFound, UpstreamError


def make_client(handler) -> TtwClient:
    return TtwClient(transport=httpx.MockTransport(handler))


def test_get_html_returns_body():
    def handler(request):
        assert request.url.path == "/players/"
        assert request.url.params["id"] == "1c18ed8"
        return httpx.Response(200, text="<html>профиль</html>")

    with make_client(handler) as client:
        assert client.get_html("/players/", {"id": "1c18ed8"}) == "<html>профиль</html>"


def test_user_agent_is_sent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="ok")

    with make_client(handler) as client:
        client.get_html("/players/", {"id": "1c18ed8"})
    assert seen["ua"] == TtwClient.USER_AGENT


def test_post_ajax_sends_form_fields():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, text="<div></div>")

    with make_client(handler) as client:
        client.post_ajax("get_tournaments_by_name", name="энерджи", date="")
    assert "action=get_tournaments_by_name" in seen["body"]


def test_404_becomes_not_found():
    def handler(request):
        return httpx.Response(404, text="not here")

    with make_client(handler) as client:
        with pytest.raises(NotFound):
            client.get_html("/players/", {"id": "deadbee"})


def test_server_error_becomes_upstream_error_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, text="boom")

    with make_client(handler) as client:
        with pytest.raises(UpstreamError):
            client.get_html("/players/", {"id": "1c18ed8"})
    assert len(calls) == 1


def test_network_error_is_retried_exactly_once_then_raises():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("нет связи")

    with make_client(handler) as client:
        with pytest.raises(UpstreamError) as excinfo:
            client.get_html("/players/", {"id": "1c18ed8"})
    assert len(calls) == 2
    # Причина называет настоящий тип сбоя, а не приписывает таймаут всему
    # подряд, а адрес сохраняет параметры — иначе неясно, что именно упало.
    assert "ConnectTimeout" in excinfo.value.reason
    assert "id=1c18ed8" in excinfo.value.url


def test_redirect_loop_becomes_upstream_error():
    # TooManyRedirects — сосед TransportError, а не потомок: узкий except
    # выпускал его наружу сырым, мимо типизации ошибок проекта.
    def handler(request):
        return httpx.Response(302, headers={"Location": "/loop"})

    with make_client(handler) as client:
        with pytest.raises(UpstreamError) as excinfo:
            client.get_html("/loop", {})
    assert "TooManyRedirects" in excinfo.value.reason


def test_retry_succeeds_on_second_attempt():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("медленно")
        return httpx.Response(200, text="получилось")

    with make_client(handler) as client:
        assert client.get_html("/players/", {"id": "1c18ed8"}) == "получилось"
    assert len(calls) == 2
