#!/usr/bin/env python3
"""Install the Orba menu bar app and its per-user login agent on macOS."""
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT / ".venv" / "bin" / "python"
BUNDLE = Path.home() / "Applications" / "ORBA Controller.app"
EXECUTABLE = BUNDLE / "Contents" / "MacOS" / "OrbaController"
AGENT = Path.home() / "Library" / "LaunchAgents" / "com.orba.controller.plist"
LABEL = "com.orba.controller"

if os.uname().sysname != "Darwin":
    raise SystemExit("This installer only supports macOS.")
if not PYTHON.is_file():
    raise SystemExit(f"Project virtualenv Python not found: {PYTHON}")

contents = BUNDLE / "Contents"
(contents / "MacOS").mkdir(parents=True, exist_ok=True)
(contents / "Resources").mkdir(parents=True, exist_ok=True)
contents.joinpath("Info.plist").write_bytes(plistlib.dumps({
    "CFBundleName": "ORBA Controller",
    "CFBundleDisplayName": "ORBA Controller",
    "CFBundleIdentifier": LABEL,
    "CFBundleVersion": "0.1.0",
    "CFBundleShortVersionString": "0.1.0",
    "CFBundlePackageType": "APPL",
    "CFBundleExecutable": "OrbaController",
    "LSUIElement": True,
    "NSHighResolutionCapable": True,
    "NSBluetoothAlwaysUsageDescription": "ORBA Controller busca y recibe MIDI de tu Orba por Bluetooth LE.",
}))
swift_source = PROJECT / "scripts" / "OrbaMenu.swift"
subprocess.run([
    "swiftc", "-O", "-framework", "AppKit", "-framework", "CoreBluetooth", "-framework", "CoreMIDI", str(swift_source), "-o", str(EXECUTABLE)
], check=True)
EXECUTABLE.chmod(0o755)
AGENT.parent.mkdir(parents=True, exist_ok=True)
AGENT.write_bytes(plistlib.dumps({
    "Label": LABEL,
    "ProgramArguments": [str(EXECUTABLE)],
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "LimitLoadToSessionType": "Aqua",
    "ProcessType": "Interactive",
    "StandardOutPath": str(Path.home() / "Library/Logs/ORBA Controller.log"),
    "StandardErrorPath": str(Path.home() / "Library/Logs/ORBA Controller.log"),
}))
uid = str(os.getuid())
domain = f"gui/{uid}"
subprocess.run(["launchctl", "bootout", domain, str(AGENT)], check=False, capture_output=True)
subprocess.run(["launchctl", "bootstrap", domain, str(AGENT)], check=True)
subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
print(f"Installed: {BUNDLE}")
print(f"Launch agent: {AGENT}")
