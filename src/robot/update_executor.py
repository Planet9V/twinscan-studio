"""Safe PuppyPi OS (apt) & ROS Container (pip) Update Engine with Docker Snapshots, Rollback, and 6-Point Smoke Tests.

Provides staged dry-run preview, pre-download, atomic ``docker commit`` snapshotting,
ABI-sensitive and protected-package guards, safe container rollback, and live 6-point
post-update hardware/ROS verification. All remote operations pass ``SUDO_PW`` via
environment variable and execute argv-list subprocesses with zero shell interpolation.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import websockets

from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode
from src.robot.rosbridge_proxy import fetch_robot_snapshot
from src.robot.ssh_manager import run_remote_python, run_ssh_command

ABI_SENSITIVE_PACKAGES = frozenset(
    {
        "torch",
        "torchvision",
        "torchaudio",
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "mediapipe",
        "numpy",
        "scipy",
        "onnxruntime",
    }
)

PROTECTED_APT_PACKAGES = frozenset(
    {
        "network-manager",
        "openssh-server",
        "docker.io",
        "docker-ce",
        "docker-ce-cli",
        "containerd",
        "systemd",
        "dbus",
        "wpasupplicant",
    }
)

VALID_ROS_CONTAINERS = frozenset({"puppypi", "puppypi_ros2"})
SAFE_PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+\-]{0,127}$")
SAFE_ROLLBACK_TAG_RE = re.compile(r"^(puppypi|puppypi_ros2):pre-update-\d{8}-\d{6}$")

PIP_TO_IMPORT_NAME: Dict[str, str] = {
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "opencv-contrib-python": "cv2",
    "pyserial": "serial",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "scikit-learn": "sklearn",
    "beautifulsoup4": "bs4",
}


def validate_package_names(packages: Optional[Sequence[str]]) -> List[str]:
    """Validate and deduplicate apt/pip package names against strict safe characters.

    Args:
        packages: Optional sequence of package names.

    Returns:
        Deduplicated list of validated package names.

    Raises:
        ValueError: When any package name contains unsafe characters.
    """
    out: List[str] = []
    seen: set[str] = set()
    for raw in packages or ():
        clean = str(raw or "").strip()
        if not clean:
            continue
        if not SAFE_PKG_RE.match(clean):
            raise ValueError(f"Invalid package name: {raw!r}")
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def validate_container_name(container: str) -> str:
    """Validate target ROS container name is strictly ``puppypi`` or ``puppypi_ros2``."""
    clean = str(container or "").strip()
    if clean not in VALID_ROS_CONTAINERS:
        raise ValueError(f"Container must be one of {sorted(VALID_ROS_CONTAINERS)}, got {container!r}")
    return clean


def parse_apt_simulation(stdout: str) -> Dict[str, Any]:
    """Parse ``apt-get -s upgrade`` simulation output for planned upgrades & protected removals.

    Args:
        stdout: Combined stdout from ``apt-get -s upgrade``.

    Returns:
        Dictionary with ``upgradable_count``, ``packages``, and ``protected_blocked``.
    """
    packages: List[Dict[str, Any]] = []
    protected_blocked: List[str] = []

    for line in (stdout or "").splitlines():
        stripped = line.strip()
        m_inst = re.match(r"^Inst\s+(\S+)\s+(?:\[([^\]]+)\]\s+)?\(([^\s)]+)([^)]*)\)", stripped)
        if m_inst:
            name = m_inst.group(1)
            cur_ver = m_inst.group(2) or ""
            cand_ver = m_inst.group(3) or ""
            origin_meta = (m_inst.group(4) or "").lower()
            packages.append(
                {
                    "name": name,
                    "current_version": cur_ver,
                    "candidate_version": cand_ver,
                    "is_security": "security" in origin_meta,
                }
            )
            continue
        m_remv = re.match(r"^Remv\s+(\S+)", stripped)
        if m_remv:
            removed_pkg = m_remv.group(1)
            if removed_pkg in PROTECTED_APT_PACKAGES and removed_pkg not in protected_blocked:
                protected_blocked.append(removed_pkg)

    return {
        "upgradable_count": len(packages),
        "packages": packages,
        "protected_blocked": protected_blocked,
    }


def parse_pip_dry_run(stdout: str, requested: Sequence[str]) -> Dict[str, Any]:
    """Parse ``pip install --dry-run --upgrade`` output and flag ABI-sensitive packages.

    Args:
        stdout: Standard output from ``pip install --dry-run --upgrade``.
        requested: Originally requested package names.

    Returns:
        Dictionary with ``packages``, ``upgradable_count``, and ``abi_sensitive_packages``.
    """
    planned: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for line in (stdout or "").splitlines():
        m = re.search(r"Would install\s+(.+)$", line.strip())
        if m:
            for tok in m.group(1).split():
                if "-" in tok:
                    pname, pver = tok.rsplit("-", 1)
                else:
                    pname, pver = tok, ""
                norm = pname.lower().replace("_", "-")
                if norm not in seen:
                    seen.add(norm)
                    planned.append({"name": pname, "candidate_version": pver})

    abi_flagged = sorted(
        {
            p.lower().replace("_", "-")
            for p in list(requested) + [item["name"] for item in planned]
            if p.lower().replace("_", "-") in ABI_SENSITIVE_PACKAGES
        }
    )
    return {
        "upgradable_count": len(planned),
        "packages": planned,
        "abi_sensitive_packages": abi_flagged,
    }


def parse_snapshot_list(stdout: str) -> List[Dict[str, str]]:
    """Parse ``docker images`` tabular output filtered to ``pre-update-*`` rollback tags."""
    snapshots: List[Dict[str, str]] = []
    for line in (stdout or "").splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        tag = parts[0].strip()
        if ":pre-update-" not in tag:
            continue
        snapshots.append(
            {
                "tag": tag,
                "created": parts[1].strip() if len(parts) > 1 else "",
                "size": parts[2].strip() if len(parts) > 2 else "",
            }
        )
    return snapshots


# --- Remote Python Helpers (all using SUDO_PW env var + zero shell interpolation) ---

_APT_ACTION_SCRIPT = r"""
import json, os, subprocess

