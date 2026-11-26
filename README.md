# Eigenia // TwinScan — Cyber-Physical Digital Twin & PuppyPi ROS 1 / ROS 2 Fleet Command Center

Multi-page **PuppyPi ROS 1 Noetic / ROS 2 Humble Dual-Mode Command Center**, **LD19 360° Spatial LiDAR Twin**, **OpenRouter Multi-Model Vision & Research Enrichment**, **PostgreSQL 18 (`pgvector`) + File Storage**, and **Neo4j 5 Knowledge Graph** platform styled with the **Eigenia B.V.** design system:

* **ROS 1 Noetic Mode (Obsidian):** `#0b0d10` / `#0E1013` / `#15171b` surfaces, `#E05A10` Signal Orange accents, `#38bdf8` Telemetry Sky.
* **ROS 2 Humble Mode (Ambient Signal Orange):** Smooth faded Eigenia Orange ambient wash & badges across the persistent shell (`Preview ROS 2` toggle or live ROS 2 activation) so operators immediately recognize which ROS stack is active.

## Upgraded Modern Stack (v2.0)

* **Frontend:** **Next.js 16.4.6** (App Router), **React 19.3.1**, **TypeScript 5.9.3**, **Tailwind CSS 4.3.5** (`@tailwindcss/postcss`), **`shadcn/ui`** / Radix UI primitives, **Babylon.js 9.37.2**, **Three.js 0.187.0** (direct WebGLRenderer), **React Flow (`@xyflow/react`) 13.0.3**, **Lucide React 1.79.0**.
* **Backend:** **Python 3.13** (`python:3.13-slim`), **FastAPI**, **Uvicorn**, **`httpx2`** + **`httpx`**, **`websockets 15+`**, **`psycopg 3` + `pgvector`**, **`neo4j 6`**, **`cryptography 46+`**, **`trimesh 5`**, **`opencv-python-headless 5`**, **`zxing-cpp 3`**, **`pytest 9`** (`pytest-asyncio 1+`).
* **Data Layer:** **PostgreSQL 18 (`pgvector/pgvector:pg18`)** with `halfvec(1536)` HNSW indexes + **Neo4j 5 Community**.

## 6-Route Eigenia Cockpit Command Center (`frontend/`)

Persistent App Router shell (`EigeniaShell` + `StudioContext` + `error.tsx` fault boundary) with a **Global `⌘K` Command Palette**, **6 animated Tailwind/shadcn Cockpit UI primitives** (`AnimatedMetric`, `WorkspaceHeader`, `SlideOverDrawer`, `InteractiveSurface`, `SegmentedTabs`, `CommandPalette`), an active robot selector, **live Wi-Fi (`wlan0`) & Ethernet (`eth0`/`eth1`) IP telemetry pills with 1-click IP switching**, **ROS 1 ↔ ROS 2 ambient mode indicator**, and a fixed global **E-STOP** button across every route:

