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
    frame_indices = sorted(
        index
        for index, step in project.measurements.items()
        if step.current_point_px is not None
    )

    for current_frame in frame_indices[1:]:
        current_metrics = segment_metrics_for_frame(project, current_frame)
        if current_metrics is not None:
            metrics.append(current_metrics)

    return metrics


def segment_metrics_for_frame(project: Project, frame_index: int) -> SegmentMetrics | None:
    step = project.measurements.get(frame_index)
    calibration = project.effective_calibration(frame_index)

    if (
        step is None
        or calibration is None
        or step.previous_point_on_this_frame_px is None
        or step.current_point_px is None
    ):
        return None

    previous_frame_indices = [
        index
        for index, previous_step in project.measurements.items()
        if index < frame_index and previous_step.current_point_px is not None
    ]
    if not previous_frame_indices:
        return None

    previous_frame = max(previous_frame_indices)
    dt_s = (frame_index - previous_frame) / project.fps
    distance_m = distance_meters(
        calibration,
        step.previous_point_on_this_frame_px,
        step.current_point_px,
    )
    speed_mps = distance_m / dt_s if dt_s > 0 else 0.0

    return SegmentMetrics(
        from_frame=previous_frame,
        to_frame=frame_index,
        distance_m=distance_m,
        dt_s=dt_s,
        speed_mps=speed_mps,
        t_end_s=frame_index / project.fps,
    )


def speed_series(metrics: list[SegmentMetrics]) -> tuple[list[float], list[float]]:
    return [metric.t_end_s for metric in metrics], [metric.speed_mps for metric in metrics]
