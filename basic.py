from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI


# -------------------- config --------------------

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
WORKSPACE = Path(os.getenv("CODE_WRITER_WORKSPACE", "./workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

MAX_BYTES = int(os.getenv("CODE_WRITER_MAX_BYTES", "200000"))  # cap per write


# -------------------- safety helpers --------------------

def _safe_py_path(rel_path: str) -> Path:

    p = Path(rel_path)

    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed.")
    if ".." in p.parts:
        raise ValueError("Path traversal ('..') is not allowed.")
    if p.suffix.lower() != ".py":
        raise ValueError("Only .py files are allowed.")

    resolved = (WORKSPACE / p).resolve()
    if resolved != WORKSPACE and WORKSPACE not in resolved.parents:
        raise ValueError("Path escapes workspace.")
    return resolved


def read_python_file(path: str) -> str:
    try:
        fp = _safe_py_path(path)
        if not fp.exists():
            return json.dumps({"ok": False, "error": "File not found", "path": path})
        content = fp.read_text(encoding="utf-8")
        return json.dumps({"ok": True, "path": path, "content": content})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path})


def write_python_file(path: str, content: str, overwrite: bool = False) -> str:
    try:
        fp = _safe_py_path(path)

        if fp.exists() and not overwrite:
            return json.dumps({
                "ok": False,
                "error": "File exists; set overwrite=true to replace it.",
                "path": path
            })

        data = content.encode("utf-8")
        if len(data) > MAX_BYTES:
            return json.dumps({
                "ok": False,
                "error": f"Content too large ({len(data)} bytes > {MAX_BYTES}).",
                "path": path
            })

        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "path": path, "bytes_written": len(data)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path})

# -------------------- tool definitions --------------------
TOOLS = [
    {
        "type": "function",
        "name": "read_python_file",
        "description": "Read a .py file from the local ./workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path under ./workspace, e.g. 'app/main.py'",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_python_file",
        "description": "Write a .py file under local ./workspace. Does NOT execute code.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative .py path under ./workspace, e.g. 'app/main.py'",
                },
                "content": {
                    "type": "string",
                    "description": "Full file contents to write",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite if file already exists (default false)",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, args: Dict[str, Any]) -> str:
    if name == "read_python_file":
        return read_python_file(path=str(args["path"]))
    if name == "write_python_file":
        return write_python_file(
            path=str(args["path"]),
            content=str(args["content"]),
            overwrite=bool(args.get("overwrite", False)),
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


def main() -> int:
    client = OpenAI()
    usage = Usage()

    instructions = (
        "You are a coding assistant.\n"
        f"You may ONLY read/write Python files via the provided tools, and ONLY under {WORKSPACE}.\n"
        "Never ask to run shell commands. Never suggest executing code.\n"
        "When you need to create or modify code, use write_python_file with full file contents.\n"
        "Avoid overwriting existing files unless necessary; prefer overwrite=false.\n"
        "After tool calls are done, explain what you wrote/changed and which files.\n"
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

        for _ in range(10):
            response = client.responses.create(
                model=DEFAULT_MODEL,
                instructions=instructions,
                tools=TOOLS,
                input=input_items,
            )
            usage.add_from_response(response)

            input_items += response.output

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if tool_calls:
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = call_tool(tc.name, args)

                    input_items.append({
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": result,
                    })
                continue

            print(response.output_text)
            break

        print(f"\n[tokens] ↑ {usage.input_tokens} ↓ {usage.output_tokens}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