* **Cockpit Route Highlights:**
  * **`/twin`:** Compact sticky `WorkspaceHeader` + Fusion Ribbon + reclaimed-height `h-[640px]` viewport (`2D Tactical Radar`, `3D Three.js Twin`, `3D Babylon.js 9 PBR`) + 3 gliding Slide-Over Drawers (`Rooms & Scenes`, `Fusion & LD19 Tuning` with **Download Full Room `.glb`** combined multi-mesh glTF 2.0 export `GET /api/spaces/{id}/reconstruct/export-room.glb`, `Assets & Filters`).
  * **`/catalog`:** Sticky `WorkspaceHeader` with live Pi 5 PMIC KPIs (`EXT5V`, `Board Power`, `USB`) + 5 URL-synced tabs (`3D & Bus Topology` with Three.js 3D ↔ React Flow Pi 5 Bus Graph & Split View, `Hardware BOM` with click-to-inspect `SlideOverDrawer`, `Software SBOM`, `Updates & Rollback`, `Fleet & Network` with safe Pi 5 **`Clean Stale Logs`** maintenance `POST /api/robots/{id}/maintenance/clean-logs`).
  * **`/voice`:** Compact `WorkspaceHeader` (live Mic RMS meter, Wake Word, Personality, TTS Engine) + 3 URL-synced tabs (`Live Conversation`, `Voice & Personalities` with Slide-Over custom persona editor & ALSA mixer, `Diagnostics & Audio Flow` with interactive 7-stage React Flow Audio Pipeline).
  * **`/control`:** Sticky Left Drive Deck (Live FPV + Dead-Man Velocity Pad + Quick Stop) paired with a 3-tab Right Control Deck (`Stances & Actions`, `Gait & Servos`, `LEDs, OLED & Buzzer`), with global **E-STOP** & manual drive commands automatically preempting both Patrol and Autonomous Explorer.
  * **`/vision`:** Sticky `WorkspaceHeader` + 3-tab Studio (`Live AI Vision & People`, **Semantic Spatial Memory Pro** with `Bento Grid` / `Small Grid` / `Line View`, Active/Archived/All filters, bulk actions, and click-to-inspect `SlideOverDrawer` for full-res images + inline Rename/Notes/Tags, and `Sentry Guard Mode`).
  * **`/graph`:** Sticky `WorkspaceHeader` + interactive React Flow 13 Neo4j 5 Knowledge Graph & PostgreSQL 18 `pgvector` semantic search.
  * **`/architect`:** **Interactive Human-AI Hardware Co-Design Canvas Studio & Universal Hardware Envelope** (5 tabs: `Co-Design Canvas` with 5-Tier Creativity Dial `T1–T5`, 2D React Flow Wiring ↔ 3D Three.js `Wireframe`/`Translucent`/`Solid` Assembly & Split View + Electrical Guardrails; `Idea Generator`; `Lab Inventory & Wishlist` CRUD; `Board Profiles & IoT` with 6 local board profiles, **BBC micro:bit v2.21 Studio** 5×5 LED Matrix Painter & MicroPython templates, and **100% Cloud-Free Local Camera Array & Pi Zero `g_mass_storage` USB-Gadget Clip Harvester**; `Saved Blueprints`).
  * **`/patrol`:** Compact `WorkspaceHeader` + **Live PuppyPi FPV Camera PiP** + 2 URL-synced tabs: **Waypoint Patrol** (5-sector live LD19 VFH clearances, single-instance LD19 deduplication + Wi-Fi jitter resilience) and **Autonomous Explore & Map (`/patrol?tab=explore`)** — Stage 3 Autonomous Frontier Explorer (`src/robot/explorer_engine.py`) with Patrol ↔ Explorer mutual exclusion, mid-transit LD19 dropout guard (`paused_lidar_wait` → `blocked_no_lidar`), startup auto-attach to live `robot_ros2` LD19 (`rotation_offset_deg: 90°`), live IMU yaw anchoring & fusion (Explorer + 360° room capture), Dark-Zone Next-Best-View targeting, Multi-Angle Pitch/Yaw 3D Mapping, and 2S LiPo Low-Battery + AprilTag Return-to-Home (`RTH`).
  * **`/welcome` — Maker Showcase Landing Page (50-User Early Bird Special):** Full-bleed showcase (no app sidebar) featuring an interactive **Three.js PuppyPi Pro 3D Digital Twin Hero**, live **React Flow** cyber-physical pipeline explorer, Hiwonder PuppyPi Pro worked example, and PostgreSQL 18-backed **50-User Early Bird Founder Pass** claim flow (`/api/early-bird/status`, `/api/early-bird/claim`).
  * **`/wiki` — Complete Wiki, 4-Step Interactive Onboarding Wizard & React Flow Site Tree:** Backed by `docs/wiki/` (11 VitePress-ready Markdown guides + `catalogue.json` authored per `wiki-architect` & `wiki-page-writer`, served via `/api/wiki/catalogue` & `/api/wiki/pages/{slug}`), interactive 4-step Onboarding Wizard, live React Flow Site Tree (`/wiki?tab=sitetree`), and Support & Troubleshooting cards (`/wiki?tab=support`).
  * **`/config`:** Compact `WorkspaceHeader` + 3 URL-synced tabs (`AI & OpenRouter Models`, `Robot OS, Wi-Fi & ROS 1/2`, `Databases & Storage`).

