from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

from pixel_track.model import FrameOverride, MeasurementStep

if TYPE_CHECKING:
    from pixel_track.controller import ProjectController


class _CalibrationCommand(QUndoCommand):
    """Undoable calibration change on a specific frame."""

    def __init__(
        self,
        controller: ProjectController,
        frame_index: int,
        old_override: FrameOverride | None,
        new_override: FrameOverride | None,
        text: str,
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._frame_index = frame_index
        self._old = dataclasses.replace(old_override) if old_override is not None else None
        self._new = dataclasses.replace(new_override) if new_override is not None else None

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)

    def _apply(self, override: FrameOverride | None) -> None:
        if override is None:
            self._controller._project.frame_overrides.pop(self._frame_index, None)
        else:
            existing = self._controller._project.frame_overrides.get(self._frame_index)
            if existing is not None:
                existing.calibration = override.calibration
            else:
                self._controller._project.frame_overrides[self._frame_index] = dataclasses.replace(override)
        self._controller._emit_calibration_signals()


class _MeasurementCommand(QUndoCommand):
    """Undoable measurement change on a specific frame."""

    def __init__(
        self,
        controller: ProjectController,
        frame_index: int,
        old_step: MeasurementStep | None,
        new_step: MeasurementStep | None,
        text: str,
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._frame_index = frame_index
        self._old = dataclasses.replace(old_step) if old_step is not None else None
        self._new = dataclasses.replace(new_step) if new_step is not None else None

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)

    def _apply(self, step: MeasurementStep | None) -> None:
        if step is None:
            self._controller._project.measurements.pop(self._frame_index, None)
        else:
            self._controller._project.measurements[self._frame_index] = dataclasses.replace(step)
        self._controller._emit_measurement_signals()
