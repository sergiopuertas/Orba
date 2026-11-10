import pytest

from orba_controller import main
from orba_controller.core.command_bus import CommandBus
from orba_controller.core.events import Event
from orba_controller.integrations import macos_actions
from orba_controller.integrations.macos_actions import MacOSActionHandlers


def action_request(name):
    return Event("action.simulated", {"action": name})


def test_macos_handlers_execute_only_after_explicit_live_dispatch(monkeypatch):
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(macos_actions.sys, "platform", "darwin")
    bus = CommandBus(dry_run=False)
    MacOSActionHandlers(runner=fake_runner).register(bus)

    volume_result = bus.dispatch(action_request("volume.down"))
    spotify_result = bus.dispatch(action_request("spotify.play_pause"))
    undo_result = bus.dispatch(action_request("system.undo"))

    assert [volume_result.name, spotify_result.name, undo_result.name] == [
        "command.completed",
        "command.completed",
        "command.completed",
    ]
    assert all(call[0][0] == "osascript" for call in calls)
    assert "set volume output volume" in calls[0][0][2]
    assert "tell application \"Spotify\" to playpause" in calls[1][0][2]
    assert "keystroke \"z\"" in calls[2][0][2]


def test_macos_handlers_require_https_for_llm_and_reject_unconfigured_actions(
    monkeypatch,
):
    monkeypatch.setattr(macos_actions.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="HTTPS"):
        MacOSActionHandlers(llm_url="http://example.test")

    bus = CommandBus(dry_run=False)
    MacOSActionHandlers(runner=lambda *args, **kwargs: None).register(bus)

    assert bus.dispatch(action_request("teams.toggle_mute")).name == "command.rejected"
    assert bus.dispatch(action_request("llm.open")).name == "command.rejected"


def test_macos_handlers_are_platform_gated(monkeypatch):
    monkeypatch.setattr(macos_actions.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="only available on macOS"):
        MacOSActionHandlers(runner=lambda *args, **kwargs: None).register(
            CommandBus(dry_run=False)
        )


def test_cli_keeps_dry_run_default_and_only_enables_live_bus_explicitly(monkeypatch):
    registered = []

    class FakeHandlers:
        def __init__(self, llm_url=None):
            self.llm_url = llm_url

        def register(self, command_bus):
            registered.append((command_bus, self.llm_url))

    monkeypatch.setattr(main, "MacOSActionHandlers", FakeHandlers)

    safe_bus = main._create_command_bus(execute_actions=False, llm_url=None)
    live_bus = main._create_command_bus(
        execute_actions=True,
        llm_url="https://example.test/assistant",
    )

    assert safe_bus.dry_run is True
    assert live_bus.dry_run is False
    assert registered == [(live_bus, "https://example.test/assistant")]