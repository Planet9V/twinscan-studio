"""Unit tests for log-odds occupancy grid and physical change detection."""

from __future__ import annotations

from src.lidar.change_detection import LogOddsOccupancyGrid
from src.lidar.simulator import FacilityRoomSimulator


def test_change_detection_flags_injected_rogue_object() -> None:
    """Baseline vs live scan diff detects a newly placed physical object."""
    sim = FacilityRoomSimulator(points_per_scan=360, noise_std_m=0.008, seed=5)
    grid = LogOddsOccupancyGrid(size_m=12.0, resolution_m=0.08)

    # Accumulate clean baseline over 3 scans.
    for _ in range(3):
        grid.update(sim.generate_scan())
    grid.capture_baseline()

    # Clean live scan should produce zero critical anomalies.
    clean_anomalies = grid.detect_changes(sim.generate_scan(), min_cells=4)
    assert len(clean_anomalies) == 0

    # Inject rogue object at (-0.4, 1.4) and verify detection.
    sim.inject_rogue_object = True
    anomalies = grid.detect_changes(sim.generate_scan(), min_cells=3)
    assert len(anomalies) >= 1
    assert anomalies[0].anomaly_type == "added"
    assert abs(anomalies[0].centroid_x - (-0.4)) < 0.8
    assert abs(anomalies[0].centroid_y - 1.4) < 0.8
