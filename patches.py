from __future__ import annotations

import subprocess
import json
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import WORKSPACE, UI_SIGNAL_MAX_BYTES, ensure_run_dir, next_patch_id
from paths import _safe_ws_path
from ui_signal import _truncate_signal_text, write_ui_signal

# Track last patch path for approval flow
LAST_PATCH_PATH: Optional[Path] = None


def _paths_from_diff(diff_text: str) -> List[Path]:
    files: List[Path] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            part = line[4:].strip()
            # strip prefixes a/ b/
            if part.startswith("a/") or part.startswith("b/"):
                part = part[2:]
            try:
                p = _safe_ws_path(part)
            except Exception:
                continue
            if p not in files:
                files.append(p)
    return files


def _preview_patch(patch_path: Path, diff_text: str) -> tuple[Optional[List[tuple[Path, str, str]]], Optional[str]]:
    """
    Apply the patch to a temporary copy of the touched files to capture before/after
    without modifying the workspace. Returns (previews, stderr). If previews is None,
    stderr carries the git apply error.
    """
    touched = _paths_from_diff(diff_text)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            for p in touched:
                dst = tmp_root / p.relative_to(WORKSPACE)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if p.exists():
                    shutil.copy2(p, dst)
                else:
                    dst.touch()
            proc = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=tmp_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if proc.returncode != 0:
                return None, proc.stderr
            previews: List[tuple[Path, str, str]] = []
            for p in touched:
                before = p.read_text(encoding="utf-8") if p.exists() else ""
                after_path = tmp_root / p.relative_to(WORKSPACE)
                after = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
                previews.append((p, before, after))
            return previews, None
    except Exception as e:
        return None, str(e)


def propose_patch(diff: str) -> str:
    try:
        run_dir = ensure_run_dir()
        patch_id = next_patch_id()
        patch_path = run_dir / "patches" / f"patch-{patch_id:04d}.diff"
        patch_path.write_text(diff, encoding="utf-8")
        previews, preview_err = _preview_patch(patch_path, diff)
        if previews:
            global LAST_PATCH_PATH
            LAST_PATCH_PATH = patch_path
            for p, before, after in previews:
                write_ui_signal({
                    "event": "file_diff",
                    "path": str(p.relative_to(WORKSPACE)),
                    "abs_path": str(p),
                    "before": _truncate_signal_text(before, UI_SIGNAL_MAX_BYTES),
                    "after": _truncate_signal_text(after, UI_SIGNAL_MAX_BYTES),
                })
        else:
            return json.dumps({
                "ok": False,
                "error": "Patch preview failed (invalid diff or git apply failure).",
                "stderr": preview_err or "",
            })
        return json.dumps({
            "ok": True,
            "patch_id": patch_id,
            "path": str(patch_path),
            "message": "Patch recorded. User must reply 'Yes' to apply the last patch.",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def apply_patch_file(patch_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False, "path": str(patch_path)}
    if not patch_path.exists():
        result["error"] = "Patch file not found"
        return result

    diff_text = patch_path.read_text(encoding="utf-8")
    touched = _paths_from_diff(diff_text)
    before: Dict[Path, str] = {}
    for p in touched:
        if p.exists():
            before[p] = p.read_text(encoding="utf-8")
        else:
            before[p] = ""

    def _run(cmd: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=WORKSPACE,
            text=True,
            input=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    check = _run(["git", "apply", "--check", str(patch_path)])
    if check.returncode != 0:
        result.update({
            "ok": False,
            "error": "git apply --check failed",
            "stderr": check.stderr,
        })
        return result

    apply = _run(["git", "apply", str(patch_path)])
    if apply.returncode != 0:
        result.update({
            "ok": False,
            "error": "git apply failed",
            "stderr": apply.stderr,
        })
        return result

    # Detect no-op applies (e.g., patch already applied or failed silently)
    unchanged = True
    after_info: List[Dict[str, str]] = []
    for p in touched:
        after = p.read_text(encoding="utf-8") if p.exists() else ""
        if after != before.get(p, ""):
            unchanged = False
        after_info.append({"path": str(p), "bytes": len(after.encode("utf-8"))})
        write_ui_signal({
            "event": "file_diff",
            "path": str(p.relative_to(WORKSPACE)),
            "abs_path": str(p),
            "before": _truncate_signal_text(before.get(p, ""), UI_SIGNAL_MAX_BYTES),
            "after": _truncate_signal_text(after, UI_SIGNAL_MAX_BYTES),
        })

    if unchanged:
        result.update({
            "ok": False,
            "error": "Patch applied but resulted in no file changes (possible bad working dir or already applied).",
        })
        return result

    result.update({
        "ok": True,
        "applied": True,
        "files": after_info,
    })
    return result
