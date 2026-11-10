from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OrbaDevice:
    name: str
    transport: str
    is_connected: bool = False


class OrbaConnectionManager:
    """High-level connection manager for Orba 1 discovery and transport selection."""

    def __init__(self, preferred_transport: str = "usb"):
        self.preferred_transport = preferred_transport
        self.device: OrbaDevice | None = None

    def discover_devices(self) -> list[OrbaDevice]:
        return [
            OrbaDevice(name="Artiphon Orba 1 (simulated)", transport=self.preferred_transport, is_connected=False),
        ]

    def connect(self, device_name: str | None = None) -> OrbaDevice:
        target = device_name or "Artiphon Orba 1 (simulated)"
        self.device = OrbaDevice(name=target, transport=self.preferred_transport, is_connected=True)
        return self.device

    def disconnect(self) -> None:
        if self.device is not None:
            self.device.is_connected = False
