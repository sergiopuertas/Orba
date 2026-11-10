from __future__ import annotations

from collections.abc import Callable

AccessTokenSource = str | Callable[[], str | None]


class MissingAccessTokenError(RuntimeError):
    pass


def get_access_token(source: AccessTokenSource) -> str:
    token = source() if callable(source) else source
    if not isinstance(token, str) or not token.strip():
        raise MissingAccessTokenError("A service access token must be provided by the caller")
    return token.strip()