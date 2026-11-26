"""Unit and API tests for Raspberry Pi 5 PMIC power, USB budget, and 22-component 3D BOM diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.robot.pi5_diagnostics import (
    CANONICAL_PI5_COMPONENT_IDS,
    build_pi5_diagnostics_payload,
    decode_throttled_mask,
    parse_pmic_adc_output,
)

SAMPLE_PMIC_OUTPUT = """
 3V7_WL_SW_A current(0)=0.10052080A
   3V3_SYS_A current(1)=0.10052080A
   1V8_SYS_A current(2)=0.17371550A
  DDR_VDD2_A current(3)=0.03318162A
  DDR_VDDQ_A current(4)=0.00000000A
   1V1_SYS_A current(5)=0.23227130A
    0V8_SW_A current(6)=0.32303280A
  VDD_CORE_A current(7)=1.79493000A
   3V3_DAC_A current(17)=0.00000000A
   3V3_ADC_A current(18)=0.00000000A
   0V8_AON_A current(16)=0.00201465A
      HDMI_A current(22)=0.01709400A
 3V7_WL_SW_V volt(8)=3.72112000V
   3V3_SYS_V volt(9)=3.31003300V
   1V8_SYS_V volt(10)=1.80268400V
  DDR_VDD2_V volt(11)=1.10292900V
  DDR_VDDQ_V volt(12)=0.60292980V
   1V1_SYS_V volt(13)=1.10146400V
    0V8_SW_V volt(14)=0.79890030V
  VDD_CORE_V volt(15)=0.86656820V
   3V3_DAC_V volt(20)=3.31776200V
   3V3_ADC_V volt(21)=3.32234100V
   0V8_AON_V volt(19)=0.79941320V
      HDMI_V volt(23)=4.98212000V
     EXT5V_V volt(24)=4.99418000V
      BATT_V volt(25)=0.00000000V
