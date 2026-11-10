from orba_controller.integrations import KeyringTokenStore


def test_keyring_token_store_get_set_delete_and_provider(monkeypatch):
    secrets = {}

    def get_password(service, account):
        return secrets.get((service, account))

    def set_password(service, account, token):
        secrets[(service, account)] = token

    def delete_password(service, account):
        del secrets[(service, account)]

    monkeypatch.setattr("orba_controller.integrations.token_store.keyring.get_password", get_password)
    monkeypatch.setattr("orba_controller.integrations.token_store.keyring.set_password", set_password)
    monkeypatch.setattr("orba_controller.integrations.token_store.keyring.delete_password", delete_password)
    store = KeyringTokenStore()

    assert store.get_token("spotify") is None
    store.set_token("spotify", "refresh-token")
    assert store.get_token("spotify") == "refresh-token"
    assert store.token_provider("spotify")() == "refresh-token"
    assert store.delete_token("spotify") is True
    assert store.delete_token("spotify") is False


def test_keyring_token_store_rejects_empty_values():
    store = KeyringTokenStore()

    for operation in (
        lambda: store.get_token(" "),
        lambda: store.set_token("spotify", " "),
        lambda: KeyringTokenStore(" "),
    ):
        try:
            operation()
        except ValueError:
            continue
        raise AssertionError("Expected ValueError for empty input")