"""Universal Multi-Board Hardware Pinout Schematics, Hiwonder Component Library & Code Generator.

Supports prototyping with shared, reusable components across:
- **BBC micro:bit v2.2** (25-pin gold edge connector, MicroPython)
- **Raspberry Pi 5 16GB** (40-pin GPIO header, Python 3 ``gpiozero`` / ``smbus2``)
- **PuppyPi Pro** (Hiwonder expansion board PH2.0 ports + LD19 LiDAR + WonderEcho AI Box, ROS 2)
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

MICROBIT_V2_PINS: List[Dict[str, Any]] = [
    {"id": "P0", "label": "P0 (Ring 0)", "pad_type": "ring", "x_mm": -17.5, "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Audio Out", "Touch"], "voltage": "3.3V", "max_ma": 5, "notes": "Primary ring pad for servos, external speaker, NeoPixels, or Hiwonder Touch."},
    {"id": "P1", "label": "P1 (Ring 1)", "pad_type": "ring", "x_mm": -8.75, "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Touch"], "voltage": "3.3V", "max_ma": 5, "notes": "General-purpose ring pad (ADC & PWM). Ideal for TM1640 CLK or NeoPixels."},
    {"id": "P2", "label": "P2 (Ring 2)", "pad_type": "ring", "x_mm": 0.0, "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Touch"], "voltage": "3.3V", "max_ma": 5, "notes": "General-purpose ring pad (ADC & PWM). Ideal for TM1640 DIO, Touch, or PIR."},
    {"id": "3V", "label": "3V Power Rail", "pad_type": "ring", "x_mm": 8.75, "capabilities": ["3.3V Regulated Power Out (190mA max)"], "voltage": "3.3V", "max_ma": 190, "notes": "Powers 3.3V sensors (AHT10, TTP223 Touch, TM1640 8x16 Matrix). Do NOT power 5V-only modules here."},
    {"id": "GND", "label": "GND (Ground)", "pad_type": "ring", "x_mm": 17.5, "capabilities": ["Common Ground (0V)"], "voltage": "0V", "max_ma": 500, "notes": "Always tie accessory GND (and any external 5V supply GND) here."},
    {"id": "P8", "label": "P8 (Edge)", "pad_type": "edge", "x_mm": -13.0, "capabilities": ["Digital I/O", "PWM"], "voltage": "3.3V", "max_ma": 5, "notes": "Dedicated digital GPIO on edge breakout."},
    {"id": "P12", "label": "P12 (Edge)", "pad_type": "edge", "x_mm": -4.2, "capabilities": ["Digital I/O", "PWM"], "voltage": "3.3V", "max_ma": 5, "notes": "Dedicated digital GPIO on edge breakout."},
    {"id": "P13", "label": "P13 (SPI SCK)", "pad_type": "edge", "x_mm": 4.2, "capabilities": ["Digital I/O", "SPI SCK"], "voltage": "3.3V", "max_ma": 5, "notes": "Hardware SPI Clock pin."},
    {"id": "P19", "label": "P19 (I2C SCL)", "pad_type": "edge", "x_mm": 12.8, "capabilities": ["I2C Clock (SCL)"], "voltage": "3.3V", "max_ma": 5, "notes": "Hardware I2C Clock (AHT10 0x38, Glowing Ultrasonic 0x77 via level shifter, SSD1306 OLED 0x3C)."},
    {"id": "P20", "label": "P20 (I2C SDA)", "pad_type": "edge", "x_mm": 14.8, "capabilities": ["I2C Data (SDA)"], "voltage": "3.3V", "max_ma": 5, "notes": "Hardware I2C Data (pair with P19 SCL)."},
]

RPI5_GPIO_PINS: List[Dict[str, Any]] = [
    {"id": "3V3", "label": "Pin 1 (3.3V)", "pad_type": "power", "x_mm": -18.0, "capabilities": ["3.3V Power Rail"], "voltage": "3.3V", "max_ma": 500, "notes": "3.3V regulated power for AHT10, TTP223 Touch, OLED, and TM1640."},
    {"id": "5V", "label": "Pin 2 (5V)", "pad_type": "power", "x_mm": -14.0, "capabilities": ["5.0V Power Rail"], "voltage": "5.0V", "max_ma": 1000, "notes": "5V rail for Hiwonder Glowing Ultrasonic v5.6, servos, and NeoPixels."},
    {"id": "GPIO2", "label": "GPIO 2 (I2C1 SDA)", "pad_type": "i2c", "x_mm": -10.0, "capabilities": ["I2C1 SDA", "Digital I/O"], "voltage": "3.3V", "max_ma": 16, "notes": "Hardware I2C1 Data (Pin 3). Connects AHT10 (0x38), Glowing Ultrasonic (0x77), OLED (0x3C)."},
    {"id": "GPIO3", "label": "GPIO 3 (I2C1 SCL)", "pad_type": "i2c", "x_mm": -6.0, "capabilities": ["I2C1 SCL", "Digital I/O"], "voltage": "3.3V", "max_ma": 16, "notes": "Hardware I2C1 Clock (Pin 5). Pair with GPIO2."},
    {"id": "GPIO17", "label": "GPIO 17 (Pin 11)", "pad_type": "gpio", "x_mm": -2.0, "capabilities": ["Digital I/O", "Touch / PIR"], "voltage": "3.3V", "max_ma": 16, "notes": "Clean general-purpose digital GPIO for Hiwonder Touch Sensor or PIR."},
    {"id": "GPIO18", "label": "GPIO 18 (PWM0)", "pad_type": "pwm", "x_mm": 2.0, "capabilities": ["Hardware PWM", "NeoPixel", "Servo"], "voltage": "3.3V", "max_ma": 16, "notes": "Hardware PWM0 (Pin 12) for SG90 servos or WS2812B NeoPixels."},
    {"id": "GPIO23", "label": "GPIO 23 (Pin 16)", "pad_type": "gpio", "x_mm": 6.0, "capabilities": ["Digital I/O", "TM1640 CLK"], "voltage": "3.3V", "max_ma": 16, "notes": "Ideal for Hiwonder 8x16 LED Matrix CLK."},
    {"id": "GPIO24", "label": "GPIO 24 (Pin 18)", "pad_type": "gpio", "x_mm": 10.0, "capabilities": ["Digital I/O", "TM1640 DIO"], "voltage": "3.3V", "max_ma": 16, "notes": "Ideal for Hiwonder 8x16 LED Matrix DIO."},
    {"id": "USB0", "label": "USB 3.0 Port", "pad_type": "usb", "x_mm": 14.0, "capabilities": ["USB Serial / UVC / LiDAR"], "voltage": "5.0V", "max_ma": 900, "notes": "Connects LD19 LiDAR, 4K Webcam, micro:bit, or WonderEcho AI Box."},
    {"id": "GND", "label": "Pin 6 (GND)", "pad_type": "ground", "x_mm": 18.0, "capabilities": ["Common Ground (0V)"], "voltage": "0V", "max_ma": 1500, "notes": "Common ground reference for all attached modules."},
]

PUPPYPI_PRO_PINS: List[Dict[str, Any]] = [
    {"id": "I2C_1", "label": "PH2.0 I2C-1 (5V)", "pad_type": "i2c", "x_mm": -16.0, "capabilities": ["I2C (0x38, 0x77, 0x3C)", "5V Power"], "voltage": "5.0V", "max_ma": 500, "notes": "Hiwonder 4-pin PH2.0 I2C port — plug Glowing Ultrasonic v5.6 or Temp/Humidity v1.1 directly in!"},
    {"id": "I2C_2", "label": "PH2.0 I2C-2 (5V)", "pad_type": "i2c", "x_mm": -9.5, "capabilities": ["I2C Bus", "5V Power"], "voltage": "5.0V", "max_ma": 500, "notes": "Second PH2.0 I2C port for daisy-chaining Temp/Humidity v1.1 + Glowing Ultrasonic v5.6."},
    {"id": "IO_1", "label": "PH2.0 IO-1 (GPIO22/23)", "pad_type": "gpio", "x_mm": -3.0, "capabilities": ["Digital I/O", "TM1640 CLK/DIO"], "voltage": "3.3V", "max_ma": 200, "notes": "Plug Hiwonder 8x16 LED Matrix (TM1640) directly into this 4-pin PH2.0 port!"},
    {"id": "IO_2", "label": "PH2.0 IO-2 (GPIO24)", "pad_type": "gpio", "x_mm": 3.5, "capabilities": ["Digital I/O", "Touch / PIR"], "voltage": "3.3V", "max_ma": 200, "notes": "Plug Hiwonder Touch Sensor (TTP223) directly into this PH2.0 port!"},
    {"id": "USB_LIDAR", "label": "USB-A (LD19 LiDAR)", "pad_type": "usb", "x_mm": 10.0, "capabilities": ["CH340 230400 baud /dev/ldlidar"], "voltage": "5.0V", "max_ma": 500, "notes": "Dedicated USB port for LD19 360° ToF LiDAR converter board."},
    {"id": "USB_AI", "label": "USB-A (WonderEcho AI)", "pad_type": "usb", "x_mm": 16.0, "capabilities": ["Offline Wake-Word + TTS Audio"], "voltage": "5.0V", "max_ma": 500, "notes": "WonderEcho Pro AI Voice Box for wake-word detection and spoken audio."},
    {"id": "5V", "label": "5V Expansion Rail", "pad_type": "power", "x_mm": 12.5, "capabilities": ["5V Regulated Power"], "voltage": "5.0V", "max_ma": 1500, "notes": "Expansion board 5V rail."},
    {"id": "3V", "label": "3.3V Expansion Rail", "pad_type": "power", "x_mm": 6.5, "capabilities": ["3.3V Regulated Power"], "voltage": "3.3V", "max_ma": 500, "notes": "Expansion board 3.3V rail."},
    {"id": "GND", "label": "GND (Common)", "pad_type": "ground", "x_mm": 18.0, "capabilities": ["Common Ground (0V)"], "voltage": "0V", "max_ma": 2000, "notes": "Common ground."},
]

BOARD_PROFILES: Dict[str, Dict[str, Any]] = {
    "microbit_v2": {
        "id": "microbit_v2",
        "name": "BBC micro:bit v2.2",
        "mcu": "Nordic nRF52833 (ARM Cortex-M4F @ 64MHz, 3.3V logic)",
        "logic_v": 3.3,
        "has_5v_rail": False,
        "language": "MicroPython",
        "pins": MICROBIT_V2_PINS,
        "sensors": ["5x5 LED Matrix", "Accelerometer & Compass", "MEMS Mic", "Piezo Speaker", "Touch Logo", "Temp"],
        "wireless": ["2.4 GHz Radio", "Bluetooth 5.1 LE"],
    },
    "rpi5_16gb": {
        "id": "rpi5_16gb",
        "name": "Raspberry Pi 5 (16 GB)",
        "mcu": "Broadcom BCM2712 Quad-Core Cortex-A76 @ 2.4GHz + RP1 I/O (3.3V GPIO, 5V Rail)",
        "logic_v": 3.3,
        "has_5v_rail": True,
        "language": "Python 3 (gpiozero / smbus2)",
        "pins": RPI5_GPIO_PINS,
        "sensors": ["40-Pin GPIO", "I2C1/SPI/PWM", "Dual USB 3.0", "PCIe", "CSI Camera"],
        "wireless": ["Dual-Band Wi-Fi", "Bluetooth 5.0", "Gigabit Ethernet"],
    },
    "puppypi_pro": {
        "id": "puppypi_pro",
        "name": "PuppyPi Pro + LD19 LiDAR + WonderEcho",
        "mcu": "Raspberry Pi + Hiwonder STM32 Quadruped Controller (PH2.0 Sensor Bus + ROS 2 Humble)",
        "logic_v": 3.3,
        "has_5v_rail": True,
        "language": "ROS 2 Humble Python",
        "pins": PUPPYPI_PRO_PINS,
        "sensors": ["8x Bus Servos", "IMU", "HD Camera", "LD19 360° LiDAR", "WonderEcho AI Box", "PH2.0 Sensor Ports"],
        "wireless": ["Wi-Fi", "ROS 2 Bridge (:9090)"],
    },
}

PIN_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in MICROBIT_V2_PINS}

MICROBIT_ACCESSORIES: List[Dict[str, Any]] = [
    # --- 4 RESEARCHED HIWONDER PUPPYPI KIT MODULES ---
    {
        "id": "hiwonder_temp_hum_v11",
        "name": "Hiwonder Temp & Humidity v1.1",
        "vendor": "Hiwonder",
        "category": "hiwonder_kit",
        "color_hex": "#0ea5e9",
        "ic": "AHT10 (I2C 0x38) / DHT11",
        "protocol": "I2C (0x38)",
        "i2c_address": "0x38",
        "voltage_min_v": 2.2,
        "voltage_max_v": 5.5,
        "requires_5v": False,
        "allowed_signal_pins": ["P19", "GPIO2", "I2C_1", "I2C_2"],
        "default_pin": "P19",
        "secondary_pin": "P20",
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P19", "secondary_pin": "P20"},
            "rpi5_16gb": {"pin": "GPIO3", "secondary_pin": "GPIO2"},
            "puppypi_pro": {"pin": "I2C_1", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "3.3V native (2.2V–5.5V)! Connects straight to I2C on micro:bit v2.2 (P19/P20), Pi 5 (GPIO2/3), or PuppyPi PH2.0.",
        "how_it_works": "Measures ambient temperature (-40°C to +85°C, ±0.3°C) and relative humidity (0–100% RH, ±2%) over I2C address 0x38 via its 4-pin PH2.0 socket.",
        "wires": [
            {"from": "SCL (Blue)", "to_role": "signal", "color": "#38bdf8"},
            {"from": "SDA (Yellow)", "to_role": "secondary", "color": "#facc15"},
            {"from": "VCC (Red)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND (Black)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "AHT10 I2C (0x38) Temp ±0.3°C & Humidity ±2% RH — 3.3V/5V native.",
    },
    {
        "id": "hiwonder_touch_sensor",
        "name": "Hiwonder Touch Sensor Board",
        "vendor": "Hiwonder",
        "category": "hiwonder_kit",
        "color_hex": "#f59e0b",
        "ic": "TTP223 Capacitive Touch",
        "protocol": "Digital GPIO",
        "i2c_address": None,
        "voltage_min_v": 2.0,
        "voltage_max_v": 5.5,
        "requires_5v": False,
        "allowed_signal_pins": ["P0", "P1", "P2", "P8", "P12", "GPIO17", "GPIO23", "GPIO24", "IO_2", "IO_1"],
        "default_pin": "P2",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P2", "secondary_pin": None},
            "rpi5_16gb": {"pin": "GPIO17", "secondary_pin": None},
            "puppypi_pro": {"pin": "IO_2", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "3.3V native (2.0V–5.5V). Outputs HIGH when finger touches the gold capacitive pad (works even through thin plastic!).",
        "how_it_works": "Uses the TTP223 capacitive touch IC on a 50×20mm Lego-hole PCB. Supports Momentary (default) or Toggle latch mode via onboard A/B solder jumpers.",
        "wires": [
            {"from": "OUT (White)", "to_role": "signal", "color": "#f59e0b"},
            {"from": "VCC (Red)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND (Black)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "TTP223 capacitive touch pad (2.0–5.5V) — click in 3D to trigger!",
    },
    {
        "id": "hiwonder_ultrasonic_v56",
        "name": "Hiwonder Glowing Ultrasonic v5.6",
        "vendor": "Hiwonder",
        "category": "hiwonder_kit",
        "color_hex": "#10b981",
        "ic": "I2C Ultrasonic (0x77) + RGB LEDs",
        "protocol": "I2C (0x77)",
        "i2c_address": "0x77",
        "voltage_min_v": 5.0,
        "voltage_max_v": 5.0,
        "requires_5v": True,
        "allowed_signal_pins": ["P19", "GPIO3", "I2C_1", "I2C_2"],
        "default_pin": "P19",
        "secondary_pin": "P20",
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P19", "secondary_pin": "P20"},
            "rpi5_16gb": {"pin": "GPIO3", "secondary_pin": "GPIO2"},
            "puppypi_pro": {"pin": "I2C_1", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "5V DC required! Direct plug-in on PuppyPi & Pi 5 (5V rail). On micro:bit v2.2, use external 5V + shared GND + 3.3V↔5V I2C level shifter.",
        "how_it_works": "40kHz ultrasonic ranger (2–400 cm, 15° beam) communicating over I2C address 0x77, with independently programmable RGB LED rings inside both transducers!",
        "wires": [
            {"from": "SCL (Blue)", "to_role": "signal", "color": "#10b981"},
            {"from": "SDA (Yellow)", "to_role": "secondary", "color": "#38bdf8"},
            {"from": "5V VCC (Red)", "to_role": "5V", "color": "#ef4444"},
            {"from": "GND (Black)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "I2C (0x77) 2–400cm ultrasonic with glowing programmable RGB rings!",
    },
    {
        "id": "hiwonder_led_matrix_8x16",
        "name": "Hiwonder 8×16 LED Matrix (64×2)",
        "vendor": "Hiwonder",
        "category": "hiwonder_kit",
        "color_hex": "#ef4444",
        "ic": "TM1640 (128 LEDs)",
        "protocol": "2-Wire Serial (CLK/DIO)",
        "i2c_address": None,
        "voltage_min_v": 3.3,
        "voltage_max_v": 5.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P1", "P0", "P8", "GPIO23", "IO_1"],
        "default_pin": "P1",
        "secondary_pin": "P2",
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P1", "secondary_pin": "P2"},
            "rpi5_16gb": {"pin": "GPIO23", "secondary_pin": "GPIO24"},
            "puppypi_pro": {"pin": "IO_1", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "3.3V–5.0V native! Works directly on micro:bit v2.2 (P1 CLK, P2 DIO), Pi 5 (GPIO23/24), or PuppyPi PH2.0 IO-1.",
        "how_it_works": "Dual 8×8 (128-LED) dot matrix driven by the TM1640 IC over a 2-wire CLK/DIO protocol with 8 hardware brightness levels for faces, numbers, and scrolling text.",
        "wires": [
            {"from": "CLK (Yellow)", "to_role": "signal", "color": "#facc15"},
            {"from": "DIO (White)", "to_role": "secondary", "color": "#22d3ee"},
            {"from": "VCC (Red)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND (Black)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "TM1640 8×16 (128 LEDs) dual dot-matrix display — 3.3V/5V native.",
    },
    # --- ROBOTICS & CORE PROTOTYPING LIBRARY ---
    {
        "id": "ld19_lidar",
        "name": "LD19 360° ToF LiDAR + CH340",
        "vendor": "LDRobot / Hiwonder",
        "category": "robotics",
        "color_hex": "#06b6d4",
        "ic": "LD19 + CH340 USB UART",
        "protocol": "USB Serial (230400 baud)",
        "i2c_address": None,
        "voltage_min_v": 5.0,
        "voltage_max_v": 5.0,
        "requires_5v": True,
        "allowed_signal_pins": ["USB_LIDAR", "USB0"],
        "default_pin": "USB_LIDAR",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P0", "secondary_pin": None},
            "rpi5_16gb": {"pin": "USB0", "secondary_pin": None},
            "puppypi_pro": {"pin": "USB_LIDAR", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "Plugs via CH340 USB converter into Raspberry Pi 5 or PuppyPi USB port (230,400 baud, 10Hz, 4500 pts/sec).",
        "how_it_works": "360° Time-of-Flight 2D laser scanner (0.02–12 m range) feeding ROS 2 /scan and SLAM Mapping.",
        "wires": [{"from": "USB-A (CH340)", "to_role": "signal", "color": "#06b6d4"}],
        "summary": "360° 10Hz laser scanner for SLAM Mapping & 3D Digital Twins.",
    },
    {
        "id": "wonderecho_ai_box",
        "name": "WonderEcho Pro AI Voice Box",
        "vendor": "Hiwonder",
        "category": "robotics",
        "color_hex": "#8b5cf6",
        "ic": "Offline Wake-Word + Speaker",
        "protocol": "USB / I2C Audio",
        "i2c_address": None,
        "voltage_min_v": 5.0,
        "voltage_max_v": 5.0,
        "requires_5v": True,
        "allowed_signal_pins": ["USB_AI", "USB0", "I2C_2"],
        "default_pin": "USB_AI",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P19", "secondary_pin": "P20"},
            "rpi5_16gb": {"pin": "USB0", "secondary_pin": None},
            "puppypi_pro": {"pin": "USB_AI", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "5V USB voice assistant module with loud speaker & offline wake-word recognition.",
        "how_it_works": "Handles far-field wake words and clear spoken TTS replies for PuppyPi Pro and Pi 5 projects.",
        "wires": [{"from": "USB-A Audio/Serial", "to_role": "signal", "color": "#8b5cf6"}],
        "summary": "AI Voice & loud speaker box for PuppyPi Pro & Raspberry Pi 5.",
    },
    {
        "id": "sg90_servo",
        "name": "SG90 Micro Servo (180°)",
        "vendor": "Generic",
        "category": "actuator",
        "color_hex": "#3b82f6",
        "ic": "50Hz PWM Servo",
        "protocol": "PWM (50Hz)",
        "i2c_address": None,
        "voltage_min_v": 3.3,
        "voltage_max_v": 6.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P0", "P1", "P2", "P8", "P12", "GPIO18", "IO_1"],
        "default_pin": "P0",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P0", "secondary_pin": None},
            "rpi5_16gb": {"pin": "GPIO18", "secondary_pin": None},
            "puppypi_pro": {"pin": "IO_1", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "Connect Red to 3V (1 micro servo) or external 5V battery pack with shared GND.",
        "how_it_works": "180° positional micro servo controlled by 1–2 ms pulse width at 50 Hz.",
        "wires": [
            {"from": "Signal (Orange)", "to_role": "signal", "color": "#f97316"},
            {"from": "VCC (Red)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND (Brown)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "180° positional micro servo controlled via 50Hz PWM.",
    },
    {
        "id": "neopixel_8",
        "name": "NeoPixel RGB LED Strip (8 LEDs)",
        "vendor": "Generic",
        "category": "display",
        "color_hex": "#a855f7",
        "ic": "WS2812B",
        "protocol": "1-Wire NZR",
        "i2c_address": None,
        "voltage_min_v": 3.3,
        "voltage_max_v": 5.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P0", "P1", "P2", "P8", "GPIO18"],
        "default_pin": "P1",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P1", "secondary_pin": None},
            "rpi5_16gb": {"pin": "GPIO18", "secondary_pin": None},
            "puppypi_pro": {"pin": "IO_2", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "Keep brightness <= 40% when powered from micro:bit 3V rail.",
        "how_it_works": "8 individually addressable WS2812B RGB LEDs controlled over a single data pin.",
        "wires": [
            {"from": "DIN (Data In)", "to_role": "signal", "color": "#22d3ee"},
            {"from": "VCC (+3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Addressable WS2812B RGB LED strip driven natively in 3D & code.",
    },
    {
        "id": "external_speaker",
        "name": "External Amplified Speaker / Piezo",
        "vendor": "Generic",
        "category": "audio",
        "color_hex": "#ec4899",
        "ic": "Amplified Audio Out",
        "protocol": "Analog / PWM Audio",
        "i2c_address": None,
        "voltage_min_v": 3.3,
        "voltage_max_v": 5.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P0", "GPIO18"],
        "default_pin": "P0",
        "secondary_pin": None,
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P0", "secondary_pin": None},
            "rpi5_16gb": {"pin": "GPIO18", "secondary_pin": None},
            "puppypi_pro": {"pin": "USB_AI", "secondary_pin": None},
        },
        "needs_power": False,
        "power_note": "Clip + to P0 and - to GND for loud melodies and speech.",
        "how_it_works": "External speaker or buzzer driven from P0 + GND, solving the quiet onboard micro:bit piezo.",
        "wires": [
            {"from": "Audio +", "to_role": "signal", "color": "#ec4899"},
            {"from": "Audio - (GND)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "External speaker on P0 + GND for crisp, loud melodies and speech.",
    },
    {
        "id": "oled_ssd1306",
        "name": "SSD1306 128×64 I2C OLED Display",
        "vendor": "Generic",
        "category": "display",
        "color_hex": "#06b6d4",
        "ic": "SSD1306 (0x3C)",
        "protocol": "I2C (0x3C)",
        "i2c_address": "0x3C",
        "voltage_min_v": 3.3,
        "voltage_max_v": 5.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P19", "GPIO3", "I2C_1", "I2C_2"],
        "default_pin": "P19",
        "secondary_pin": "P20",
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P19", "secondary_pin": "P20"},
            "rpi5_16gb": {"pin": "GPIO3", "secondary_pin": "GPIO2"},
            "puppypi_pro": {"pin": "I2C_2", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "3.3V native I2C display at address 0x3C.",
        "how_it_works": "Monochrome 128×64 OLED screen for live sensor dashboards over I2C.",
        "wires": [
            {"from": "SCL", "to_role": "signal", "color": "#facc15"},
            {"from": "SDA", "to_role": "secondary", "color": "#22d3ee"},
            {"from": "VCC (3.3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Crisp monochrome I2C OLED display (0x3C) for live sensor readouts.",
    },
    {
        "id": "i2c_level_shifter",
        "name": "3.3V ↔ 5V I2C Logic Level Shifter",
        "vendor": "Prototyping Passive",
        "category": "helper",
        "color_hex": "#64748b",
        "ic": "BSS138 4-Ch Bidirectional",
        "protocol": "Logic Translation",
        "i2c_address": None,
        "voltage_min_v": 3.3,
        "voltage_max_v": 5.0,
        "requires_5v": False,
        "allowed_signal_pins": ["P19", "GPIO3"],
        "default_pin": "P19",
        "secondary_pin": "P20",
        "default_pins_by_board": {
            "microbit_v2": {"pin": "P19", "secondary_pin": "P20"},
            "rpi5_16gb": {"pin": "GPIO3", "secondary_pin": "GPIO2"},
            "puppypi_pro": {"pin": "I2C_1", "secondary_pin": None},
        },
        "needs_power": True,
        "power_note": "Protects 3.3V boards (micro:bit / Pi 5) when connecting 5V I2C modules like Glowing Ultrasonic v5.6.",
        "how_it_works": "Safely translates 3.3V LV SDA/SCL lines to 5V HV SDA/SCL lines bidirectionally.",
        "wires": [
            {"from": "LV1 (SCL)", "to_role": "signal", "color": "#94a3b8"},
            {"from": "LV2 (SDA)", "to_role": "secondary", "color": "#cbd5e1"},
            {"from": "LV (3.3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Protects 3.3V boards when driving 5V I2C sensors (like Ultrasonic v5.6).",
    },
]

ACCESSORY_BY_ID: Dict[str, Dict[str, Any]] = {a["id"]: a for a in MICROBIT_ACCESSORIES}

STARTER_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "interactive_reactions",
        "name": "Interactive Lift, Shake & Button Demo",
        "code": (
            "from microbit import *\n"
            "import audio\n"
            "import math\n\n"
            "speaker.on()\n"
            "set_volume(255)\n"
            "display.show(Image.HAPPY)\n"
            "audio.play(Sound.HAPPY, wait=True)\n\n"
            "last_z = accelerometer.get_z()\n"
            "last_ms = running_time()\n\n"
            "while True:\n"
            "    now = running_time()\n"
            "    x, y, z = accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_z()\n"
            "    mag = math.sqrt(x*x + y*y + z*z)\n"
            "    dz = z - last_z\n"
            "    last_z = last_z * 0.8 + z * 0.2\n"
            "    if (now - last_ms > 1200) and (abs(dz) > 380 or mag > 1500 or mag < 520):\n"
            "        display.show(Image.SURPRISED)\n"
            "        audio.play(Sound.SLIDE, wait=True)\n"
            "        display.show(Image.HAPPY)\n"
            "        last_ms = running_time()\n"
            "    elif button_a.was_pressed():\n"
            "        display.show(Image.HEART)\n"
            "        audio.play(Sound.GIGGLE, wait=True)\n"
            "        display.show(Image.HAPPY)\n"
            "    sleep(35)\n"
        ),
    },
]


def validate_project_wiring(
    attachments: Sequence[Dict[str, Any]],
    board_id: str = "microbit_v2",
) -> Dict[str, Any]:
    """Validate pin conflicts, I2C addresses, and 5V/3.3V safety across any supported board.

    Args:
        attachments: Sequence of attachment dicts with ``accessory_id`` and ``pin``.
        board_id: Target board profile (``microbit_v2``, ``rpi5_16gb``, ``puppypi_pro``).

    Returns:
        Dictionary with ``ok``, ``conflicts``, ``warnings``, ``used_pins``,
        and ordered ``wiring_steps``.
    """
    board = BOARD_PROFILES.get(board_id, BOARD_PROFILES["microbit_v2"])
    shared_bus_pins = {"3V", "3V3", "5V", "GND", "P19", "P20", "GPIO2", "GPIO3", "I2C_1", "I2C_2"}
    pin_owners: Dict[str, List[str]] = {}
    conflicts: List[str] = []
    warnings: List[str] = []
    wiring_steps: List[Dict[str, str]] = []
    has_level_shifter = any(a.get("accessory_id") == "i2c_level_shifter" for a in attachments)

    step_num = 1
    for att in attachments:
        acc_id = str(att.get("accessory_id") or "")
        spec = ACCESSORY_BY_ID.get(acc_id)
        if not spec:
            continue
        label = str(att.get("label") or spec["name"])
        board_defaults = (spec.get("default_pins_by_board") or {}).get(board_id) or {}
        sig_pin = str(att.get("pin") or board_defaults.get("pin") or spec["default_pin"]).upper()
        sec_pin = att.get("secondary_pin") or board_defaults.get("secondary_pin") or spec.get("secondary_pin")
        if sec_pin:
            sec_pin = str(sec_pin).upper()

        if sig_pin not in shared_bus_pins:
            pin_owners.setdefault(sig_pin, []).append(label)
        if sec_pin and sec_pin not in shared_bus_pins:
            pin_owners.setdefault(sec_pin, []).append(label)

        # Voltage & 5V safety checks!
        if spec.get("requires_5v") and not board.get("has_5v_rail"):
            if acc_id == "hiwonder_ultrasonic_v56" and not has_level_shifter:
                warnings.append(
                    f"5V Safety ({label}): micro:bit v2.2 only has a 3.3V rail. Power this module from an external 5V supply (share GND) and add a 3.3V↔5V I2C Level Shifter to protect P19/P20."
                )
            elif acc_id in {"ld19_lidar", "wonderecho_ai_box"}:
                warnings.append(
                    f"USB Host Required ({label}): Plug this USB device into Raspberry Pi 5 or PuppyPi Pro (micro:bit does not have a USB Host port)."
                )

        for wire in spec.get("wires", []):
            role = wire["to_role"]
            target_pin = sig_pin if role == "signal" else (sec_pin if role == "secondary" else role)
            if target_pin == "3V" and board_id == "rpi5_16gb":
                target_pin = "3V3"
            if not target_pin:
                continue
            wiring_steps.append(
                {
                    "step": str(step_num),
                    "accessory": label,
                    "from_pin": wire["from"],
                    "to_pin": target_pin,
                    "color": wire["color"],
                    "instruction": f"Connect {wire['from']} on {label} → {board['name']} {target_pin}",
                }
            )
            step_num += 1

    for pin_id, owners in pin_owners.items():
        if len(owners) > 1:
            conflicts.append(f"Pin conflict on {pin_id}: shared by {' and '.join(owners)}. Reassign one to a free pin.")

    return {
        "ok": len(conflicts) == 0,
        "conflicts": conflicts,
        "warnings": warnings,
        "used_pins": sorted(pin_owners.keys()),
        "wiring_steps": wiring_steps,
    }


def generate_prototype_code(
    attachments: Sequence[Dict[str, Any]],
    project_name: str = "Prototype",
    board_id: str = "microbit_v2",
) -> str:
    """Auto-generate ready-to-run board-specific code for all attached accessories."""
    if board_id == "rpi5_16gb":
        lines = [
            f"#!/usr/bin/env python3",
            f'"""Raspberry Pi 5 Prototype: {project_name}"""',
            "import time",
            "try:\n    import smbus2\n    bus = smbus2.SMBus(1)\nexcept Exception:\n    bus = None",
            "",
            "print('Raspberry Pi 5 Prototype Started:', " + repr(project_name) + ")",
        ]
        for att in attachments:
            aid = att.get("accessory_id")
            if aid == "hiwonder_temp_hum_v11":
                lines.append("# Hiwonder Temp & Humidity v1.1 (AHT10 I2C 0x38 on GPIO2/GPIO3)")
                lines.append("if bus: bus.write_i2c_block_data(0x38, 0xAC, [0x33, 0x00])")
            elif aid == "hiwonder_ultrasonic_v56":
                lines.append("# Hiwonder Glowing Ultrasonic v5.6 (I2C 0x77 on 5V + GPIO2/GPIO3)")
                lines.append("if bus: bus.write_i2c_block_data(0x77, 3, [0, 255, 220])  # Set RGB Cyan")
            elif aid == "hiwonder_touch_sensor":
                lines.append(f"# Hiwonder Touch Sensor (TTP223) on {att.get('pin', 'GPIO17')}")
            elif aid == "hiwonder_led_matrix_8x16":
                lines.append(f"# Hiwonder 8x16 LED Matrix (TM1640) CLK={att.get('pin','GPIO23')} DIO={att.get('secondary_pin','GPIO24')}")
        lines.append("while True:\n    time.sleep(0.5)")
        return "\n".join(lines) + "\n"

    if board_id == "puppypi_pro":
        lines = [
            "#!/usr/bin/env python3",
            f'"""PuppyPi Pro ROS 2 Humble Prototype: {project_name}"""',
            "import rclpy",
            "from rclpy.node import Node",
            "",
            "class PuppyPrototypeNode(Node):",
            "    def __init__(self):",
            "        super().__init__('puppy_prototype')",
            f"        self.get_logger().info('PuppyPi Pro Prototype Ready: {project_name}')",
        ]
        for att in attachments:
            lines.append(f"        # Attached: {att.get('label')} on {att.get('pin')}")
        lines.append("\nif __name__ == '__main__':\n    rclpy.init()\n    rclpy.spin(PuppyPrototypeNode())")
        return "\n".join(lines) + "\n"

    # Default: BBC micro:bit v2.2 MicroPython
    if not attachments:
        return STARTER_TEMPLATES[0]["code"]

    imports = ["from microbit import *"]
    setup = [f"# micro:bit v2.2 Prototype: {project_name}", "speaker.on()", "set_volume(255)", "display.show(Image.HAPPY)"]
    loop: List[str] = []

    if any(a.get("accessory_id") == "neopixel_8" for a in attachments):
        imports.append("import neopixel")
    if any(a.get("accessory_id") == "external_speaker" for a in attachments):
        imports.append("import music")

    for idx, att in enumerate(attachments):
        aid = str(att.get("accessory_id") or "")
        pin_name = str(att.get("pin") or "P0").lower()
        pvar = f"pin{pin_name[1:]}" if pin_name.startswith("p") and pin_name[1:].isdigit() else "pin0"
        if aid == "hiwonder_temp_hum_v11":
            setup.append("# Hiwonder Temp & Humidity v1.1 (AHT10 I2C 0x38 on P19/P20)")
            loop.append("    try:\n        i2c.write(0x38, bytes([0xAC, 0x33, 0x00]))\n        sleep(80)\n        raw = i2c.read(0x38, 6)\n        hum = ((raw[1] << 12) | (raw[2] << 4) | (raw[3] >> 4)) * 100 / 1048576\n        temp = (((raw[3] & 0x0F) << 16) | (raw[4] << 8) | raw[5]) * 200 / 1048576 - 50\n        print('AHT10:', round(temp, 1), 'C', round(hum, 1), '%')\n    except Exception:\n        pass")
        elif aid == "hiwonder_touch_sensor":
            loop.append(f"    if {pvar}.read_digital() == 1:\n        display.show(Image.HEART)\n        print('TOUCH_DETECTED')")
        elif aid == "hiwonder_ultrasonic_v56":
            setup.append("# Hiwonder Glowing Ultrasonic v5.6 (I2C 0x77 — external 5V + level shifter)")
            loop.append("    try:\n        i2c.write(0x77, bytes([0]))\n        dist_mm = int.from_bytes(i2c.read(0x77, 2), 'little')\n        print('ULTRASONIC_CM:', dist_mm // 10)\n    except Exception:\n        pass")
        elif aid == "hiwonder_led_matrix_8x16":
            setup.append(f"# Hiwonder 8x16 LED Matrix (TM1640) CLK={pvar}, DIO=pin2")
            loop.append("    display.show(Image.HAPPY)")
        elif aid == "sg90_servo":
            setup.append(f"{pvar}.set_analog_period(20)  # 50Hz SG90 Servo")
            loop.append(f"    if button_a.was_pressed(): {pvar}.write_analog(128)\n    elif button_b.was_pressed(): {pvar}.write_analog(26)")
        elif aid == "neopixel_8":
            setup.append(f"np_{idx} = neopixel.NeoPixel({pvar}, 8)")
            loop.append(f"    for i in range(8): np_{idx}[i] = (0, 35, 55)\n    np_{idx}.show()")
        elif aid == "external_speaker":
            loop.append(f"    if pin_logo.is_touched(): music.play(['C5:2', 'E5:2', 'G5:3'], pin={pvar})")

    if not loop:
        loop.append("    print('TEMP_C:', temperature())")

    return "\n".join(imports) + "\n\n" + "\n".join(setup) + "\n\nwhile True:\n" + "\n".join(loop) + "\n    sleep(150)\n"


# ---------------------------------------------------------------------------
# 1:1 Millimeter Mechanical Specs (inspired by Baggage Claims Device Envelope)
# ---------------------------------------------------------------------------
_BOARD_MECHANICAL_SPECS: Dict[str, Dict[str, Any]] = {
    "microbit_v2": {
        "dimensions_mm": [51.6, 42.0, 11.7],
        "pcb_thickness_mm": 1.6,
        "mass_g": 8.0,
        "mounting_holes_mm": [[-24.0, 16.5, 4.8], [-16.0, 16.5, 3.1], [16.0, 16.5, 3.1], [24.0, 16.5, 4.8]],
        "svg_icon_kind": "microbit_v2",
    },
    "rpi5_16gb": {
        "dimensions_mm": [85.0, 56.0, 16.0],
        "pcb_thickness_mm": 1.6,
        "mass_g": 46.0,
        "mounting_holes_mm": [[-39.0, -24.5, 2.75], [19.0, -24.5, 2.75], [-39.0, 24.5, 2.75], [19.0, 24.5, 2.75]],
        "svg_icon_kind": "rpi5_16gb",
    },
    "puppypi_pro": {
        "dimensions_mm": [149.0, 226.0, 46.0],
        "pcb_thickness_mm": 2.0,
        "mass_g": 720.0,
        "mounting_holes_mm": [[-45.0, -60.0, 3.2], [45.0, -60.0, 3.2], [-45.0, 60.0, 3.2], [45.0, 60.0, 3.2]],
        "svg_icon_kind": "puppypi_pro",
    },
}

_ACCESSORY_MECHANICAL_SPECS: Dict[str, Dict[str, Any]] = {
    "hiwonder_temp_hum_v11": {
        "dimensions_mm": [48.0, 24.0, 10.5],
        "mass_g": 6.0,
        "mounting_holes_mm": [[-16.0, 0.0, 4.8], [16.0, 0.0, 4.8]],
        "cutout_profile": {"face": "top", "w_mm": 16.0, "h_mm": 12.0},
        "svg_icon_kind": "temp_hum",
    },
    "hiwonder_touch_sensor": {
        "dimensions_mm": [50.0, 20.0, 9.0],
        "mass_g": 5.5,
        "mounting_holes_mm": [[-16.0, 0.0, 4.8], [16.0, 0.0, 4.8]],
        "cutout_profile": {"face": "top", "w_mm": 16.0, "h_mm": 16.0},
        "svg_icon_kind": "touch_pad",
    },
    "hiwonder_ultrasonic_v56": {
        "dimensions_mm": [45.0, 20.0, 15.0],
        "mass_g": 11.0,
        "mounting_holes_mm": [[-16.0, 0.0, 4.8], [0.0, 0.0, 4.8], [16.0, 0.0, 4.8]],
        "cutout_profile": {"face": "front", "w_mm": 42.0, "h_mm": 16.5},
        "svg_icon_kind": "ultrasonic",
    },
    "hiwonder_led_matrix_8x16": {
        "dimensions_mm": [64.0, 32.0, 11.0],
        "mass_g": 18.0,
        "mounting_holes_mm": [[-28.0, -12.0, 3.0], [28.0, -12.0, 3.0], [-28.0, 12.0, 3.0], [28.0, 12.0, 3.0]],
        "cutout_profile": {"face": "top", "w_mm": 54.0, "h_mm": 24.0},
        "svg_icon_kind": "led_matrix",
    },
    "ld19_lidar": {
        "dimensions_mm": [38.6, 38.6, 33.5],
        "mass_g": 47.0,
        "mounting_holes_mm": [[-15.0, -15.0, 2.6], [15.0, -15.0, 2.6], [-15.0, 15.0, 2.6], [15.0, 15.0, 2.6]],
        "cutout_profile": {"face": "top", "w_mm": 40.0, "h_mm": 40.0},
        "svg_icon_kind": "lidar",
    },
    "wonderecho_ai_box": {
        "dimensions_mm": [45.0, 30.0, 18.0],
        "mass_g": 28.0,
        "mounting_holes_mm": [[-18.0, 0.0, 3.0], [18.0, 0.0, 3.0]],
        "cutout_profile": {"face": "top", "w_mm": 24.0, "h_mm": 24.0},
        "svg_icon_kind": "ai_box",
    },
    "sg90_servo": {
        "dimensions_mm": [22.5, 11.8, 31.0],
        "mass_g": 9.0,
        "mounting_holes_mm": [[-13.75, 0.0, 2.2], [13.75, 0.0, 2.2]],
        "cutout_profile": {"face": "top", "w_mm": 23.0, "h_mm": 12.2},
        "svg_icon_kind": "servo",
    },
    "neopixel_8": {
        "dimensions_mm": [52.0, 10.0, 3.5],
        "mass_g": 4.0,
        "mounting_holes_mm": [[-22.0, 0.0, 2.5], [22.0, 0.0, 2.5]],
        "cutout_profile": {"face": "top", "w_mm": 50.0, "h_mm": 8.0},
        "svg_icon_kind": "neopixel",
    },
    "external_speaker": {
        "dimensions_mm": [40.0, 40.0, 14.0],
        "mass_g": 24.0,
        "mounting_holes_mm": [[-16.0, -16.0, 3.0], [16.0, -16.0, 3.0], [-16.0, 16.0, 3.0], [16.0, 16.0, 3.0]],
        "cutout_profile": {"face": "top", "w_mm": 36.0, "h_mm": 36.0},
        "svg_icon_kind": "speaker",
    },
    "oled_ssd1306": {
        "dimensions_mm": [27.0, 27.8, 4.2],
        "mass_g": 5.0,
        "mounting_holes_mm": [[-11.5, -11.5, 2.2], [11.5, -11.5, 2.2], [-11.5, 11.5, 2.2], [11.5, 11.5, 2.2]],
        "cutout_profile": {"face": "top", "w_mm": 24.0, "h_mm": 14.0},
        "svg_icon_kind": "oled",
    },
    "i2c_level_shifter": {
        "dimensions_mm": [15.2, 12.7, 4.5],
        "mass_g": 1.8,
        "mounting_holes_mm": [],
        "cutout_profile": None,
        "svg_icon_kind": "level_shifter",
    },
}

for _bid, _mspec in _BOARD_MECHANICAL_SPECS.items():
    if _bid in BOARD_PROFILES:
        BOARD_PROFILES[_bid].update(_mspec)

for _acc in MICROBIT_ACCESSORIES:
    _aspec = _ACCESSORY_MECHANICAL_SPECS.get(_acc["id"])
    if _aspec:
        _acc.update(_aspec)
    else:
        _acc.setdefault("dimensions_mm", [28.0, 20.0, 10.0])
        _acc.setdefault("mass_g", 6.0)
        _acc.setdefault("mounting_holes_mm", [])
        _acc.setdefault("cutout_profile", None)
        _acc.setdefault("svg_icon_kind", "generic")

