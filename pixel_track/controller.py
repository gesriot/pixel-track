from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pixel_track.analysis import SegmentMetrics, build_segment_metrics, segment_metrics_for_frame
from pixel_track.model import Calibration, MeasurementStep, Point, Project


class ToolMode(str, Enum):
    NAVIGATE = "navigate"
    CALIBRATE = "calibrate"
    MARK_PREVIOUS = "mark_previous"
    MARK_CURRENT = "mark_current"
    EDIT_HANDLES = "edit_handles"


class ProjectController(QObject):
    frame_changed = Signal(int)
    project_changed = Signal(object)
    mode_changed = Signal(str)
    fps_changed = Signal(float)
    calibration_changed = Signal(object)
    measurement_changed = Signal(object)
    metrics_changed = Signal(object)
    history_changed = Signal(object)

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._current_frame_index = 0
        self._tool_mode = ToolMode.NAVIGATE

    @property
    def project(self) -> Project:
        return self._project

    @property
    def current_frame_index(self) -> int:
        return self._current_frame_index

    @property
    def tool_mode(self) -> ToolMode:
        return self._tool_mode

    def current_calibration(self) -> Calibration | None:
        return self._project.effective_calibration(self._current_frame_index)

    def current_measurement(self) -> MeasurementStep | None:
        return self._project.measurements.get(self._current_frame_index)

    def current_segment_metrics(self) -> SegmentMetrics | None:
        return segment_metrics_for_frame(self._project, self._current_frame_index)

    def segment_metrics_history(self) -> list[SegmentMetrics]:
        return build_segment_metrics(self._project)

    def previous_measured_frame_index(self, frame_index: int | None = None) -> int | None:
        current_index = self._current_frame_index if frame_index is None else frame_index
        previous_frame_indices = [
            index
            for index, step in self._project.measurements.items()
            if index < current_index and step.current_point_px is not None
        ]
        if not previous_frame_indices:
            return None
        return max(previous_frame_indices)

    def current_calibration_source_index(self) -> int | None:
        for current in range(self._current_frame_index, -1, -1):
            override = self._project.frame_overrides.get(current)
            if override and override.calibration is not None:
                return current
        return None

    def current_frame_path(self) -> Path | None:
        if self._project.frame_count == 0:
            return None
        return self._project.get_frame_path(self._current_frame_index)

    def load_frames(self, frame_paths: list[Path], source_directory: Path | None = None) -> None:
        project = Project(
            frame_paths=list(frame_paths),
            fps=self._project.fps,
            source_directory=source_directory,
        )
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self._project = project
        self._current_frame_index = 0
        self._autofill_previous_point_for_current_frame()
        self.project_changed.emit(project)
        self.frame_changed.emit(self._current_frame_index)
        self.fps_changed.emit(project.fps)
        self.calibration_changed.emit(self.current_calibration())
        self.measurement_changed.emit(self.current_measurement())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def set_frame(self, index: int) -> None:
        if self._project.frame_count == 0:
            self._current_frame_index = 0
            self.frame_changed.emit(self._current_frame_index)
            return

        bounded_index = max(0, min(index, self._project.frame_count - 1))
        if bounded_index == self._current_frame_index:
            return

        self._current_frame_index = bounded_index
        self._autofill_previous_point_for_current_frame()
        self.frame_changed.emit(self._current_frame_index)
        self.calibration_changed.emit(self.current_calibration())
        self.measurement_changed.emit(self.current_measurement())
        self.metrics_changed.emit(self.current_segment_metrics())

    def next_frame(self) -> None:
        self.set_frame(self._current_frame_index + 1)

    def previous_frame(self) -> None:
        self.set_frame(self._current_frame_index - 1)

    def set_tool_mode(self, mode: ToolMode) -> None:
        if mode == self._tool_mode:
            return

        self._tool_mode = mode
        self.mode_changed.emit(mode.value)

    def set_fps(self, fps: float) -> None:
        if fps <= 0:
            return
        if abs(self._project.fps - fps) < 1e-9:
            return

        self._project.fps = fps
        self.fps_changed.emit(fps)
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def set_current_calibration(self, p1: Point, p2: Point, length_m: float) -> Calibration | None:
        calibration = self._build_calibration(p1, p2, length_m)
        if calibration is None:
            return None

        override = self._project.get_or_create_override(self._current_frame_index)
        override.calibration = calibration
        self.calibration_changed.emit(self.current_calibration())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())
        return calibration

    def set_current_calibration_length(self, length_m: float) -> Calibration | None:
        if length_m <= 0:
            return None

        current = self.current_calibration()
        if current is None:
            return None

        calibration = Calibration(current.p1, current.p2, length_m)
        override = self._project.get_or_create_override(self._current_frame_index)
        override.calibration = calibration
        self.calibration_changed.emit(self.current_calibration())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())
        return calibration

    def clear_current_frame_calibration(self) -> None:
        if self._project.frame_overrides.pop(self._current_frame_index, None) is None:
            return
        self.calibration_changed.emit(self.current_calibration())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def set_previous_point(self, pos: Point) -> MeasurementStep:
        step = self._project.measurements.get(self._current_frame_index)
        if step is None:
            step = MeasurementStep(frame_index=self._current_frame_index)

        step.previous_point_on_this_frame_px = pos
        step.previous_point_is_auto = False
        self._project.measurements[self._current_frame_index] = step
        self.measurement_changed.emit(step)
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())
        return step

    def set_current_point(self, pos: Point) -> MeasurementStep:
        step = self._project.measurements.get(self._current_frame_index)
        if step is None:
            step = MeasurementStep(frame_index=self._current_frame_index)

        step.current_point_px = pos
        self._project.measurements[self._current_frame_index] = step
        self.measurement_changed.emit(step)
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())
        return step

    def clear_current_measurement(self) -> None:
        if self._project.measurements.pop(self._current_frame_index, None) is None:
            return
        self.measurement_changed.emit(self.current_measurement())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def _build_calibration(self, p1: Point, p2: Point, length_m: float) -> Calibration | None:
        if length_m <= 0:
            return None

        calibration = Calibration(p1, p2, length_m)
        if calibration.pixel_length == 0:
            return None
        return calibration

    def _autofill_previous_point_for_current_frame(self) -> None:
        if self._current_frame_index <= 0:
            return

        previous_step = self._project.measurements.get(self._current_frame_index - 1)
        if previous_step is None or previous_step.current_point_px is None:
            return

        current_step = self._project.measurements.get(self._current_frame_index)
        if current_step is None:
            current_step = MeasurementStep(frame_index=self._current_frame_index)
            self._project.measurements[self._current_frame_index] = current_step

        if (
            current_step.previous_point_on_this_frame_px is not None
            and not current_step.previous_point_is_auto
        ):
            return

        current_step.previous_point_on_this_frame_px = previous_step.current_point_px
        current_step.previous_point_is_auto = True
