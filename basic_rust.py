from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


# -------------------- config --------------------

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

WORKSPACE = Path(os.getenv("CODE_WRITER_WORKSPACE", "./workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

MAX_BYTES = int(os.getenv("CODE_WRITER_MAX_BYTES", "200000"))  # cap per write
MAX_AGENT_TURNS = int(os.getenv("CODE_WRITER_MAX_AGENT_TURNS", "15"))
MAX_KANI_TRIES = int(os.getenv("CODE_WRITER_MAX_KANI_TRIES", "3"))

KANI_DOCKER_IMAGE = os.getenv("KANI_DOCKER_IMAGE", "kani-runner:0.66")
KANI_TIMEOUT_SECS = int(os.getenv("KANI_TIMEOUT_SECS", "300"))

ALLOWED_SUFFIXES = {".py", ".rs", ".toml", ".lock", ".md", ".txt"}

_ALLOWED_KANI_ARGS = {
    "--quiet",
    "--verbose",
    "--tests",
    "--harness",
    "--default-unwind",
    "--unwind",
}


# -------------------- path safety helpers --------------------

def _normalize_project_dir(project_dir: str) -> str:
    """
    Normalize project_dir so the model can pass:
      - "demo"
      - "./demo"
      - "workspace/demo"
    and we always resolve it under WORKSPACE as "demo".
    """
    p = (project_dir or "").strip()
    p = p.lstrip("./")
    if p.startswith("workspace/"):
        p = p[len("workspace/"):]
    # remove any leading slashes accidentally included
    p = p.lstrip("/")
    return p


def _safe_ws_path(rel_path: str) -> Path:
    p = Path(rel_path)

    if p.is_absolute() or p.drive:
        raise ValueError("Absolute/drive paths are not allowed.")
    if ".." in p.parts:
        raise ValueError("Path traversal ('..') is not allowed.")
    if not p.suffix:
        raise ValueError("Path must include a file extension.")
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"File type not allowed: {p.suffix}")

    resolved = (WORKSPACE / p).resolve()
    try:
        resolved.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("Path escapes workspace.")
    return resolved


def _safe_ws_dir(rel_dir: str) -> Path:
    p = Path(rel_dir)

    if p.is_absolute() or p.drive:
        raise ValueError("Absolute/drive paths are not allowed.")
    if ".." in p.parts:
        raise ValueError("Path traversal ('..') is not allowed.")

    resolved = (WORKSPACE / p).resolve()
    try:
        resolved.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("Path escapes workspace.")
    return resolved


# -------------------- file tools --------------------

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

        if fp.exists() and not overwrite:
            return json.dumps({"ok": False, "error": "File exists; set overwrite=true.", "path": path})

        data = content.encode("utf-8")
        if len(data) > MAX_BYTES:
            return json.dumps({"ok": False, "error": f"Too large ({len(data)}>{MAX_BYTES}).", "path": path})

        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "path": path, "bytes_written": len(data)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path})


# -------------------- rust crate init tool --------------------

def init_rust_crate(project_dir: str, crate_name: Optional[str] = None, lib: bool = True) -> str:
    try:
        project_dir = _normalize_project_dir(project_dir)
        proj = _safe_ws_dir(project_dir)

        name = crate_name or Path(project_dir).name
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


# -------------------- kani tool --------------------

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
        uid, gid = os.getuid(), os.getgid()

        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "512",
            "--memory", "6g",
            "--cpus", "2",
            "--user", f"{uid}:{gid}",
            "--tmpfs", "/tmp:exec,size=4g",

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


# -------------------- tool definitions --------------------

TOOLS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a file from the local ./workspace directory (allowed: .py, .rs, .toml, .lock, .md, .txt).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path under ./workspace, e.g. 'demo/src/lib.rs'"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write a file under local ./workspace. Does NOT execute code.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path under ./workspace"},
                "content": {"type": "string", "description": "Full file contents to write"},
                "overwrite": {"type": "boolean", "description": "Overwrite if file exists (default false)"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "init_rust_crate",
        "description": "Create/ensure a minimal Rust crate exists under ./workspace/<project_dir> with Cargo.toml and src/lib.rs (or main.rs).",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
                "crate_name": {"type": ["string", "null"]},
                "lib": {"type": "boolean", "description": "Create a library crate (default true)."},
            },
            "required": ["project_dir"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "run_kani",
        "description": "Run `cargo kani` for a Rust project inside a sandboxed Docker container (offline, network none).",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": "Relative dir under ./workspace containing Cargo.toml, e.g. 'demo'"},
                "args": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Optional allowlisted cargo-kani args"},
            },
            "required": ["project_dir"],
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, args: Dict[str, Any]) -> str:
    if name == "read_file":
        return read_file(path=str(args["path"]))
    if name == "write_file":
        return write_file(
            path=str(args["path"]),
            content=str(args["content"]),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "init_rust_crate":
        return init_rust_crate(
            project_dir=str(args["project_dir"]),
            crate_name=args.get("crate_name"),
            lib=bool(args.get("lib", True)),
        )
    if name == "run_kani":
        return run_kani(
            project_dir=str(args["project_dir"]),
            args=args.get("args"),
        )
    return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})