1. **`/` — Mission Control (Fleet Overview):** Live fleet health with a **15-second background TCP liveness probe** (accurate `online`/`offline` status), 1-click LAN auto-discovery, Wi-Fi/Ethernet interface status & 1-click active IP switcher, ROS 1 vs ROS 2 comparison summary, alerts triage, and recent spatial twin scans.
2. **`/twin` — Spatial LiDAR Twin (2D / 3D Three.js / 3D Babylon.js):**
   * 60 FPS 2D Tactical LiDAR & floorplan canvas (`Lidar2DCanvas`) with **2–20 Hz configurable polling (`50–500 ms`)**, **PuppyPi ROS 2 `/scan` live bridge** (with hardened CycloneDDS 1-click `start-lidar`), **LD19 Forward Orientation Calibrator** (`FRONT ↑` Camera FOV Cone, live 4-cardinal meters `FRONT`/`RIGHT`/`BACK`/`LEFT`, 1-click `0°/90°/180°/270°` mounting rotation with `90°` ROS 2 default), **Kalman Moving-Object Radar** (velocity vectors & trajectory trails), RANSAC walls, DBSCAN equipment clusters, click-to-place, ruler, and physical change detection.
   * **Multi-Room / Saved Scenes Manager (`GET/POST/PATCH/DELETE /api/spaces` & `POST /api/spaces/{id}/clone`):** Top-bar **`+ New Room`** button, **Rooms & Saved Scenes** gallery with live JPEG panel thumbnails, inline Rename, zero-copy Clone Checkpoint, Archive to PostgreSQL 18, and safe Delete.
   * Dual direct WebGL 3D digital twin viewports: **Three.js 187** (`DigitalTwin3D`) and **Babylon.js 9.37 PBR** (`BabylonTwinCanvas`) with a **Live 3D PuppyPi Avatar Mirror** (real-time heading, stance, gait, and camera frustum), safe WebGL fallbacks, and clean resource disposal.
   * **3D Real-Room Camera + LiDAR + Depth Fusion (`src/lidar/scene_reconstructor.py`):**
     * **Stage 1 — Zero-Movement Wall Capture (`POST /api/spaces/{id}/reconstruct/capture-wall`) & 5-Pass Composite Enhancement Pipeline (`Fast` / `Balanced` / `Studio Ultra`):** Captures a live PuppyPi camera frame (with multi-frame burst stacking), runs LAB CLAHE + detail sharpen + `2×` Lanczos `1280×960` texture upscaling, **Flip-TTA Depth Anything V2 Small ONNX** (`depth_anything_v2_vits.onnx`, auto-cached in `twinscan_models/`) refined with **`O(N)` He et al. RGB-Guided Depth Filtering**, **Multi-Sweep LD19 LiDAR Denoising + MAD-trimmed Affine & Residual Warp Calibration**, **Taubin Mesh Polish**, and **Baked Tangent-Space PBR Normal Maps** (`normal_map_url`), persisting panels in PostgreSQL 18 (`scene_panels`) with 1-click re-enhance (`POST /reconstruct/panels/{id}/enhance`) and binary **glTF 2.0 `.glb`** export.
     * **Stage 2 — 360° Stepped Turn Capture (`POST /api/spaces/{id}/reconstruct/capture-360`):** Automated multi-heading room sweep with E-STOP/disconnect safety guards and guaranteed zero-velocity halt.
     * **Interactive Render Modes & Drawer:** Switch live between **`Fast` / `Balanced` / `Studio Ultra`** and **Solid (Shaded)**, **Translucent**, and **Wireframe** in both **Three.js** and **Babylon.js 9 PBR** (consuming PBR diffuse + normal maps), with an expandable **Tuning & Panels** drawer for 6 pass switches, quality chips (`1280×960`, `Normal Map`, `Enhance`), thumbnails, and 1-click `.glb` downloads.
   * **Dark-Zone Focus Queue** (`src/lidar/dark_zones.py`) to guide operators toward occluded/unmapped sectors and close spatial completeness gaps (`src/twin/completeness.py`).
   * **Vision Nameplate Inspector** & **Direct Research Enrichment** (`src/enrichment/research_enricher.py`) with OpenRouter multi-model VLM + web-grounded equipment specs.
