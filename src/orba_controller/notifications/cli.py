from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime


def _emit_event(event_name: str, title: str, message: str) -> None:
    payload = {
        "event": event_name,
        "title": title,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit a local ORBA notification event.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["started", "progress", "completed", "failed", "needs_input", "needs_approval"]:
        subparser = subparsers.add_parser(name, help=f"Emit the {name} event")
        subparser.add_argument("--title", required=True)
        subparser.add_argument("--message", required=True)

    args = parser.parse_args()
    _emit_event(args.command, args.title, args.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
