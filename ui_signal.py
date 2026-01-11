from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from config import UI_SIGNAL_MAX_BYTES

SCRIPT_DIR = Path(__file__).resolve().parent
UI_SIGNAL_DIR = SCRIPT_DIR / ".coding_checker"
UI_SIGNAL_FILE = UI_SIGNAL_DIR / "ui.signal.json"


def _truncate_signal_text(text: str, max_bytes: int = UI_SIGNAL_MAX_BYTES) -> str:
    if not text:
        return ""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    clipped = data[:max_bytes].decode("utf-8", errors="ignore")
    return clipped + "\n...[truncated]\n"


def write_ui_signal(payload: Dict[str, Any]) -> None:
    try:
        if not (os.getenv("VSCODE_PID") or os.getenv("TERM_PROGRAM") == "vscode"):
            return
        UI_SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            **payload,
            "time": time.time(),
            "pid": os.getpid(),
        }
        UI_SIGNAL_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