3. **`/control`, `/vision`, `/voice`, `/patrol` — Live Robot Control, AI Vision, Voice & Autonomous Patrol:**
   * **Drive & Stance Control (`/control`):** Single-origin FastAPI MJPEG FPV relay (`web_video_server`) with clean MJPEG socket teardown on topic/tab switch, dual-mode ROS 1 / ROS 2 ROSBridge WebSocket Proxy with a **0.5s server-side Dead-Man's Switch**, clamped PuppyPi velocity (`/puppy_control/velocity/autogait` + manual gait toggle), 7 stance presets (`Stand`, `LieDown`, `StandLow`, `LookDown*`), 6 gait presets (`Fast`, `Slow`, `Trot`, `Amble`, `Walk`, `Crawl`) + `MarkTime`, 38 `.d6ac`/`.d6a` action groups, 2-DOF arm servos (IDs 9–11), STM32 buzzer/RGB/OLED, and ROS 1 OpenCV / ROS 2 Humble Autonomy decks + 1-click **Snap-to-Vision**.
   * **AI Vision, Spatial Memory & Sentry Guard Studio (`/vision`, 3 Sub-Tabs, `pgvector`):**
     * **Live AI Vision & People:** Real-time backend inference (`src/vision/robot_ai_vision.py`) using auto-cached YuNet / SFace / YOLO11n ONNX weights in `twinscan_models` (`TWINSCAN_MODELS_DIR=/app/data/models`) with Kaizen V1–V5 hardening (OpenCV 5.1 AprilTag 1D ID fix, immediate Offline HUD JPEG fallback instead of stream hangs, dynamic YOLO target re-locking + `LOST TARGET` telemetry, live **Target FPS `2–20`** & **Confidence `0.20–0.80`** tuning, and leak-free MJPEG `<img>` teardown). Supports 6 modes (`raw`, `face_recognition`, `object_animal`, `track_follow` with `< 0.35m` LD19 hard-stop, `line_follow`, `apriltag`) and OpenRouter `deep_identify_frame`.
     * **Semantic Spatial Memory:** Persists detected object/person/room sightings (`spatial_memory_sightings` in PostgreSQL 18) with snapshot previews, `(x, y)` coordinates, one-click **`Scan & Remember Room Now`**, and voice recall (*"Hey OX, where did you last see my laptop?"*).
     * **Autonomous Sentry Guard Mode:** Armable perimeter patrol guard (`sentry_rules` & `sentry_events`) triggered by LiDAR moving objects, unknown faces, or animals with configurable cooldowns, spoken personality challenges, RGB alert flashes, and an evidence photo alert feed.
   * **Conversational Voice Assistant & WonderEcho Pro Speaker Studio (5 Sub-Tabs, `/voice`):**
     * **Default Offline Neural TTS + Multi-Engine Cascade:** Defaults to 100% offline local **`piper-tts`** (`en_US-lessac-medium`, auto-cached in `twinscan_models/piper/`), with `edge_tts` Microsoft Neural voices, `auto`, and `espeak-ng` selectable, all conditioned through **`ffmpeg`** anti-clipping speaker EQ (`highpass=f=180,acompressor,alimiter=limit=0.88`, 16 kHz mono WAV) piped over SSH to auto-detected WonderEcho USB ALSA card (`plughw:<card>,0`).
     * **Offline STT (`faster-whisper`) & Configurable `"Hey OX"` Wake Word:** CPU INT8 `faster-whisper` (`tiny.en`) powers Push-to-Talk and the hands-free multi-turn conversation loop (dynamic USB ALSA card auto-detection, USB disconnect error surfacing, RMS VAD gate, 12s follow-up window, 350ms echo guard, sleep phrases, and one-breath wake phrases like *"Hey OX, tell me a joke"* with phonetic alias matching, alongside WonderEcho 5-byte `/dev/wonderecho` UART hardware wake support).
     * **5 Built-In + Custom Personalities & Multi-Turn Memory:** Includes Playful Robot Dog (`dog`), Aloof Robot Cat (`cat`), Irritable Paranoid Android (`marvin`), Dad-Joke Nerd (`dad_joke_nerd`), and Eigenia Lab Engineer (`lab_assistant`), plus full Custom Personality CRUD, OpenRouter multimodal camera-grounded chat (with rich in-character offline fallbacks), and persistent `voice_assistant_config` / `voice_personalities` / `voice_conversation_turns` / `voice_interaction_logs` in PostgreSQL 18.
     * **Audio Mixer, Chimes & 6-Point Diagnostics:** Direct ALSA speaker/mic mixer controls (1-click **Ideal 80%** anti-distortion level), 4 synthesized chimes, and a **Diagnostics & Test** tab with a 6-point Voice & `"Hey OX"` scorecard (USB power/throttling, ALSA audio card, `/dev/wonderecho` serial symlink, Piper → Whisper loopback, live mic wake-word test, and speaker test).
   * **Autonomous Multi-Waypoint Patrol:** Route builder & executor (`src/robot/patrol_engine.py`) with 5-sector VFH LiDAR + visual obstacle avoidance, persistent `patrol_routes` in PostgreSQL 18, and instant global **E-STOP** disarm/halt.
