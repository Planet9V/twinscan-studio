"""LD19 360-degree DTOF LiDAR binary protocol decoder and stream assembler.

Implements the official 47-byte LD19 UART frame specification (230,400 baud),
CRC-8 integrity validation, linear angle interpolation across 12 points per
packet, and full-revolution scan assembly.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Iterable, List, Optional

LD19_HEADER = 0x54
LD19_VER_LEN = 0x2C
LD19_POINTS_PER_PACKET = 12
LD19_PACKET_SIZE = 47

# Official LDROBOT CRC-8 lookup table (polynomial 0x4D).
LD19_CRC_TABLE: tuple[int, ...] = (
    0x00, 0x4D, 0x9A, 0xD7, 0x79, 0x34, 0xE3, 0xAE, 0xF2, 0xBF, 0x68, 0x25,
    0x8B, 0xC6, 0x11, 0x5C, 0xA9, 0xE4, 0x33, 0x7E, 0xD0, 0x9D, 0x4A, 0x07,
    0x5B, 0x16, 0xC1, 0x8C, 0x22, 0x6F, 0xB8, 0xF5, 0x1F, 0x52, 0x85, 0xC8,
    0x66, 0x2B, 0xFC, 0xB1, 0xED, 0xA0, 0x77, 0x3A, 0x94, 0xD9, 0x0E, 0x43,
    0xB6, 0xFB, 0x2C, 0x61, 0xCF, 0x82, 0x55, 0x18, 0x44, 0x09, 0xDE, 0x93,
    0x3D, 0x70, 0xA7, 0xEA, 0x3E, 0x73, 0xA4, 0xE9, 0x47, 0x0A, 0xDD, 0x90,
    0xCC, 0x81, 0x56, 0x1B, 0xB5, 0xF8, 0x2F, 0x62, 0x97, 0xDA, 0x0D, 0x40,
    0xEE, 0xA3, 0x74, 0x39, 0x65, 0x28, 0xFF, 0xB2, 0x1C, 0x51, 0x86, 0xCB,
    0x21, 0x6C, 0xBB, 0xF6, 0x58, 0x15, 0xC2, 0x8F, 0xD3, 0x9E, 0x49, 0x04,
    0xAA, 0xE7, 0x30, 0x7D, 0x88, 0xC5, 0x12, 0x5F, 0xF1, 0xBC, 0x6B, 0x26,
    0x7A, 0x37, 0xE0, 0xAD, 0x03, 0x4E, 0x99, 0xD4, 0x7C, 0x31, 0xE6, 0xAB,
    0x05, 0x48, 0x9F, 0xD2, 0x8E, 0xC3, 0x14, 0x59, 0xF7, 0xBA, 0x6D, 0x20,
    0xD5, 0x98, 0x4F, 0x02, 0xAC, 0xE1, 0x36, 0x7B, 0x27, 0x6A, 0xBD, 0xF0,
    0x5E, 0x13, 0xC4, 0x89, 0x63, 0x2E, 0xF9, 0xB4, 0x1A, 0x57, 0x80, 0xCD,
    0x91, 0xDC, 0x0B, 0x46, 0xE8, 0xA5, 0x72, 0x3F, 0xCA, 0x87, 0x50, 0x1D,
    0xB3, 0xFE, 0x29, 0x64, 0x38, 0x75, 0xA2, 0xEF, 0x41, 0x0C, 0xDB, 0x96,
    0x42, 0x0F, 0xD8, 0x95, 0x3B, 0x76, 0xA1, 0xEC, 0xB0, 0xFD, 0x2A, 0x67,
    0xC9, 0x84, 0x53, 0x1E, 0xEB, 0xA6, 0x71, 0x3C, 0x92, 0xDF, 0x08, 0x45,
    0x19, 0x54, 0x83, 0xCE, 0x60, 0x2D, 0xFA, 0xB7, 0x5D, 0x10, 0xC7, 0x8A,
    0x24, 0x69, 0xBE, 0xF3, 0xAF, 0xE2, 0x35, 0x78, 0xD6, 0x9B, 0x4C, 0x01,
    0xF4, 0xB9, 0x6E, 0x23, 0x8D, 0xC0, 0x17, 0x5A, 0x06, 0x4B, 0x9C, 0xD1,
    0x7F, 0x32, 0xE5, 0xA8,
)


@dataclass(frozen=True)
class LidarPoint:
    """Single 2D polar and Cartesian LiDAR measurement.

    Attributes:
        angle_deg: Azimuth angle in degrees in range ``[0, 360)``.
        distance_m: Measured radial distance in meters.
        intensity: Signal reflectance confidence in range ``[0, 255]``.
        x: Cartesian X coordinate in meters (forward axis).
        y: Cartesian Y coordinate in meters (left axis).
    """

    angle_deg: float
    distance_m: float
    intensity: int
    x: float
    y: float

    def to_dict(self) -> dict[str, float | int]:
        """Serialize the point to a compact JSON-ready dictionary.

        Returns:
            Dictionary containing angle, distance, intensity, x, and y.
        """
        return {
            "angle_deg": round(self.angle_deg, 3),
            "distance_m": round(self.distance_m, 4),
            "intensity": int(self.intensity),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
        }


@dataclass(frozen=True)
class LidarPacket:
    """Decoded 47-byte LD19 telemetry packet.

    Attributes:
        speed_dps: Rotational speed in degrees per second.
        start_angle_deg: Angle of the first measurement in degrees.
        end_angle_deg: Angle of the twelfth measurement in degrees.
        timestamp_ms: Internal LD19 millisecond counter modulo 30000.
        points: List of 12 interpolated ``LidarPoint`` objects.
    """

    speed_dps: int
    start_angle_deg: float
    end_angle_deg: float
    timestamp_ms: int
    points: List[LidarPoint]


def compute_ld19_crc8(payload: bytes) -> int:
    """Compute the LD19 CRC-8 checksum over a byte buffer.

    Args:
        payload: Raw packet bytes excluding the final CRC byte (typically 46 bytes).

    Returns:
        Unsigned 8-bit CRC checksum integer.
    """
    crc = 0
    for byte in payload:
        crc = LD19_CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def polar_to_cartesian(angle_deg: float, distance_m: float) -> tuple[float, float]:
    """Convert polar LiDAR coordinates to Cartesian (x, y) meters.

    Args:
        angle_deg: Azimuth angle in degrees (clockwise from forward axis).
        distance_m: Radial distance in meters.

    Returns:
        Tuple ``(x, y)`` in meters.
    """
    rad = math.radians(angle_deg)
    return distance_m * math.cos(rad), distance_m * math.sin(rad)


def parse_ld19_packet(packet: bytes) -> Optional[LidarPacket]:
    """Decode and validate a single 47-byte LD19 packet.

    Args:
        packet: Exactly 47 bytes starting with ``0x54 0x2C``.

    Returns:
        Parsed ``LidarPacket`` when header and CRC-8 are valid, otherwise ``None``.
    """
    if len(packet) != LD19_PACKET_SIZE:
        return None
    if packet[0] != LD19_HEADER or packet[1] != LD19_VER_LEN:
        return None
    if compute_ld19_crc8(packet[:-1]) != packet[-1]:
        return None

    speed_dps, start_raw = struct.unpack_from("<HH", packet, 2)
    end_raw, timestamp_ms = struct.unpack_from("<HH", packet, 42)

    start_angle = (start_raw / 100.0) % 360.0
    end_angle = (end_raw / 100.0) % 360.0
    span = (end_angle - start_angle) % 360.0
    step = span / (LD19_POINTS_PER_PACKET - 1) if LD19_POINTS_PER_PACKET > 1 else 0.0

    points: List[LidarPoint] = []
    offset = 6
    for idx in range(LD19_POINTS_PER_PACKET):
        dist_mm, intensity = struct.unpack_from("<HB", packet, offset)
        offset += 3
        angle = (start_angle + idx * step) % 360.0
        dist_m = dist_mm / 1000.0
        x, y = polar_to_cartesian(angle, dist_m)
        points.append(
            LidarPoint(
                angle_deg=angle,
                distance_m=dist_m,
                intensity=intensity,
                x=x,
                y=y,
            )
        )

    return LidarPacket(
        speed_dps=speed_dps,
        start_angle_deg=start_angle,
        end_angle_deg=end_angle,
        timestamp_ms=timestamp_ms,
        points=points,
    )


def encode_ld19_packet(
    speed_dps: int,
    start_angle_deg: float,
    end_angle_deg: float,
    measurements: Iterable[tuple[int, int]],
    timestamp_ms: int = 0,
) -> bytes:
    """Encode 12 ``(distance_mm, intensity)`` measurements into a valid LD19 packet.

    Args:
        speed_dps: Rotational speed in degrees per second (e.g., 3600 for 10 Hz).
        start_angle_deg: Angle of first measurement in degrees.
        end_angle_deg: Angle of last measurement in degrees.
        measurements: Exactly 12 tuples of ``(distance_mm, intensity)``.
        timestamp_ms: Millisecond counter modulo 30000.

    Returns:
        47-byte binary LD19 packet with valid CRC-8 suffix.

    Raises:
        ValueError: If ``measurements`` does not contain exactly 12 entries.
    """
    items = list(measurements)
    if len(items) != LD19_POINTS_PER_PACKET:
        raise ValueError(f"Expected {LD19_POINTS_PER_PACKET} measurements, got {len(items)}")

    buf = bytearray()
    buf.append(LD19_HEADER)
    buf.append(LD19_VER_LEN)
    buf.extend(
        struct.pack(
            "<HH",
            int(speed_dps) & 0xFFFF,
            int(round((start_angle_deg % 360.0) * 100)) & 0xFFFF,
        )
    )
    for dist_mm, intensity in items:
        buf.extend(struct.pack("<HB", max(0, min(65535, int(dist_mm))), max(0, min(255, int(intensity)))))
    buf.extend(
        struct.pack(
            "<HH",
            int(round((end_angle_deg % 360.0) * 100)) & 0xFFFF,
            int(timestamp_ms) % 30000,
        )
    )
    buf.append(compute_ld19_crc8(bytes(buf)))
    return bytes(buf)


class LD19StreamDecoder:
    """Stateful streaming decoder that reassembles full 360-degree LD19 scans.

    Synchronizes on arbitrary incoming byte chunks, discards corrupted frames,
    and emits completed 360-degree point lists whenever azimuth wraps past 0 deg.
    """

    def __init__(self, max_buffer_bytes: int = 16384) -> None:
        """Initialize an empty decoder state.

        Args:
            max_buffer_bytes: Safety cap on unconsumed bytes before trimming.
        """
        self._buffer = bytearray()
        self._current_scan: List[LidarPoint] = []
        self._last_angle: Optional[float] = None
        self._last_speed_dps: int = 0
        self._max_buffer_bytes = max_buffer_bytes
        self.packets_decoded: int = 0
        self.crc_errors: int = 0

    @property
    def last_rpm(self) -> float:
        """Return the most recently observed LiDAR rotation rate in RPM."""
        return round(self._last_speed_dps / 6.0, 2)

    def feed(self, chunk: bytes) -> List[List[LidarPoint]]:
        """Feed raw serial bytes and return any completed 360-degree scans.

        Args:
            chunk: Raw bytes read from the LD19 serial port or WebSocket stream.

        Returns:
            List of completed full-revolution scans (each a list of ``LidarPoint``).
        """
        if not chunk:
            return []
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_buffer_bytes:
            del self._buffer[:-self._max_buffer_bytes]

        completed_scans: List[List[LidarPoint]] = []

        while len(self._buffer) >= LD19_PACKET_SIZE:
            header_idx = self._buffer.find(bytes([LD19_HEADER, LD19_VER_LEN]))
            if header_idx == -1:
                # Preserve the last byte in case it is 0x54 split across chunks.
                if self._buffer and self._buffer[-1] == LD19_HEADER:
                    self._buffer = bytearray([LD19_HEADER])
                else:
                    self._buffer.clear()
                break

            if header_idx > 0:
                del self._buffer[:header_idx]

            if len(self._buffer) < LD19_PACKET_SIZE:
                break

            candidate = bytes(self._buffer[:LD19_PACKET_SIZE])
            packet = parse_ld19_packet(candidate)
            if packet is None:
                self.crc_errors += 1
                del self._buffer[:1]
                continue

            del self._buffer[:LD19_PACKET_SIZE]
            self.packets_decoded += 1
            self._last_speed_dps = packet.speed_dps

            for pt in packet.points:
                if self._last_angle is not None and pt.angle_deg < self._last_angle - 180.0:
                    if self._current_scan:
                        completed_scans.append(self._current_scan)
                        self._current_scan = []
                self._current_scan.append(pt)
                self._last_angle = pt.angle_deg

        return completed_scans
