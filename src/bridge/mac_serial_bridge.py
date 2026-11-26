"""macOS/Linux host USB-serial bridge streaming LD19 packets into Docker over WebSocket.

Docker Desktop on macOS cannot natively mount ``/dev/cu.usbserial-*`` into Linux
containers. Run this lightweight host script on macOS (or directly on PuppyPi)
to stream binary LD19 frames to the Dockerized Eigenia TwinScan backend.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import sys
from typing import Optional

import serial
import websockets


def discover_ld19_serial_port() -> Optional[str]:
    """Auto-detect a likely CP2102/CH340 USB-serial port for the LD19 LiDAR.

    Returns:
        Device path string if found, otherwise ``None``.
    """
    patterns = (
        "/dev/cu.usbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.wchusbserial*",
        "/dev/ttyUSB*",
        "/dev/ldlidar*",
    )
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


async def stream_serial_to_websocket(
    port: str,
    ws_url: str,
    baudrate: int = 230400,
    chunk_size: int = 470,
    max_retries: int = 3,
) -> None:
    """Read raw LD19 binary bytes from serial and stream them to the backend WebSocket.

    Wraps connection attempts in ``try/except`` with ``stderr`` logging and up to
    ``max_retries`` exponential backoff retries.

    Args:
        port: Serial device path (e.g., ``/dev/cu.usbserial-0001``).
        ws_url: Target WebSocket ingest URL (e.g., ``ws://localhost:8000/api/lidar/ingest``).
        baudrate: UART baud rate (LD19 default is ``230400``).
        chunk_size: Bytes read per batch (multiple of 47 bytes recommended).
        max_retries: Maximum reconnect retries before exiting.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            with serial.Serial(port=port, baudrate=baudrate, timeout=0.2) as ser:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    attempt = 0
                    sys.stderr.write(f"[bridge] Streaming {port} @ {baudrate} -> {ws_url}\n")
                    while True:
                        data = ser.read(chunk_size)
                        if data:
                            await ws.send(data)
                        else:
                            await asyncio.sleep(0.005)
        except KeyboardInterrupt:
            sys.stderr.write("[bridge] Stopped by user.\n")
            return
        except Exception as exc:
            attempt += 1
            sys.stderr.write(f"[bridge] Connection error (attempt {attempt}/{max_retries}): {exc}\n")
            if attempt >= max_retries:
                raise
            await asyncio.sleep(min(2.0 ** attempt, 8.0))


def run_cli() -> None:
    """Parse CLI arguments and launch the LD19 serial-to-WebSocket bridge."""
    parser = argparse.ArgumentParser(description="Eigenia TwinScan LD19 Serial-to-WebSocket Bridge")
    parser.add_argument("--port", default=None, help="Serial device path (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=230400, help="LD19 baud rate (default: 230400)")
    parser.add_argument(
        "--ws-url",
        default="ws://localhost:8000/api/lidar/ingest",
        help="Backend WebSocket ingest URL",
    )
    args = parser.parse_args()

    port = args.port or discover_ld19_serial_port()
    if not port:
        sys.stderr.write("[bridge] ERROR: No LD19 USB serial device found. Pass --port explicitly.\n")
        sys.exit(1)

    asyncio.run(stream_serial_to_websocket(port=port, ws_url=args.ws_url, baudrate=args.baud))


if __name__ == "__main__":
    run_cli()
