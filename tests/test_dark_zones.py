"""Unit tests for Spatial Dark-Zone occlusion detection and Next-Best-View waypoint planning."""

from __future__ import annotations

from src.lidar.dark_zones import detect_spatial_dark_zones
from src.lidar.mapping import extract_walls_ransac, segment_object_clusters
from src.lidar.simulator import FacilityRoomSimulator


def test_detect_spatial_dark_zones_finds_shadows_and_unidentified_clusters() -> None:
    """Simulator room produces occlusion shadows behind racks and unidentified hardware clusters."""
    sim = FacilityRoomSimulator(points_per_scan=540, noise_std_m=0.008, seed=11)
    scan = sim.generate_scan()
    _, residuals = extract_walls_ransac(scan, distance_threshold_m=0.06, min_inliers=14)
    clusters = segment_object_clusters(residuals, eps_m=0.25, min_samples=4)

    dark_zones = detect_spatial_dark_zones(scan, clusters, placed_equipment=[])
    assert len(dark_zones) >= 2
    kinds = {d.kind for d in dark_zones}
    assert "unidentified_cluster" in kinds
    assert all(0 <= d.priority_score <= 100 for d in dark_zones)
    assert dark_zones[0].priority_score >= dark_zones[-1].priority_score

    # Pinning equipment directly over a cluster removes it from unidentified_cluster dark zones.
    first_cluster = clusters[0]
    dark_after = detect_spatial_dark_zones(
        scan,
        clusters,
        placed_equipment=[{"x": first_cluster.centroid_x, "y": first_cluster.centroid_y}],
    )
    cluster_ids_after = {d.id for d in dark_after if d.kind == "unidentified_cluster"}
    assert f"dark-cluster-{first_cluster.cluster_id}" not in cluster_ids_after