"""

SAMPLE_SECTIONS = {
    "pmic": SAMPLE_PMIC_OUTPUT,
    "throttled": "throttled=0x0",
    "temp": "temp=57.1'C",
    "arm_freq": "frequency(0)=2400023808",
    "chosen_power": (
        "max_current=5000\n"
        "power_reset=0\n"
        "usb_max_current_enable=1\n"
        "usb_over_current_detected=0\n"
    ),
    "usb_devices": (
        "1-1|32e6:9005|480|100mA|uvcvideo|icSpring|icspring camera\n"
        "3-1|1a86:8091|480|100mA|hub||USB HUB\n"
        "3-1.1|1a86:7523|12|102mA|ch341||USB Serial\n"
        "3-1.2|0c76:161f|12|100mA|snd-usb-audio||USB PnP Audio Device\n"
        "3-2|2563:0575|12|350mA|usbhid||USB WirelessGamepad\n"
    ),
    "dmesg_usb": (
        "[  374.91] usb 3-1: USB disconnect, device number 12\n"
        "[  390.48] usb 3-1: USB disconnect, device number 15\n"
        "[  397.05] usb 3-1: USB disconnect, device number 18\n"
    ),
    "model": "Raspberry Pi 5 Model B Rev 1.1",
    "cpu": "Architecture: aarch64\nModel name: Cortex-A76\n",
    "mem": "               total        used        free      shared  buff/cache   available\nMem:            8064        1240        5500           6        1324        6824\n",
    "disk": "Filesystem     1G-blocks  Used Available Use% Mounted on\n/dev/mmcblk0p2       57G   47G        9G  86% /\n",
    "uptime": " 01:31:53 up  1:07,  1 user,  load average: 1.27, 1.44, 1.50",
    "pcie": "00:00.0 PCI bridge: Broadcom BCM2712 PCIe Bridge\n01:00.0 Ethernet controller: Raspberry Pi RP1 South Bridge",
    "serial": "/dev/rrc -> ttyAMA0\n/dev/ttyAMA0\n/dev/ttyUSB1\n/dev/wonderecho -> ttyUSB1\n",
    "i2c": "/dev/i2c-1\n/dev/i2c-13\n/dev/i2c-14",
    "spi": "/dev/spidev10.0",
    "video": "icspring camera (usb-xhci-hcd.0-1):\n\t/dev/video0\n\t/dev/video1",
    "audio": (
        "card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0\n"
        "card 1: vc4hdmi1 [vc4-hdmi-1], device 0: MAI PCM i2s-hifi-0\n"
        "card 2: Device [USB PnP Audio Device], device 0: USB Audio\n"
    ),
    "pinctrl": "14: a4 pd | hi // GPIO14 = TXD0\n15: a4 pu | hi // GPIO15 = RXD0",
    "network": "lo UNKNOWN 127.0.0.1/8\neth0 DOWN\nwlan0 UP 192.168.1.119/24",
    "docker": "puppypi\tUp 3 hours\npuppypi_ros2\tExited (137) 1 hour ago",
}


def _make_test_client() -> tuple[TestClient, str]:
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    repo = InMemoryTwinRepository()
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(settings=settings, repository=repo, robot_store=robot_store, robot_ai_store=ai_store)
    robot = robot_store.upsert_robot(
        {
            "ip_address": "192.168.1.119",
            "name": "PuppyPi Pro",
            "model": "Raspberry Pi 5 Model B Rev 1.1",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "battery_mv": 8469,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_parse_pmic_adc_output_real_pi5_rails() -> None:
    """Verify DA9091 PMIC ADC parsing computes EXT5V_V, per-rail Watts, and total board Watts."""
    rails, ext5v_v, total_w = parse_pmic_adc_output(SAMPLE_PMIC_OUTPUT)
    assert ext5v_v is not None and abs(ext5v_v - 4.9942) < 1e-3
    assert total_w is not None and 3.0 < total_w < 3.6
    by_name = {r["name"]: r for r in rails}
    assert "VDD_CORE" in by_name
    assert abs(by_name["VDD_CORE"]["volts"] - 0.8666) < 1e-3
    assert abs(by_name["VDD_CORE"]["amps"] - 1.7949) < 1e-3
    assert abs(by_name["VDD_CORE"]["watts"] - (0.8666 * 1.7949)) < 0.01
    assert by_name["EXT5V"]["amps"] is None
    assert by_name["EXT5V"]["watts"] is None


def test_decode_throttled_mask() -> None:
    """Verify Raspberry Pi throttled bitmask decoding for healthy 0x0 and fault 0x50005."""
    assert decode_throttled_mask("throttled=0x0") == []
    flags = decode_throttled_mask("throttled=0x50005")
    assert flags == [
        "under_voltage_now",
        "throttled_now",
        "under_voltage_occurred",
        "throttled_occurred",
    ]


def test_build_pi5_diagnostics_payload_22_components_and_faults() -> None:
    """Verify full payload schema, 22 canonical components, 752/1600 mA USB, flap warning, and LD19 fault."""
    robot = {
        "id": "bot-pi5-1",
        "name": "PuppyPi Pro",
        "ip_address": "192.168.1.119",
        "battery_mv": 8469,
    }
    payload = build_pi5_diagnostics_payload(robot, SAMPLE_SECTIONS)

    assert payload["robot_id"] == "bot-pi5-1"
    assert payload["board_model"] == "Raspberry Pi 5 Model B Rev 1.1"
    assert payload["cpu_temp_c"] == 57.1
    assert payload["arm_freq_mhz"] == 2400.0
    assert payload["load_avg"] == [1.27, 1.44, 1.5]
    assert payload["usb_max_current_enable"] is True
    assert payload["usb_budget_ma"] == 1600
    assert payload["usb_total_draw_ma"] == 752
    assert payload["usb_over_current"] is False
    assert payload["disk_used_pct"] == 86.0
    assert payload["ld19_verdict"]["detected"] is False
    assert len(payload["ld19_verdict"]["likely_causes"]) >= 2

    # All 22 canonical 3D BOM component IDs present in exact contract order
    comp_ids = tuple(c["component_id"] for c in payload["components"])
    assert len(comp_ids) == 22
    assert comp_ids == CANONICAL_PI5_COMPONENT_IDS

    comp_map = {c["component_id"]: c for c in payload["components"]}
    assert comp_map["usb3_port_3_1"]["status"] == "warning"
    assert comp_map["usb3_port_3_1"]["metrics"]["flap_count"] == 3
    assert comp_map["wonderecho_pro"]["status"] == "warning"
    assert comp_map["ld19_lidar_module"]["status"] == "fault"
    assert comp_map["microsd_slot"]["status"] == "warning"
    assert comp_map["usb2_port_1_2"]["status"] == "empty"
    assert comp_map["da9091_pmic"]["status"] == "ok"


def test_hardware_diagnostics_api_endpoint() -> None:
    """Verify GET /api/robots/{robot_id}/hardware-diagnostics returns live schema and 404 on unknown ID."""
    client, robot_id = _make_test_client()
    expected = build_pi5_diagnostics_payload(
        {"id": robot_id, "name": "PuppyPi Pro", "ip_address": "192.168.1.119", "battery_mv": 8469},
        SAMPLE_SECTIONS,
    )

    with patch(
        "src.api.routes_robots.collect_pi5_hardware_diagnostics",
        new=AsyncMock(return_value=expected),
    ) as mock_collect:
        resp = client.get(f"/api/robots/{robot_id}/hardware-diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["robot_id"] == robot_id
        assert data["usb_total_draw_ma"] == 752
        assert data["usb_budget_ma"] == 1600
        assert len(data["components"]) == 22
        assert mock_collect.await_count == 1

    resp_404 = client.get("/api/robots/nonexistent-id/hardware-diagnostics")
    assert resp_404.status_code == 404
