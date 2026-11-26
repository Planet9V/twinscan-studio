"""Realistic synthetic LD19 facility room and equipment simulator.

Ray-casts 360-degree scans against a virtual critical-infrastructure room with
walls, a doorway opening, server racks, PLC cabinets, HVAC unit, and an optional
rogue/moved object for live testing without hardware attached.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from src.lidar.ld19_parser import (
    LD19_POINTS_PER_PACKET,
    LidarPoint,
    encode_ld19_packet,
    polar_to_cartesian,
)


def _ray_segment_intersection(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> Optional[float]:
    """Return ray distance ``t > 0`` to line segment ``(x1, y1)-(x2, y2)``, or None."""
    vx, vy = x2 - x1, y2 - y1
    denom = dx * vy - dy * vx
    if abs(denom) < 1e-9:
        return None
    wx, wy = x1 - ox, y1 - oy
    t = (wx * vy - wy * vx) / denom
    u = (wx * dy - wy * dx) / denom
    if t > 0.05 and 0.0 <= u <= 1.0:
        return t
    return None


def _box_segments(cx: float, cy: float, w: float, d: float) -> List[Tuple[float, float, float, float]]:
    """Return the four boundary wall segments of an axis-aligned rectangle."""
    hw, hd = w / 2.0, d / 2.0
    p1 = (cx - hw, cy - hd)
    p2 = (cx + hw, cy - hd)
    p3 = (cx + hw, cy + hd)
    p4 = (cx - hw, cy + hd)
    return [
        (p1[0], p1[1], p2[0], p2[1]),
        (p2[0], p2[1], p3[0], p3[1]),
        (p3[0], p3[1], p4[0], p4[1]),
        (p4[0], p4[1], p1[0], p1[1]),
    ]


class FacilityRoomSimulator:
    """Synthetic LD19 360-degree scanner inside a simulated OT/server room."""

    def __init__(
        self,
        points_per_scan: int = 360,
        noise_std_m: float = 0.012,
        seed: int = 7,
    ) -> None:
        """Initialize the simulated room geometry and sensor noise model.

        Args:
            points_per_scan: Number of angular rays per 360-degree revolution.
            noise_std_m: Gaussian radial measurement noise standard deviation in meters.
            seed: Seed for deterministic testing.
        """
        self.points_per_scan = points_per_scan
        self.noise_std_m = noise_std_m
        self._rng = np.random.default_rng(seed)
        self.inject_rogue_object: bool = False
        self.simulate_moving_targets: bool = False
        self.sensor_x: float = 0.0
        self.sensor_y: float = 0.0
        self._timestamp_ms: int = 0
        self._sim_elapsed_s: float = 0.0

        # 7.6m x 5.8m room with a 1.1m doorway opening on the south wall.
        self._base_segments: List[Tuple[float, float, float, float, int]] = [
            # Outer walls (intensity ~185)
            (-3.8, -2.9, -0.6, -2.9, 185),
            (0.5, -2.9, 3.8, -2.9, 185),
            (3.8, -2.9, 3.8, 2.9, 185),
            (3.8, 2.9, -3.8, 2.9, 185),
            (-3.8, 2.9, -3.8, -2.9, 185),
        ]
        # Internal OT / Cyber equipment blocks (high metallic reflectance ~230)
        for seg in _box_segments(2.1, 1.5, 0.85, 0.95):  # Server Rack A1
            self._base_segments.append((*seg, 232))
        for seg in _box_segments(2.1, 0.1, 0.85, 0.95):  # Server Rack A2
            self._base_segments.append((*seg, 228))
        for seg in _box_segments(-2.3, 1.4, 0.9, 0.6):   # Siemens PLC Control Cabinet
            self._base_segments.append((*seg, 240))
        for seg in _box_segments(-2.4, -1.5, 1.1, 0.7):  # Chilled Water / HVAC Unit
            self._base_segments.append((*seg, 210))

        self._rogue_segments: List[Tuple[float, float, float, float, int]] = [
            (*seg, 248) for seg in _box_segments(-0.4, 1.4, 0.55, 0.45)
        ]

    def generate_scan(self, dt_s: float = 0.1) -> List[LidarPoint]:
        """Generate one full 360-degree simulated LiDAR revolution.

        Args:
            dt_s: Elapsed time step in seconds used to advance virtual moving targets.

        Returns:
            List of ``LidarPoint`` objects representing the current room sweep.
        """
        segments = list(self._base_segments)
        if self.inject_rogue_object:
            segments.extend(self._rogue_segments)
        if self.simulate_moving_targets:
            self._sim_elapsed_s += max(0.02, min(1.0, float(dt_s)))
            # Target 1: smooth horizontal patrol (~0.45 m/s) across north corridor
            tx1 = 1.2 * math.sin(self._sim_elapsed_s * 0.375)
            ty1 = 1.15
            for seg in _box_segments(tx1, ty1, 0.36, 0.36):
                segments.append((*seg, 246))
            # Target 2: smooth vertical/diagonal patrol (~0.35 m/s) across west aisle
            tx2 = -0.85 + 0.55 * math.cos(self._sim_elapsed_s * 0.42)
            ty2 = -0.75 + 0.65 * math.sin(self._sim_elapsed_s * 0.42)
            for seg in _box_segments(tx2, ty2, 0.34, 0.34):
                segments.append((*seg, 244))

        points: List[LidarPoint] = []
        angles = np.linspace(0.0, 360.0, self.points_per_scan, endpoint=False)
        for angle in angles:
            rad = math.radians(float(angle))
            dx, dy = math.cos(rad), math.sin(rad)
            best_t = 12.0
            best_intensity = 90
            for x1, y1, x2, y2, inten in segments:
                hit = _ray_segment_intersection(self.sensor_x, self.sensor_y, dx, dy, x1, y1, x2, y2)
                if hit is not None and hit < best_t:
                    best_t = hit
                    best_intensity = inten

            noisy_dist = max(0.08, best_t + float(self._rng.normal(0.0, self.noise_std_m)))
            noisy_int = max(0, min(255, int(best_intensity + self._rng.integers(-8, 9))))
            x, y = polar_to_cartesian(float(angle), noisy_dist)
            points.append(
                LidarPoint(
                    angle_deg=float(angle),
                    distance_m=noisy_dist,
                    intensity=noisy_int,
                    x=x,
                    y=y,
                )
            )
        self._timestamp_ms = (self._timestamp_ms + 100) % 30000
        return points

    def generate_ld19_packets(self) -> List[bytes]:
        """Generate CRC-valid 47-byte binary LD19 packets for one simulated revolution.

        Returns:
            List of 47-byte binary LD19 frames.
        """
        scan = self.generate_scan()
        packets: List[bytes] = []
        for idx in range(0, len(scan) - LD19_POINTS_PER_PACKET + 1, LD19_POINTS_PER_PACKET):
            chunk = scan[idx : idx + LD19_POINTS_PER_PACKET]
            measurements = [(int(round(p.distance_m * 1000)), p.intensity) for p in chunk]
            packets.append(
                encode_ld19_packet(
                    speed_dps=3600,
                    start_angle_deg=chunk[0].angle_deg,
                    end_angle_deg=chunk[-1].angle_deg,
                    measurements=measurements,
                    timestamp_ms=self._timestamp_ms,
                )
            )
        return packets
