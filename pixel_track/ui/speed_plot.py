from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from pixel_track.analysis import SegmentMetrics, speed_series


class SpeedPlotWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        pg.setConfigOptions(antialias=True)

        self._plot = pg.PlotWidget(background="#101418")
        self._plot.setMinimumHeight(220)
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.setLabel("left", "Speed", units="m/s")
        self._plot.setLabel("bottom", "Time", units="s")
        self._plot.setTitle("Speed over time", color="#f8f9fa")
        self._plot.getPlotItem().getAxis("left").setTextPen("#ced4da")
        self._plot.getPlotItem().getAxis("bottom").setTextPen("#ced4da")
        self._plot.getPlotItem().getAxis("left").setPen("#495057")
        self._plot.getPlotItem().getAxis("bottom").setPen("#495057")

        self._curve = self._plot.plot(
            [],
            [],
            pen=pg.mkPen("#4cc9f0", width=2),
            symbol="o",
            symbolBrush="#4cc9f0",
            symbolPen=pg.mkPen("#4cc9f0"),
            symbolSize=7,
        )
        self._current_point = self._plot.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolBrush="#ffd43b",
            symbolPen=pg.mkPen("#ffd43b"),
            symbolSize=11,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

    def set_metrics(
        self,
        metrics: list[SegmentMetrics],
        current_frame_index: int | None = None,
    ) -> None:
        x_values, y_values = speed_series(metrics)
        self._curve.setData(x_values, y_values)

        if current_frame_index is None:
            self._current_point.setData([], [])
            return

        current_metric = next(
            (metric for metric in metrics if metric.to_frame == current_frame_index),
            None,
        )
        if current_metric is None:
            self._current_point.setData([], [])
            return

        self._current_point.setData([current_metric.t_end_s], [current_metric.speed_mps])
