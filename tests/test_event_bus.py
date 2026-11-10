from orba_controller.core.event_bus import EventBus
from orba_controller.core.events import Event


def test_event_bus_publishes_and_subscribes():
    bus = EventBus()
    seen: list[str] = []

    def subscriber(event: Event) -> None:
        seen.append(event.name)

    bus.subscribe("midi_event", subscriber)
    bus.emit("midi_event", {"note": 69})

    assert seen == ["midi_event"]