action = PAYLOAD["action"]
packages = PAYLOAD.get("packages") or []
sudo_pw = os.environ.get("SUDO_PW", "")
env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

def sudo_run(args, timeout=240):
    return subprocess.run(
        ["sudo", "-S", "-p", "", "env", "DEBIAN_FRONTEND=noninteractive"] + args,
        input=sudo_pw + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

if action == "preview":
    u = sudo_run(["apt-get", "update", "-qq"], timeout=90)
    s = sudo_run(["apt-get", "-s", "upgrade"], timeout=90)
    print(json.dumps({
        "returncode": s.returncode,
        "stdout": s.stdout[-12000:],
        "stderr": (u.stderr + "\n" + s.stderr).strip()[-4000:],
    }))
elif action == "download":
    cmd = ["apt-get", "-d", "-y", "install", "--only-upgrade"] + packages if packages else ["apt-get", "-d", "-y", "upgrade"]
    r = sudo_run(cmd, timeout=300)
    print(json.dumps({"returncode": r.returncode, "stdout": r.stdout[-8000:], "stderr": r.stderr[-4000:]}))
elif action == "apply":
    cmd = ["apt-get", "-y", "--only-upgrade", "install"] + packages if packages else ["apt-get", "-y", "upgrade"]
    r = sudo_run(cmd, timeout=420)
    print(json.dumps({"returncode": r.returncode, "stdout": r.stdout[-8000:], "stderr": r.stderr[-4000:]}))
else:
    raise ValueError(f"Unsupported apt action: {action}")
"""


_DOCKER_HELPER_HEADER = r"""
import json, os, subprocess

sudo_pw = os.environ.get("SUDO_PW", "")

def run_docker(args, timeout=240):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r
    except Exception:
        pass
    return subprocess.run(
        ["sudo", "-S", "-p", "", "docker"] + args,
        input=sudo_pw + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
    )
"""


_PIP_ACTION_SCRIPT = (
    _DOCKER_HELPER_HEADER
    + r"""
action = PAYLOAD["action"]
container = PAYLOAD["container"]
packages = PAYLOAD["packages"]

if action == "preview":
    r = run_docker(["exec", container, "python3", "-m", "pip", "install", "--dry-run", "--upgrade"] + packages, timeout=180)
elif action == "download":
    run_docker(["exec", container, "mkdir", "-p", "/tmp/twinscan_pip_cache"], timeout=20)
    r = run_docker(["exec", container, "python3", "-m", "pip", "download", "--dest", "/tmp/twinscan_pip_cache"] + packages, timeout=300)
elif action == "apply":
    r = run_docker(["exec", container, "python3", "-m", "pip", "install", "--upgrade"] + packages, timeout=420)
else:
    raise ValueError(f"Unsupported pip action: {action}")

print(json.dumps({"returncode": r.returncode, "stdout": r.stdout[-12000:], "stderr": r.stderr[-4000:]}))
"""
)


_SNAPSHOT_SCRIPT = (
    _DOCKER_HELPER_HEADER
    + r"""
action = PAYLOAD["action"]
if action == "commit":
    container = PAYLOAD["container"]
    tag = PAYLOAD["tag"]
    r = run_docker(["commit", container, tag], timeout=180)
    print(json.dumps({"returncode": r.returncode, "tag": tag, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:]}))
