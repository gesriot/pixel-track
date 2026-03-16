from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pixel_track.controller import ProjectController
from pixel_track.model import Project
from pixel_track.ui.main_window import MainWindow


def build_application() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Pixel Track")
    app.setOrganizationName("Pixel Track")
    return app


def main() -> int:
    app = build_application()
    controller = ProjectController(Project(frame_paths=[]))
    window = MainWindow(controller)
    window.show()
    return app.exec()
