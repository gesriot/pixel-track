from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QImageReader


_NATURAL_SPLIT_RE = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts = _NATURAL_SPLIT_RE.split(value.casefold())
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def supported_image_suffixes() -> set[str]:
    return {f".{bytes(fmt).decode('ascii').lower()}" for fmt in QImageReader.supportedImageFormats()}


def collect_frame_paths(directory: Path) -> list[Path]:
    suffixes = supported_image_suffixes()
    frame_paths = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    ]
    return sorted(frame_paths, key=lambda path: natural_sort_key(path.name))
