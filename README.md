# AI Coding Agent for Large TypeScript/Rust Codebases with a Checker

Minimal CLIs that steer an OpenAI model to edit code inside a sandboxed `./workspace` directory. Now modularized:
- `basic.py` for a Python-only flow.
- `basic_rust.py` for Rust + Kani verification (uses Docker), built on modules:
  - `config.py`, `paths.py`, `ui_signal.py`, `files.py`, `patches.py`, `kani.py`

## Requirements
- Python 3.10+
- pip packages in `requirements.txt`
- `OPENAI_API_KEY` in your environment (plus optional `CODE_WRITER_*` overrides)
- Docker to build the Kani runner image when using the Rust flow

## Quick start
1) Install deps: `pip install -r requirements.txt`
2) Run the Python agent: `python basic.py`
3) For Rust/Kani: build the image `docker build -t kani-runner:0.66 -f docker/kani.Dockerfile .`, then run `python basic_rust.py`

## Patch + approval workflow (Rust agent)
- Edits must be proposed as unified diffs via the `propose_patch` tool. The model does **not** apply patches itself.
- The CLI shows the latest proposed patch; type `Yes` in the REPL to apply the last patch after reviewing.
- Existing files: require `propose_patch` + approval. New files: allowed via `write_file`.
- Patch application uses `git apply --check` then `git apply`; failures are surfaced to the REPL.
- After a successful apply, the agent emits `.coding_checker/ui.signal.json` events so the VS Code extension opens before/after diffs automatically.
- Invalid patches are rejected before approval (preview/dry-run git apply); `Yes` only applies a validated patch.

## Run directory layout
- Each run creates `runs/run-<Day-YYYYMMDD>-<unix>[-<tag>]` (tag set via `CODE_WRITER_RUN_TAG`).
- Inside: `patches/patch-XXXX.diff` plus `patch-XXXX.apply.out/err` logs, and `metadata.json` describing the session (model, workspace, env).
- Patch IDs increment per run; `Yes` applies the most recent patch.

## Quick test of the patch flow (manual)
1) Start the Rust agent in VS Code terminal: `python basic_rust.py`
2) Prompt it to edit an existing file (e.g., tweak a comment in `workspace/demo/src/lib.rs`); it should call `propose_patch` and print the patch path.
3) Type `Yes` in the REPL to apply; confirm the VS Code diff opens and the file is updated.
4) For a new file, ask it to create one; it should use `write_file` and succeed without approval.