4. **`/catalog` — Fleet BOM, SBOM (CycloneDX 1.6), Live Pi 5 PMIC Diagnostics & 3D Hardware Twin, Update Checker & Safe Update Executor:**
   * **Live Raspberry Pi 5 PMIC/Wattage/USB Diagnostics & Interactive Exploded 3D Pi 5 BOM Hardware Twin (`GET /api/robots/{id}/hardware-diagnostics`):** Live DA9091 PMIC voltage/current rails, `total_pmic_watts`, `usb_budget_ma` (`1600 mA` headroom), per-port USB/I2C/UART/camera/audio health across 22 components, and an interactive **Three.js Exploded 3D Pi 5 Hardware Twin** (`Wireframe` / `Translucent` / `Solid (Shaded)`, Exploded View, label filters, and bidirectional 3D ↔ BOM click selection).
   * Automated SSH **Hardware BOM** (Raspberry Pi 5 board, USB/serial bus tree, camera, audio, UART/I2C, Wi-Fi/Ethernet interfaces) and **6-Layer Software SBOM** (Host Debian dpkg/pip + Docker ROS 1 Noetic & ROS 2 Humble dpkg/ros/pip).
   * **Live PyPI, ROS Lifecycle & 9-Item Hardware/Feature Readiness Checker** (`/api/robots/{id}/update-check`) + **Safe Update Executor** (`dry-run`, `download`, `snapshot + apply`, 6-point live smoke test scorecard, Docker snapshot rollback, and PostgreSQL 18 `robot_update_jobs` ledger).
   * Persisted to **PostgreSQL 18** (`robots`, `robot_devices`, `robot_sbom_packages`), synced to **Neo4j 5**, and downloadable as **OWASP CycloneDX 1.6 JSON**.
5. **`/graph` — Knowledge Graph & `pgvector` Search:**
   * Interactive **React Flow 13** (`@xyflow/react`) topology visualizer backed by **Neo4j 5** (`Schema G_CPDT`: `Facility -> Space -> Equipment` + `Robot -> HardwareDevice / Container`) and **PostgreSQL 18 `pgvector`** `halfvec(1536)` HNSW semantic search.
