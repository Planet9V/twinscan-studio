"""Unit tests for multi-station 2D LiDAR scan registration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.lidar.registration import register_scans_2d
from src.lidar.simulator import FacilityRoomSimulator


def test_register_scans_2d_recovers_translation_and_rotation() -> None:
    """ICP registration recovers a known small translation and yaw offset."""
    sim = FacilityRoomSimulator(points_per_scan=240, noise_std_m=0.002, seed=9)
    target = np.array([[p.x, p.y] for p in sim.generate_scan()], dtype=np.float64)

    # Apply inverse offset to create source scan shifted by (+0.25m, -0.15m, +6 deg).
    theta = math.radians(-6.0)
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    source = (target - np.array([0.25, -0.15])) @ rot.T

    result = register_scans_2d(source, target, max_iterations=50)
    assert result["converged"] is True
    assert result["rmse_m"] < 0.08
    assert abs(result["dx_m"] - 0.25) < 0.12
    assert abs(result["dy_m"] - (-0.15)) < 0.12


def test_register_scans_2d_rejects_insufficient_points() -> None:
    """Fewer than 3 points raises ValueError."""
    with pytest.raises(ValueError):
        register_scans_2d(np.zeros((2, 2)), np.zeros((5, 2)))
