from orba_controller.core.command_bus import CommandBus
from orba_controller.core.event_bus import EventBus
from orba_controller.core.events import Event


def action_event(action="safe_ack"):
    return Event(
        name="action.simulated",
        payload={"action": action, "gesture": "gesture.tap"},
    )


def test_dry_run_does_not_invoke_registered_handler():
    invocations = []
    bus = CommandBus()
    bus.register("safe_ack", lambda payload: invocations.append(payload))

    result = bus.dispatch(action_event())

    assert result.name == "command.dry_run"
    assert result.payload["action"] == "safe_ack"
    assert invocations == []


def test_live_dispatch_requires_and_calls_registered_handler():
    received = []
    bus = CommandBus(dry_run=False)
    bus.register("safe_ack", lambda payload: received.append(payload) or {"accepted": True})

    result = bus.dispatch(action_event())

    assert result.name == "command.completed"
    assert result.payload["result"] == {"accepted": True}
    assert received == [{"action": "safe_ack", "gesture": "gesture.tap"}]


def test_live_dispatch_rejects_unregistered_handler():
    result = CommandBus(dry_run=False).dispatch(action_event("open_app"))

    assert result.name == "command.rejected"
    assert result.payload["reason"] == "no_handler_registered"


def test_dispatch_publishes_command_result_to_event_bus():
    event_bus = EventBus()
    seen = []
    event_bus.subscribe("command.dry_run", seen.append)
    result = CommandBus(event_bus=event_bus).dispatch(action_event())

    assert seen == [result]