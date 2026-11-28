# Changelog

All notable changes to **Eigenia // TwinScan Studio** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-11-28

### Added
- **Universal Multi-Board 3D Hardware Lab & AI Co-Pilot (`/microbit`)**
  - Switchable Three.js `r187` 3D digital twin workbench supporting **BBC micro:bit v2.2**, **Raspberry Pi 5 16 GB**, and **Hiwonder PuppyPi Pro (+ LD19 LiDAR & WonderEcho AI Box)**.
  - Drag-and-drop **Hiwonder Sensor & Component Library**: Temp & Humidity v1.1 (`AHT10` I2C `0x38`), Touch Sensor (`TTP223`), Glowing Ultrasonic v5.6 (`I2C 0x77`), 8×16 LED Matrix (`TM1640`), LD19 360° LiDAR, WonderEcho Pro AI Box, and 3.3V↔5V I2C Level Shifter with live electrical safety notices.
  - Interactive 3D browser simulator with clickable buttons, touch logo, sensor controls, Web Audio speaker synthesis, and Web Speech TTS.
  - Built-in **OpenRouter AI Co-Pilot** chat that builds/updates 3D wiring & behavior code in real time before 1-click deployment to physical hardware over USB/SSH.
- **Standalone Compositional Room Twin Studio (`/room-studio`)**
  - Full-bleed Three.js `r187` glassmorphic viewport for multi-photo wall stitching, OpenRouter Vision scene-graph object detection & interactive boxing, Photo-to-3D `.glb` synthesis (`local_depth3d`, `fal-ai/trellis-2`, `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d`, `tripo3d`), `TransformControls`, 3DGS/PLY/GLB import/export, and AI Next-Best-View Ghost Camera Capture Coach.
- **Dedicated SLAM Mapping Studio (`/slam`)**
  - Live ROS 2 Humble Occupancy-Grid SLAM controller (`hiwonder_slam` / `slam_toolbox`) for PuppyPi Pro's LD19 360° LiDAR with live occupancy canvas, mapped area (`m²`) telemetry, and 1-click **Export → 3D Digital Twin** (extruded 3D `.glb` walls + Room Studio project).
- **Overwatch Multi-Camera Stage, Pi 5 4K Puller & Self-Calibration (`/overwatch`)**
  - Spotlight Main+Mini, Grid, and Map Focus stage modes with `localStorage`-persisted collapse/hide controls.
  - `RemoteOverwatchPullerManager` and `FleetCameraDiscovery` for automatic Raspberry Pi 5 4K USB webcam (`eigenia-pi5-cam.service`) ingestion.
  - 4-tab Guided Self-Calibration Wizard with built-in Calibration Guide.
- **Universal Multi-Platform Device Flasher (`/flash`) & Auto Fleet-to-Architect Sync (`/architect`)**
  - Unified flashing workflows for Raspberry Pi OS, ROS 2, MicroPython, ESP32/ESPHome, and BBC micro:bit.
  - Automatic synchronization of discovered LAN fleet devices and USB peripherals into Lab Architect.
- **Mission Control Landing Page (`/`)**
  - Added `v2.1.0` release badge, **What's New in v2.1 — Featured Studios** 4-card spotlight strip, and expanded 10-tile Core Operations grid covering all 18 studio routes.

### Changed
- Upgraded sidebar navigation with grouped sections, favorites pinning, and DNN concurrency locking.
- Persisted cleared patrol waypoints and added dedicated `/explore` route alias.
- Bumped backend FastAPI and frontend Next.js package versions from `2.0.0` to `2.1.0`.
- Expanded automated test suite from `199` to `220` passing `pytest` tests.

## [2.0.0] - 2026-11-26

### Added
- Initial public release of **Eigenia // TwinScan Studio** with Tactical Multi-Camera Overwatch, Real-Room 3D Reconstruction (Three.js + Babylon.js 9 PBR), Autonomous Waypoint Patrol & Frontier Explorer with low-battery RTH, Lab Architect Hardware Co-Design, Live ROS 1 / ROS 2 Teleop, Fleet BOM/SBOM, Knowledge Graph, Voice/OX Assistant, and 4-Step Onboarding Wizard.
