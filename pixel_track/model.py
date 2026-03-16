from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from pathlib import Path

Point = tuple[float, float]


@dataclass(slots=True)
class Calibration:
    p1: Point
    p2: Point
    length_m: float

    @property
    def pixel_length(self) -> float:
        return hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    @property
    def pixels_per_meter(self) -> float:
        if self.length_m <= 0:
            return 0.0
        return self.pixel_length / self.length_m

    def meters_between(self, a: Point, b: Point) -> float:
        ppm = self.pixels_per_meter
        if ppm == 0:
            return 0.0
        return hypot(b[0] - a[0], b[1] - a[1]) / ppm


@dataclass(slots=True)
class FrameOverride:
    calibration: Calibration | None = None


@dataclass(slots=True)
class MeasurementStep:
    frame_index: int
    current_point_px: Point
    previous_point_on_this_frame_px: Point | None = None


@dataclass(slots=True)
class Project:
    frame_paths: list[Path]
    fps: float = 25.0
    source_directory: Path | None = None
    base_calibration: Calibration | None = None
    frame_overrides: dict[int, FrameOverride] = field(default_factory=dict)
    measurements: dict[int, MeasurementStep] = field(default_factory=dict)

    @property
    def frame_count(self) -> int:
        return len(self.frame_paths)

    def get_frame_path(self, index: int) -> Path:
        return self.frame_paths[index]

    def get_or_create_override(self, index: int) -> FrameOverride:
        override = self.frame_overrides.get(index)
        if override is None:
            override = FrameOverride()
            self.frame_overrides[index] = override
        return override

    def effective_calibration(self, index: int) -> Calibration | None:
        for current in range(index, -1, -1):
            override = self.frame_overrides.get(current)
            if override and override.calibration is not None:
                return override.calibration
        return self.base_calibration
