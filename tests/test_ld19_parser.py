"""Unit tests for the LD19 binary protocol decoder and stream assembler."""

from __future__ import annotations

import pytest

from src.lidar.ld19_parser import (
    LD19_PACKET_SIZE,
    LD19StreamDecoder,
    compute_ld19_crc8,
    encode_ld19_packet,
    parse_ld19_packet,
    polar_to_cartesian,
)


def test_encode_and_parse_ld19_packet_roundtrip() -> None:
    """Valid 47-byte LD19 packet encodes and decodes with exact CRC and interpolation."""
    measurements = [(1000 + i * 50, 200 + i) for i in range(12)]
    raw = encode_ld19_packet(
        speed_dps=3600,
        start_angle_deg=10.0,
        end_angle_deg=21.0,
        measurements=measurements,
        timestamp_ms=1234,
    )
    assert len(raw) == LD19_PACKET_SIZE
    assert compute_ld19_crc8(raw[:-1]) == raw[-1]

    pkt = parse_ld19_packet(raw)
    assert pkt is not None
    assert pkt.speed_dps == 3600
    assert pkt.timestamp_ms == 1234
    assert len(pkt.points) == 12
    assert pytest.approx(pkt.points[0].angle_deg, abs=0.05) == 10.0
    assert pytest.approx(pkt.points[-1].angle_deg, abs=0.05) == 21.0
    assert pytest.approx(pkt.points[0].distance_m, abs=1e-4) == 1.0
    assert pkt.points[0].intensity == 200


def test_parse_ld19_packet_rejects_bad_crc_and_length() -> None:
    """Corrupted CRC or truncated buffers return None."""
    measurements = [(1500, 180)] * 12
    raw = bytearray(encode_ld19_packet(3600, 0.0, 11.0, measurements))
    raw[-1] ^= 0xFF
    assert parse_ld19_packet(bytes(raw)) is None
    assert parse_ld19_packet(b"\x54\x2c\x00") is None


def test_encode_ld19_packet_validates_point_count() -> None:
    """Encoding fewer or more than 12 points raises ValueError."""
    with pytest.raises(ValueError):
        encode_ld19_packet(3600, 0.0, 10.0, [(1000, 100)] * 5)


def test_polar_to_cartesian_axes() -> None:
    """0 deg maps to +X and 90 deg maps to +Y."""
    x0, y0 = polar_to_cartesian(0.0, 2.0)
    assert pytest.approx(x0, abs=1e-6) == 2.0
    assert pytest.approx(y0, abs=1e-6) == 0.0
    x90, y90 = polar_to_cartesian(90.0, 3.0)
    assert pytest.approx(x90, abs=1e-6) == 0.0
    assert pytest.approx(y90, abs=1e-6) == 3.0


def test_stream_decoder_recovers_from_garbage_and_emits_full_scan() -> None:
    """Stream decoder skips leading noise bytes and emits a full revolution on wrap."""
    decoder = LD19StreamDecoder()
    stream = bytearray(b"\x00\xFF\x12\x34")
    # Build 30 packets covering 0..360 plus one wrapped packet to trigger emission.
    for p in range(31):
        start = (p * 12.0) % 360.0
        end = (start + 11.0) % 360.0
        stream.extend(encode_ld19_packet(3600, start, end, [(2000, 210)] * 12, p * 3))

    scans = decoder.feed(bytes(stream[:120]))
    scans.extend(decoder.feed(bytes(stream[120:])))
    assert len(scans) >= 1
    assert len(scans[0]) == 360
    assert decoder.packets_decoded == 31
    assert decoder.last_rpm == 600.0
