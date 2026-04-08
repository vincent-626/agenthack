"""File I/O helpers for structured output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if isinstance(data, BaseModel):
            f.write(data.model_dump_json(indent=2))
        elif isinstance(data, list) and data and isinstance(data[0], BaseModel):
            f.write(json.dumps([item.model_dump() for item in data], indent=2))
        else:
            json.dump(data, f, indent=2)


def write_md(path: str | Path, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def read_json(path: str | Path) -> Any:
    with open(path) as f:
        return json.load(f)


def read_md(path: str | Path) -> str:
    with open(path) as f:
        return f.read()
