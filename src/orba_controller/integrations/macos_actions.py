from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from orba_controller.core.command_bus import CommandBus

CommandRunner = Callable[..., Any]


class MacOSActionHandlers:
    """Explicit macOS command handlers; callers must opt into execution."""

    _MODIFIERS = {
        "command": "command down",
        "control": "control down",
        "option": "option down",
        "shift": "shift down",
    }
    _KEY_CODES = {
        **dict(zip("asdfghzxcv", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])),
        **dict(zip("qwertyuiop", [12, 13, 14, 15, 17, 16, 32, 34, 31, 35])),
        **dict(zip("jklbnm", [38, 37, 40, 45, 46, 44])),
        **dict(zip("1234567890", [18, 19, 20, 21, 23, 22, 26, 28, 25, 29])),
        "space": 49,
        "return": 36,
        "tab": 48,
        "escape": 53,
    }

    def __init__(
        self,
        *,
        llm_url: str | None = None,
        chatgpt_voice_shortcut: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.llm_url = self._validate_llm_url(llm_url) if llm_url else None
        self.chatgpt_voice_shortcut = (
            self._validate_shortcut(chatgpt_voice_shortcut)
            if chatgpt_voice_shortcut else None
        )
        self._runner = runner or subprocess.run

    def register(self, command_bus: CommandBus) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS action handlers are only available on macOS")

        scripts = {
            "volume.down": (
                "set currentVolume to output volume of (get volume settings)\n"
                "if currentVolume > 5 then\n"
                "set volume output volume (currentVolume - 5)\n"
                "else\n"
                "set volume output volume 0\n"
                "end if"
            ),
            "volume.up": (
                "set currentVolume to output volume of (get volume settings)\n"
                "if currentVolume < 95 then\n"
                "set volume output volume (currentVolume + 5)\n"
                "else\n"
                "set volume output volume 100\n"
                "end if"
            ),
            "volume.down_twice": (
                "set currentVolume to output volume of (get volume settings)\n"
                "if currentVolume > 10 then\n"
                "set volume output volume (currentVolume - 10)\n"
                "else\n"
                "set volume output volume 0\n"
                "end if"
            ),
            "volume.up_twice": (
                "set currentVolume to output volume of (get volume settings)\n"
                "if currentVolume < 90 then\n"
                "set volume output volume (currentVolume + 10)\n"
                "else\n"
                "set volume output volume 100\n"
                "end if"
            ),
            "volume.mute_toggle": (
                "set currentMute to output muted of (get volume settings)\n"
                "set volume output muted (not currentMute)"
            ),
            "system.undo": 'tell application "System Events" to keystroke "z" using {command down}',
            "system.back": 'tell application "System Events" to keystroke "[" using {command down}',
            "spotify.next": 'tell application "Spotify" to next track',
            "spotify.previous": 'tell application "Spotify" to previous track',
        }
        for action, script in scripts.items():
            command_bus.register(action, self._script_handler(script))

        command_bus.register("spotify.play_pause", self._spotify_play_pause)
        command_bus.register("spotify.open", self._open_spotify)
        command_bus.register("chatgpt.open", self._open_chatgpt)
        command_bus.register("chatgpt.new_chat", self._open_chatgpt_new_chat)
        command_bus.register("chatgpt.voice_toggle", self._toggle_chatgpt_voice)
        if self.llm_url is not None:
            command_bus.register("llm.open", self._open_llm)

    def _script_handler(self, script: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def run(_: dict[str, Any]) -> dict[str, Any]:
            self._runner(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
            return {"executor": "osascript"}

        return run

    def _spotify_play_pause(self, _: dict[str, Any]) -> dict[str, Any]:
        script = (
            'tell application "System Events" to set spotifyIsRunning to '
            'exists process "Spotify"\n'
            'if spotifyIsRunning then\n'
            'tell application "Spotify" to playpause\n'
            'return "toggled"\n'
            'else\n'
            'return "not_running"\n'
            'end if'
        )
        result = self._runner(
            ["osascript", "-e", script], check=True, capture_output=True, text=True
        )
        state = (getattr(result, "stdout", "") or "").strip() or "unknown"
        return {"executor": "osascript", "spotify": state}

    def _open_spotify(self, _: dict[str, Any]) -> dict[str, Any]:
        self._runner(["open", "-a", "Spotify"], check=True, capture_output=True, text=True)
        script = (
            'tell application "Spotify" to activate\n'
            'delay 0.6\n'
            'tell application "System Events"\n'
            'tell process "Spotify"\n'
            'set frontmost to true\n'
            'repeat with spotifyWindow in windows\n'
            'try\n'
            'set value of attribute "AXMinimized" of spotifyWindow to false\n'
            'end try\n'
            'end repeat\n'
            'end tell\n'
            'end tell\n'
            'tell application "Spotify"\n'
            'if player state is playing then pause\n'
            'end tell'
        )
        self._runner(["osascript", "-e", script], check=True, capture_output=True, text=True)
        return {"executor": "open+osascript", "application": "Spotify", "paused": True}

    def _open_chatgpt(self, _: dict[str, Any]) -> dict[str, Any]:
        self._runner(["open", "-a", "ChatGPT"], check=True, capture_output=True, text=True)
        return {"executor": "open", "application": "ChatGPT"}

    def _open_chatgpt_new_chat(self, _: dict[str, Any]) -> dict[str, Any]:
        self._runner(["open", "-a", "ChatGPT"], check=True, capture_output=True, text=True)
        script = (
            'tell application "ChatGPT" to activate\n'
            'delay 0.4\n'
            'tell application "System Events" to key code 49 using {option down}'
        )
        self._runner(["osascript", "-e", script], check=True, capture_output=True, text=True)
        return {"executor": "osascript", "shortcut": "option+space", "fallback": "new_chat"}

    def _toggle_chatgpt_voice(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.chatgpt_voice_shortcut is None:
            return self._open_chatgpt_new_chat(_)
        modifiers, key = self.chatgpt_voice_shortcut
        using = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
        script = (
            'tell application "ChatGPT" to activate\n'
            'delay 0.4\n'
            f'tell application "System Events" to key code {key}{using}'
        )
        self._runner(["open", "-a", "ChatGPT"], check=True, capture_output=True, text=True)
        self._runner(["osascript", "-e", script], check=True, capture_output=True, text=True)
        return {"executor": "osascript", "shortcut": self.chatgpt_voice_shortcut}

    def _open_llm(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.llm_url is None:
            raise RuntimeError("Set --llm-url before executing llm.open")
        self._runner(["open", self.llm_url], check=True, capture_output=True, text=True)
        return {"executor": "open", "url": self.llm_url}

    @classmethod
    def _validate_shortcut(cls, shortcut: str) -> tuple[list[str], int]:
        parts = [part.strip().lower() for part in shortcut.split("+")]
        if not parts or any(not part for part in parts):
            raise ValueError("Voice shortcut must look like option+shift+space")
        key = parts[-1]
        modifiers = parts[:-1]
        if (
            len(set(modifiers)) != len(modifiers)
            or any(modifier not in cls._MODIFIERS for modifier in modifiers)
            or key not in cls._KEY_CODES
        ):
            raise ValueError("Unsupported voice shortcut; use modifiers plus one letter, digit, or space")
        return [cls._MODIFIERS[modifier] for modifier in modifiers], cls._KEY_CODES[key]

    @staticmethod
    def _validate_llm_url(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("llm_url must be an HTTPS URL")
        return url