elif action == "list":
    r = run_docker(["images", "--format", "{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}\t{{.Size}}"], timeout=30)
    print(json.dumps({"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr[-4000:]}))
else:
    raise ValueError(f"Unsupported snapshot action: {action}")
"""
)


_ROLLBACK_SCRIPT = (
    _DOCKER_HELPER_HEADER
    + r"""
import time

container = PAYLOAD["container"]
rollback_tag = PAYLOAD["rollback_tag"]
ts = time.strftime("%Y%m%d%H%M%S")
backup_name = f"{container}_failed_{ts}"

# 1. Verify rollback image exists before touching live container
chk = run_docker(["image", "inspect", rollback_tag], timeout=20)
if chk.returncode != 0:
    print(json.dumps({"ok": False, "error": f"Rollback image {rollback_tag} not found", "stderr": chk.stderr[-2000:]}))
    raise SystemExit(0)

# 2. Inspect current container mounts, network mode, restart policy, privileged, devices, env, cmd
ins = run_docker(["inspect", container], timeout=20)
if ins.returncode != 0 or not ins.stdout.strip():
    print(json.dumps({"ok": False, "error": f"Container {container} inspect failed", "stderr": ins.stderr[-2000:]}))
    raise SystemExit(0)

meta = json.loads(ins.stdout)[0]
hc = meta.get("HostConfig") or {}
cfg = meta.get("Config") or {}
run_args = ["run", "-d", "--name", container]

net_mode = hc.get("NetworkMode") or "host"
run_args.extend(["--network", net_mode])
if hc.get("Privileged"):
    run_args.append("--privileged")
rp = (hc.get("RestartPolicy") or {}).get("Name")
if rp and rp != "no":
    run_args.extend(["--restart", rp])
for b in (hc.get("Binds") or []):
    run_args.extend(["-v", b])
for dev in (hc.get("Devices") or []):
    hp = dev.get("PathOnHost")
    cp = dev.get("PathInContainer") or hp
    if hp:
        run_args.extend(["--device", f"{hp}:{cp}"])
for e in (cfg.get("Env") or []):
    if "=" in e:
        run_args.extend(["-e", e])
if cfg.get("Tty"):
    run_args.append("-t")
if cfg.get("OpenStdin"):
    run_args.append("-i")
run_args.append(rollback_tag)
if cfg.get("Cmd"):
    run_args.extend(cfg["Cmd"])

# 3. Safely stop & rename current container before launching rollback snapshot
run_docker(["stop", container], timeout=35)
ren = run_docker(["rename", container, backup_name], timeout=20)
if ren.returncode != 0:
    run_docker(["start", container], timeout=20)
    print(json.dumps({"ok": False, "error": f"Failed renaming {container} to {backup_name}", "stderr": ren.stderr[-2000:]}))
    raise SystemExit(0)

# 4. Launch rollback container; if it fails, restore backup_name immediately!
started = run_docker(run_args, timeout=45)
if started.returncode != 0:
    run_docker(["rm", "-f", container], timeout=20)
    run_docker(["rename", backup_name, container], timeout=20)
    run_docker(["start", container], timeout=30)
    print(json.dumps({
        "ok": False,
        "error": f"Rollback start failed and original container was restored: {started.stderr[-1000:]}",
        "stderr": started.stderr[-2000:],
    }))
    raise SystemExit(0)

print(json.dumps({
    "ok": True,
    "container": container,
    "rollback_tag": rollback_tag,
    "backup_container": backup_name,
    "stdout": started.stdout[-2000:],
    "stderr": started.stderr[-2000:],
}))
"""
)


# --- Public Update Executor API ---


async def preview_apt_updates(ip: str, user: str, password: str) -> Dict[str, Any]:
    """Run ``apt-get update && apt-get -s upgrade`` dry-run preview on the PuppyPi host.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.

    Returns:
        Structured preview dictionary with planned upgrades, security flags, and protected blocks.
    """
    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_APT_ACTION_SCRIPT,
        payload={"action": "preview"},
        timeout=150.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    parsed = parse_apt_simulation(res.get("stdout") or "")
    return {
        "ok": res.get("returncode") == 0,
        "track": "host_apt",
        "action": "dry_run",
        "status": "preview_ready" if res.get("returncode") == 0 else "failed",
        **parsed,
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def download_apt_updates(
    ip: str,
    user: str,
    password: str,
    packages: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Pre-download Debian 12 ``.deb`` packages without installing (``apt-get -d -y``).

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        packages: Optional list of specific apt packages to download.

    Returns:
        Structured download result dictionary.
    """
    valid_pkgs = validate_package_names(packages)
    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_APT_ACTION_SCRIPT,
        payload={"action": "download", "packages": valid_pkgs},
        timeout=330.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    return {
        "ok": res.get("returncode") == 0,
        "track": "host_apt",
        "action": "download",
        "status": "downloaded" if res.get("returncode") == 0 else "failed",
        "packages": [{"name": p} for p in valid_pkgs],
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def apply_apt_updates(
    ip: str,
    user: str,
    password: str,
    packages: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Validate against ``PROTECTED_APT_PACKAGES`` removal and apply Debian 12 apt upgrades.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        packages: Optional list of specific apt packages to upgrade.

    Returns:
        Structured apply result dictionary (blocked cleanly if protected removals detected).
    """
    valid_pkgs = validate_package_names(packages)
    preview = await preview_apt_updates(ip=ip, user=user, password=password)
    if preview.get("protected_blocked"):
        blocked = preview["protected_blocked"]
        return {
            "ok": False,
            "track": "host_apt",
            "action": "apply",
            "status": "blocked_protected_packages",
            "protected_blocked": blocked,
            "error": f"Blocked: apt upgrade would remove protected system packages: {', '.join(blocked)}",
            "stdout_tail": preview.get("stdout_tail", ""),
            "stderr_tail": preview.get("stderr_tail", ""),
        }

    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_APT_ACTION_SCRIPT,
        payload={"action": "apply", "packages": valid_pkgs},
        timeout=450.0,
        retries=1,
        env_vars={"SUDO_PW": password},
    )
    return {
        "ok": res.get("returncode") == 0,
        "track": "host_apt",
        "action": "apply",
        "status": "applied" if res.get("returncode") == 0 else "failed",
        "upgradable_count": preview.get("upgradable_count", 0),
        "packages": [{"name": p} for p in valid_pkgs] or preview.get("packages", []),
        "protected_blocked": [],
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def preview_pip_updates(
    ip: str,
    user: str,
    password: str,
    container: str,
    packages: Sequence[str],
) -> Dict[str, Any]:
    """Run ``pip install --dry-run --upgrade`` inside a ROS Docker container and flag ABI-sensitive packages."""
    valid_container = validate_container_name(container)
    valid_pkgs = validate_package_names(packages)
    if not valid_pkgs:
        raise ValueError("Select at least one Python package to preview.")

    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_PIP_ACTION_SCRIPT,
        payload={"action": "preview", "container": valid_container, "packages": valid_pkgs},
        timeout=210.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    parsed = parse_pip_dry_run(res.get("stdout") or "", valid_pkgs)
    return {
        "ok": res.get("returncode") == 0,
        "track": "ros_pip",
        "action": "dry_run",
        "container": valid_container,
        "status": "preview_ready" if res.get("returncode") == 0 else "failed",
        **parsed,
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def download_pip_updates(
    ip: str,
    user: str,
    password: str,
    container: str,
    packages: Sequence[str],
) -> Dict[str, Any]:
    """Download Python wheels to ``/tmp/twinscan_pip_cache`` inside the ROS Docker container."""
    valid_container = validate_container_name(container)
    valid_pkgs = validate_package_names(packages)
    if not valid_pkgs:
        raise ValueError("Select at least one Python package to download.")

    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_PIP_ACTION_SCRIPT,
        payload={"action": "download", "container": valid_container, "packages": valid_pkgs},
        timeout=330.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    return {
        "ok": res.get("returncode") == 0,
        "track": "ros_pip",
        "action": "download",
        "container": valid_container,
        "status": "downloaded" if res.get("returncode") == 0 else "failed",
        "packages": [{"name": p} for p in valid_pkgs],
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def snapshot_ros_container(
    ip: str,
    user: str,
    password: str,
    container: str,
) -> Dict[str, Any]:
    """Create a ``docker commit`` rollback snapshot ``<container>:pre-update-<YYYYMMDD-HHMMSS>``."""
    valid_container = validate_container_name(container)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    tag = f"{valid_container}:pre-update-{ts}"
    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_SNAPSHOT_SCRIPT,
        payload={"action": "commit", "container": valid_container, "tag": tag},
        timeout=210.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
    if res.get("returncode") != 0:
        raise RuntimeError(f"Failed creating Docker snapshot {tag}: {res.get('stderr')}")
    return {"ok": True, "rollback_tag": tag, "container": valid_container}


async def list_container_snapshots(ip: str, user: str, password: str) -> List[Dict[str, str]]:
    """List available ``pre-update-*`` Docker container rollback snapshots on the robot."""
    try:
        res = await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_SNAPSHOT_SCRIPT,
            payload={"action": "list"},
            timeout=35.0,
            retries=2,
            env_vars={"SUDO_PW": password},
        )
        if res.get("returncode") != 0:
            return []
        return parse_snapshot_list(res.get("stdout") or "")
    except Exception as exc:
        sys.stderr.write(f"[update_executor] Failed listing container snapshots on {ip}: {exc}\n")
        return []


async def apply_pip_updates(
    ip: str,
    user: str,
    password: str,
    container: str,
    packages: Sequence[str],
    allow_abi_sensitive: bool = False,
) -> Dict[str, Any]:
    """Snapshot the ROS container first, enforce ABI-sensitive guard, then ``pip install --upgrade``.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        container: Target container (``"puppypi"`` or ``"puppypi_ros2"``).
        packages: Python packages to upgrade.
        allow_abi_sensitive: Must be ``True`` to upgrade ABI-sensitive native wheels like ``torch`` or ``opencv-python``.

    Returns:
        Result dictionary containing ``rollback_tag``, status, and pip logs.
    """
    valid_container = validate_container_name(container)
    valid_pkgs = validate_package_names(packages)
    if not valid_pkgs:
        raise ValueError("Select at least one Python package to upgrade.")

    abi_hits = sorted(
        p for p in valid_pkgs if p.lower().replace("_", "-") in ABI_SENSITIVE_PACKAGES
    )
    if abi_hits and not allow_abi_sensitive:
        return {
            "ok": False,
            "track": "ros_pip",
            "action": "apply",
            "container": valid_container,
            "status": "blocked_abi_sensitive",
            "abi_sensitive_packages": abi_hits,
            "error": (
                f"Blocked: ABI-sensitive packages selected ({', '.join(abi_hits)}). "
                "Enable 'Allow ABI-sensitive upgrades' after verifying rollback snapshot."
            ),
        }

    snap = await snapshot_ros_container(ip=ip, user=user, password=password, container=valid_container)
    rollback_tag = snap["rollback_tag"]

    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_PIP_ACTION_SCRIPT,
        payload={"action": "apply", "container": valid_container, "packages": valid_pkgs},
        timeout=450.0,
        retries=1,
        env_vars={"SUDO_PW": password},
    )
    return {
        "ok": res.get("returncode") == 0,
        "track": "ros_pip",
        "action": "apply",
        "container": valid_container,
        "status": "applied" if res.get("returncode") == 0 else "failed",
        "packages": [{"name": p} for p in valid_pkgs],
        "abi_sensitive_packages": abi_hits,
        "rollback_tag": rollback_tag,
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


async def rollback_container_snapshot(
    ip: str,
    user: str,
    password: str,
    container: str,
    rollback_tag: str,
) -> Dict[str, Any]:
    """Safely roll back a ROS container to a ``pre-update-*`` Docker snapshot.

    Renames the current container to ``<container>_failed_<ts>`` before starting the rollback
    image and automatically restores the renamed container if startup fails.
    """
    valid_container = validate_container_name(container)
    clean_tag = str(rollback_tag or "").strip()
    if not SAFE_ROLLBACK_TAG_RE.match(clean_tag):
        raise ValueError(f"Invalid rollback tag: {rollback_tag!r}")
    if not clean_tag.startswith(f"{valid_container}:"):
        raise ValueError(f"Rollback tag {clean_tag!r} does not match container {valid_container!r}")

    res = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_ROLLBACK_SCRIPT,
        payload={"container": valid_container, "rollback_tag": clean_tag},
        timeout=120.0,
        retries=1,
        env_vars={"SUDO_PW": password},
    )
    return {
        "ok": bool(res.get("ok")),
        "track": "ros_pip",
        "action": "rollback",
        "container": valid_container,
        "status": "rolled_back" if res.get("ok") else "failed",
        "rollback_tag": clean_tag,
        "error": res.get("error"),
        "stdout_tail": (res.get("stdout") or "")[-4000:],
        "stderr_tail": (res.get("stderr") or "")[-4000:],
    }


# --- 6-Point Post-Update Smoke Test Suite ---

_SMOKE_DOCKER_AND_IMPORTS_SCRIPT = (
    _DOCKER_HELPER_HEADER
    + r"""
container = PAYLOAD["container"]
modules = PAYLOAD["modules"]

ps = run_docker(["ps", "--filter", f"name=^{container}$", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"], timeout=15)
running = False
status_txt = ""
if ps.returncode == 0 and ps.stdout.strip():
    for ln in ps.stdout.splitlines():
        parts = ln.split("\t")
        if parts and parts[0].strip() == container:
            running = (len(parts) > 1 and parts[1].strip().lower() == "running")
            status_txt = parts[2].strip() if len(parts) > 2 else parts[1].strip()

import_ok = False
import_detail = "Container not running"
if running:
    code = "import importlib, json; mods=" + json.dumps(modules) + "; res={}; " \
           "\nfor m in mods:\n" \
           "    try:\n        importlib.import_module(m); res[m]='ok'\n" \
           "    except Exception as e:\n        res[m]=str(e)\n" \
           "print(json.dumps(res))"
    ir = run_docker(["exec", container, "python3", "-c", code], timeout=25)
    if ir.returncode == 0 and ir.stdout.strip():
        try:
            parsed = json.loads(ir.stdout.strip().splitlines()[-1])
            failed = {k: v for k, v in parsed.items() if v != "ok"}
            import_ok = (len(failed) == 0)
            import_detail = f"Verified {len(parsed)} imports ({', '.join(parsed.keys())})" if import_ok else f"Failed imports: {failed}"
        except Exception as exc:
            import_detail = f"Import check parse error: {exc}"
    else:
        import_detail = (ir.stderr or ir.stdout or "python import check failed")[-300:]

rrc_exists = os.path.exists("/dev/rrc") or os.path.exists("/dev/ttyAMA0")
print(json.dumps({
    "container_running": running,
    "container_status": status_txt,
    "import_ok": import_ok,
    "import_detail": import_detail,
    "rrc_exists": rrc_exists,
}))
"""
)


async def run_post_update_smoke_tests(
    ip: str,
    user: str,
    password: str,
    ros_mode: str = "ros1",
    updated_packages: Optional[Sequence[str]] = None,
    rosbridge_port: int = 9090,
    video_port: int = 8080,
) -> Dict[str, Any]:
    """Run 6 live post-update smoke tests across SSH, Docker ROS, imports, ROSBridge, FPV camera, and STM32 battery.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH password.
        ros_mode: ``"ros1"`` or ``"ros2"``.
        updated_packages: Optional recently updated Python packages to import-verify.
        rosbridge_port: ROSBridge TCP port (default ``9090``).
        video_port: ``web_video_server`` TCP port (default ``8080``).

    Returns:
        ``SmokeTestReport`` dict ``{passed, passed_count, total_count, checks}``.
    """
    norm_mode = normalize_ros_mode(ros_mode)
    profile = get_ros_profile(norm_mode)
    container = profile["container_name"]
    checks: List[Dict[str, Any]] = []

    # 1. Wi-Fi & SSH Reachability
    t0 = time.perf_counter()
    ssh_ok = False
    try:
        rc, out = await run_ssh_command(ip, user, password, "echo SSH_READY && hostname -I", timeout=10.0, retries=2)
        ssh_ok = rc == 0 and "SSH_READY" in out
        checks.append(
            {
                "id": "wifi_ssh",
                "name": "Wi-Fi & SSH Reachability",
                "status": "pass" if ssh_ok else "fail",
                "detail": f"SSH responsive at {ip} ({out.splitlines()[-1].strip() if out.splitlines() else ip})" if ssh_ok else f"SSH failed (rc={rc})",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        )
    except Exception as exc:
        sys.stderr.write(f"[smoke.ssh] Failed on {ip}: {exc}\n")
        checks.append(
            {
                "id": "wifi_ssh",
                "name": "Wi-Fi & SSH Reachability",
                "status": "fail",
                "detail": str(exc),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        )

    # 2 & 3. Docker ROS Container + Package Imports
    modules = ["cv2", "numpy"]
    for pkg in validate_package_names(updated_packages):
        norm = pkg.lower().replace("_", "-")
        mod = PIP_TO_IMPORT_NAME.get(norm, norm.replace("-", "_"))
        if mod not in modules:
            modules.append(mod)

    t1 = time.perf_counter()
    rrc_exists = False
    try:
        dres = await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_SMOKE_DOCKER_AND_IMPORTS_SCRIPT,
            payload={"container": container, "modules": modules[:10]},
            timeout=35.0,
            retries=2,
            env_vars={"SUDO_PW": password},
        )
        lat_d = int((time.perf_counter() - t1) * 1000)
        rrc_exists = bool(dres.get("rrc_exists"))
        checks.append(
            {
                "id": "docker_ros_container",
                "name": f"Docker Container ({container})",
                "status": "pass" if dres.get("container_running") else "fail",
                "detail": (
                    f"{container} running ({dres.get('container_status')})"
                    if dres.get("container_running")
                    else f"{container} is not running ({dres.get('container_status') or 'stopped'})"
                ),
                "latency_ms": lat_d,
            }
        )
        checks.append(
            {
                "id": "package_imports",
                "name": "Python & ROS Package Imports",
                "status": "pass" if dres.get("import_ok") else "fail",
                "detail": str(dres.get("import_detail") or ""),
                "latency_ms": lat_d,
            }
        )
    except Exception as exc:
        lat_d = int((time.perf_counter() - t1) * 1000)
        sys.stderr.write(f"[smoke.docker] Failed on {ip}: {exc}\n")
        checks.append(
            {"id": "docker_ros_container", "name": f"Docker Container ({container})", "status": "fail", "detail": str(exc), "latency_ms": lat_d}
        )
        checks.append(
            {"id": "package_imports", "name": "Python & ROS Package Imports", "status": "fail", "detail": str(exc), "latency_ms": lat_d}
        )

    # 4 & 6. ROSBridge :9090 Graph + STM32 Battery Telemetry
    t2 = time.perf_counter()
    battery_mv: Optional[int] = None
    try:
        uri = f"ws://{ip}:{rosbridge_port}"
        async with websockets.connect(uri, open_timeout=4.0, close_timeout=2.0) as ws:
            await ws.send(json.dumps({"op": "call_service", "service": "/rosapi/nodes", "args": {}}))
            await ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "topic": "/ros_robot_controller/battery",
                        "type": profile["message_types"]["battery"],
                    }
                )
            )
            node_count: Optional[int] = None
            deadline = time.monotonic() + 2.2
            while time.monotonic() < deadline and (node_count is None or battery_mv is None):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.2, deadline - time.monotonic()))
                    msg = json.loads(raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw)
                    if msg.get("op") == "service_response" and msg.get("service") == "/rosapi/nodes":
                        nodes = (msg.get("values") or {}).get("nodes") or []
                        node_count = len(nodes)
                    elif msg.get("op") == "publish" and msg.get("topic") == "/ros_robot_controller/battery":
                        data = (msg.get("msg") or {}).get("data")
                        if data is not None:
                            battery_mv = int(data)
                except asyncio.TimeoutError:
                    break
        lat_rb = int((time.perf_counter() - t2) * 1000)
        checks.append(
            {
                "id": "ros_graph_rosbridge",
                "name": f"ROSBridge (:{rosbridge_port}) Graph",
                "status": "pass",
                "detail": (
                    f"Connected to {uri} ({node_count} active ROS nodes)"
                    if node_count is not None
                    else f"Connected to {uri}"
                ),
                "latency_ms": lat_rb,
            }
        )
    except Exception as exc:
        lat_rb = int((time.perf_counter() - t2) * 1000)
        sys.stderr.write(f"[smoke.rosbridge] Failed on {ip}:{rosbridge_port}: {exc}\n")
        checks.append(
            {
                "id": "ros_graph_rosbridge",
                "name": f"ROSBridge (:{rosbridge_port}) Graph",
                "status": "fail",
                "detail": str(exc),
                "latency_ms": lat_rb,
            }
        )

    # 5. FPV Camera :8080 Snapshot
    t3 = time.perf_counter()
    try:
        jpg = await fetch_robot_snapshot(ip=ip, port=video_port, topic=profile["camera_topic"], timeout=4.0, retries=1)
        valid_jpg = len(jpg) > 100 and jpg[:3] == b"\xff\xd8\xff"
        checks.append(
            {
                "id": "fpv_camera",
                "name": f"FPV Camera (:{video_port})",
                "status": "pass" if valid_jpg else "fail",
                "detail": f"Live JPEG frame received ({len(jpg):,} B on {profile['camera_topic']})" if valid_jpg else "Invalid JPEG payload",
                "latency_ms": int((time.perf_counter() - t3) * 1000),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "id": "fpv_camera",
                "name": f"FPV Camera (:{video_port})",
                "status": "fail",
                "detail": str(exc),
                "latency_ms": int((time.perf_counter() - t3) * 1000),
            }
        )

    # 6. STM32 / Battery Telemetry
    if battery_mv is not None:
        checks.append(
            {
                "id": "stm32_battery",
                "name": "STM32 / Battery Telemetry",
                "status": "pass",
                "detail": f"Live battery telemetry: {battery_mv / 1000.0:.2f} V ({battery_mv} mV)",
                "latency_ms": lat_rb,
            }
        )
    elif rrc_exists:
        checks.append(
            {
                "id": "stm32_battery",
                "name": "STM32 / Battery Telemetry",
                "status": "warn",
                "detail": "STM32 serial device present, but /ros_robot_controller/battery did not emit within 2.2s",
                "latency_ms": lat_rb,
            }
        )
    else:
        checks.append(
            {
                "id": "stm32_battery",
                "name": "STM32 / Battery Telemetry",
                "status": "fail",
                "detail": "No STM32 serial device or live battery voltage detected",
                "latency_ms": lat_rb,
            }
        )

    passed_count = sum(1 for c in checks if c["status"] == "pass")
    failed_count = sum(1 for c in checks if c["status"] == "fail")
    return {
        "passed": failed_count == 0,
        "passed_count": passed_count,
        "total_count": len(checks),
        "checks": checks,
    }
