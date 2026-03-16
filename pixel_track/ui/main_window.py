from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFileDialog,
    QGroupBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pixel_track.controller import ProjectController
from pixel_track.frame_sequence import collect_frame_paths, supported_image_suffixes
from pixel_track.ui.image_view import ImageView


class MainWindow(QMainWindow):
    def __init__(self, controller: ProjectController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller

        self.setWindowTitle("Pixel Track")
        self.resize(1440, 900)

        self.image_view = ImageView(self)
        self.frame_label = QLabel("0 / 0")
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        self.mode_label = QLabel(controller.tool_mode.value)
        self.distance_label = QLabel("0.00 m")
        self.speed_label = QLabel("0.00 m/s")
        self.zoom_label = QLabel("100%")
        self.fps_spinbox = QDoubleSpinBox(self)
        self.frame_spinbox = QSpinBox(self)
        self._last_open_directory = Path.cwd()

        self._configure_inputs()
        self._build_menu()
        self._build_toolbar()
        self._build_layout()
        self._connect_signals()
        self._refresh_labels()

        self.statusBar().showMessage("Sprint 1: open a frames folder to begin.")

    def _configure_inputs(self) -> None:
        self.fps_spinbox.setRange(0.001, 10_000.0)
        self.fps_spinbox.setDecimals(3)
        self.fps_spinbox.setSingleStep(1.0)
        self.fps_spinbox.setValue(self.controller.project.fps)

        self.frame_spinbox.setRange(1, 1)
        self.frame_spinbox.setEnabled(False)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")

        open_action = QAction("Open Frames Folder...", self)
        open_action.triggered.connect(self._open_frames_folder)
        file_menu.addAction(open_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_button = QPushButton("Open Folder")
        self._prev_button = QPushButton("Prev")
        self._next_button = QPushButton("Next")

        open_button.clicked.connect(self._open_frames_folder)
        self._prev_button.clicked.connect(self.controller.previous_frame)
        self._next_button.clicked.connect(self.controller.next_frame)

        toolbar.addWidget(open_button)
        toolbar.addSeparator()
        toolbar.addWidget(self._prev_button)
        toolbar.addWidget(self._next_button)

    def _build_layout(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.image_view)
        splitter.addWidget(self._build_sidebar())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1100, 340])
        self.setCentralWidget(splitter)

    def _build_sidebar(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)

        project_box = QGroupBox("Project", container)
        project_form = QFormLayout(project_box)
        project_form.addRow("Folder", self.folder_label)
        project_form.addRow("Frames", self.frame_label)
        project_form.addRow("Current", self.frame_spinbox)
        project_form.addRow("Mode", self.mode_label)
        project_form.addRow("FPS", self.fps_spinbox)
        project_form.addRow("Zoom", self.zoom_label)

        measurement_box = QGroupBox("Measurement", container)
        measurement_form = QFormLayout(measurement_box)
        measurement_form.addRow("Distance", self.distance_label)
        measurement_form.addRow("Speed", self.speed_label)

        notes_box = QGroupBox("Status", container)
        notes_layout = QVBoxLayout(notes_box)
        notes = QLabel(
            "This sprint loads frame folders, preserves zoom while moving between frames, "
            "and lets you set FPS from the sidebar."
        )
        notes.setWordWrap(True)
        notes_layout.addWidget(notes)

        layout.addWidget(project_box)
        layout.addWidget(measurement_box)
        layout.addWidget(notes_box)
        layout.addStretch(1)
        return container

    def _connect_signals(self) -> None:
        self.controller.frame_changed.connect(self._on_frame_changed)
        self.controller.project_changed.connect(self._on_project_changed)
        self.controller.mode_changed.connect(self._on_mode_changed)
        self.controller.fps_changed.connect(self._on_fps_changed)
        self.frame_spinbox.valueChanged.connect(self._on_frame_spinbox_changed)
        self.fps_spinbox.valueChanged.connect(self.controller.set_fps)
        self.image_view.zoom_changed.connect(self._on_zoom_changed)

    def _on_frame_changed(self, _: int) -> None:
        self._load_current_frame()
        self._refresh_labels()

    def _on_project_changed(self, _: object) -> None:
        self.image_view.reset_view_state()
        self._refresh_labels()

    def _on_mode_changed(self, mode: str) -> None:
        self.mode_label.setText(mode)

    def _on_fps_changed(self, fps: float) -> None:
        with QSignalBlocker(self.fps_spinbox):
            self.fps_spinbox.setValue(fps)

    def _on_frame_spinbox_changed(self, value: int) -> None:
        if self.controller.project.frame_count == 0:
            return
        self.controller.set_frame(value - 1)

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        self.zoom_label.setText(f"{zoom_factor * 100:.0f}%")

    def _refresh_labels(self) -> None:
        frame_count = self.controller.project.frame_count
        directory = self.controller.project.source_directory
        self.folder_label.setText(str(directory) if directory else "No folder selected")
        self._prev_button.setEnabled(frame_count > 0 and self.controller.current_frame_index > 0)
        self._next_button.setEnabled(
            frame_count > 0 and self.controller.current_frame_index < frame_count - 1
        )

        if frame_count == 0:
            self.frame_label.setText("0 / 0")
            self.frame_spinbox.setEnabled(False)
            with QSignalBlocker(self.frame_spinbox):
                self.frame_spinbox.setRange(1, 1)
                self.frame_spinbox.setValue(1)
            self.image_view.show_placeholder(
                "No frames loaded yet.\n\nUse File -> Open Frames Folder... to load an image sequence."
            )
        else:
            current = self.controller.current_frame_index + 1
            self.frame_label.setText(f"{current} / {frame_count}")
            self.frame_spinbox.setEnabled(True)
            with QSignalBlocker(self.frame_spinbox):
                self.frame_spinbox.setRange(1, frame_count)
                self.frame_spinbox.setValue(current)

    def _open_frames_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Open Frames Folder",
            str(self._last_open_directory),
        )
        if not directory:
            return

        folder = Path(directory)
        self._last_open_directory = folder
        frame_paths = collect_frame_paths(folder)
        if not frame_paths:
            formats = ", ".join(sorted(supported_image_suffixes()))
            QMessageBox.information(
                self,
                "No Images Found",
                "No supported image files were found in the selected folder.\n\n"
                f"Supported suffixes: {formats}",
            )
            self.statusBar().showMessage("Selected folder does not contain supported image files.")
            return

        self.controller.load_frames(frame_paths, source_directory=folder)
        self.statusBar().showMessage(f"Loaded {len(frame_paths)} frame(s) from {folder}.")

    def _load_current_frame(self) -> None:
        frame_path = self.controller.current_frame_path()
        if frame_path is None:
            return

        pixmap = QPixmap(str(frame_path))
        if pixmap.isNull():
            self.image_view.show_placeholder(
                f"Could not load image:\n{frame_path.name}\n\nTry another file or folder."
            )
            self.statusBar().showMessage(f"Failed to load image: {frame_path}")
            return

        self.image_view.set_pixmap(pixmap)
        self.statusBar().showMessage(f"Viewing frame {self.controller.current_frame_index + 1}")
