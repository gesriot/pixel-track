from __future__ import annotations

from dataclasses import dataclass

from pixel_track.model import Calibration, Project


@dataclass(slots=True)
class SegmentMetrics:
    from_frame: int
    to_frame: int
    distance_m: float
    dt_s: float
    speed_mps: float
    t_end_s: float


def distance_meters(calibration: Calibration, start: tuple[float, float], end: tuple[float, float]) -> float:
    return calibration.meters_between(start, end)


def build_segment_metrics(project: Project) -> list[SegmentMetrics]:
    metrics: list[SegmentMetrics] = []
    frame_indices = sorted(project.measurements)

    for previous_frame, current_frame in zip(frame_indices, frame_indices[1:]):
        step = project.measurements[current_frame]
        calibration = project.effective_calibration(current_frame)

        if calibration is None or step.previous_point_on_this_frame_px is None:
            continue

        dt_s = (current_frame - previous_frame) / project.fps
        distance_m = distance_meters(
            calibration,
            step.previous_point_on_this_frame_px,
            step.current_point_px,
        )
        speed_mps = distance_m / dt_s if dt_s > 0 else 0.0

        metrics.append(
            SegmentMetrics(
                from_frame=previous_frame,
                to_frame=current_frame,
                distance_m=distance_m,
                dt_s=dt_s,
                speed_mps=speed_mps,
                t_end_s=current_frame / project.fps,
            )
        )

    return metrics
