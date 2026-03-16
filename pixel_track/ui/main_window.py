from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QDockWidget,
    QFormLayout,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pixel_track.analysis import SegmentMetrics
from pixel_track.controller import ProjectController, ToolMode
from pixel_track.frame_sequence import collect_frame_paths, supported_image_suffixes
from pixel_track.model import MeasurementStep
from pixel_track.project_io import export_metrics_csv, load_project, save_project
from pixel_track.ui.image_view import ImageView
from pixel_track.ui.speed_plot import SpeedPlotWidget


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
        self.distance_label = QLabel("—")
        self.speed_label = QLabel("—")
        self.zoom_label = QLabel("100%")
        self.fps_spinbox = QDoubleSpinBox(self)
        self.frame_spinbox = QSpinBox(self)
        self.calibration_length_spinbox = QDoubleSpinBox(self)
        self.calibration_pixel_label = QLabel("—")
        self.calibration_distance_label = QLabel("—")
        self.calibration_scale_label = QLabel("—")
        self.calibration_source_label = QLabel("Not set")
        self.calibration_status_label = QLabel("Select a frame and enter calibration mode.")
        self.calibration_status_label.setWordWrap(True)
        self.measurement_reference_label = QLabel("—")
        self.measurement_status_label = QLabel(
            "Use Current mode to set the starting position of the object."
        )
        self.measurement_status_label.setWordWrap(True)
        self._history_metrics: list[SegmentMetrics] = []
        self._suppress_history_navigation = False
        self._last_open_directory = Path.cwd()
        self._pending_calibration_start: tuple[float, float] | None = None
        self._project_file_path: Path | None = None
        self._pixmap_cache: OrderedDict[Path, QPixmap] = OrderedDict()
        self._pixmap_cache_capacity = 12

        self._configure_inputs()
        self._create_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_layout()
        self._build_analysis_dock()
        self._connect_signals()
        self._refresh_labels()
        self._refresh_window_title()

        self.statusBar().showMessage(
            "Sprint 6: use hotkeys, drag handles directly on the image, and work faster on long sequences."
        )

    def _configure_inputs(self) -> None:
        self.fps_spinbox.setRange(0.001, 10_000.0)
        self.fps_spinbox.setDecimals(3)
        self.fps_spinbox.setSingleStep(1.0)
        self.fps_spinbox.setValue(self.controller.project.fps)

        self.frame_spinbox.setRange(1, 1)
        self.frame_spinbox.setEnabled(False)

        self.calibration_length_spinbox.setRange(0.001, 1_000_000.0)
        self.calibration_length_spinbox.setDecimals(3)
        self.calibration_length_spinbox.setSingleStep(1.0)
        self.calibration_length_spinbox.setSuffix(" m")
        self.calibration_length_spinbox.setValue(10.0)

    def _create_actions(self) -> None:
        self._open_frames_action = QAction("Open Frames Folder...", self)
        self._open_frames_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._open_frames_action.triggered.connect(self._open_frames_folder)

        self._open_project_action = QAction("Open Project...", self)
        self._open_project_action.setShortcut(QKeySequence("Ctrl+O"))
        self._open_project_action.triggered.connect(self._open_project)

        self._save_project_action = QAction("Save Project", self)
        self._save_project_action.setShortcut(QKeySequence("Ctrl+S"))
        self._save_project_action.triggered.connect(self._save_project)

        self._save_project_as_action = QAction("Save Project As...", self)
        self._save_project_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_project_as_action.triggered.connect(self._save_project_as)

        self._export_csv_action = QAction("Export Measurements CSV...", self)
        self._export_csv_action.setShortcut(QKeySequence("Ctrl+E"))
        self._export_csv_action.triggered.connect(self._export_measurements_csv)

        self._prev_frame_action = QAction("Prev", self)
        self._prev_frame_action.setShortcut(QKeySequence(Qt.Key_Left))
        self._prev_frame_action.triggered.connect(self.controller.previous_frame)

        self._next_frame_action = QAction("Next", self)
        self._next_frame_action.setShortcut(QKeySequence(Qt.Key_Right))
        self._next_frame_action.triggered.connect(self.controller.next_frame)

        self._jump_back_action = QAction("Back 10", self)
        self._jump_back_action.setShortcut(QKeySequence(Qt.Key_PageUp))
        self._jump_back_action.triggered.connect(lambda: self.controller.jump_frames(-10))

        self._jump_forward_action = QAction("Forward 10", self)
        self._jump_forward_action.setShortcut(QKeySequence(Qt.Key_PageDown))
        self._jump_forward_action.triggered.connect(lambda: self.controller.jump_frames(10))

        self._first_frame_action = QAction("First Frame", self)
        self._first_frame_action.setShortcut(QKeySequence(Qt.Key_Home))
        self._first_frame_action.triggered.connect(self.controller.first_frame)

        self._last_frame_action = QAction("Last Frame", self)
        self._last_frame_action.setShortcut(QKeySequence(Qt.Key_End))
        self._last_frame_action.triggered.connect(self.controller.last_frame)

        self._zoom_in_action = QAction("Zoom In", self)
        self._zoom_in_action.setShortcuts(
            [QKeySequence("Ctrl+="), QKeySequence("Ctrl++")]
        )
        self._zoom_in_action.triggered.connect(self.image_view.zoom_in)

        self._zoom_out_action = QAction("Zoom Out", self)
        self._zoom_out_action.setShortcuts([QKeySequence("Ctrl+-")])
        self._zoom_out_action.triggered.connect(self.image_view.zoom_out)

        self._fit_view_action = QAction("Fit to Frame", self)
        self._fit_view_action.setShortcut(QKeySequence("Ctrl+0"))
        self._fit_view_action.triggered.connect(self.image_view.reset_view_state)

        for action in (
            self._jump_back_action,
            self._jump_forward_action,
            self._first_frame_action,
            self._last_frame_action,
            self._zoom_in_action,
            self._zoom_out_action,
            self._fit_view_action,
        ):
            self.addAction(action)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self._open_frames_action)
        file_menu.addAction(self._open_project_action)

        file_menu.addSeparator()
        file_menu.addAction(self._save_project_action)
        file_menu.addAction(self._save_project_as_action)

        file_menu.addSeparator()
        file_menu.addAction(self._export_csv_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._mode_action_group = QActionGroup(self)
        self._mode_action_group.setExclusive(True)

        self._navigate_action = QAction("Navigate", self)
        self._navigate_action.setCheckable(True)
        self._navigate_action.setChecked(True)
        self._navigate_action.triggered.connect(
            lambda checked: checked and self.controller.set_tool_mode(ToolMode.NAVIGATE)
        )

        self._calibrate_action = QAction("Calibrate", self)
        self._calibrate_action.setCheckable(True)
        self._calibrate_action.triggered.connect(
            lambda checked: checked and self.controller.set_tool_mode(ToolMode.CALIBRATE)
        )

        self._mark_previous_action = QAction("Mark Previous", self)
        self._mark_previous_action.setCheckable(True)
        self._mark_previous_action.triggered.connect(
            lambda checked: checked and self.controller.set_tool_mode(ToolMode.MARK_PREVIOUS)
        )

        self._mark_current_action = QAction("Mark Current", self)
        self._mark_current_action.setCheckable(True)
        self._mark_current_action.triggered.connect(
            lambda checked: checked and self.controller.set_tool_mode(ToolMode.MARK_CURRENT)
        )

        self._edit_handles_action = QAction("Edit Handles", self)
        self._edit_handles_action.setCheckable(True)
        self._edit_handles_action.triggered.connect(
            lambda checked: checked and self.controller.set_tool_mode(ToolMode.EDIT_HANDLES)
        )

        self._navigate_action.setShortcut(QKeySequence("N"))
        self._calibrate_action.setShortcut(QKeySequence("C"))
        self._mark_previous_action.setShortcut(QKeySequence("P"))
        self._mark_current_action.setShortcut(QKeySequence("M"))
        self._edit_handles_action.setShortcut(QKeySequence("E"))

        self._mode_action_group.addAction(self._navigate_action)
        self._mode_action_group.addAction(self._calibrate_action)
        self._mode_action_group.addAction(self._mark_previous_action)
        self._mode_action_group.addAction(self._mark_current_action)
        self._mode_action_group.addAction(self._edit_handles_action)

        toolbar.addAction(self._open_frames_action)
        toolbar.addSeparator()
        toolbar.addAction(self._prev_frame_action)
        toolbar.addAction(self._next_frame_action)
        toolbar.addAction(self._jump_back_action)
        toolbar.addAction(self._jump_forward_action)
        toolbar.addSeparator()
        toolbar.addAction(self._navigate_action)
        toolbar.addAction(self._calibrate_action)
        toolbar.addAction(self._mark_previous_action)
        toolbar.addAction(self._mark_current_action)
        toolbar.addAction(self._edit_handles_action)
        toolbar.addSeparator()
        toolbar.addAction(self._zoom_in_action)
        toolbar.addAction(self._zoom_out_action)
        toolbar.addAction(self._fit_view_action)

    def _build_layout(self) -> None:
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.image_view)
        splitter.addWidget(self._build_sidebar())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1100, 340])
        self.setCentralWidget(splitter)

    def _build_analysis_dock(self) -> None:
        dock = QDockWidget("Analysis", self)
        dock.setObjectName("analysisDock")
        dock.setAllowedAreas(Qt.BottomDockWidgetArea)

        self.speed_plot = SpeedPlotWidget(dock)
        self.history_table = QTableWidget(0, 6, dock)
        self.history_table.setHorizontalHeaderLabels(
            ["From", "To", "t_end (s)", "dt (s)", "Distance (m)", "Speed (m/s)"]
        )
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        dock_content = QWidget(dock)
        dock_layout = QVBoxLayout(dock_content)
        dock_layout.setContentsMargins(8, 8, 8, 8)
        dock_layout.addWidget(self.speed_plot)
        dock_layout.addWidget(self.history_table)
        dock.setWidget(dock_content)

        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

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

        calibration_box = QGroupBox("Calibration", container)
        calibration_form = QFormLayout(calibration_box)
        calibration_form.addRow("Length", self.calibration_length_spinbox)
        calibration_form.addRow("Pixel length", self.calibration_pixel_label)
        calibration_form.addRow("Distance", self.calibration_distance_label)
        calibration_form.addRow("Scale", self.calibration_scale_label)
        calibration_form.addRow("Source", self.calibration_source_label)
        calibration_form.addRow("Status", self.calibration_status_label)

        clear_button = QPushButton("Clear Current Frame")
        clear_button.clicked.connect(self._clear_current_frame_calibration)
        calibration_form.addRow("", clear_button)

        measurement_box = QGroupBox("Measurement", container)
        measurement_form = QFormLayout(measurement_box)
        measurement_form.addRow("Reference", self.measurement_reference_label)
        measurement_form.addRow("Distance", self.distance_label)
        measurement_form.addRow("Speed", self.speed_label)
        measurement_form.addRow("Status", self.measurement_status_label)

        clear_measurement_button = QPushButton("Clear Current Measurement")
        clear_measurement_button.clicked.connect(self._clear_current_measurement)
        measurement_form.addRow("", clear_measurement_button)

        notes_box = QGroupBox("Status", container)
        notes_layout = QVBoxLayout(notes_box)
        notes = QLabel(
            "Shortcuts: Left/Right for frames, PageUp/PageDown for +/-10, Home/End for first/last, "
            "N/C/P/M/E for modes, Ctrl+Plus/Ctrl+Minus/Ctrl+0 for zoom. In Edit Handles mode, drag "
            "the visible points directly on the image."
        )
        notes.setWordWrap(True)
        notes_layout.addWidget(notes)

        layout.addWidget(project_box)
        layout.addWidget(calibration_box)
        layout.addWidget(measurement_box)
        layout.addWidget(notes_box)
        layout.addStretch(1)
        return container

    def _connect_signals(self) -> None:
        self.controller.frame_changed.connect(self._on_frame_changed)
        self.controller.project_changed.connect(self._on_project_changed)
        self.controller.mode_changed.connect(self._on_mode_changed)
        self.controller.fps_changed.connect(self._on_fps_changed)
        self.controller.calibration_changed.connect(self._on_calibration_changed)
        self.controller.measurement_changed.connect(self._on_measurement_changed)
        self.controller.metrics_changed.connect(self._on_metrics_changed)
        self.controller.history_changed.connect(self._on_history_changed)
        self.frame_spinbox.valueChanged.connect(self._on_frame_spinbox_changed)
        self.fps_spinbox.valueChanged.connect(self.controller.set_fps)
        self.calibration_length_spinbox.valueChanged.connect(self._on_calibration_length_changed)
        self.image_view.zoom_changed.connect(self._on_zoom_changed)
        self.image_view.scene_clicked.connect(self._on_scene_clicked)
        self.image_view.scene_hovered.connect(self._on_scene_hovered)
        self.image_view.overlay_handle_released.connect(self._on_overlay_handle_released)
        self.history_table.cellDoubleClicked.connect(self._on_history_row_activated)

    def _on_frame_changed(self, _: int) -> None:
        self._cancel_pending_calibration()
        self._load_current_frame()
        self._refresh_labels()
        self._sync_history_selection()

    def _on_project_changed(self, _: object) -> None:
        self._cancel_pending_calibration()
        self._pixmap_cache.clear()
        self.image_view.reset_view_state()
        self._refresh_labels()
        self._refresh_window_title()

    def _on_mode_changed(self, mode: str) -> None:
        self.mode_label.setText(mode)
        self.image_view.set_edit_handles_enabled(mode == ToolMode.EDIT_HANDLES.value)
        with QSignalBlocker(self._navigate_action):
            self._navigate_action.setChecked(mode == ToolMode.NAVIGATE.value)
        with QSignalBlocker(self._calibrate_action):
            self._calibrate_action.setChecked(mode == ToolMode.CALIBRATE.value)
        with QSignalBlocker(self._mark_previous_action):
            self._mark_previous_action.setChecked(mode == ToolMode.MARK_PREVIOUS.value)
        with QSignalBlocker(self._mark_current_action):
            self._mark_current_action.setChecked(mode == ToolMode.MARK_CURRENT.value)
        with QSignalBlocker(self._edit_handles_action):
            self._edit_handles_action.setChecked(mode == ToolMode.EDIT_HANDLES.value)

        if mode != ToolMode.CALIBRATE.value:
            self._cancel_pending_calibration()
            if mode == ToolMode.NAVIGATE.value:
                self.calibration_status_label.setText("Navigate mode is active.")
            elif mode == ToolMode.EDIT_HANDLES.value:
                self.calibration_status_label.setText(
                    "Drag visible handles on the image to refine calibration or measurement points."
                )
        elif self.controller.project.frame_count == 0:
            self.calibration_status_label.setText("Load frames before calibrating.")
        else:
            self.calibration_status_label.setText("Click the first point of the calibration segment.")

        self._refresh_measurement_mode_status()

    def _on_fps_changed(self, fps: float) -> None:
        with QSignalBlocker(self.fps_spinbox):
            self.fps_spinbox.setValue(fps)

    def _on_frame_spinbox_changed(self, value: int) -> None:
        if self.controller.project.frame_count == 0:
            return
        self.controller.set_frame(value - 1)

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        self.zoom_label.setText(f"{zoom_factor * 100:.0f}%")

    def _on_calibration_changed(self, calibration: object) -> None:
        self.image_view.set_calibration(calibration)
        self._refresh_calibration_panel()

    def _on_measurement_changed(self, measurement: object) -> None:
        self.image_view.set_measurement(measurement)
        self._refresh_measurement_panel()

    def _on_metrics_changed(self, metrics: object) -> None:
        self._refresh_measurement_panel(metrics)

    def _on_history_changed(self, metrics: object) -> None:
        self._history_metrics = list(metrics)
        self._refresh_history_views()

    def _on_calibration_length_changed(self, value: float) -> None:
        if self.controller.current_calibration() is None:
            return
        self.controller.set_current_calibration_length(value)

    def _on_scene_clicked(self, x: float, y: float) -> None:
        if self.controller.project.frame_count == 0:
            return

        point = (x, y)
        if self.controller.tool_mode is ToolMode.CALIBRATE:
            if self._pending_calibration_start is None:
                self._pending_calibration_start = point
                self.image_view.set_calibration_preview(point, point)
                self.calibration_status_label.setText("Click the second point of the calibration segment.")
                self.statusBar().showMessage("Calibration: first point selected.")
                return

            calibration = self.controller.set_current_calibration(
                self._pending_calibration_start,
                point,
                self.calibration_length_spinbox.value(),
            )
            self._cancel_pending_calibration()

            if calibration is None:
                self.calibration_status_label.setText(
                    "Calibration failed. Use a positive length and two different points."
                )
                self.statusBar().showMessage("Calibration failed.")
                return

            self.calibration_status_label.setText("Calibration saved for the current frame.")
            self.statusBar().showMessage("Calibration updated.")
            return

        if self.controller.tool_mode is ToolMode.MARK_PREVIOUS:
            self.controller.set_previous_point(point)
            self.measurement_status_label.setText(
                "Previous position marked. Now click the current object position."
            )
            self.statusBar().showMessage("Previous position marked on current frame.")
            return

        if self.controller.tool_mode is ToolMode.MARK_CURRENT:
            step = self.controller.set_current_point(point)
            metrics = self.controller.current_segment_metrics()
            if metrics is not None:
                self.measurement_status_label.setText(
                    f"Step recorded: {metrics.distance_m:.3f} m over {metrics.dt_s:.3f} s."
                )
                self.statusBar().showMessage("Current position marked. Distance and speed updated.")
            elif step.previous_point_on_this_frame_px is None:
                self.measurement_status_label.setText(
                    "Current position saved. Mark the previous position on this frame to compute motion."
                )
                self.statusBar().showMessage("Current position marked.")
            else:
                self.measurement_status_label.setText(
                    "Current position saved. Need an earlier measured frame to compute speed."
                )
                self.statusBar().showMessage("Current position marked.")
            return

    def _on_scene_hovered(self, x: float, y: float) -> None:
        if self._pending_calibration_start is None:
            return
        self.image_view.set_calibration_preview(self._pending_calibration_start, (x, y))

    def _on_overlay_handle_released(self, role: str, x: float, y: float) -> None:
        point = (x, y)
        if role == "calibration_p1":
            calibration = self.controller.set_current_calibration_endpoint("p1", point)
            if calibration is not None:
                self.statusBar().showMessage("Calibration start updated.")
            return

        if role == "calibration_p2":
            calibration = self.controller.set_current_calibration_endpoint("p2", point)
            if calibration is not None:
                self.statusBar().showMessage("Calibration end updated.")
            return

        if role == "measurement_previous":
            self.controller.set_previous_point(point)
            self.statusBar().showMessage("Previous measurement point updated.")
            return

        if role == "measurement_current":
            self.controller.set_current_point(point)
            self.statusBar().showMessage("Current measurement point updated.")
            return

    def _on_history_row_activated(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._history_metrics):
            return
        metric = self._history_metrics[row]
        self.controller.set_frame(metric.to_frame)

    def _refresh_labels(self) -> None:
        frame_count = self.controller.project.frame_count
        directory = self.controller.project.source_directory
        self.folder_label.setText(str(directory) if directory else "No folder selected")
        self._prev_frame_action.setEnabled(frame_count > 0 and self.controller.current_frame_index > 0)
        self._next_frame_action.setEnabled(
            frame_count > 0 and self.controller.current_frame_index < frame_count - 1
        )
        self._jump_back_action.setEnabled(frame_count > 0 and self.controller.current_frame_index > 0)
        self._jump_forward_action.setEnabled(
            frame_count > 0 and self.controller.current_frame_index < frame_count - 1
        )
        self._first_frame_action.setEnabled(frame_count > 0 and self.controller.current_frame_index > 0)
        self._last_frame_action.setEnabled(
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
            self.calibration_status_label.setText("Load frames before calibrating.")
        else:
            current = self.controller.current_frame_index + 1
            self.frame_label.setText(f"{current} / {frame_count}")
            self.frame_spinbox.setEnabled(True)
            with QSignalBlocker(self.frame_spinbox):
                self.frame_spinbox.setRange(1, frame_count)
                self.frame_spinbox.setValue(current)
            if self.controller.tool_mode is ToolMode.CALIBRATE and self._pending_calibration_start is None:
                self.calibration_status_label.setText(
                    "Click the first point of the calibration segment."
                )
        self._refresh_calibration_panel()
        self._refresh_measurement_panel()

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
        self._project_file_path = None
        self._refresh_window_title()
        self.statusBar().showMessage(f"Loaded {len(frame_paths)} frame(s) from {folder}.")

    def _open_project(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            str(self._last_open_directory),
            "Pixel Track Project (*.pixeltrack.json *.json);;All Files (*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            project = load_project(path)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Could Not Open Project",
                f"Failed to open project:\n{path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Failed to open project: {path}")
            return

        self._project_file_path = path
        self._last_open_directory = path.parent
        self.controller.set_project(project)
        self._refresh_window_title()
        self.statusBar().showMessage(f"Project loaded from {path}.")

    def _save_project(self) -> None:
        if self._project_file_path is None:
            self._save_project_as()
            return

        try:
            save_project(self.controller.project, self._project_file_path)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Could Not Save Project",
                f"Failed to save project:\n{self._project_file_path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Failed to save project: {self._project_file_path}")
            return

        self._refresh_window_title()
        self.statusBar().showMessage(f"Project saved to {self._project_file_path}.")

    def _save_project_as(self) -> None:
        suggested_directory = self._project_file_path.parent if self._project_file_path else self._last_open_directory
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            str(suggested_directory / "project.pixeltrack.json"),
            "Pixel Track Project (*.pixeltrack.json *.json);;All Files (*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".pixeltrack.json")

        try:
            save_project(self.controller.project, path)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Could Not Save Project",
                f"Failed to save project:\n{path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Failed to save project: {path}")
            return

        self._project_file_path = path
        self._last_open_directory = path.parent
        self._refresh_window_title()
        self.statusBar().showMessage(f"Project saved to {path}.")

    def _export_measurements_csv(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Measurements CSV",
            str(self._last_open_directory / "measurements.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")

        try:
            export_metrics_csv(self._history_metrics, path)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Could Not Export CSV",
                f"Failed to export CSV:\n{path}\n\n{error}",
            )
            self.statusBar().showMessage(f"Failed to export CSV: {path}")
            return

        self._last_open_directory = path.parent
        self.statusBar().showMessage(f"Measurements exported to {path}.")

    def _load_current_frame(self) -> None:
        frame_path = self.controller.current_frame_path()
        if frame_path is None:
            return

        pixmap = self._load_pixmap(frame_path)
        if pixmap.isNull():
            self.image_view.show_placeholder(
                f"Could not load image:\n{frame_path.name}\n\nTry another file or folder."
            )
            self.statusBar().showMessage(f"Failed to load image: {frame_path}")
            return

        self.image_view.set_pixmap(pixmap)
        self._preload_adjacent_pixmaps()
        self.statusBar().showMessage(f"Viewing frame {self.controller.current_frame_index + 1}")

    def _refresh_calibration_panel(self) -> None:
        calibration = self.controller.current_calibration()
        if calibration is None:
            self.calibration_pixel_label.setText("—")
            self.calibration_distance_label.setText("—")
            self.calibration_scale_label.setText("—")
            self.calibration_source_label.setText("Not set")
            return

        source_index = self.controller.current_calibration_source_index()
        if source_index is None:
            source_text = "Not set"
        elif source_index == self.controller.current_frame_index:
            source_text = f"Frame {source_index + 1}"
        else:
            source_text = f"Inherited from frame {source_index + 1}"

        self.calibration_pixel_label.setText(f"{calibration.pixel_length:.2f} px")
        self.calibration_distance_label.setText(f"{calibration.length_m:.3f} m")
        self.calibration_scale_label.setText(f"{calibration.pixels_per_meter:.3f} px/m")
        self.calibration_source_label.setText(source_text)
        with QSignalBlocker(self.calibration_length_spinbox):
            self.calibration_length_spinbox.setValue(calibration.length_m)

    def _refresh_measurement_panel(self, metrics: SegmentMetrics | None = None) -> None:
        measurement = self.controller.current_measurement()
        metrics = self.controller.current_segment_metrics() if metrics is None else metrics
        previous_frame = self.controller.previous_measured_frame_index()

        if previous_frame is None:
            self.measurement_reference_label.setText("No earlier measurement")
        else:
            self.measurement_reference_label.setText(f"Frame {previous_frame + 1}")

        if metrics is None:
            self.distance_label.setText("—")
            self.speed_label.setText("—")
        else:
            self.distance_label.setText(f"{metrics.distance_m:.3f} m")
            self.speed_label.setText(f"{metrics.speed_mps:.3f} m/s")

        self._refresh_measurement_mode_status(measurement, metrics)

    def _refresh_history_views(self) -> None:
        self.speed_plot.set_metrics(self._history_metrics, self.controller.current_frame_index)

        self._suppress_history_navigation = True
        try:
            self.history_table.setRowCount(len(self._history_metrics))
            for row, metric in enumerate(self._history_metrics):
                values = [
                    str(metric.from_frame + 1),
                    str(metric.to_frame + 1),
                    f"{metric.t_end_s:.3f}",
                    f"{metric.dt_s:.3f}",
                    f"{metric.distance_m:.3f}",
                    f"{metric.speed_mps:.3f}",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, metric.to_frame)
                    self.history_table.setItem(row, column, item)
        finally:
            self._suppress_history_navigation = False

        self._sync_history_selection()

    def _sync_history_selection(self) -> None:
        if self._suppress_history_navigation:
            return

        self.speed_plot.set_metrics(self._history_metrics, self.controller.current_frame_index)
        target_row = next(
            (row for row, metric in enumerate(self._history_metrics) if metric.to_frame == self.controller.current_frame_index),
            -1,
        )

        self._suppress_history_navigation = True
        try:
            self.history_table.clearSelection()
            if target_row >= 0:
                self.history_table.selectRow(target_row)
                self.history_table.scrollToItem(
                    self.history_table.item(target_row, 0),
                    QAbstractItemView.PositionAtCenter,
                )
        finally:
            self._suppress_history_navigation = False

    def _refresh_measurement_mode_status(
        self,
        measurement: MeasurementStep | None = None,
        metrics: SegmentMetrics | None = None,
    ) -> None:
        measurement = self.controller.current_measurement() if measurement is None else measurement
        metrics = self.controller.current_segment_metrics() if metrics is None else metrics

        if self.controller.project.frame_count == 0:
            self.measurement_status_label.setText("Load frames before marking movement.")
            return

        if self.controller.tool_mode is ToolMode.MARK_PREVIOUS:
            reference = self.controller.previous_measured_frame_index()
            if reference is None:
                self.measurement_status_label.setText(
                    "No earlier measured frame yet. Use Current mode to set a starting point first."
                )
            else:
                self.measurement_status_label.setText(
                    f"Click where the object was on frame {reference + 1}, but on the current image."
                )
            return

        if self.controller.tool_mode is ToolMode.MARK_CURRENT:
            if metrics is not None:
                self.measurement_status_label.setText(
                    f"Current step ready: {metrics.distance_m:.3f} m at {metrics.speed_mps:.3f} m/s."
                )
            elif measurement and measurement.previous_point_on_this_frame_px is not None:
                self.measurement_status_label.setText(
                    "Click the current object position to finish this step."
                )
            else:
                self.measurement_status_label.setText(
                    "Click the current object position. On the first frame this becomes the start point."
                )
            return

        if self.controller.tool_mode is ToolMode.EDIT_HANDLES:
            if measurement is None and self.controller.current_calibration() is None:
                self.measurement_status_label.setText(
                    "Nothing to edit on this frame yet. Create a calibration or measurement first."
                )
            else:
                self.measurement_status_label.setText(
                    "Edit mode is active. Drag the visible handles directly on the image."
                )
            return

        if measurement is None:
            self.measurement_status_label.setText(
                "Use Current mode to set the starting position of the object."
            )
            return

        if measurement.current_point_px is not None and measurement.previous_point_on_this_frame_px is None:
            self.measurement_status_label.setText(
                "Start position is stored. Move to a later frame and mark Previous, then Current."
            )
            return

        if metrics is not None:
            self.measurement_status_label.setText(
                f"Latest step: {metrics.distance_m:.3f} m at {metrics.speed_mps:.3f} m/s."
            )
            return

        self.measurement_status_label.setText(
            "Measurement for this frame is incomplete. Mark both Previous and Current points."
        )

    def _cancel_pending_calibration(self) -> None:
        self._pending_calibration_start = None
        self.image_view.clear_calibration_preview()

    def _clear_current_frame_calibration(self) -> None:
        self._cancel_pending_calibration()
        self.controller.clear_current_frame_calibration()
        if self.controller.current_calibration() is None:
            self.calibration_status_label.setText("No calibration is set for this frame yet.")
            self.statusBar().showMessage("Calibration cleared from current frame.")
            return

        self.calibration_status_label.setText("Current frame override cleared. Inherited calibration is shown.")
        self.statusBar().showMessage("Current frame calibration override cleared.")

    def _clear_current_measurement(self) -> None:
        self.controller.clear_current_measurement()
        self.measurement_status_label.setText("Current frame measurement cleared.")
        self.statusBar().showMessage("Measurement cleared from current frame.")

    def _refresh_window_title(self) -> None:
        project_name = (
            self._project_file_path.name
            if self._project_file_path is not None
            else "Unsaved Session"
        )
        self.setWindowTitle(f"Pixel Track - {project_name}")

    def _load_pixmap(self, frame_path: Path) -> QPixmap:
        cached_pixmap = self._pixmap_cache.pop(frame_path, None)
        if cached_pixmap is not None:
            self._pixmap_cache[frame_path] = cached_pixmap
            return cached_pixmap

        pixmap = QPixmap(str(frame_path))
        if not pixmap.isNull():
            self._pixmap_cache[frame_path] = pixmap
            while len(self._pixmap_cache) > self._pixmap_cache_capacity:
                self._pixmap_cache.popitem(last=False)
        return pixmap

    def _preload_adjacent_pixmaps(self) -> None:
        if self.controller.project.frame_count == 0:
            return

        current = self.controller.current_frame_index
        preload_indices = (
            current - 2,
            current - 1,
            current + 1,
            current + 2,
        )
        for index in preload_indices:
            if 0 <= index < self.controller.project.frame_count:
                frame_path = self.controller.project.get_frame_path(index)
                if frame_path not in self._pixmap_cache:
                    self._load_pixmap(frame_path)
