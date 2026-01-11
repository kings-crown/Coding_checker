from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from openai import OpenAI

import config
from files import read_file, write_file
from patches import propose_patch, apply_patch_file, LAST_PATCH_PATH
from kani import init_rust_crate, run_kani


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
        "description": "Write a file under local ./workspace. Intended for new files; existing files require propose_patch + user approval.",
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
        "name": "propose_patch",
        "description": "Propose a unified diff patch. The user must reply 'Yes' to apply the last patch. Do NOT apply yourself.",
        "parameters": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "Unified diff to apply relative to workspace root."},
            },
            "required": ["diff"],
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
    if name == "propose_patch":
        return propose_patch(diff=str(args["diff"]))
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


def main() -> int:
    client = OpenAI()
    usage = Usage()
    run_dir = config.ensure_run_dir()

    instructions = (
        "You are a Rust coding assistant.\n"
        f"You may ONLY read/write files via read_file/write_file under {config.WORKSPACE}.\n"
        "You may ONLY execute verification via run_kani (which runs `cargo kani` in Docker).\n"
        "Never ask the user to run shell commands.\n"
        f"You have at most {config.MAX_KANI_TRIES} total run_kani attempts per user request.\n"
        "Workflow you MUST follow:\n"
        "0) Call init_rust_crate(project_dir=...) before writing Rust files.\n"
        "1) For existing files, propose unified diffs via propose_patch. Do NOT apply patches; wait for user approval.\n"
        "2) For brand-new files, you may use write_file (if file does not yet exist).\n"
        "3) After code changes are applied, call run_kani.\n"
        "4) If verification fails, use the failure output to fix the code/harness/spec and re-run.\n"
        "5) Stop when run_kani returns passed=true, then explain what you changed and what is proven.\n"
        "When calling run_kani, pass project_dir like 'demo' (NOT 'workspace/demo').\n"
    )

    input_items: List[Dict[str, Any]] = []
    print(f"Run dir: {run_dir}")
    print(f"Workspace: {config.WORKSPACE}")
    print("Type '/clear' to reset, 'exit' to quit. Type 'Yes' to apply the last valid patch.\n")

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
        if user.lower() == "yes":
            from patches import LAST_PATCH_PATH as _LAST
            if _LAST is None:
                print("No pending patch to apply.\n")
                continue
            print(f"Applying last patch: {_LAST}")
            apply_res = apply_patch_file(_LAST)
            print(json.dumps(apply_res, indent=2))
            if apply_res.get("ok"):
                from patches import LAST_PATCH_PATH
                LAST_PATCH_PATH = None
            input_items.append({
                "role": "assistant",
                "content": f"Patch applied: {json.dumps(apply_res)}",
            })
            continue

        input_items.append({"role": "user", "content": user})
        kani_tries = 0

        for _ in range(config.MAX_AGENT_TURNS):
            response = client.responses.create(
                model=config.DEFAULT_MODEL,
                instructions=instructions,
                tools=TOOLS,
                input=input_items,
            )
            usage.add_from_response(response)

            input_items += response.output

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if tool_calls:
                stop_due_to_limit = False

                for tc in tool_calls:
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
                        if kani_tries > config.MAX_KANI_TRIES:
                            msg = (
                                f"Stopping: exceeded MAX_KANI_TRIES={config.MAX_KANI_TRIES}. "
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
