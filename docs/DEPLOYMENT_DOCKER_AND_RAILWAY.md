# Deploying Eigenia TwinScan Studio: macOS, Windows 11 (WSL 2), Linux / Pi 5, and Railway

Eigenia TwinScan Studio runs as a portable Docker Compose stack (`docker-compose.yml`) with **PostgreSQL 18 (`pgvector`)**, **Neo4j 5 Community**, the **FastAPI backend (`Dockerfile.backend`)**, the **Next.js 16 frontend (`Dockerfile.frontend`)**, and an optional **`openclaw-gateway`** sidecar (`--profile openclaw`).

All operational secrets live encrypted inside PostgreSQL 18 via `/config` rather than in `.env` files or cloud environment dashboards, so moving the stack between a MacBook, a Windows 11 workstation, a Raspberry Pi 5 server, or Railway takes a single database dump.

---

## 1. Database-First Secrets Architecture

TwinScan separates **container bootstrap wiring** (how containers find PostgreSQL and Neo4j on the internal Docker network) from **application and hardware secrets** (API keys, robot SSH passwords, and agent tokens).

Every secret saved in **`/config`** (`PUT /api/admin/settings`) or registered on a robot (`src/db/robot_store.py`) is encrypted at rest using Fernet symmetric encryption (`src/db/crypto.py`) and masked before leaving the API. Changes hot-reload into the running backend with no container restart.

| Setting / Secret | Where It Lives | Required? | Notes |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Container bootstrap env | Yes | Points `backend` at `pgvector/pgvector:pg18` |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Container bootstrap env | Optional | Connects `backend` to `neo4j:5-community` (auto-falls back to in-memory graph if omitted) |
| `TWINSCAN_ENCRYPTION_KEY` | Container bootstrap env | Recommended | Single master key used by `SecretCipher` (`src/db/crypto.py`). Keep the same value when migrating a Postgres dump to another machine. |
| `TWINSCAN_ADMIN_TOKEN` | Container bootstrap env | Recommended on cloud | Requires `X-Admin-Token` header on `/api/admin/*` writes |
| `openrouter_api_key` | **PostgreSQL 18 (Fernet-encrypted via `/config`)** | Optional | Used for OpenRouter vision, chat, and Lab Architect |
| Robot SSH passwords (`pi@192.168.1.119`) | **PostgreSQL 18 (Fernet-encrypted via `robots` table)** | Per robot | Used by stdlib PTY SSH diagnostics, ROS switching, and voice audio |
| `openclaw_gateway_url` | **PostgreSQL 18 (via `/config`)** | Optional | Default `http://openclaw-gateway:18789` on Docker network |
| `openclaw_gateway_token` | **PostgreSQL 18 (Fernet-encrypted via `/config`)** | Optional | Gateway auth token; zero copy in Railway Variables or `.env` |
| `openclaw_mcp_bearer_token` | **PostgreSQL 18 (Fernet-encrypted via `/config`)** | Recommended on cloud | Enforces `Authorization: Bearer <token>` on `POST /api/agent/mcp` and `POST /api/agent/execute` |
| `openclaw_telegram_bot_token` | **PostgreSQL 18 (Fernet-encrypted via `/config`)** | Optional | Stored encrypted in Postgres for OpenClaw chat relay |
| `openclaw_discord_bot_token` | **PostgreSQL 18 (Fernet-encrypted via `/config`)** | Optional | Stored encrypted in Postgres for OpenClaw Discord relay |

> **Important for migrations:** If you set `TWINSCAN_ENCRYPTION_KEY` explicitly before storing secrets in `/config`, reuse that exact key on the destination host so existing encrypted rows decrypt immediately after `psql` restore. If you change the key on a new host, simply re-enter your tokens once in `/config`.

---

## 2. macOS (Apple Silicon & Intel) + Docker Desktop

### Prerequisites
- macOS 13+ with **Docker Desktop for Mac** installed and running (allocate at least 4 GB RAM and 20 GB disk in Docker Desktop Settings).
- Git (`xcode-select --install`).

### Standard 4-Container Stack
```bash
git clone https://github.com/Planet9V/twinscan-studio.git
cd twinscan-studio
cp .env.example .env
docker compose up -d --build
```

### Including the Optional Portable OpenClaw Gateway Sidecar
```bash
docker compose --profile openclaw up -d --build
```

Verify the stack:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
curl -s http://localhost:8000/health | python3 -m json.tool
```

Open:
- **Studio UI:** `http://localhost:3000`
- **Maker Showcase:** `http://localhost:3000/welcome`
- **Secrets & Admin Config:** `http://localhost:3000/config`
- **Portable HTTP MCP Endpoint:** `http://localhost:8000/api/agent/mcp` (inside Docker: `http://backend:8000/api/agent/mcp`)

