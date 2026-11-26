---
name: puppypi-twinscan
description: Control, inspect, scan, and autonomously explore with a Hiwonder PuppyPi Pro quadruped robot via Eigenia TwinScan's 10-tool MCP Bridge (100% local, zero cloud lock-in).
---

# Eigenia TwinScan — Hiwonder PuppyPi Pro Skill (OpenClaw + MCP)

Use this skill whenever the user asks to inspect, speak through, move, capture camera snapshots from, recall Spatial Memory from, 3D-scan a room with, or autonomously explore with their **Hiwonder PuppyPi Pro** (Raspberry Pi 5 + LD19 360° LiDAR + UVC FPV Camera + WonderEcho Pro + ROS 2 Humble).

## Available MCP Tools (`eigenia-puppypi`)

1. **`get_robot_status`** — Live 2S LiPo battery voltage & %, ROS distro, online/offline state, 5-sector LD19 LiDAR clearances, and active patrol/explorer status.
2. **`speak_aloud`** (`{text, voice?}`) — Speak aloud on PuppyPi's WonderEcho Pro USB speaker via offline Piper TTS (`<= 320` chars).
3. **`run_body_action`** (`{action}`) — Safe allow-listed postures & tricks: `sit`, `stand`, `stand_low`, `lie_down`, `bow`, `wave`, `shake_hands`, `nod`, `push_up`, `moonwalk`, `go_home`.
4. **`capture_camera_snapshot`** (`{analyze?: true}`) — Capture a live FPV frame + local offline YOLO11n & YuNet/SFace detections.
5. **`recall_spatial_memory`** (`{query?, limit?}`) — Search Semantic Spatial Memory for previously sighted people, pets, or objects.
6. **`start_autonomous_explore`** (`{space_context?, max_iterations?, rth_battery_v?}`) — Launch Stage 3 Autonomous Frontier Explorer & Multi-Angle 3D Room Mapper (auto-stops active Patrol and enforces low-battery RTH).
7. **`return_to_home`** — Trigger safe Return-to-Home Base (RTH) to `(0, 0)` + `go_home` crouch.
8. **`stop_robot_estop`** — Immediate global Emergency Stop across Patrol, Explorer, Sentry, AI Vision, and ROSBridge.
9. **`scan_room_wall_3d`** (`{quality?: "fast"|"balanced"|"ultra"}`) — Zero-movement Stage 1 3D wall relief panel fusing Camera + LD19 LiDAR + Depth Anything V2.
10. **`chat_as_ox`** (`{message, speak?}`) — Delegate a conversational prompt to PuppyPi's onboard "Hey OX" persona.

## Safety Rules

- Always check `get_robot_status` before starting `start_autonomous_explore` if battery voltage is unknown (default auto-RTH threshold is `7.1 V` for 2S LiPo).
- If the user says "stop", "freeze", "halt", or "emergency stop", call **`stop_robot_estop`** immediately as the first tool call.
- Never invent shell commands or raw ROS topics — always use the 10 validated MCP tools above.

## Quick Setup

1. Ensure Eigenia TwinScan backend is running (`http://localhost:8000`).
2. Copy this skill folder into `~/.openclaw/skills/puppypi-twinscan/`.
3. Merge `openclaw/mcp-config.json` into your OpenClaw MCP servers configuration.
