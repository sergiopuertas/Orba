from __future__ import annotations

from collections.abc import Callable

import keyring


class KeyringTokenStore:
    """Store provider tokens in the operating system credential store."""

    def __init__(self, service_name: str = "orba-controller") -> None:
        if not service_name.strip():
            raise ValueError("service_name must be non-empty")
        self.service_name = service_name

    def get_token(self, provider: str) -> str | None:
        self._validate_provider(provider)
        return keyring.get_password(self.service_name, provider)

    def set_token(self, provider: str, token: str) -> None:
        self._validate_provider(provider)
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        keyring.set_password(self.service_name, provider, token)

    def delete_token(self, provider: str) -> bool:
        self._validate_provider(provider)
        if keyring.get_password(self.service_name, provider) is None:
            return False
        keyring.delete_password(self.service_name, provider)
        return True

    def token_provider(self, provider: str) -> Callable[[], str | None]:
        self._validate_provider(provider)
        return lambda: self.get_token(provider)

    @staticmethod
    def _validate_provider(provider: str) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")