> **Direct macOS USB LiDAR note:** Docker Desktop on macOS cannot attach `/dev/cu.usbserial-*` directly into Linux containers. When the LD19 LiDAR is plugged into PuppyPi Pro over Wi-Fi, no host bridge is needed; if you plug an LD19 directly into your MacBook, run `.venv/bin/python -m src.bridge.mac_serial_bridge --ws-url ws://localhost:8000/api/lidar/ingest`.

---

## 3. Windows 11 + WSL 2 (Ubuntu) + Docker Desktop

Running TwinScan on Windows 11 works best through **WSL 2 (Ubuntu)** with Docker Desktop's WSL 2 engine.

### Step 1: Install WSL 2 and Docker Desktop
Run in an elevated **PowerShell** terminal:
```powershell
wsl --install -d Ubuntu
```
Reboot if prompted, finish creating your Ubuntu username/password, then install **Docker Desktop for Windows** and verify in **Settings -> Resources -> WSL Integration** that integration is enabled for your `Ubuntu` distro.

### Step 2: Clone Inside WSL ext4 (Never `/mnt/c/...`)
Open the **Ubuntu (WSL 2)** terminal and clone inside the native Linux filesystem (`~/twinscan-studio`). Do **not** clone under `/mnt/c/Users/...` — cross-filesystem NTFS binds slow down Docker builds, Next.js hot builds, and file watchers significantly.

```bash
cd ~
git clone https://github.com/Planet9V/twinscan-studio.git
cd ~/twinscan-studio
cp .env.example .env

# Start core 4-container stack
docker compose up -d --build

# Or start with the optional OpenClaw gateway profile
docker compose --profile openclaw up -d --build
```

Verify from Ubuntu WSL or Windows PowerShell:
```bash
curl -s http://localhost:8000/health
```

### Step 3: Verify LAN Reachability to PuppyPi Pro (`192.168.1.119`)
Containers inside WSL 2 Docker reach home-LAN robots via outbound TCP (`:22` SSH, `:8080` MJPEG, `:9090` ROSBridge) through Windows' network stack:
```bash
# Test from inside the running backend container on Windows 11 WSL 2
docker exec eigenia-twinscan-backend python3 -c "
import socket
for port in (22, 8080, 9090):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(('192.168.1.119', port))
        print(f'192.168.1.119:{port} OPEN')
    except Exception as e:
        print(f'192.168.1.119:{port} FAIL ({e})')
    finally:
        s.close()
"
```
If Windows Defender Firewall prompts on first run, allow **Private networks** for Docker Desktop / `vEthernet (WSL)`.

### Step 4: Migrate Everything From MacBook to Windows 11 (`pg_dump` -> `psql`)
Because rooms, 3D scene panels, JPEG textures, PBR normal maps, `.glb` files, Spatial Memory sightings, known-person face vectors, inventory, blueprints, and Fernet-encrypted secrets all live in PostgreSQL 18, migrating your MacBook state to Windows 11 takes two commands:

**1. Export on MacBook:**
```bash
docker exec eigenia-twinscan-pg18 pg_dump \
  -U twinscan \
  -d eigenia_twinscan \
  --clean --if-exists --no-owner \
  > twinscan_backup.sql
```
Copy `twinscan_backup.sql` (and your `TWINSCAN_ENCRYPTION_KEY` value if set) to your Windows 11 WSL home directory (for example via `scp`, USB drive, or local file share).

**2. Restore on Windows 11 (Ubuntu WSL 2):**
```bash
cd ~/twinscan-studio
# Ensure Postgres is up first
docker compose up -d postgres

# Restore the full database (rooms, 3D panels, stored_files, sightings, encrypted settings)
docker exec -i eigenia-twinscan-pg18 psql \
  -U twinscan \
  -d eigenia_twinscan \
  < ~/twinscan_backup.sql

# Start the rest of the stack
docker compose up -d --build
```
*(Optional: if you also want to avoid re-downloading cached ONNX / Piper / Whisper weights in `twinscan_models`, copy `/app/data/models` or let the backend re-cache them automatically on first use.)*

---

## 4. Linux Server or 2nd Raspberry Pi 5 (ARM64 / x86_64)

Both `Dockerfile.backend` (`python:3.13-slim`) and `Dockerfile.frontend` (`node:22-slim`), along with `pgvector/pgvector:pg18` and `neo4j:5-community`, publish multi-arch `linux/amd64` and `linux/arm64` images.

### Install Docker Engine + Compose v2 (Debian / Ubuntu / Raspberry Pi OS 64-bit)
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

