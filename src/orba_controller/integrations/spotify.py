from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import httpx

from .auth import AccessTokenSource, get_access_token


@dataclass(frozen=True, slots=True)
class SpotifyPlayback:
    is_playing: bool
    item_name: str | None
    item_type: str | None
    artists: tuple[str, ...]
    progress_ms: int | None
    device_name: str | None


class SpotifyClient:
    """Read the current Spotify playback state using a caller-supplied token."""

    endpoint = "https://api.spotify.com/v1/me/player/currently-playing"

    def __init__(
        self,
        access_token: AccessTokenSource,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client or httpx.Client(timeout=5.0)
        self._owns_client = client is None

    def current_playback(self) -> SpotifyPlayback | None:
        token = get_access_token(self._access_token)
        response = self._client.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        response.raise_for_status()

        payload = response.json()
        item = payload.get("item")
        item = item if isinstance(item, dict) else {}
        raw_artists = item.get("artists", [])
        artists = tuple(
            artist["name"]
            for artist in raw_artists
            if isinstance(artist, dict) and isinstance(artist.get("name"), str)
        ) if isinstance(raw_artists, list) else ()
        raw_progress = payload.get("progress_ms")
        progress = raw_progress if type(raw_progress) is int else None
        device = payload.get("device")
        device_name = device.get("name") if isinstance(device, dict) else None

        return SpotifyPlayback(
            is_playing=payload.get("is_playing") is True,
            item_name=item.get("name") if isinstance(item.get("name"), str) else None,
            item_type=item.get("type") if isinstance(item.get("type"), str) else None,
            artists=artists,
            progress_ms=progress,
            device_name=device_name if isinstance(device_name, str) else None,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()