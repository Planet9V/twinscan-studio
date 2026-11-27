"""Unit tests for src/vision/overwatch_tracker.py."""

from __future__ import annotations

import numpy as np
import pytest

from src.vision.overwatch_tracker import (
    CrossViewTargetTracker,
    compute_hsv_descriptor,
    hsv_cosine_similarity,
    triangulate_n_rays_weighted,
)


def test_triangulate_n_rays_orthogonal_vs_collinear_gdop() -> None:
    """90-degree rays produce tight OPTIMAL GDOP; narrow-angle rays produce higher GDOP."""
    # Target at (0, 0, 0.5)
    o1 = np.array([-2.0, 0.0, 0.5])
    d1 = np.array([1.0, 0.0, 0.0])
    o2 = np.array([0.0, -2.0, 0.5])
    d2 = np.array([0.0, 1.0, 0.0])

    ortho = triangulate_n_rays_weighted(
        [
            {"camera_id": "usb_4k", "origin": o1, "direction": d1, "angular_sigma_rad": 0.005},
            {"camera_id": "macbook_cam", "origin": o2, "direction": d2, "angular_sigma_rad": 0.01},
        ]
    )
    assert abs(ortho["x"]) < 0.02
    assert abs(ortho["y"]) < 0.02
    assert abs(ortho["z"] - 0.5) < 0.02
    assert ortho["gdop_rating"] == "OPTIMAL"
    assert ortho["gdop"] <= 1.6

    # Narrow 10-degree baseline looking at (0, 2, 0.5)
    o3 = np.array([-0.18, 0.0, 0.5])
    d3 = np.array([0.18, 2.0, 0.0])
    o4 = np.array([0.18, 0.0, 0.5])
    d4 = np.array([-0.18, 2.0, 0.0])
    narrow = triangulate_n_rays_weighted(
        [
            {"camera_id": "usb_4k", "origin": o3, "direction": d3, "angular_sigma_rad": 0.01},
            {"camera_id": "macbook_cam", "origin": o4, "direction": d4, "angular_sigma_rad": 0.01},
        ]
    )
    assert narrow["gdop"] > ortho["gdop"] * 2.0
    assert narrow["ellipse_2sigma"]["semi_major_m"] > narrow["ellipse_2sigma"]["semi_minor_m"]


def test_cross_view_tracker_fuses_and_persists_track_id() -> None:
    """Two cameras observing the same person fuse into one persistent TRK-01 with 2 cameras."""
    tracker = CrossViewTargetTracker(track_ttl_sec=5.0, obs_ttl_sec=2.0)

    # Frame from usb_4k
    t1 = tracker.update_camera_observations(
        "usb_4k",
        [
            {
                "label": "person",
                "kind": "object",
                "confidence": 0.9,
                "origin": [-2.0, 0.0, 1.0],
                "direction": [2.0, 0.0, -0.5],
                "angular_sigma_rad": 0.006,
                "ground_xy": (0.0, 0.0),
                "bbox_norm": [0.4, 0.3, 0.6, 0.8],
                "hsv_desc": None,
            }
        ],
        now_mono=100.0,
    )
    assert len(t1) == 1
    assert t1[0]["track_id"] == "TRK-01"
    assert t1[0]["cameras"] == ["usb_4k"]

    # Frame from macbook_cam looking at the same 3D point (0, 0, 0.5)
    t2 = tracker.update_camera_observations(
        "macbook_cam",
        [
            {
                "label": "person",
                "kind": "object",
                "confidence": 0.85,
                "origin": [0.0, -2.0, 1.0],
                "direction": [0.0, 2.0, -0.5],
                "angular_sigma_rad": 0.012,
                "ground_xy": (0.0, 0.0),
                "bbox_norm": [0.45, 0.3, 0.65, 0.8],
                "hsv_desc": None,
            }
        ],
        now_mono=100.2,
    )
    assert len(t2) == 1
    assert t2[0]["track_id"] == "TRK-01"
    assert set(t2[0]["cameras"]) == {"usb_4k", "macbook_cam"}
    assert len(t2[0]["sightlines"]) == 2
    assert t2[0]["gdop_rating"] in ("OPTIMAL", "GOOD")

    # Track expires after TTL
    assert tracker.list_tracks(now_mono=110.0) == []


def test_hsv_descriptor_similarity() -> None:
    """Identical solid color crops have cosine similarity ~1.0; distinct hues score lower."""
    blue = np.full((100, 100, 3), (220, 40, 20), dtype=np.uint8)
    red = np.full((100, 100, 3), (20, 40, 220), dtype=np.uint8)
    h1 = compute_hsv_descriptor(blue, [0.1, 0.1, 0.9, 0.9])
    h2 = compute_hsv_descriptor(blue, [0.2, 0.2, 0.8, 0.8])
    h3 = compute_hsv_descriptor(red, [0.1, 0.1, 0.9, 0.9])
    assert hsv_cosine_similarity(h1, h2) > 0.99
    assert hsv_cosine_similarity(h1, h3) < 0.7


def test_triangulate_n_rays_requires_two_rays() -> None:
    """Single ray raises ValueError."""
    with pytest.raises(ValueError, match="at least 2"):
        triangulate_n_rays_weighted([{"origin": [0, 0, 1], "direction": [1, 0, 0]}])
