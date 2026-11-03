"""Load model and system prompt settings from the configs folder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"
DEFAULT_CONFIG = "default"
_KEYS = ("planner_model", "coder_model", "planner_system_prompt", "coder_system_prompt")


@dataclass(frozen=True)
class Config:
    planner_model: str
    coder_model: str
    planner_system_prompt: str
    coder_system_prompt: str


def load_config(name: str | None = None, directory: Path = CONFIGS_DIR) -> Config:
    name = name or DEFAULT_CONFIG
    if Path(name).name != name:
        raise ValueError(f"Config name must be a file name in the configs folder: {name}")
    path = directory / name
    if not path.suffix:
        path = path.with_suffix(".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Config file not found: {path}") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in config {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Config {path} must be a JSON object")
    for key in _KEYS:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Config {path} must define a non-empty string for '{key}'")
    return Config(**{key: data[key] for key in _KEYS})
