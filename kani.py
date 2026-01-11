from __future__ import annotations

import json
import os
import subprocess
from typing import List, Optional

from config import (
    WORKSPACE,
    KANI_DOCKER_IMAGE,
    KANI_TIMEOUT_SECS,
)
from paths import _safe_ws_dir

_ALLOWED_KANI_ARGS = {
    "--quiet",
    "--verbose",
    "--tests",
    "--harness",
    "--default-unwind",
    "--unwind",
}


def _normalize_project_dir(project_dir: str) -> str:
    p = (project_dir or "").strip()
    p = p.lstrip("./")
    if p.startswith("workspace/"):
        p = p[len("workspace/"):]
    p = p.lstrip("/")
    return p


def _validate_kani_args(args: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a not in _ALLOWED_KANI_ARGS:
            raise ValueError(f"Disallowed kani arg: {a}")

        if a in {"--harness", "--default-unwind", "--unwind"}:
            if i + 1 >= len(args):
                raise ValueError(f"{a} requires a value")
            out.extend([a, args[i + 1]])
            i += 2
            continue

        out.append(a)
        i += 1
    return out


def init_rust_crate(project_dir: str, crate_name: Optional[str] = None, lib: bool = True) -> str:
    try:
        project_dir = _normalize_project_dir(project_dir)
        proj = _safe_ws_dir(project_dir)

        name = crate_name or os.path.basename(project_dir)
        if not name or not name.replace("_", "").isalnum():
            return json.dumps({"ok": False, "error": f"Invalid crate name: {name}", "project_dir": project_dir})

        (proj / "src").mkdir(parents=True, exist_ok=True)
        cargo_toml = proj / "Cargo.toml"

        if lib:
            entry = proj / "src" / "lib.rs"
            entry_rel = "src/lib.rs"
            cargo_kind = '[lib]\npath = "src/lib.rs"\n'
            default_src = "pub fn placeholder() -> i32 { 0 }\n"
        else:
            entry = proj / "src" / "main.rs"
            entry_rel = "src/main.rs"
            cargo_kind = ""
            default_src = 'fn main() { println!("hello"); }\n'

        created = {"Cargo.toml": False, entry_rel: False}

        if not cargo_toml.exists():
            cargo_toml.write_text(
                f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

{cargo_kind}""",
                encoding="utf-8",
            )
            created["Cargo.toml"] = True

        if not entry.exists():
            entry.write_text(default_src, encoding="utf-8")
            created[entry_rel] = True

        return json.dumps({"ok": True, "project_dir": project_dir, "path": str(proj), "created": created})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "project_dir": project_dir})


def run_kani(project_dir: str, args: Optional[List[str]] = None) -> str:
    try:
        project_dir = _normalize_project_dir(project_dir)

        init_res = json.loads(init_rust_crate(project_dir))
        if not init_res.get("ok"):
            return json.dumps(init_res)

        proj = _safe_ws_dir(project_dir)
        cargo_toml = proj / "Cargo.toml"
        if not cargo_toml.exists():
            return json.dumps({
                "ok": False,
                "error": f"Cargo.toml not found at {cargo_toml}",
                "project_dir": project_dir,
            })

        safe_args = _validate_kani_args(args or [])

        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "512",
            "--memory", "6g",
            "--cpus", "2",
            # keep default user (root) for cached toolchain

            "-e", "HOME=/root",
            "-e", "RUSTUP_HOME=/root/.rustup",
            "-e", "CARGO_HOME=/root/.cargo",
            "-e", "RUSTUP_TOOLCHAIN=stable",

            "-e", "CARGO_TARGET_DIR=/tmp/target",
            "-e", "CARGO_NET_OFFLINE=true",

            "-v", f"{WORKSPACE}:/work",
            "-w", f"/work/{project_dir}",

            KANI_DOCKER_IMAGE,
            "cargo", "kani",
        ] + safe_args

        proc = subprocess.run(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=KANI_TIMEOUT_SECS,
        )

        return json.dumps({
            "ok": True,
            "project_dir": project_dir,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-20000:],
        })

    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "Kani timed out", "project_dir": project_dir})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "project_dir": project_dir})
