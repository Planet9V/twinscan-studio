"""Unit tests for RANSAC wall extraction, DBSCAN object clustering, and room metrology."""

from __future__ import annotations

from src.lidar.mapping import compute_room_metrics, extract_walls_ransac, segment_object_clusters
from src.lidar.simulator import FacilityRoomSimulator


def test_extract_walls_and_clusters_on_simulated_room() -> None:
    """RANSAC extracts perimeter walls and DBSCAN segments internal equipment clusters."""
    sim = FacilityRoomSimulator(points_per_scan=540, noise_std_m=0.008, seed=11)
    scan = sim.generate_scan()

    walls, residuals = extract_walls_ransac(scan, distance_threshold_m=0.06, min_inliers=14)
    assert len(walls) >= 4
    assert all(w.length_m >= 0.6 for w in walls)

    clusters = segment_object_clusters(residuals, eps_m=0.25, min_samples=4)
    assert len(clusters) >= 2
    assert all(c.width_m > 0 and c.depth_m > 0 for c in clusters)

    metrics = compute_room_metrics(walls, scan)
    assert metrics["area_m2"] > 20.0
    assert metrics["width_m"] > 5.0
    assert metrics["depth_m"] > 4.0