### Deploy the Stack
```bash
git clone https://github.com/Planet9V/twinscan-studio.git
cd twinscan-studio
cp .env.example .env

# Set the host LAN IP so browsers on other devices reach the backend API & WebSockets
export NEXT_PUBLIC_API_URL="http://$(hostname -I | awk '{print $1}'):8000"
export NEXT_PUBLIC_WS_URL="ws://$(hostname -I | awk '{print $1}'):8000"

docker compose up -d --build
# Optional: include OpenClaw gateway
docker compose --profile openclaw up -d --build
```

On a **2nd Raspberry Pi 5 (8 GB)** acting as a dedicated lab server, ensure `PSU_MAX_CURRENT=5000` is set in EEPROM (`sudo rpi-eeprom-config`) and active cooling is installed before running continuous YOLO11n + Depth Anything V2 workloads.

---

## 5. Railway (Cloud Docker Deployment)

You can deploy TwinScan Studio to **Railway** as a 4-service (or 5-service with OpenClaw) Docker project with **zero application secrets stored in Railway Variables**.

### Service Blueprint on Railway

| Railway Service | Image / Dockerfile | Persistent Volume | Internal / Public Port | Required Bootstrap Variables |
| :--- | :--- | :--- | :--- | :--- |
| `postgres` | `pgvector/pgvector:pg18` | `/var/lib/postgresql` | Internal `5432` | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| `neo4j` *(optional)* | `neo4j:5-community` | `/data` | Internal `7687` | `NEO4J_AUTH=neo4j/<strong_password>`, `NEO4J_PLUGINS=[]` |
| `backend` | `Dockerfile.backend` | `/app/data` (models & cache) | Public `8000` | `DATABASE_URL=${{postgres.DATABASE_URL}}`, `NEO4J_URI=bolt://neo4j.railway.internal:7687`, `TWINSCAN_ENCRYPTION_KEY`, `TWINSCAN_ADMIN_TOKEN` |
| `frontend` | `Dockerfile.frontend` | None | Public `3000` | Build args & env: `NEXT_PUBLIC_API_URL=https://<backend-domain>`, `NEXT_PUBLIC_WS_URL=wss://<backend-domain>` |
| `openclaw-gateway` *(optional)* | OpenClaw Docker image | `/home/node/.openclaw` | Internal `18789` | `TWINSCAN_API_URL=http://backend.railway.internal:8000`, `TWINSCAN_MCP_URL=http://backend.railway.internal:8000/api/agent/mcp` |

### Hardening a Cloud Railway Deployment
Never expose an unauthenticated robot control API to the public internet:
1. Set **`TWINSCAN_ADMIN_TOKEN`** and a 32-byte random **`TWINSCAN_ENCRYPTION_KEY`** in the `backend` service bootstrap variables.
2. Open `https://<frontend-domain>/config`, enter your admin token, and configure all runtime secrets inside PostgreSQL 18:
   - Click **Generate Strong Token** for **`openclaw_mcp_bearer_token`** and save it to PostgreSQL. Once saved, `POST /api/agent/mcp` and `POST /api/agent/execute` reject requests without `Authorization: Bearer <token>` (`HTTP 401`).
   - Add your optional `openrouter_api_key`, `openclaw_gateway_token`, and Telegram/Discord bot tokens in `/config` — none of them ever sit in Railway's environment panel.

### Bridging a Cloud Railway Backend Back to a Home-LAN PuppyPi Pro (Tailscale)
Do **not** port-forward SSH (`:22`), `web_video_server` (`:8080`), or `rosbridge_websocket` (`:9090`) on your home router. Instead, connect the robot and cloud backend over a private **Tailscale** tailnet:

1. **On PuppyPi Pro (or your 2nd Pi 5 on home LAN):**
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --ssh=false
   tailscale ip -4   # Example: 100.88.14.22
   ```
   *(Alternatively, advertise your home subnet `192.168.1.0/24` from a Pi 5 Tailscale subnet router with `sudo tailscale up --advertise-routes=192.168.1.0/24`.)*
2. **In your Railway `backend` service:** Run Tailscale in userspace networking mode (`tailscaled --tun=userspace-networking` with an ephemeral auth key or Tailscale exit/SOCKS proxy) so the backend container can dial PuppyPi's private `100.x.y.z` Tailscale IP on `:22`, `:8080`, and `:9090`.
3. **In TwinScan `/control` or `/catalog`:** Register or switch the active robot IP to PuppyPi's Tailscale IP (`100.88.14.22`). Live `/scan`, FPV snapshots, PMIC diagnostics, and E-STOP then flow end-to-end encrypted through WireGuard with zero open router ports.
