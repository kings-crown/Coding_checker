# AI Coding Agent for Large TypeScript/Rust Codebases with a Checker

Minimal CLIs that steer an OpenAI model to edit code inside a sandboxed `./workspace` directory. Includes:
- `basic.py` for a Python-only flow.
- `basic_rust.py` for Rust + Kani verification (uses Docker).

## Requirements
- Python 3.10+
- pip packages in `requirements.txt`
- `OPENAI_API_KEY` in your environment (plus optional `CODE_WRITER_*` overrides)
- Docker to build the Kani runner image when using the Rust flow

## Quick start
1) Install deps: `pip install -r requirements.txt`
2) Run the Python agent: `python basic.py`
3) For Rust/Kani: build the image `docker build -t kani-runner:0.66 -f docker/kani.Dockerfile .`, then run `python basic_rust.py`

