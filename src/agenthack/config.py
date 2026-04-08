"""Configuration loading from YAML + env vars."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: Any) -> Any:
    """Replace ${VAR} placeholders with environment variable values."""
    if isinstance(value, str):
        def replacer(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_RE.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


class AppConfig(BaseModel):
    defaults: dict[str, Any] = {}
    models: dict[str, str] = {}
    judge_weights: dict[str, float] = {}
    budget: dict[str, Any] = {}
    scraping: dict[str, Any] = {}


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load agenthack.yaml if it exists, otherwise return defaults."""
    candidates = [path, "agenthack.yaml", Path.home() / ".agenthack.yaml"]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            with open(candidate) as f:
                raw = yaml.safe_load(f) or {}
            raw = _resolve_env(raw)
            return AppConfig(**raw)
    return AppConfig()
