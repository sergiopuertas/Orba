import httpx
import pytest

from orba_controller.integrations import SpotifyClient, TeamsPresenceClient
from orba_controller.integrations.auth import MissingAccessTokenError


def test_spotify_reads_current_track_and_uses_supplied_token():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "is_playing": True,
            "progress_ms": 1234,
            "item": {
                "type": "track",
                "name": "Test track",
                "artists": [{"name": "Test artist"}],
            },
            "device": {"name": "Desktop"},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        playback = SpotifyClient(lambda: "spotify-token", client=http_client).current_playback()

    assert playback is not None
    assert playback.is_playing
    assert playback.item_name == "Test track"
    assert playback.artists == ("Test artist",)
    assert playback.device_name == "Desktop"
    assert requests[0].url.path == "/v1/me/player/currently-playing"
    assert requests[0].headers["Authorization"] == "Bearer spotify-token"


def test_spotify_returns_none_when_nothing_is_playing():
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))
    )

    with http_client:
        playback = SpotifyClient("token", client=http_client).current_playback()

    assert playback is None


def test_teams_reads_presence_with_delegated_token():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"availability": "Busy", "activity": "InACall"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        presence = TeamsPresenceClient("graph-token", client=http_client).get_presence()

    assert presence.availability == "Busy"
    assert presence.activity == "InACall"
    assert requests[0].url.path == "/v1.0/me/presence"
    assert requests[0].headers["Authorization"] == "Bearer graph-token"


@pytest.mark.parametrize("client_type, method_name", [
    (SpotifyClient, "current_playback"),
    (TeamsPresenceClient, "get_presence"),
])
def test_integrations_fail_before_request_without_token(client_type, method_name):
    requests = []
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: requests.append(request))
    )

    with http_client, pytest.raises(MissingAccessTokenError):
        getattr(client_type(None, client=http_client), method_name)()

    assert requests == []