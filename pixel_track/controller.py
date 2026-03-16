from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from pixel_track.analysis import SegmentMetrics, build_segment_metrics, segment_metrics_for_frame
from pixel_track.model import Calibration, FrameOverride, MeasurementStep, Point, Project
from pixel_track.undo_commands import _CalibrationCommand, _MeasurementCommand


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
        self._undo_stack = QUndoStack(self)

    @property
    def project(self) -> Project:
        return self._project

    @property
    def current_frame_index(self) -> int:
        return self._current_frame_index

    @property
    def tool_mode(self) -> ToolMode:
        return self._tool_mode

    @property
    def undo_stack(self) -> QUndoStack:
        return self._undo_stack

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

    def _emit_calibration_signals(self) -> None:
        self.calibration_changed.emit(self.current_calibration())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def _emit_measurement_signals(self) -> None:
        self.measurement_changed.emit(self.current_measurement())
        self.metrics_changed.emit(self.current_segment_metrics())
        self.history_changed.emit(self.segment_metrics_history())

    def set_project(self, project: Project) -> None:
        self._project = project
        self._current_frame_index = 0
        self._undo_stack.clear()
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

    def jump_frames(self, offset: int) -> None:
        self.set_frame(self._current_frame_index + offset)

    def first_frame(self) -> None:
        self.set_frame(0)

    def last_frame(self) -> None:
        if self._project.frame_count == 0:
            return
        self.set_frame(self._project.frame_count - 1)

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

        frame_index = self._current_frame_index
        old_override = self._project.frame_overrides.get(frame_index)
        new_override = FrameOverride(calibration=calibration)
        self._undo_stack.push(_CalibrationCommand(
            self, frame_index, old_override, new_override,
            f"Set calibration on frame {frame_index + 1}",
        ))
        return calibration

    def set_current_calibration_length(self, length_m: float) -> Calibration | None:
        if length_m <= 0:
            return None

        current = self.current_calibration()
        if current is None:
            return None

        calibration = Calibration(current.p1, current.p2, length_m)
        frame_index = self._current_frame_index
        old_override = self._project.frame_overrides.get(frame_index)
        new_override = FrameOverride(calibration=calibration)
        self._undo_stack.push(_CalibrationCommand(
            self, frame_index, old_override, new_override,
            f"Update calibration length on frame {frame_index + 1}",
        ))
        return calibration

    def set_current_calibration_endpoint(
        self,
        endpoint: str,
        pos: Point,
    ) -> Calibration | None:
        current = self.current_calibration()
        if current is None:
            return None

        if endpoint == "p1":
            calibration = Calibration(pos, current.p2, current.length_m)
        elif endpoint == "p2":
            calibration = Calibration(current.p1, pos, current.length_m)
        else:
            raise ValueError(f"Unsupported calibration endpoint: {endpoint}")

        if calibration.pixel_length == 0:
            return None

        frame_index = self._current_frame_index
        old_override = self._project.frame_overrides.get(frame_index)
        new_override = FrameOverride(calibration=calibration)
        self._undo_stack.push(_CalibrationCommand(
            self, frame_index, old_override, new_override,
            f"Move calibration endpoint on frame {frame_index + 1}",
        ))
        return calibration

    def clear_current_frame_calibration(self) -> None:
        frame_index = self._current_frame_index
        old_override = self._project.frame_overrides.get(frame_index)
        if old_override is None or old_override.calibration is None:
            return
        # Null only the calibration field so future fields on FrameOverride are preserved.
        new_override = dataclasses.replace(old_override, calibration=None)
        self._undo_stack.push(_CalibrationCommand(
            self, frame_index, old_override, new_override,
            f"Clear calibration on frame {frame_index + 1}",
        ))

    def set_previous_point(self, pos: Point) -> MeasurementStep:
        frame_index = self._current_frame_index
        old_step = self._project.measurements.get(frame_index)
        if old_step is not None:
            new_step = dataclasses.replace(old_step, previous_point_on_this_frame_px=pos, previous_point_is_auto=False)
        else:
            new_step = MeasurementStep(frame_index=frame_index, previous_point_on_this_frame_px=pos, previous_point_is_auto=False)
        self._undo_stack.push(_MeasurementCommand(
            self, frame_index, old_step, new_step,
            f"Mark previous point on frame {frame_index + 1}",
        ))
        return self._project.measurements[frame_index]

    def set_current_point(self, pos: Point) -> MeasurementStep:
        frame_index = self._current_frame_index
        old_step = self._project.measurements.get(frame_index)
        if old_step is not None:
            new_step = dataclasses.replace(old_step, current_point_px=pos)
        else:
            new_step = MeasurementStep(frame_index=frame_index, current_point_px=pos)
        self._undo_stack.push(_MeasurementCommand(
            self, frame_index, old_step, new_step,
            f"Mark current point on frame {frame_index + 1}",
        ))
        return self._project.measurements[frame_index]

    def clear_current_measurement(self) -> None:
        frame_index = self._current_frame_index
        old_step = self._project.measurements.get(frame_index)
        if old_step is None:
            return
        self._undo_stack.push(_MeasurementCommand(
            self, frame_index, old_step, None,
            f"Clear measurement on frame {frame_index + 1}",
        ))

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
