"""PostgreSQL 18 and in-memory robot fleet BOM/SBOM store with Fernet SSH credential encryption.

Implements ``RobotStoreProtocol``, ``InMemoryRobotStore``, and ``PostgresRobotStore``
backed by ``psycopg_pool.ConnectionPool`` and ``SecretCipher`` from ``src.db.crypto``.
Manages three normalized tables: ``robots``, ``robot_devices``, and
``robot_sbom_packages``. No sample robots are seeded automatically.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Protocol, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.db.crypto import SecretCipher


class RobotStoreProtocol(Protocol):
    """Unified storage interface for discovered robots, hardware BOM, and software SBOM."""

    def initialize(self) -> None:
        """Create schema tables if needed (never seeds synthetic robots)."""
        ...

    def close(self) -> None:
        """Release underlying connection pool resources."""
        ...

    def upsert_robot(
        self,
        robot_data: dict[str, Any],
        ssh_password: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert or update a robot record by ID or IP address, encrypting SSH password."""
        ...

    def list_robots(self) -> List[dict[str, Any]]:
        """List all saved robots without exposing encrypted or plaintext SSH passwords."""
        ...

    def get_robot(self, robot_id: str) -> Optional[dict[str, Any]]:
        """Return a single robot record by ID without exposing SSH password."""
        ...

    def get_robot_by_ip(self, ip_address: str) -> Optional[dict[str, Any]]:
        """Return a single robot record by IP address without exposing SSH password."""
        ...

    def get_robot_ssh_password(self, robot_id: str) -> str:
        """Return the decrypted SSH password for ``robot_id`` or empty string if unset."""
        ...

    def update_robot_credentials(
        self,
        robot_id: str,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update SSH username and/or Fernet-encrypted SSH password for a robot."""
        ...

    def save_robot_catalogue(
        self,
        robot_id: str,
        devices: Sequence[dict[str, Any]],
        sbom_packages: Sequence[dict[str, Any]],
        hbom_sbom: dict[str, Any],
        robot_updates: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Replace a robot's hardware BOM devices, software SBOM packages, and CycloneDX JSONB."""
        ...

    def list_robot_devices(self, robot_id: str) -> List[dict[str, Any]]:
        """List hardware BOM devices catalogued for a robot."""
        ...

    def list_robot_sbom(
        self,
        robot_id: str,
        layer: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """List software SBOM packages catalogued for a robot with optional filtering."""
        ...

    def delete_robot(self, robot_id: str) -> bool:
        """Delete a robot and cascade-remove its devices and SBOM entries."""
        ...

    def record_update_job(self, robot_id: str, job: dict[str, Any]) -> dict[str, Any]:
        """Persist a robot software update or smoke-test job record."""
        ...

    def list_update_jobs(self, robot_id: str, limit: int = 25) -> List[dict[str, Any]]:
        """List recent software update and smoke-test jobs for a robot."""
        ...


def _sanitize_robot_record(row: dict[str, Any]) -> dict[str, Any]:
    """Strip secret columns and normalize timestamps to ISO-8601 strings."""
    out = dict(row)
    out.pop("ssh_password_enc", None)
    out.pop("ssh_password", None)
    for key in ("last_seen_at", "created_at", "updated_at"):
        val = out.get(key)
        if isinstance(val, datetime):
            out[key] = val.isoformat()
    return out


class InMemoryRobotStore:
    """In-memory robot fleet store matching PostgreSQL semantics for pytest and offline runs."""

    def __init__(self, encryption_key: str = "") -> None:
        """Initialize empty in-memory tables and Fernet cipher.

        Args:
            encryption_key: Passphrase or Fernet key used to encrypt SSH passwords.
        """
        self._cipher = SecretCipher(encryption_key)
        self._robots: dict[str, dict[str, Any]] = {}
        self._devices: dict[str, List[dict[str, Any]]] = {}
        self._sbom: dict[str, List[dict[str, Any]]] = {}
        self._update_jobs: dict[str, List[dict[str, Any]]] = {}

    def initialize(self) -> None:
        """Initialize the in-memory store (intentionally seeds no robots)."""
        return None

    def close(self) -> None:
        """No-op close for in-memory store."""
        return None

    def upsert_robot(
        self,
        robot_data: dict[str, Any],
        ssh_password: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert or update a robot by ID or IP address.

        Args:
            robot_data: Robot metadata fields (must include ``ip_address`` when creating).
            ssh_password: Optional plaintext SSH password to encrypt and persist.

        Returns:
            Sanitized robot record dictionary without SSH password fields.
        """
        now = datetime.now(timezone.utc).isoformat()
        existing: Optional[dict[str, Any]] = None
        rid = robot_data.get("id")
        ip_addr = str(robot_data.get("ip_address") or "").strip()

        if rid and rid in self._robots:
            existing = self._robots[rid]
        elif ip_addr:
            for candidate in self._robots.values():
                if candidate["ip_address"] == ip_addr:
                    existing = candidate
                    rid = candidate["id"]
                    break

        if existing is None:
            if not ip_addr:
                raise ValueError("ip_address is required to register a robot")
            rid = str(rid or uuid.uuid4())
            enc_pw = self._cipher.encrypt(ssh_password) if ssh_password else ""
            rec: dict[str, Any] = {
                "id": rid,
                "name": str(robot_data.get("name") or f"PuppyPi ({ip_addr})"),
                "model": str(robot_data.get("model") or "Hiwonder PuppyPi Pro"),
                "serial_number": robot_data.get("serial_number"),
                "ip_address": ip_addr,
                "mac_address": robot_data.get("mac_address"),
                "ssh_user": str(robot_data.get("ssh_user") or "pi"),
                "ssh_password_enc": enc_pw,
                "rosbridge_port": int(robot_data.get("rosbridge_port") or 9090),
                "video_port": int(robot_data.get("video_port") or 8080),
                "active_ros_distro": robot_data.get("active_ros_distro"),
                "status": str(robot_data.get("status") or "discovered"),
                "battery_mv": robot_data.get("battery_mv"),
                "cpu_temp_c": robot_data.get("cpu_temp_c"),
                "capabilities": dict(robot_data.get("capabilities") or {}),
                "hbom_sbom": dict(robot_data.get("hbom_sbom") or {}),
                "last_seen_at": robot_data.get("last_seen_at") or now,
                "created_at": now,
                "updated_at": now,
            }
            self._robots[rid] = rec
            self._devices.setdefault(rid, [])
            self._sbom.setdefault(rid, [])
            return _sanitize_robot_record(rec)

        updatable = (
            "name",
            "model",
            "serial_number",
            "ip_address",
            "mac_address",
            "ssh_user",
            "rosbridge_port",
            "video_port",
            "active_ros_distro",
            "status",
            "battery_mv",
            "cpu_temp_c",
            "last_seen_at",
        )
        for field in updatable:
            if field in robot_data and robot_data[field] is not None:
                existing[field] = robot_data[field]
        if "capabilities" in robot_data and isinstance(robot_data["capabilities"], dict):
            existing["capabilities"] = {**existing.get("capabilities", {}), **robot_data["capabilities"]}
        if "hbom_sbom" in robot_data and isinstance(robot_data["hbom_sbom"], dict):
            existing["hbom_sbom"] = dict(robot_data["hbom_sbom"])
        if ssh_password is not None:
            existing["ssh_password_enc"] = self._cipher.encrypt(ssh_password)
        existing["updated_at"] = now
        return _sanitize_robot_record(existing)

    def list_robots(self) -> List[dict[str, Any]]:
        """List all registered robots ordered by creation time.

        Returns:
            List of sanitized robot dictionaries.
        """
        rows = sorted(self._robots.values(), key=lambda r: str(r.get("created_at") or ""))
        return [_sanitize_robot_record(r) for r in rows]

    def get_robot(self, robot_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a robot by ID.

        Args:
            robot_id: Unique robot UUID string.

        Returns:
            Sanitized robot dictionary or ``None`` if not found.
        """
        rec = self._robots.get(robot_id)
        return _sanitize_robot_record(rec) if rec else None

    def get_robot_by_ip(self, ip_address: str) -> Optional[dict[str, Any]]:
        """Retrieve a robot by IP address.

        Args:
            ip_address: IPv4 address string.

        Returns:
            Sanitized robot dictionary or ``None`` if not found.
        """
        for rec in self._robots.values():
            if rec["ip_address"] == ip_address:
                return _sanitize_robot_record(rec)
        return None

    def get_robot_ssh_password(self, robot_id: str) -> str:
        """Decrypt and return the stored SSH password for a robot.

        Args:
            robot_id: Unique robot UUID string.

        Returns:
            Decrypted plaintext SSH password or empty string.
        """
        rec = self._robots.get(robot_id)
        if not rec:
            return ""
        return self._cipher.decrypt(str(rec.get("ssh_password_enc") or ""))

    def update_robot_credentials(
        self,
        robot_id: str,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update SSH credentials for an existing robot.

        Args:
            robot_id: Unique robot UUID string.
            ssh_user: Optional new SSH username.
            ssh_password: Optional new plaintext SSH password (encrypted at rest).

        Returns:
            Updated sanitized robot dictionary or ``None`` if not found.
        """
        rec = self._robots.get(robot_id)
        if not rec:
            return None
        if ssh_user is not None and ssh_user.strip():
            rec["ssh_user"] = ssh_user.strip()
        if ssh_password is not None:
            rec["ssh_password_enc"] = self._cipher.encrypt(ssh_password)
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        return _sanitize_robot_record(rec)

    def save_robot_catalogue(
        self,
        robot_id: str,
        devices: Sequence[dict[str, Any]],
        sbom_packages: Sequence[dict[str, Any]],
        hbom_sbom: dict[str, Any],
        robot_updates: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Replace hardware BOM, software SBOM, and CycloneDX JSONB for a robot.

        Args:
            robot_id: Unique robot UUID string.
            devices: Hardware device BOM dictionaries.
            sbom_packages: Software SBOM package dictionaries.
            hbom_sbom: CycloneDX 1.6 JSON document.
            robot_updates: Optional metadata updates for the parent robot row.

        Returns:
            Updated sanitized robot dictionary or ``None`` if robot does not exist.
        """
        rec = self._robots.get(robot_id)
        if not rec:
            return None
        now = datetime.now(timezone.utc).isoformat()
        stored_devices: List[dict[str, Any]] = []
        for dev in devices:
            stored_devices.append(
                {
                    "id": str(dev.get("id") or uuid.uuid4()),
                    "robot_id": robot_id,
                    "subsystem": str(dev.get("subsystem") or "hardware"),
                    "make": str(dev.get("make") or "Unknown"),
                    "model": str(dev.get("model") or "Unknown"),
                    "bus_type": str(dev.get("bus_type") or "unknown"),
                    "device_path": dev.get("device_path"),
                    "usb_id": dev.get("usb_id"),
                    "status": str(dev.get("status") or "online"),
                    "metadata": dict(dev.get("metadata") or {}),
                }
            )
        stored_sbom: List[dict[str, Any]] = []
        for pkg in sbom_packages:
            stored_sbom.append(
                {
                    "id": str(pkg.get("id") or uuid.uuid4()),
                    "robot_id": robot_id,
                    "layer": str(pkg.get("layer") or "host_dpkg"),
                    "name": str(pkg.get("name") or ""),
                    "version": str(pkg.get("version") or ""),
                    "purl": pkg.get("purl"),
                }
            )
        self._devices[robot_id] = stored_devices
        self._sbom[robot_id] = stored_sbom
        rec["hbom_sbom"] = dict(hbom_sbom)
        rec["last_seen_at"] = now
        rec["updated_at"] = now
        for k, v in (robot_updates or {}).items():
            if v is not None and k in rec and k not in {"id", "ssh_password_enc"}:
                if k == "capabilities" and isinstance(v, dict):
                    rec["capabilities"] = {**rec.get("capabilities", {}), **v}
                else:
                    rec[k] = v
        return _sanitize_robot_record(rec)

    def list_robot_devices(self, robot_id: str) -> List[dict[str, Any]]:
        """List catalogued hardware devices for a robot.

        Args:
            robot_id: Unique robot UUID string.

        Returns:
            List of hardware device dictionaries.
        """
        return [dict(d) for d in self._devices.get(robot_id, [])]

    def list_robot_sbom(
        self,
        robot_id: str,
        layer: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """List catalogued software SBOM packages for a robot.

        Args:
            robot_id: Unique robot UUID string.
            layer: Optional SBOM layer filter (e.g. ``host_dpkg``, ``ros1_pip``).
            query: Optional case-insensitive substring filter on package name or purl.

        Returns:
            List of SBOM package dictionaries.
        """
        items = list(self._sbom.get(robot_id, []))
        if layer:
            items = [p for p in items if p["layer"] == layer]
        if query:
            q = query.lower().strip()
            items = [
                p for p in items
                if q in p["name"].lower() or q in str(p.get("purl") or "").lower()
            ]
        return [dict(p) for p in items]

    def delete_robot(self, robot_id: str) -> bool:
        """Delete a robot and its catalogued devices, SBOM entries, and update jobs.

        Args:
            robot_id: Unique robot UUID string.

        Returns:
            ``True`` when the robot existed and was deleted, else ``False``.
        """
        removed = self._robots.pop(robot_id, None)
        self._devices.pop(robot_id, None)
        self._sbom.pop(robot_id, None)
        self._update_jobs.pop(robot_id, None)
        return removed is not None

    def record_update_job(self, robot_id: str, job: dict[str, Any]) -> dict[str, Any]:
        """Record a robot software update, rollback, or smoke-test job in memory.

        Args:
            robot_id: Target robot UUID string.
            job: Job payload dictionary (track, action, status, packages, rollback_tag, etc.).

        Returns:
            Stored ``RobotUpdateJobRecord`` dictionary.
        """
        rec = {
            "id": str(job.get("id") or uuid.uuid4()),
            "robot_id": robot_id,
            "track": str(job.get("track") or "ros_pip"),
            "action": str(job.get("action") or "dry_run"),
            "status": str(job.get("status") or "ok"),
            "packages": list(job.get("packages") or []),
            "rollback_tag": job.get("rollback_tag"),
            "smoke_tests": job.get("smoke_tests"),
            "stdout_tail": str(job.get("stdout_tail") or "")[-4000:],
            "stderr_tail": str(job.get("stderr_tail") or "")[-4000:],
            "created_at": str(job.get("created_at") or datetime.now(timezone.utc).isoformat()),
        }
        self._update_jobs.setdefault(robot_id, []).insert(0, rec)
        return dict(rec)

    def list_update_jobs(self, robot_id: str, limit: int = 25) -> List[dict[str, Any]]:
        """List recent software update jobs for a robot ordered newest first.

        Args:
            robot_id: Target robot UUID string.
            limit: Maximum records to return.

        Returns:
            List of ``RobotUpdateJobRecord`` dictionaries.
        """
        return [dict(j) for j in self._update_jobs.get(robot_id, [])[: max(1, int(limit))]]


class PostgresRobotStore:
    """Pooled PostgreSQL 18 robot fleet BOM/SBOM store with Fernet SSH credential encryption."""

    def __init__(
        self,
        database_url: str,
        encryption_key: str = "",
        max_retries: int = 3,
    ) -> None:
        """Configure the PostgreSQL robot store.

        Args:
            database_url: PostgreSQL connection URI.
            encryption_key: Fernet key or passphrase for encrypting SSH passwords.
            max_retries: Maximum retry attempts on transient database errors.
        """
        self.database_url = database_url
        self._cipher = SecretCipher(encryption_key)
        self.max_retries = max_retries
        self._pool: Optional[ConnectionPool] = None

    def _ensure_pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                conninfo=self.database_url,
                min_size=1,
                max_size=8,
                kwargs={"row_factory": dict_row},
                open=True,
            )
        return self._pool

    def _with_retry(self, fn: Any) -> Any:
        """Execute a database callable with try/except, stderr logging, and 3x retry."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                sys.stderr.write(
                    f"[robot_store] PostgreSQL operation failed (attempt {attempt}/{self.max_retries}): {exc}\n"
                )
                if attempt < self.max_retries:
                    time.sleep(min(0.4 * attempt, 2.0))
        assert last_exc is not None
        raise last_exc

    def initialize(self) -> None:
        """Create ``robots``, ``robot_devices``, and ``robot_sbom_packages`` tables."""
        ddl = """
        CREATE TABLE IF NOT EXISTS robots (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT 'Hiwonder PuppyPi Pro',
            serial_number TEXT,
            ip_address TEXT NOT NULL UNIQUE,
            mac_address TEXT,
            ssh_user TEXT NOT NULL DEFAULT 'pi',
            ssh_password_enc TEXT NOT NULL DEFAULT '',
            rosbridge_port INTEGER NOT NULL DEFAULT 9090,
            video_port INTEGER NOT NULL DEFAULT 8080,
            active_ros_distro TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            battery_mv INTEGER,
            cpu_temp_c DOUBLE PRECISION,
            capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
            hbom_sbom JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_seen_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS robot_devices (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            subsystem TEXT NOT NULL,
            make TEXT NOT NULL DEFAULT 'Unknown',
            model TEXT NOT NULL DEFAULT 'Unknown',
            bus_type TEXT NOT NULL DEFAULT 'unknown',
            device_path TEXT,
            usb_id TEXT,
            status TEXT NOT NULL DEFAULT 'online',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_robot_devices_robot_id ON robot_devices(robot_id);

        CREATE TABLE IF NOT EXISTS robot_sbom_packages (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            layer TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '',
            purl TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_robot_sbom_robot_layer ON robot_sbom_packages(robot_id, layer);

        CREATE TABLE IF NOT EXISTS robot_update_jobs (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            track TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            packages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            rollback_tag TEXT,
            smoke_tests_json JSONB,
            stdout_tail TEXT NOT NULL DEFAULT '',
            stderr_tail TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_robot_update_jobs_robot ON robot_update_jobs(robot_id, created_at DESC);
        """

        def _init() -> None:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(ddl)
                conn.commit()
            self._ensure_pool()

        self._with_retry(_init)

    def close(self) -> None:
        """Close the PostgreSQL connection pool cleanly."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def upsert_robot(
        self,
        robot_data: dict[str, Any],
        ssh_password: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert or update a robot record in PostgreSQL, encrypting SSH password with Fernet.

        Args:
            robot_data: Robot metadata dictionary.
            ssh_password: Optional plaintext SSH password to encrypt and store.

        Returns:
            Sanitized robot dictionary without SSH password columns.
        """
        ip_addr = str(robot_data.get("ip_address") or "").strip()
        if not ip_addr and not robot_data.get("id"):
            raise ValueError("ip_address is required to register a robot")

        def _op() -> dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                existing = None
                if robot_data.get("id"):
                    existing = conn.execute(
                        "SELECT * FROM robots WHERE id = %s", (str(robot_data["id"]),)
                    ).fetchone()
                if existing is None and ip_addr:
                    existing = conn.execute(
                        "SELECT * FROM robots WHERE ip_address = %s", (ip_addr,)
                    ).fetchone()

                if existing is None:
                    rid = str(robot_data.get("id") or uuid.uuid4())
                    enc_pw = self._cipher.encrypt(ssh_password) if ssh_password else ""
                    row = conn.execute(
                        """
                        INSERT INTO robots (
                            id, name, model, serial_number, ip_address, mac_address,
                            ssh_user, ssh_password_enc, rosbridge_port, video_port,
                            active_ros_distro, status, battery_mv, cpu_temp_c,
                            capabilities, hbom_sbom, last_seen_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, NOW()
                        )
                        RETURNING *
                        """,
                        (
                            rid,
                            str(robot_data.get("name") or f"PuppyPi ({ip_addr})"),
                            str(robot_data.get("model") or "Hiwonder PuppyPi Pro"),
                            robot_data.get("serial_number"),
                            ip_addr,
                            robot_data.get("mac_address"),
                            str(robot_data.get("ssh_user") or "pi"),
                            enc_pw,
                            int(robot_data.get("rosbridge_port") or 9090),
                            int(robot_data.get("video_port") or 8080),
                            robot_data.get("active_ros_distro"),
                            str(robot_data.get("status") or "discovered"),
                            robot_data.get("battery_mv"),
                            robot_data.get("cpu_temp_c"),
                            json.dumps(robot_data.get("capabilities") or {}),
                            json.dumps(robot_data.get("hbom_sbom") or {}),
                        ),
                    ).fetchone()
                    conn.commit()
                    return _sanitize_robot_record(row)

                merged_caps = {**(existing.get("capabilities") or {}), **(robot_data.get("capabilities") or {})}
                enc_pw = (
                    self._cipher.encrypt(ssh_password)
                    if ssh_password is not None
                    else existing.get("ssh_password_enc", "")
                )
                row = conn.execute(
                    """
                    UPDATE robots SET
                        name = %s,
                        model = %s,
                        serial_number = %s,
                        ip_address = %s,
                        mac_address = %s,
                        ssh_user = %s,
                        ssh_password_enc = %s,
                        rosbridge_port = %s,
                        video_port = %s,
                        active_ros_distro = %s,
                        status = %s,
                        battery_mv = %s,
                        cpu_temp_c = %s,
                        capabilities = %s::jsonb,
                        hbom_sbom = %s::jsonb,
                        last_seen_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        robot_data.get("name") or existing["name"],
                        robot_data.get("model") or existing["model"],
                        robot_data.get("serial_number") if robot_data.get("serial_number") is not None else existing["serial_number"],
                        ip_addr or existing["ip_address"],
                        robot_data.get("mac_address") if robot_data.get("mac_address") is not None else existing["mac_address"],
                        robot_data.get("ssh_user") or existing["ssh_user"],
                        enc_pw,
                        int(robot_data.get("rosbridge_port") or existing["rosbridge_port"]),
                        int(robot_data.get("video_port") or existing["video_port"]),
                        robot_data.get("active_ros_distro") if robot_data.get("active_ros_distro") is not None else existing["active_ros_distro"],
                        robot_data.get("status") or existing["status"],
                        robot_data.get("battery_mv") if robot_data.get("battery_mv") is not None else existing["battery_mv"],
                        robot_data.get("cpu_temp_c") if robot_data.get("cpu_temp_c") is not None else existing["cpu_temp_c"],
                        json.dumps(merged_caps),
                        json.dumps(robot_data["hbom_sbom"] if "hbom_sbom" in robot_data else existing.get("hbom_sbom") or {}),
                        existing["id"],
                    ),
                ).fetchone()
                conn.commit()
                return _sanitize_robot_record(row)

        return self._with_retry(_op)

    def list_robots(self) -> List[dict[str, Any]]:
        """List all saved robots from PostgreSQL."""
        def _op() -> List[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute("SELECT * FROM robots ORDER BY created_at ASC").fetchall()
                return [_sanitize_robot_record(r) for r in rows]

        return self._with_retry(_op)

    def get_robot(self, robot_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single robot by ID."""
        def _op() -> Optional[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM robots WHERE id = %s", (robot_id,)).fetchone()
                return _sanitize_robot_record(row) if row else None

        return self._with_retry(_op)

    def get_robot_by_ip(self, ip_address: str) -> Optional[dict[str, Any]]:
        """Fetch a single robot by IP address."""
        def _op() -> Optional[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM robots WHERE ip_address = %s", (ip_address,)).fetchone()
                return _sanitize_robot_record(row) if row else None

        return self._with_retry(_op)

    def get_robot_ssh_password(self, robot_id: str) -> str:
        """Decrypt and return the Fernet-encrypted SSH password for a robot."""
        def _op() -> str:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    "SELECT ssh_password_enc FROM robots WHERE id = %s", (robot_id,)
                ).fetchone()
                if not row:
                    return ""
                return self._cipher.decrypt(str(row.get("ssh_password_enc") or ""))

        return self._with_retry(_op)

    def update_robot_credentials(
        self,
        robot_id: str,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update SSH username and/or Fernet-encrypted SSH password in PostgreSQL."""
        def _op() -> Optional[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                existing = conn.execute("SELECT * FROM robots WHERE id = %s", (robot_id,)).fetchone()
                if not existing:
                    return None
                new_user = ssh_user.strip() if ssh_user and ssh_user.strip() else existing["ssh_user"]
                new_pw_enc = (
                    self._cipher.encrypt(ssh_password)
                    if ssh_password is not None
                    else existing["ssh_password_enc"]
                )
                row = conn.execute(
                    """
                    UPDATE robots
                    SET ssh_user = %s, ssh_password_enc = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (new_user, new_pw_enc, robot_id),
                ).fetchone()
                conn.commit()
                return _sanitize_robot_record(row) if row else None

        return self._with_retry(_op)

    def save_robot_catalogue(
        self,
        robot_id: str,
        devices: Sequence[dict[str, Any]],
        sbom_packages: Sequence[dict[str, Any]],
        hbom_sbom: dict[str, Any],
        robot_updates: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Atomically replace a robot's hardware BOM devices, software SBOM, and CycloneDX JSONB."""
        def _op() -> Optional[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                existing = conn.execute("SELECT * FROM robots WHERE id = %s", (robot_id,)).fetchone()
                if not existing:
                    return None

                conn.execute("DELETE FROM robot_devices WHERE robot_id = %s", (robot_id,))
                conn.execute("DELETE FROM robot_sbom_packages WHERE robot_id = %s", (robot_id,))

                with conn.cursor() as cur:
                    if devices:
                        cur.executemany(
                            """
                            INSERT INTO robot_devices (
                                id, robot_id, subsystem, make, model, bus_type,
                                device_path, usb_id, status, metadata
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                            """,
                            [
                                (
                                    str(dev.get("id") or uuid.uuid4()),
                                    robot_id,
                                    str(dev.get("subsystem") or "hardware"),
                                    str(dev.get("make") or "Unknown"),
                                    str(dev.get("model") or "Unknown"),
                                    str(dev.get("bus_type") or "unknown"),
                                    dev.get("device_path"),
                                    dev.get("usb_id"),
                                    str(dev.get("status") or "online"),
                                    json.dumps(dev.get("metadata") or {}),
                                )
                                for dev in devices
                            ],
                        )
                    if sbom_packages:
                        cur.executemany(
                            """
                            INSERT INTO robot_sbom_packages (
                                id, robot_id, layer, name, version, purl
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            [
                                (
                                    str(pkg.get("id") or uuid.uuid4()),
                                    robot_id,
                                    str(pkg.get("layer") or "host_dpkg"),
                                    str(pkg.get("name") or ""),
                                    str(pkg.get("version") or ""),
                                    pkg.get("purl"),
                                )
                                for pkg in sbom_packages
                            ],
                        )

                upd = robot_updates or {}
                merged_caps = {**(existing.get("capabilities") or {}), **(upd.get("capabilities") or {})}
                row = conn.execute(
                    """
                    UPDATE robots SET
                        model = %s,
                        serial_number = %s,
                        mac_address = %s,
                        active_ros_distro = %s,
                        status = %s,
                        battery_mv = %s,
                        cpu_temp_c = %s,
                        capabilities = %s::jsonb,
                        hbom_sbom = %s::jsonb,
                        last_seen_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        upd.get("model") or existing["model"],
                        upd.get("serial_number") if upd.get("serial_number") is not None else existing["serial_number"],
                        upd.get("mac_address") if upd.get("mac_address") is not None else existing["mac_address"],
                        upd.get("active_ros_distro") if upd.get("active_ros_distro") is not None else existing["active_ros_distro"],
                        upd.get("status") or existing["status"],
                        upd.get("battery_mv") if upd.get("battery_mv") is not None else existing["battery_mv"],
                        upd.get("cpu_temp_c") if upd.get("cpu_temp_c") is not None else existing["cpu_temp_c"],
                        json.dumps(merged_caps),
                        json.dumps(hbom_sbom),
                        robot_id,
                    ),
                ).fetchone()
                conn.commit()
                return _sanitize_robot_record(row) if row else None

        return self._with_retry(_op)

    def list_robot_devices(self, robot_id: str) -> List[dict[str, Any]]:
        """List catalogued hardware devices for a robot."""
        def _op() -> List[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, robot_id, subsystem, make, model, bus_type,
                           device_path, usb_id, status, metadata
                    FROM robot_devices
                    WHERE robot_id = %s
                    ORDER BY subsystem ASC, make ASC, model ASC
                    """,
                    (robot_id,),
                ).fetchall()
                return [dict(r) for r in rows]

        return self._with_retry(_op)

    def list_robot_sbom(
        self,
        robot_id: str,
        layer: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """List catalogued SBOM packages for a robot with optional layer and substring filters."""
        def _op() -> List[dict[str, Any]]:
            sql = "SELECT id, robot_id, layer, name, version, purl FROM robot_sbom_packages WHERE robot_id = %s"
            params: List[Any] = [robot_id]
            if layer:
                sql += " AND layer = %s"
                params.append(layer)
            if query and query.strip():
                sql += " AND (LOWER(name) LIKE %s OR LOWER(COALESCE(purl, '')) LIKE %s)"
                like_q = f"%{query.strip().lower()}%"
                params.extend([like_q, like_q])
            sql += " ORDER BY layer ASC, name ASC"
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [dict(r) for r in rows]

        return self._with_retry(_op)

    def delete_robot(self, robot_id: str) -> bool:
        """Delete a robot and cascade-remove its devices, SBOM entries, and update jobs."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM robots WHERE id = %s", (robot_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    @staticmethod
    def _serialize_job_row(row: dict[str, Any]) -> dict[str, Any]:
        created = row.get("created_at")
        return {
            "id": str(row["id"]),
            "robot_id": str(row["robot_id"]),
            "track": str(row["track"]),
            "action": str(row["action"]),
            "status": str(row["status"]),
            "packages": list(row.get("packages_json") or []),
            "rollback_tag": row.get("rollback_tag"),
            "smoke_tests": row.get("smoke_tests_json"),
            "stdout_tail": str(row.get("stdout_tail") or ""),
            "stderr_tail": str(row.get("stderr_tail") or ""),
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def record_update_job(self, robot_id: str, job: dict[str, Any]) -> dict[str, Any]:
        """Persist a robot software update, rollback, or smoke-test job in PostgreSQL."""
        jid = str(job.get("id") or uuid.uuid4())

        def _op() -> dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO robot_update_jobs (
                        id, robot_id, track, action, status,
                        packages_json, rollback_tag, smoke_tests_json,
                        stdout_tail, stderr_tail
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s::jsonb,
                        %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        jid,
                        robot_id,
                        str(job.get("track") or "ros_pip"),
                        str(job.get("action") or "dry_run"),
                        str(job.get("status") or "ok"),
                        json.dumps(list(job.get("packages") or [])),
                        job.get("rollback_tag"),
                        json.dumps(job["smoke_tests"]) if job.get("smoke_tests") is not None else None,
                        str(job.get("stdout_tail") or "")[-4000:],
                        str(job.get("stderr_tail") or "")[-4000:],
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_job_row(row)

        return self._with_retry(_op)

    def list_update_jobs(self, robot_id: str, limit: int = 25) -> List[dict[str, Any]]:
        """List recent update jobs for ``robot_id`` from PostgreSQL ordered newest first."""
        def _op() -> List[dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM robot_update_jobs
                    WHERE robot_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (robot_id, max(1, int(limit))),
                ).fetchall()
                return [self._serialize_job_row(r) for r in rows]

        return self._with_retry(_op)
