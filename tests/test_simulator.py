"""Unit tests for the synthetic LD19 facility simulator and serial bridge discovery."""

from __future__ import annotations

from unittest.mock import patch

from src.bridge.mac_serial_bridge import discover_ld19_serial_port
from src.lidar.ld19_parser import LD19StreamDecoder
from src.lidar.simulator import FacilityRoomSimulator


def test_simulator_generates_valid_ld19_binary_packets() -> None:
    """Simulated LD19 binary packets decode cleanly through LD19StreamDecoder."""
    sim = FacilityRoomSimulator(points_per_scan=360, noise_std_m=0.01, seed=3)
    packets = sim.generate_ld19_packets()
    assert len(packets) == 30

    decoder = LD19StreamDecoder()
    # Feed two revolutions so wrap-around emits at least one full scan.
    raw_stream = b"".join(packets) + b"".join(sim.generate_ld19_packets())
    scans = decoder.feed(raw_stream)
    assert decoder.crc_errors == 0
    assert len(scans) >= 1
    assert len(scans[0]) == 360


def test_discover_ld19_serial_port() -> None:
    """Serial discovery returns first matching USB-serial device path."""
    with patch("src.bridge.mac_serial_bridge.glob.glob") as mock_glob:
        mock_glob.side_effect = lambda p: ["/dev/cu.usbserial-0001"] if "usbserial" in p else []
        assert discover_ld19_serial_port() == "/dev/cu.usbserial-0001"