6. **`/config` — Remote Robot Configurator & Kaizen Platform Admin:**
   * Safe SSH configurator (`src/robot/ssh_manager.py`, zero shell injection, base64 JSON stdin payloads, `py_compile` preflight validation, 3x retry + `stderr` logging):
     * **Wi-Fi / Network & Active IP:** Hardened STA mode (`nmcli con add` + `autoconnect-priority 10` + `powersave 2` + `wifi.service` disable so Wi-Fi survives reboots) + live `wlan0`/`eth0`/`eth1` interface inspector and 1-click IP switch (`PUT /api/robots/{id}/active-ip`).
     * **Voice & Audio:** Live WonderEcho Pro ALSA Card 2 speaker/mic sliders, quick TTS speech test, and 1-click persistent 2-stage udev rules installer (`/dev/wonderecho` vs `/dev/ldlidar`).
     * **Linux Credentials:** `sudo chpasswd` over stdin for `pi`/`root` with encrypted Postgres sync.
     * **Robot Mechanics:** Targets active ROS 1 (`puppypi`) or ROS 2 (`puppypi_ros2`) `puppy.py` (`with_arm` / `x_shift`) + `servo_deviation.json` trims.
     * **ROS 1 ↔ ROS 2 Dual-Mode Switcher, Persistent Auto-Boot & AI Voice Language:** Side-by-side ROS 1 Noetic vs ROS 2 Humble comparison (`/api/robots/ros-comparison`), `ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION` / `ASR_LANGUAGE` controls, reversible persistent ROS 2 auto-boot across power-cycles (`start_node_ros2.service` + Docker restart policies), automatic full ROS 2 Humble bringup launch (`ros_robot_controller`, `puppy_control`, `usb_cam`, `web_video_server`, `rosbridge_websocket`, deduplicated `ldlidar_stl_ros2_node`), and auto-type ROSBridge telemetry reconnection with a `6.0s` silence watchdog.
     * **Service & Power Control:** Restart ROS, reboot, or shutdown safely.
   * **Kaizen PostgreSQL 18 Admin & File Storage** (`src/api/routes_admin.py`): encrypted OpenRouter key management (`cryptography` Fernet) with inline **`Test Key`** verification (`/api/admin/openrouter/test-key`), searchable/sortable/categorized **Live OpenRouter Model Picker** (500+ live models with per-1M pricing & context windows), live PostgreSQL 18 + Neo4j health & schema stats, and deduplicated `stored_files` archive.

## Backend Architecture (`src/`)

* **`src/robot/`:**
  * `discovery.py`: 3-tier async LAN auto-discovery (`asyncio.Semaphore(64)`) probing saved Postgres IPs, TCP `9090` (ROSBridge), TCP `8080` (`web_video_server`), TCP `22` (SSH banner, excluding Windows false positives), and unicast UDP `9027` (`LOBOT_NET_DISCOVER` -> `PUPPY_1.0:<SN>`).
  * `ros_profiles.py`: Authoritative ROS 1 Noetic vs ROS 2 Humble topic, service, message-type, camera-topic, and feature comparison definitions.
  * `rosbridge_proxy.py`: Dual-mode ROSBridge v2 translator, `puppy.py`-exact velocity/pose/gait/servo clampers, `DeadManWatchdog` (0.5s timeout), automatic Hiwonder CV vision mode activator + heartbeat manager, out-of-band `trigger_estop`, `/scan` ingestion bridge, and async literal-URL MJPEG/snapshot relay.
  * `ssh_manager.py`: stdlib `pty` (`TIOCSCTTY`) + `openssh-client` runner for HBOM/SBOM CycloneDX 1.6 collection, `ip -j -br addr` / `nmcli` network interface collection, hardened STA Wi-Fi provisioning, ROS 1 ↔ ROS 2 bringup switching, and validated remote configuration.
  * `update_checker.py`: Concurrent PyPI version checker (3x retry + `stderr` logging), ROS lifecycle & `apt --upgradable` analyzer, and 9-item Hardware & Feature Readiness Matrix.
