import json
from pathlib import Path

from pixel_track.controller import ProjectController
from pixel_track.analysis import build_segment_metrics, segment_metrics_for_frame
from pixel_track.frame_sequence import collect_frame_paths, natural_sort_key
from pixel_track.model import Calibration, FrameOverride, MeasurementStep, Project
from pixel_track.project_io import export_metrics_csv, load_project, save_project


def test_calibration_converts_pixels_to_meters() -> None:
    calibration = Calibration(p1=(0.0, 0.0), p2=(100.0, 0.0), length_m=10.0)
    assert calibration.pixel_length == 100.0
    assert calibration.pixels_per_meter == 10.0
    assert calibration.meters_between((0.0, 0.0), (50.0, 0.0)) == 5.0


def test_project_uses_nearest_previous_calibration() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png"), Path("003.png")])
    project.base_calibration = Calibration((0.0, 0.0), (10.0, 0.0), 1.0)
    project.frame_overrides[1] = FrameOverride(
        calibration=Calibration((0.0, 0.0), (20.0, 0.0), 2.0)
    )

    calibration = project.effective_calibration(2)
    assert calibration is not None
    assert calibration.length_m == 2.0


def test_build_segment_metrics_uses_current_frame_calibration() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png"), Path("003.png")], fps=25.0)
    project.base_calibration = Calibration((0.0, 0.0), (100.0, 0.0), 10.0)
    project.measurements[0] = MeasurementStep(frame_index=0, current_point_px=(10.0, 10.0))
    project.measurements[2] = MeasurementStep(
        frame_index=2,
        previous_point_on_this_frame_px=(10.0, 10.0),
        current_point_px=(60.0, 10.0),
    )

    metrics = build_segment_metrics(project)

    assert len(metrics) == 1
    assert metrics[0].distance_m == 5.0
    assert metrics[0].dt_s == 2 / 25.0


def test_natural_sort_key_orders_numeric_suffixes() -> None:
    names = ["frame_10.png", "frame_2.png", "frame_1.png"]
    assert sorted(names, key=natural_sort_key) == ["frame_1.png", "frame_2.png", "frame_10.png"]


def test_collect_frame_paths_filters_and_sorts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pixel_track.frame_sequence.supported_image_suffixes", lambda: {".png", ".jpg"})

    for name in ["frame_10.png", "frame_2.png", "frame_1.jpg", "notes.txt"]:
        (tmp_path / name).write_text("x")

    frame_paths = collect_frame_paths(tmp_path)
    assert [path.name for path in frame_paths] == ["frame_1.jpg", "frame_2.png", "frame_10.png"]


def test_controller_creates_current_frame_calibration_override() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")])
    project.frame_overrides[0] = FrameOverride(
        calibration=Calibration((0.0, 0.0), (10.0, 0.0), 1.0)
    )
    controller = ProjectController(project)
    controller.set_frame(1)

    calibration = controller.set_current_calibration((1.0, 1.0), (21.0, 1.0), 2.0)

    assert calibration is not None
    assert controller.current_calibration() is not None
    assert controller.current_calibration_source_index() == 1
    assert controller.current_calibration().length_m == 2.0


def test_controller_updates_length_from_inherited_calibration() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")])
    project.frame_overrides[0] = FrameOverride(
        calibration=Calibration((0.0, 0.0), (20.0, 0.0), 2.0)
    )
    controller = ProjectController(project)
    controller.set_frame(1)

    calibration = controller.set_current_calibration_length(4.0)

    assert calibration is not None
    assert controller.current_calibration_source_index() == 1
    assert controller.current_calibration().length_m == 4.0


def test_controller_updates_calibration_endpoint_on_current_frame() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")])
    project.frame_overrides[0] = FrameOverride(
        calibration=Calibration((0.0, 0.0), (20.0, 0.0), 2.0)
    )
    controller = ProjectController(project)
    controller.set_frame(1)

    calibration = controller.set_current_calibration_endpoint("p2", (40.0, 5.0))

    assert calibration is not None
    assert controller.current_calibration_source_index() == 1
    assert controller.current_calibration() is not None
    assert controller.current_calibration().p1 == (0.0, 0.0)
    assert controller.current_calibration().p2 == (40.0, 5.0)
    assert controller.current_calibration().length_m == 2.0


def test_segment_metrics_for_frame_uses_previous_measured_frame() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png"), Path("003.png")], fps=20.0)
    project.base_calibration = Calibration((0.0, 0.0), (100.0, 0.0), 10.0)
    project.measurements[0] = MeasurementStep(frame_index=0, current_point_px=(10.0, 10.0))
    project.measurements[2] = MeasurementStep(
        frame_index=2,
        previous_point_on_this_frame_px=(10.0, 10.0),
        current_point_px=(60.0, 10.0),
    )

    metrics = segment_metrics_for_frame(project, 2)

    assert metrics is not None
    assert metrics.from_frame == 0
    assert metrics.to_frame == 2
    assert metrics.distance_m == 5.0
    assert metrics.speed_mps == 50.0


def test_controller_sets_previous_and_current_points() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")], fps=25.0)
    project.base_calibration = Calibration((0.0, 0.0), (100.0, 0.0), 10.0)
    controller = ProjectController(project)

    controller.set_current_point((10.0, 10.0))
    controller.set_frame(1)
    controller.set_previous_point((12.0, 10.0))
    controller.set_current_point((42.0, 10.0))

    step = controller.current_measurement()
    metrics = controller.current_segment_metrics()

    assert step is not None
    assert step.previous_point_on_this_frame_px == (12.0, 10.0)
    assert step.current_point_px == (42.0, 10.0)
    assert metrics is not None
    assert metrics.distance_m == 3.0


