from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pixel_track.model import Project


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
        self.project_changed.emit(project)
        self.frame_changed.emit(self._current_frame_index)
        self.fps_changed.emit(project.fps)

    def set_frame(self, index: int) -> None:
        if self._project.frame_count == 0:
            self._current_frame_index = 0
            self.frame_changed.emit(self._current_frame_index)
            return

        bounded_index = max(0, min(index, self._project.frame_count - 1))
        if bounded_index == self._current_frame_index:
            return

        self._current_frame_index = bounded_index
        self.frame_changed.emit(self._current_frame_index)

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
