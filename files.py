from __future__ import annotations

import json
from pathlib import Path

from config import MAX_BYTES, REQUIRE_APPROVAL
from paths import _safe_ws_path
from ui_signal import _truncate_signal_text, write_ui_signal


def read_file(path: str) -> str:
    try:
        fp = _safe_ws_path(path)
        if not fp.exists():
            return json.dumps({"ok": False, "error": "File not found", "path": path})
        return json.dumps({"ok": True, "path": path, "content": fp.read_text(encoding="utf-8")})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path})


def write_file(path: str, content: str, overwrite: bool = False) -> str:
    try:
        fp = _safe_ws_path(path)

        before = ""
        if fp.exists():
            before = fp.read_text(encoding="utf-8")

        if fp.exists() and REQUIRE_APPROVAL:
            return json.dumps({
                "ok": False,
                "error": "File exists. Use propose_patch + approval instead of write_file.",
                "path": path,
            })
        if fp.exists() and not overwrite:
            return json.dumps({"ok": False, "error": "File exists; set overwrite=true.", "path": path})

        data = content.encode("utf-8")
        if len(data) > MAX_BYTES:
            return json.dumps({"ok": False, "error": f"Too large ({len(data)}>{MAX_BYTES}).", "path": path})

        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

        write_ui_signal({
            "event": "file_diff",
            "path": path,
            "abs_path": str(fp),
            "before": _truncate_signal_text(before),
            "after": _truncate_signal_text(content),
        })
        return json.dumps({"ok": True, "path": path, "bytes_written": len(data)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path})
