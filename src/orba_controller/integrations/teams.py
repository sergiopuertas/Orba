from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import httpx

from .auth import AccessTokenSource, get_access_token


@dataclass(frozen=True, slots=True)
class TeamsPresence:
    availability: str | None
    activity: str | None


class TeamsPresenceClient:
    """Read the signed-in work account's Microsoft Graph presence."""

    endpoint = "https://graph.microsoft.com/v1.0/me/presence"

    def __init__(
        self,
        access_token: AccessTokenSource,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client or httpx.Client(timeout=5.0)
        self._owns_client = client is None

    def get_presence(self) -> TeamsPresence:
        token = get_access_token(self._access_token)
        response = self._client.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
        availability = payload.get("availability")
        activity = payload.get("activity")
        return TeamsPresence(
            availability=availability if isinstance(availability, str) else None,
            activity=activity if isinstance(activity, str) else None,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()