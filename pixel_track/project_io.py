from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pixel_track.analysis import SegmentMetrics
from pixel_track.model import Calibration, FrameOverride, MeasurementStep, Project


PROJECT_VERSION = 1


def save_project(project: Project, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PROJECT_VERSION,
        "fps": _serialize_fps(project.fps),
        "source_directory": _serialize_path_reference(project.source_directory, destination.parent),
        "frame_paths": [
            _serialize_frame_path(frame_path, project.source_directory, destination.parent)
            for frame_path in project.frame_paths
        ],
        "base_calibration": _serialize_calibration(project.base_calibration),
        "frame_overrides": {
            str(index): _serialize_frame_override(override)
            for index, override in sorted(project.frame_overrides.items())
        },
        "measurements": {
            str(index): _serialize_measurement(step)
            for index, step in sorted(project.measurements.items())
        },
    }
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_project(source: Path) -> Project:
    payload = json.loads(source.read_text(encoding="utf-8"))
    version = payload.get("version")
    if version != PROJECT_VERSION:
        raise ValueError(f"Unsupported project version: {version}")

    source_directory = _deserialize_path_reference(
        payload.get("source_directory"),
        source.parent,
    )
    frame_paths = [
        _deserialize_frame_path(source, source_directory, entry)
        for entry in payload.get("frame_paths", [])
    ]

    project = Project(
        frame_paths=frame_paths,
        fps=_deserialize_fps(payload.get("fps")),
        source_directory=source_directory,
    )
    project.base_calibration = _deserialize_calibration(payload.get("base_calibration"))

    for index_str, override_payload in payload.get("frame_overrides", {}).items():
        project.frame_overrides[int(index_str)] = _deserialize_frame_override(override_payload)

    for index_str, measurement_payload in payload.get("measurements", {}).items():
        project.measurements[int(index_str)] = _deserialize_measurement(measurement_payload)

    return project


def export_metrics_csv(metrics: list[SegmentMetrics], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "from_frame",
                "to_frame",
                "t_end_s",
                "dt_s",
                "distance_m",
                "speed_mps",
            ]
        )
        for metric in metrics:
            writer.writerow(
                [
                    metric.from_frame + 1,
                    metric.to_frame + 1,
                    f"{metric.t_end_s:.6f}",
                    f"{metric.dt_s:.6f}",
                    f"{metric.distance_m:.6f}",
                    f"{metric.speed_mps:.6f}",
                ]
            )


def _serialize_path_reference(
    path: Path | None,
    project_directory: Path,
) -> dict[str, Any] | None:
    if path is None:
        return None

    if path.is_relative_to(project_directory):
        return {"path": path.relative_to(project_directory).as_posix(), "relative_to": "project"}

    return {"path": str(path), "relative_to": "absolute"}


def _deserialize_path_reference(
    payload: dict[str, Any] | str | None,
    project_directory: Path,
) -> Path | None:
    if payload is None:
        return None

    if isinstance(payload, str):
        stored_path = Path(payload)
        return stored_path if stored_path.is_absolute() else project_directory / stored_path

    stored_path = Path(payload["path"])
    relative_to = payload.get("relative_to", "absolute")
    if relative_to == "project":
        return project_directory / stored_path
    if stored_path.is_absolute():
        return stored_path
    return project_directory / stored_path


def _serialize_frame_path(
    frame_path: Path,
    source_directory: Path | None,
    project_directory: Path,
) -> dict[str, Any]:
    if source_directory is not None and frame_path.is_relative_to(source_directory):
        return {"path": frame_path.relative_to(source_directory).as_posix(), "relative_to": "source"}
    if frame_path.is_relative_to(project_directory):
        return {"path": frame_path.relative_to(project_directory).as_posix(), "relative_to": "project"}
    return {"path": str(frame_path), "relative_to": "absolute"}


def _deserialize_frame_path(
    project_path: Path,
    source_directory: Path | None,
    payload: dict[str, Any],
) -> Path:
    stored_path = Path(payload["path"])
    if payload.get("relative_to_source") and source_directory is not None:
        return source_directory / stored_path
    relative_to = payload.get("relative_to")
    if relative_to == "source" and source_directory is not None:
        return source_directory / stored_path
    if relative_to == "project":
        return project_path.parent / stored_path
    if stored_path.is_absolute():
        return stored_path
    return project_path.parent / stored_path


def _serialize_calibration(calibration: Calibration | None) -> dict[str, Any] | None:
    if calibration is None:
        return None
    return {
        "p1": [calibration.p1[0], calibration.p1[1]],
        "p2": [calibration.p2[0], calibration.p2[1]],
        "length_m": calibration.length_m,
    }


def _deserialize_calibration(payload: dict[str, Any] | None) -> Calibration | None:
    if payload is None:
        return None
    return Calibration(
        p1=_deserialize_point(payload.get("p1")),
        p2=_deserialize_point(payload.get("p2")),
        length_m=float(payload.get("length_m", 0.0)),
    )


def _serialize_frame_override(override: FrameOverride) -> dict[str, Any]:
    return {"calibration": _serialize_calibration(override.calibration)}


def _deserialize_frame_override(payload: dict[str, Any]) -> FrameOverride:
    return FrameOverride(calibration=_deserialize_calibration(payload.get("calibration")))


def _serialize_measurement(step: MeasurementStep) -> dict[str, Any]:
    return {
        "frame_index": step.frame_index,
        "current_point_px": _serialize_point(step.current_point_px),
        "previous_point_on_this_frame_px": _serialize_point(step.previous_point_on_this_frame_px),
        "previous_point_is_auto": step.previous_point_is_auto,
    }


def _deserialize_measurement(payload: dict[str, Any]) -> MeasurementStep:
    return MeasurementStep(
        frame_index=int(payload.get("frame_index", 0)),
        current_point_px=_deserialize_point(payload.get("current_point_px")),
        previous_point_on_this_frame_px=_deserialize_point(
            payload.get("previous_point_on_this_frame_px")
        ),
        previous_point_is_auto=bool(payload.get("previous_point_is_auto", False)),
    )


def _serialize_point(point: tuple[float, float] | None) -> list[float] | None:
    if point is None:
        return None
    return [float(point[0]), float(point[1])]


def _deserialize_point(payload: list[float] | None) -> tuple[float, float] | None:
    if payload is None:
        return None
    return float(payload[0]), float(payload[1])


def _serialize_fps(value: float) -> float:
    return value if value > 0 else 25.0


def _deserialize_fps(value: Any) -> float:
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return 25.0
    return fps if fps > 0 else 25.0
