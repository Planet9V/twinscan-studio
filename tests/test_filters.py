"""Unit tests for LiDAR filtering, sector masking, and safety zone intrusion detection."""

from __future__ import annotations

import pytest

from src.lidar.filters import FilterConfig, apply_lidar_filters, detect_zone_intrusions
from src.lidar.ld19_parser import LidarPoint, polar_to_cartesian


def _make_pt(angle: float, dist: float, intensity: int = 200) -> LidarPoint:
    x, y = polar_to_cartesian(angle, dist)
    return LidarPoint(angle_deg=angle, distance_m=dist, intensity=intensity, x=x, y=y)


def test_apply_lidar_filters_range_intensity_and_sector() -> None:
    """Range, intensity, and sector keep/exclude rules filter points accurately."""
    pts = [
        _make_pt(10.0, 0.05, 200),  # too close
        _make_pt(20.0, 1.5, 5),     # low intensity
        _make_pt(30.0, 2.0, 200),   # inside [0, 90]
        _make_pt(180.0, 2.0, 200),  # outside [0, 90]
        _make_pt(45.0, 15.0, 200),  # too far
    ]
    cfg = FilterConfig(
        min_range_m=0.1,
        max_range_m=10.0,
        min_intensity=20,
        sector_start_deg=0.0,
        sector_end_deg=90.0,
        exclude_sector=False,
    )
    kept = apply_lidar_filters(pts, cfg)
    assert len(kept) == 1
    assert pytest.approx(kept[0].angle_deg) == 30.0

    cfg_excl = FilterConfig(
        min_range_m=0.1,
        max_range_m=10.0,
        min_intensity=20,
        sector_start_deg=0.0,
        sector_end_deg=90.0,
        exclude_sector=True,
    )
    kept_excl = apply_lidar_filters(pts, cfg_excl)
    assert len(kept_excl) == 1
    assert pytest.approx(kept_excl[0].angle_deg) == 180.0


def test_apply_lidar_filters_outlier_removal_and_rotation() -> None:
    """Isolated speckle point is removed while clustered points survive."""
    cluster = [_make_pt(0.0 + i * 0.5, 2.0, 220) for i in range(6)]
    speckle = _make_pt(180.0, 5.0, 220)
    cfg = FilterConfig(
        rotation_offset_deg=90.0,
        enable_outlier_filter=True,
        outlier_radius_m=0.2,
        outlier_min_neighbors=2,
    )
    res = apply_lidar_filters(cluster + [speckle], cfg)
    assert len(res) == 6
    assert pytest.approx(res[0].angle_deg) == 90.0


def test_detect_zone_intrusions() -> None:
    """Zone intrusion detector flags polygon breaches above threshold."""
    pts = [
        LidarPoint(0.0, 1.0, 200, 1.1, 1.1),
        LidarPoint(0.0, 1.0, 200, 1.2, 1.2),
        LidarPoint(0.0, 1.0, 200, 1.3, 1.3),
        LidarPoint(0.0, 5.0, 200, -4.0, -4.0),
    ]
    zones = [
        {"id": "z1", "name": "Rack Clearance", "polygon": [[0.5, 0.5], [2.0, 0.5], [2.0, 2.0], [0.5, 2.0]], "threshold": 3}
    ]
    alerts = detect_zone_intrusions(pts, zones)
    assert len(alerts) == 1
    assert alerts[0]["zone_id"] == "z1"
    assert alerts[0]["hit_count"] == 3
