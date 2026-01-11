from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Workspace and run directories
WORKSPACE = Path(os.getenv("CODE_WRITER_WORKSPACE", "./workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

RUN_ROOT = Path(os.getenv("CODE_WRITER_RUN_ROOT", Path(__file__).resolve().parent / "runs")).resolve()
RUN_ROOT.mkdir(parents=True, exist_ok=True)

# Model / limits
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
MAX_BYTES = int(os.getenv("CODE_WRITER_MAX_BYTES", "200000"))
MAX_AGENT_TURNS = int(os.getenv("CODE_WRITER_MAX_AGENT_TURNS", "15"))
MAX_KANI_TRIES = int(os.getenv("CODE_WRITER_MAX_KANI_TRIES", "3"))
KANI_DOCKER_IMAGE = os.getenv("KANI_DOCKER_IMAGE", "kani-runner:0.66")
KANI_TIMEOUT_SECS = int(os.getenv("KANI_TIMEOUT_SECS", "300"))

# UI signal limits
UI_SIGNAL_MAX_BYTES = int(os.getenv("CODE_WRITER_UI_SIGNAL_MAX_BYTES", "400000"))

# Patch approval
REQUIRE_APPROVAL = True  # explicit "Yes" to apply

RUN_DIR: Optional[Path] = None
PATCH_COUNTER = 0


def ensure_run_dir() -> Path:
    global RUN_DIR
    if RUN_DIR is not None:
        return RUN_DIR
    tag_env = os.getenv("CODE_WRITER_RUN_TAG")
    ts = int(time.time())
    day_date = time.strftime("%a-%Y%m%d")
    slug = f"{day_date}-{ts}"
    if tag_env:
        slug = f"{slug}-{tag_env}"
    RUN_DIR = RUN_ROOT / f"run-{slug}"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "patches").mkdir(parents=True, exist_ok=True)
    return RUN_DIR


def next_patch_id() -> int:
    global PATCH_COUNTER
    PATCH_COUNTER += 1
    return PATCH_COUNTER