# -------------------- CLI loop --------------------

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add_from_response(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        if not u:
            return
        self.input_tokens += int(getattr(u, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(u, "output_tokens", 0) or 0)


def debug_print_response(response: Any) -> None:
    print("\n=== RAW RESPONSE JSON ===")
    print(response.model_dump_json(indent=2))

    print("\n=== OUTPUT ITEMS ===")
    for i, item in enumerate(response.output):
        print(f"[{i}] type={item.type}")
        if item.type == "function_call":
            print(f"    name={item.name}")
            print(f"    call_id={item.call_id}")
            print(f"    arguments={item.arguments}")
        elif item.type == "message":
            for block in item.content:
                if block.type == "output_text":
                    print("    text:", block.text)


def main() -> int:
    client = OpenAI()
    usage = Usage()

    instructions = (
        "You are a Rust coding assistant.\n"
        f"You may ONLY read/write files via read_file/write_file under {WORKSPACE}.\n"
        "You may ONLY execute verification via run_kani (which runs `cargo kani` in Docker).\n"
        "Never ask the user to run shell commands.\n"
        f"You have at most {MAX_KANI_TRIES} total run_kani attempts per user request.\n"
        "Workflow you MUST follow:\n"
        "0) Call init_rust_crate(project_dir=...) before writing Rust files.\n"
        "1) Write/modify Rust code + Kani proof harnesses.\n"
        "2) Call run_kani.\n"
        "3) If verification fails, use the failure output to fix the code/harness/spec and re-run.\n"
        "4) Stop when run_kani returns passed=true, then explain what you changed and what is proven.\n"
        "When you write files, always use write_file with full file contents.\n"
        "When calling run_kani, pass project_dir like 'demo' (NOT 'workspace/demo').\n"
    )

    input_items: List[Dict[str, Any]] = []

    print(f"Workspace: {WORKSPACE}")
    print("Type '/clear' to reset, 'exit' to quit.\n")

    while True:
        user = input("> ").strip()
        if not user:
            continue
        if user == "exit":
            break
        if user == "/clear":
            input_items = []
            usage = Usage()
            print("(cleared)\n")
            continue

        input_items.append({"role": "user", "content": user})
        kani_tries = 0

        for _ in range(MAX_AGENT_TURNS):
            response = client.responses.create(
                model=DEFAULT_MODEL,
                instructions=instructions,
                tools=TOOLS,
                input=input_items,
            )
            usage.add_from_response(response)

            # debug_print_response(response)

            input_items += response.output

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if tool_calls:
                stop_due_to_limit = False

                for tc in tool_calls:
                    # Parse arguments robustly
                    try:
                        raw_args = tc.arguments
                        if isinstance(raw_args, str):
                            args = json.loads(raw_args or "{}")
                        elif isinstance(raw_args, dict):
                            args = raw_args
                        else:
                            args = {}
                    except Exception:
                        args = {}

                    if tc.name == "run_kani":
                        kani_tries += 1
                        if kani_tries > MAX_KANI_TRIES:
                            msg = (
                                f"Stopping: exceeded MAX_KANI_TRIES={MAX_KANI_TRIES}. "
                                "Last run_kani output is above. "
                                "Suggest revising the spec/harness or increasing the limit."
                            )
                            input_items.append({"role": "assistant", "content": msg})
                            print(msg)
                            stop_due_to_limit = True
                            break

                    result = call_tool(tc.name, args)

                    if tc.name == "run_kani":
                        print("\n=== run_kani OUTPUT ===")
                        try:
                            print(json.dumps(json.loads(result), indent=2))
                        except Exception:
                            print(result)

                    input_items.append({
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": result,
                    })

                if stop_due_to_limit:
                    break
                continue

            print(response.output_text)
            break

        print(f"\n[tokens] ↑ {usage.input_tokens} ↓ {usage.output_tokens}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