* **`src/lidar/`:** LD19 47-byte CRC-8 parser, filters, RANSAC/DBSCAN mapping, log-odds occupancy & change detection, dark-zone focus queue, `small_gicp`/SVD ICP registration, `trimesh` 3D extrusion & camera raycast, and simulator.
* **`src/vision/` & `src/enrichment/`:** CLAHE + `zxing-cpp` barcode/DataMatrix preprocessing, OpenRouter multi-model VLM + dual-model consensus, and web-grounded Direct Research Enrichment (`perplexity/sonar-pro`).
* **`src/db/` & `src/graph/` & `src/twin/`:** PostgreSQL 18 + `pgvector` repositories (`repository.py`, `robot_store.py`, `crypto.py`), Neo4j 5 sync (`neo4j_store.py`), completeness metrics, and CycloneDX 1.6 / DEXPI / Cypher / DXF / GLB / PLY exporters.

## Dependencies

* **Backend (`requirements.txt`, Python 3.13):** `fastapi`, `uvicorn[standard]`, `websockets>=15.0`, `python-multipart`, `pydantic`, `pydantic-settings`, `psycopg[binary]`, `psycopg-pool`, `pgvector`, `cryptography>=46.0`, `neo4j>=6.0`, `httpx`, `httpx2>=2.0`, `numpy`, `scikit-learn`, `shapely`, `trimesh>=5.0`, `ezdxf`, `opencv-python-headless>=5.0`, `zxing-cpp>=3.0`, `pyserial`, **`edge-tts>=7.0`**, **`piper-tts>=1.2`**, **`faster-whisper>=1.1.0,<2.0.0`**, `pytest>=9.0`, `pytest-asyncio>=1.0` (plus `openssh-client`, **`espeak-ng`**, **`ffmpeg`** anti-clipping audio conditioner, and optional `small-gicp` in `Dockerfile.backend`; persistent **`twinscan_models`** Docker volume at `/app/data/models` for cached ONNX vision, Piper TTS & Whisper STT weights).
* **Frontend (`frontend/package.json`, Node 22):** `next@^16.4.6`, `react@^19.3.1`, `react-dom@^19.3.1`, `typescript@^5.9.3`, `tailwindcss@^4.3.5`, `@tailwindcss/postcss@^4.3.5`, `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react@^1.79.0`, `@radix-ui/react-slider`, `@radix-ui/react-slot`, `@radix-ui/react-switch`, `@radix-ui/react-tabs`, `three@^0.187.0`, `@babylonjs/core@^9.37.2`, `@xyflow/react@^13.0.3`.

## Quick Start (Docker Compose)

1. Copy `.env.example` to `.env` and configure `OPENROUTER_API_KEY` (or manage keys in `/config`):
   ```bash
   cp .env.example .env
   ```
2. Build and launch **PostgreSQL 18 (`pgvector`)**, **Neo4j 5**, **FastAPI Backend (Python 3.13)**, and **Next.js 16 Eigenia Command Center**:
   ```bash
   docker compose up -d --build
   ```
3. Open the platform:
   * **Eigenia Command Center UI:** http://localhost:3000 (`/`, `/twin`, `/control`, `/catalog`, `/graph`, `/config`)
   * **FastAPI OpenAPI Docs:** http://localhost:8000/docs
   * **Neo4j Browser:** http://localhost:7474 (`neo4j` / `twinscan_graph_secret`)
   * **PostgreSQL 18 + `pgvector`:** `localhost:5438` (`twinscan` / `twinscan_dev_secret`)

## Connecting the LD19 LiDAR on macOS (Optional USB Bridge)

When attaching an LD19 USB-UART adapter directly to macOS (Docker Desktop cannot pass `/dev/cu.usbserial-*` into Linux containers), run the host bridge:

```bash
.venv/bin/python -m src.bridge.mac_serial_bridge --ws-url ws://localhost:8000/api/lidar/ingest
```

When the LD19 is attached to **PuppyPi**, live `/scan` frames stream directly from the robot over LAN/Wi-Fi via the ROSBridge proxy.

## Running Tests & Local Builds

```bash
# Backend unit & integration tests (160 tests, 0 warnings)
.venv/bin/pytest -v

# Frontend TypeScript check & production build (Next.js 16 + React 19 + Tailwind 4)
cd frontend && npm run typecheck && npm run build
```