def test_controller_autofills_previous_point_from_adjacent_frame() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")], fps=25.0)
    controller = ProjectController(project)

    controller.set_current_point((15.0, 25.0))
    controller.set_frame(1)

    step = controller.current_measurement()
    assert step is not None
    assert step.previous_point_on_this_frame_px == (15.0, 25.0)
    assert step.previous_point_is_auto is True


def test_manual_previous_point_is_not_overwritten_by_autofill() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png")], fps=25.0)
    controller = ProjectController(project)

    controller.set_current_point((10.0, 20.0))
    controller.set_frame(1)
    controller.set_previous_point((30.0, 40.0))
    controller.set_frame(0)
    controller.set_current_point((99.0, 99.0))
    controller.set_frame(1)

    step = controller.current_measurement()
    assert step is not None
    assert step.previous_point_on_this_frame_px == (30.0, 40.0)
    assert step.previous_point_is_auto is False


def test_metrics_ignore_frames_that_only_have_autofilled_previous_point() -> None:
    project = Project(frame_paths=[Path("001.png"), Path("002.png"), Path("003.png")], fps=10.0)
    project.base_calibration = Calibration((0.0, 0.0), (100.0, 0.0), 10.0)
    controller = ProjectController(project)

    controller.set_current_point((10.0, 10.0))
    controller.set_frame(1)
    controller.set_frame(2)
    controller.set_previous_point((12.0, 10.0))
    controller.set_current_point((60.0, 10.0))

    metrics = controller.current_segment_metrics()
    assert metrics is not None
    assert metrics.from_frame == 0
    assert metrics.to_frame == 2
    assert metrics.dt_s == 0.2


def test_project_roundtrip_persists_calibration_and_measurements(tmp_path) -> None:
    source_directory = tmp_path / "frames"
    source_directory.mkdir()
    frame_paths = [source_directory / "001.png", source_directory / "002.png"]
    for frame_path in frame_paths:
        frame_path.write_text("frame")

    project = Project(frame_paths=frame_paths, fps=30.0, source_directory=source_directory)
    project.base_calibration = Calibration((0.0, 0.0), (100.0, 0.0), 10.0)
    project.frame_overrides[1] = FrameOverride(
        calibration=Calibration((1.0, 2.0), (101.0, 2.0), 10.0)
    )
    project.measurements[0] = MeasurementStep(frame_index=0, current_point_px=(10.0, 20.0))
    project.measurements[1] = MeasurementStep(
        frame_index=1,
        current_point_px=(40.0, 20.0),
        previous_point_on_this_frame_px=(12.0, 20.0),
        previous_point_is_auto=True,
    )

    path = tmp_path / "session.pixeltrack.json"
    save_project(project, path)
    restored = load_project(path)

    assert restored.fps == 30.0
    assert restored.source_directory == source_directory
    assert restored.frame_paths == frame_paths
    assert restored.base_calibration is not None
    assert restored.base_calibration.length_m == 10.0
    assert restored.frame_overrides[1].calibration is not None
    assert restored.measurements[1].current_point_px == (40.0, 20.0)
    assert restored.measurements[1].previous_point_is_auto is True


def test_project_roundtrip_keeps_bundle_portable_after_move(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    source_directory = bundle / "frames"
    source_directory.mkdir()
    frame_paths = [source_directory / "001.png", source_directory / "002.png"]
    for frame_path in frame_paths:
        frame_path.write_text("frame")

    project = Project(frame_paths=frame_paths, fps=60.0, source_directory=source_directory)
    project.measurements[0] = MeasurementStep(frame_index=0, current_point_px=(5.0, 10.0))

    project_path = bundle / "session.pixeltrack.json"
    save_project(project, project_path)

    payload = json.loads(project_path.read_text(encoding="utf-8"))
    assert payload["source_directory"]["relative_to"] == "project"
    assert payload["source_directory"]["path"] == "frames"
    assert payload["frame_paths"][0]["relative_to"] == "source"

    moved_bundle = tmp_path / "moved-bundle"
    bundle.rename(moved_bundle)
    moved_project_path = moved_bundle / "session.pixeltrack.json"

    restored = load_project(moved_project_path)

    assert restored.source_directory == moved_bundle / "frames"
    assert restored.frame_paths == [
        moved_bundle / "frames" / "001.png",
        moved_bundle / "frames" / "002.png",
    ]
    assert restored.measurements[0].current_point_px == (5.0, 10.0)


def test_export_metrics_csv_writes_rows(tmp_path) -> None:
    metrics = [
        segment_metrics_for_frame(
            Project(
                frame_paths=[Path("001.png"), Path("002.png")],
                fps=25.0,
                base_calibration=Calibration((0.0, 0.0), (100.0, 0.0), 10.0),
                measurements={
                    0: MeasurementStep(frame_index=0, current_point_px=(10.0, 10.0)),
                    1: MeasurementStep(
                        frame_index=1,
                        previous_point_on_this_frame_px=(12.0, 10.0),
                        current_point_px=(42.0, 10.0),
                    ),
                },
            ),
            1,
        )
    ]
    metrics = [metric for metric in metrics if metric is not None]

    destination = tmp_path / "measurements.csv"
    export_metrics_csv(metrics, destination)
    content = destination.read_text(encoding="utf-8")

    assert "from_frame,to_frame,t_end_s,dt_s,distance_m,speed_mps" in content
    assert "1,2," in content
