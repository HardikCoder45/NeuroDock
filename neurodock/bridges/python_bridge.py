#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time


def emit(event_type: str, data: dict) -> None:
    sys.stdout.write(json.dumps({"type": event_type, "data": data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    agent_id = payload.get("agent", {}).get("id", "python-agent")
    emit("agent.run.in_progress", {"status": "running", "adapter": "python-bridge"})
    text = f"Python bridge placeholder for {agent_id}. Replace this bridge with a framework-native adapter."
    emit("agent.text.delta", {"item_id": "msg_1", "content_index": 0, "delta": text, "role": "assistant", "modality": "text"})
    emit("agent.text.done", {"item_id": "msg_1", "text": text, "role": "assistant", "finish_reason": "bridge_placeholder"})
    emit("agent.final", {"output": text, "messages": [], "artifacts": [], "finish_reason": "bridge_placeholder"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
