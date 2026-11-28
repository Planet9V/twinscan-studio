"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Battery,
  Bot,
  Box,
  Cable,
  Camera,
  CheckCircle2,
  CircuitBoard,
  Compass,
  Cpu,
  Gamepad2,
  HardDriveDownload,
  Layers,
  Map,
  Mic,
  Network,
  Radar,
  RefreshCw,
  Route,
  ScanFace,
  Search,
  Settings2,
  Sparkles,
  Thermometer,
  Wifi,
  WifiOff,
  Wrench,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStudio } from "@/context/StudioContext";
import { discoverRobots } from "@/lib/robotApi";

export function MissionControlLanding() {
  const router = useRouter();
  const {
    space,
    equipment,
    graph,
    focusQueue,
    darkZones,
    robots,
    activeRobot,
    setActiveRobotId,
    refreshRobots,
    activeRosMode,
    uiRosPreview,
    setUiRosPreview,
    robotNetwork,
    refreshRobotNetwork,
    switchRobotActiveIp,
    frame,
    wsConnected,
    dbBackend,
    setSelectedEquipmentId,
    setFocusTarget,
    enrichingId,
    handleEnrichAsset,
  } = useStudio();

  const [discovering, setDiscovering] = useState(false);
  const [discoverBanner, setDiscoverBanner] = useState<string | null>(null);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [netRefreshing, setNetRefreshing] = useState(false);
  const [switchingIp, setSwitchingIp] = useState<string | null>(null);

  const isRos2 = activeRosMode === "ros2";

  const handleDiscover = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    setDiscoverBanner(null);
    try {
      const res = await discoverRobots();
      await refreshRobots();
      const foundCount = res.discovered.length || res.robots.length;
      setDiscoverBanner(
        foundCount > 0
          ? `Discovered ${foundCount} LAN robot unit(s) and synchronized fleet registry.`
          : "LAN scan completed — 0 new PuppyPi units responded on UDP 9027 / TCP 9090."
      );
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : "LAN discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const handleRefreshNet = async () => {
    setNetRefreshing(true);
    try {
      await refreshRobotNetwork();
    } finally {
      setNetRefreshing(false);
    }
  };

  const handleUseIp = async (ip: string) => {
    setSwitchingIp(ip);
    setDiscoverError(null);
    try {
      await switchRobotActiveIp(ip);
      setDiscoverBanner(`Active robot control IP switched to ${ip}.`);
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : `Failed to switch active IP to ${ip}`);
    } finally {
      setSwitchingIp(null);
    }
  };

  const incompleteCount = useMemo(
    () => equipment.filter((e) => (e.completeness?.status ?? "INCOMPLETE") !== "VERIFIED").length,
    [equipment]
  );

  const topAlerts = useMemo(
    () =>
      [...focusQueue]
        .sort((a, b) => b.priority_score - a.priority_score)
        .slice(0, 5),
    [focusQueue]
  );

  const roomArea = Number(frame?.metrics?.area_m2 ?? space?.metrics?.area_m2 ?? 0) || 0;
  const wallCount = frame?.walls?.length ?? space?.walls?.length ?? 0;

  const featuredStudios = [
    {
      href: "/microbit",
      badge: "NEW · 3D LAB",
      badgeVariant: "default" as const,
      title: "Universal 3D Hardware Lab & AI Co-Pilot",
      desc: "Prototype BBC micro:bit v2.2, Raspberry Pi 5 16GB & PuppyPi Pro in interactive 3D with drag-and-drop Hiwonder sensors, Web Speech/Audio sim & live USB flashing.",
      highlights: ["3 Switchable 3D Boards", "Hiwonder Sensor Kit", "AI Co-Pilot Chat"],
      cta: "Open 3D Hardware Lab",
      icon: CircuitBoard,
      accent: "text-eigenia-orange",
    },
    {
      href: "/room-studio",
      badge: "NEW · PHOTO → 3D",
      badgeVariant: "sky" as const,
      title: "Compositional Room Twin Studio",
      desc: "Build high-fidelity PBR .glb & 3DGS room digital twins from photos with OpenRouter Vision scene-graph boxing, TransformControls & Ghost Camera NBV Coach.",
      highlights: ["Photo-to-GLB", "Vision Scene Graph", "3DGS / GLB Export"],
      cta: "Launch Room Studio",
      icon: Box,
      accent: "text-eigenia-sky",
    },
    {
      href: "/slam",
      badge: "NEW · ROS 2 SLAM",
      badgeVariant: "amber" as const,
      title: "SLAM Mapping Studio",
      desc: "Run live ROS 2 Humble Occupancy-Grid SLAM on PuppyPi Pro's LD19 360° LiDAR, track mapped m² coverage in real time, and export 3D extruded wall twins in 1 click.",
      highlights: ["LD19 360° LiDAR", "Live Occupancy Grid", "1-Click 3D Export"],
      cta: "Open SLAM Studio",
      icon: Map,
      accent: "text-eigenia-amber",
    },
    {
      href: "/overwatch",
      badge: "UPGRADED · STAGE",
      badgeVariant: "sky" as const,
      title: "Overwatch Multi-Camera Stage",
      desc: "Spotlight Main+Mini camera stage with Raspberry Pi 5 4K auto-discovery, Shapely GDOP frustum fusion, ROI upscale loupe & Guided Self-Calibration Wizard.",
      highlights: ["Pi 5 4K Auto-Sync", "GDOP Fusion", "Self-Cal Wizard"],
      cta: "Open Overwatch",
      icon: Camera,
      accent: "text-eigenia-sky",
    },
  ];

  const quickModules = [
    {
      href: "/twin",
      title: "Spatial LiDAR Twin",
      desc: "2D Tactical Radar, Three.js 3D & Babylon.js 9 PBR with Dark-Zone NBV",
      metric: `${wallCount} walls · ${darkZones.length} dark zones`,
      icon: Radar,
      accent: "text-eigenia-orange",
    },
    {
      href: "/control",
      title: "Robot Control & FPV",
      desc: "Live MJPEG stream, WASD dead-man's gamepad, pose, gait & 2-DOF arm",
      metric: `${robots.length} robot(s) · ${isRos2 ? "ROS 2 DDS" : "ROS 1"}`,
      icon: Gamepad2,
      accent: "text-eigenia-sky",
    },
    {
      href: "/voice",
      title: "Voice & OX Assistant",
      desc: "Hands-free \"Hey OX\" wake-word chat, 5 personalities, offline Piper & mixer",
      metric: "WonderEcho Pro · Offline Piper",
      icon: Mic,
      accent: "text-eigenia-orange",
    },
    {
      href: "/vision",
      title: "AI Vision & People",
      desc: "Face recognition (pgvector), YOLO11n animals/objects, click-to-track & Line v2",
      metric: "YuNet + SFace + YOLO11n",
      icon: ScanFace,
      accent: "text-eigenia-sky",
    },
    {
      href: "/patrol",
      title: "Autonomous Patrol",
      desc: "Click-to-drop 2D waypoint routes with 5-sector LiDAR VFH obstacle avoidance",
      metric: "Multi-waypoint · VFH Safety",
      icon: Route,
      accent: "text-eigenia-amber",
    },
    {
      href: "/architect",
      title: "Lab Architect Co-Design",
      desc: "Auto Fleet & USB Peripheral Sync, 2D wiring schematics & 3D hardware assembly",
      metric: "6 Hardware Profiles · Auto-Sync",
      icon: Wrench,
      accent: "text-eigenia-orange",
    },
    {
      href: "/flash",
      title: "Universal Device Flasher",
      desc: "Flash Raspberry Pi OS, ROS 2, MicroPython, ESP32/ESPHome & micro:bit via USB/SSH",
      metric: "Multi-Platform · Zero CLI",
      icon: HardDriveDownload,
      accent: "text-eigenia-sky",
    },
    {
      href: "/catalog",
      title: "Fleet BOM & SBOM",
      desc: "SSH hardware BOM audit, ROS1/ROS2 packages, update check & CycloneDX 1.6",
      metric: `${robots.filter((r) => r.status === "online").length} online unit(s)`,
      icon: Cpu,
      accent: "text-eigenia-amber",
    },
    {
      href: "/graph",
      title: "Knowledge Graph",
      desc: "G_CPDT asset topology, dark-zone nodes, CVE posture & pgvector search",
      metric: `${graph?.stats?.node_count ?? 0} nodes · ${graph?.stats?.edge_count ?? 0} edges`,
      icon: Network,
      accent: "text-eigenia-sky",
    },
    {
      href: "/config",
      title: "Robot Config & Admin",
      desc: "ROS 1 <-> ROS 2 switch, Wi-Fi/ETH IPs, SSH/servos & PG18 Fernet settings",
      metric: dbBackend,
      icon: Settings2,
      accent: "text-eigenia-orange",
    },
  ];

  const wifiIface = robotNetwork?.wifi ?? null;
  const ethIfaces = robotNetwork?.ethernet ?? [];

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-5">
      {/* Hero Status Bar */}
      <Card
        className={
          isRos2
            ? "border-eigenia-orange/60 bg-eigenia-shell/95 shadow-[0_0_24px_rgba(224,90,16,0.16)]"
            : "border-eigenia-orange/30 bg-eigenia-shell"
        }
      >
        <CardContent className="flex flex-col justify-between gap-4 p-5 lg:flex-row lg:items-center">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default">MISSION CONTROL</Badge>
              <Badge variant="sky">v2.1.0</Badge>
              <Badge variant={isRos2 ? "default" : "sky"}>
                <Zap className="h-3 w-3" />
                {isRos2 ? "ROS 2 HUMBLE DDS" : "ROS 1 NOETIC"}
              </Badge>
              <Badge variant={wsConnected ? "sky" : "fault"}>
                {wsConnected ? "LD19 TELEMETRY LIVE" : "TELEMETRY STANDBY"}
              </Badge>
              <Badge variant="neutral">{dbBackend}</Badge>
            </div>
            <h1 className="font-mono text-xl font-bold tracking-tight text-white md:text-2xl">
              EIGENIA <span className="text-eigenia-orange">//</span> PUPPYPI & SPATIAL TWIN COMMAND CENTER
            </h1>
            <p className="max-w-2xl text-xs text-eigenia-muted">
              Active Space:{" "}
              <span className="font-mono text-white">
                {space ? `${space.facility} · ${space.name}` : "Initializing..."}
              </span>{" "}
              — Orchestrate LAN PuppyPi quadruped discovery, ROS 2 Humble SLAM & Photo-to-3D Room Twins,
              Overwatch Multi-Camera fusion, and Universal 3D Hardware Prototyping for micro:bit v2.2 &amp; Pi 5.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              size="lg"
              onClick={() => void handleDiscover()}
              disabled={discovering}
              className="font-mono text-xs"
            >
              {discovering ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              {discovering ? "Scanning LAN (UDP 9027 / TCP 9090)..." : "Auto-Discover PuppyPi & LAN Fleet"}
            </Button>
            <Button size="lg" variant="secondary" asChild className="font-mono text-xs">
              <Link href="/microbit">
                <CircuitBoard className="h-4 w-4 text-eigenia-orange" />
                3D Hardware Lab
              </Link>
            </Button>
            <Button
              size="lg"
              variant={isRos2 ? "secondary" : "outline"}
              onClick={() => setUiRosPreview(isRos2 ? (uiRosPreview === "ros2" ? null : "ros1") : "ros2")}
              className="font-mono text-xs"
            >
              <Zap className="h-4 w-4 text-eigenia-orange" />
              {isRos2 ? "Preview ROS 1 Theme" : "Preview ROS 2 Orange Theme"}
            </Button>
            <Button size="lg" variant="sky" asChild>
              <Link href="/twin">
                <Compass className="h-4 w-4" />
                Launch Spatial Twin
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {discoverBanner && (
        <div className="flex items-center justify-between rounded-lg border border-eigenia-sky/40 bg-eigenia-sky/10 px-4 py-2.5 font-mono text-xs text-eigenia-sky">
          <span>{discoverBanner}</span>
          <Button size="sm" variant="ghost" onClick={() => setDiscoverBanner(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {discoverError && (
        <div className="flex items-center justify-between rounded-lg border border-eigenia-fault/40 bg-eigenia-fault/15 px-4 py-2.5 font-mono text-xs text-eigenia-fault">
          <span>{discoverError}</span>
          <Button size="sm" variant="ghost" onClick={() => setDiscoverError(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {/* Prominent Live Robot Network Interfaces (Wi-Fi + Ethernet) & Active ROS Mode Card */}
      {activeRobot && (
        <Card className={isRos2 ? "border-eigenia-orange/45 bg-eigenia-shell/95" : "border-white/10"}>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <Wifi className="h-4 w-4 text-eigenia-sky" />
                Live Robot Network Interfaces — {activeRobot.name}
                <Badge variant="neutral">Active Control IP: {activeRobot.ip_address}</Badge>
              </CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant={isRos2 ? "default" : "sky"}>
                  {isRos2 ? "ROS 2 HUMBLE (LTS 2027)" : "ROS 1 NOETIC (EOL 2025)"}
                </Badge>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={netRefreshing}
                  onClick={() => void handleRefreshNet()}
                >
                  <RefreshCw className={`h-3 w-3 ${netRefreshing ? "animate-spin" : ""}`} />
                  Refresh IPs
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link href="/config">ROS & Wi-Fi Config</Link>
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {/* Wi-Fi Interface Card */}
            <div className="flex flex-col justify-between gap-3 rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-white">
                    {wifiIface?.enabled ? (
                      <Wifi className="h-4 w-4 text-eigenia-sky" />
                    ) : (
                      <WifiOff className="h-4 w-4 text-eigenia-muted" />
                    )}
                    Wi-Fi ({wifiIface?.ifname || "wlan0"})
                  </div>
                  <Badge variant={wifiIface?.enabled ? "sky" : "fault"}>
                    {wifiIface?.enabled ? "ENABLED" : "DISABLED"}
                  </Badge>
                </div>
                <div className="space-y-1 font-mono text-[11px]">
                  <div className="text-base font-bold text-white">
                    {wifiIface?.ipv4 || "No IPv4 assigned"}
                  </div>
                  <div className="text-eigenia-muted">
                    SSID: <span className="text-white">{wifiIface?.ssid || wifiIface?.connection || "—"}</span>
                  </div>
                  <div className="text-[10px] text-eigenia-muted">
                    {wifiIface?.freq_mhz ? `${(wifiIface.freq_mhz / 1000).toFixed(1)} GHz` : "—"}
                    {wifiIface?.signal_pct != null ? ` · Signal ${wifiIface.signal_pct}%` : ""}
                    {wifiIface?.mac ? ` · ${wifiIface.mac}` : ""}
                  </div>
                </div>
              </div>
              {wifiIface?.ipv4 && (
                <Button
                  size="sm"
                  variant={activeRobot.ip_address === wifiIface.ipv4 ? "sky" : "default"}
                  disabled={activeRobot.ip_address === wifiIface.ipv4 || switchingIp === wifiIface.ipv4}
                  onClick={() => void handleUseIp(wifiIface.ipv4!)}
                >
                  {activeRobot.ip_address === wifiIface.ipv4 ? (
                    <>
                      <CheckCircle2 className="h-3.5 w-3.5" /> Active Control IP
                    </>
                  ) : switchingIp === wifiIface.ipv4 ? (
                    "Switching..."
                  ) : (
                    `Use IP (${wifiIface.ipv4})`
                  )}
                </Button>
              )}
            </div>

            {/* Ethernet Interface Cards */}
            {ethIfaces.length === 0 ? (
              <div className="flex flex-col justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5 md:col-span-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold text-white">
                    <Cable className="h-4 w-4 text-eigenia-amber" />
                    Ethernet (eth0 / eth1)
                  </div>
                  <Badge variant="neutral">QUERYING...</Badge>
                </div>
                <p className="font-mono text-[11px] text-eigenia-muted">
                  Click &ldquo;Refresh IPs&rdquo; to poll live `wlan0` and `eth0`/`eth1` addresses via SSH.
                </p>
              </div>
            ) : (
              ethIfaces.slice(0, 2).map((eth) => {
                const isActiveIp = Boolean(eth.ipv4 && activeRobot.ip_address === eth.ipv4);
                return (
                  <div
                    key={eth.ifname}
                    className="flex flex-col justify-between gap-3 rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5"
                  >
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 text-xs font-semibold text-white">
                          <Cable className="h-4 w-4 text-eigenia-amber" />
                          Ethernet ({eth.ifname})
                        </div>
                        <Badge variant={eth.enabled ? "amber" : "neutral"}>
                          {eth.enabled ? "ENABLED" : "DISABLED"}
                        </Badge>
                      </div>
                      <div className="space-y-1 font-mono text-[11px]">
                        <div className="text-base font-bold text-white">
                          {eth.ipv4 || "No link / No IPv4"}
                        </div>
                        <div className="text-eigenia-muted">
                          Profile: <span className="text-white">{eth.connection || eth.state || "—"}</span>
                        </div>
                        <div className="text-[10px] text-eigenia-muted">
                          State: {eth.state}
                          {eth.mac ? ` · ${eth.mac}` : ""}
                        </div>
                      </div>
                    </div>
                    {eth.ipv4 && (
                      <Button
                        size="sm"
                        variant={isActiveIp ? "sky" : "secondary"}
                        disabled={isActiveIp || switchingIp === eth.ipv4}
                        onClick={() => void handleUseIp(eth.ipv4!)}
                      >
                        {isActiveIp ? (
                          <>
                            <CheckCircle2 className="h-3.5 w-3.5" /> Active Control IP
                          </>
                        ) : switchingIp === eth.ipv4 ? (
                          "Switching..."
                        ) : (
                          `Use IP (${eth.ipv4})`
                        )}
                      </Button>
                    )}
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      )}

      {/* Facility & Spatial Twin KPI Cards */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Card>
          <CardContent className="p-4">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">Room Area</div>
            <div className="mt-1 font-mono text-2xl font-bold text-white">{roomArea.toFixed(1)} m²</div>
            <div className="mt-1 font-mono text-[10px] text-eigenia-sky">
              {frame?.point_count ?? 0} live LiDAR pts
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
              Extracted Walls
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-white">{wallCount}</div>
            <div className="mt-1 font-mono text-[10px] text-eigenia-muted">RANSAC structural segments</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
              Placed Equipment
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-eigenia-orange">{equipment.length}</div>
            <div className="mt-1 font-mono text-[10px] text-eigenia-muted">Pinned G_CPDT twins</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
              Spatial Dark Zones
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-eigenia-fault">{darkZones.length}</div>
            <div className="mt-1 font-mono text-[10px] text-eigenia-amber">Occlusion shadows & NBV</div>
          </CardContent>
        </Card>

        <Card className="col-span-2 md:col-span-1">
          <CardContent className="p-4">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
              Incomplete Assets
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-eigenia-amber">{incompleteCount}</div>
            <div className="mt-1 font-mono text-[10px] text-eigenia-muted">Needs Pass-3 enrichment</div>
          </CardContent>
        </Card>
      </section>

      {/* v2.1 Featured Studios Spotlight */}
      <section className="space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-eigenia-orange" />
            <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-white">
              What&apos;s New in v2.1 — Featured Studios
            </h2>
            <Badge variant="default">4 NEW &amp; UPGRADED WORKSPACES</Badge>
          </div>
          <span className="font-mono text-[11px] text-eigenia-muted">
            3D Hardware Prototyping · Photo-to-3D Room Twins · Live ROS 2 SLAM · Multi-Camera Overwatch
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {featuredStudios.map((studio) => {
            const Icon = studio.icon;
            return (
              <Link key={studio.href} href={studio.href} className="group">
                <Card className="h-full border-eigenia-orange/25 bg-eigenia-shell/90 transition-colors hover:border-eigenia-orange/60 hover:bg-eigenia-shell">
                  <CardContent className="flex h-full flex-col justify-between gap-3 p-4">
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex h-9 w-9 items-center justify-center rounded-md border border-white/10 bg-eigenia-obsidian">
                          <Icon className={`h-4 w-4 ${studio.accent}`} />
                        </div>
                        <Badge variant={studio.badgeVariant}>{studio.badge}</Badge>
                      </div>
                      <div className="text-sm font-semibold text-white">{studio.title}</div>
                      <p className="text-[11px] leading-relaxed text-eigenia-muted">{studio.desc}</p>
                    </div>
                    <div className="space-y-2.5 border-t border-white/10 pt-2.5">
                      <div className="flex flex-wrap gap-1">
                        {studio.highlights.map((tag) => (
                          <Badge key={tag} variant="neutral">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                      <div className="flex items-center justify-between font-mono text-[11px] font-semibold text-eigenia-orange">
                        <span>{studio.cta}</span>
                        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Quick-Launch Navigation Tiles (10 Operational Modules) */}
      <section className="space-y-2.5">
        <div className="flex items-center justify-between">
          <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-eigenia-muted">
            Core Fleet &amp; Spatial Operations
          </h2>
          <span className="font-mono text-[10px] text-eigenia-muted">
            {quickModules.length + featuredStudios.length} Studio Modules Ready
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {quickModules.map((mod) => {
            const Icon = mod.icon;
            return (
              <Link key={mod.href} href={mod.href} className="group">
                <Card className="h-full transition-colors hover:border-eigenia-orange/50 hover:bg-eigenia-shell">
                  <CardContent className="flex h-full flex-col justify-between gap-3 p-4">
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-eigenia-obsidian">
                          <Icon className={`h-4 w-4 ${mod.accent}`} />
                        </div>
                        <ArrowRight className="h-3.5 w-3.5 text-eigenia-muted transition-transform group-hover:translate-x-0.5 group-hover:text-eigenia-orange" />
                      </div>
                      <div className="text-xs font-semibold text-white">{mod.title}</div>
                      <p className="text-[11px] leading-relaxed text-eigenia-muted">{mod.desc}</p>
                    </div>
                    <div className="border-t border-white/10 pt-2 font-mono text-[10px] text-eigenia-sky">
                      {mod.metric}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Bottom Split: Live Discovered Robot Fleet & Top-5 Priority Dark-Zone Alerts */}
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* Live Discovered Robot Cards */}
        <Card className="xl:col-span-7">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-eigenia-orange" />
                Live Discovered Fleet ({robots.length})
              </CardTitle>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="secondary" onClick={() => void refreshRobots()}>
                  <RefreshCw className="h-3 w-3" /> Refresh
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link href="/catalog">Open Fleet Catalog</Link>
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {robots.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-white/15 bg-eigenia-obsidian p-8 text-center">
                <Wifi className="h-8 w-8 text-eigenia-muted" />
                <div className="space-y-1">
                  <div className="text-sm font-semibold text-white">No Robots Registered Yet</div>
                  <p className="max-w-md text-xs text-eigenia-muted">
                    Click &ldquo;Auto-Discover PuppyPi & LAN Fleet&rdquo; to probe UDP 9027 & TCP 9090/8080/22,
                    or manually add your PuppyPi IP in Fleet BOM & SBOM.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => void handleDiscover()} disabled={discovering}>
                    <Search className="h-3.5 w-3.5" /> Scan LAN Now
                  </Button>
                  <Button size="sm" variant="secondary" asChild>
                    <Link href="/catalog">Manual Add IP</Link>
                  </Button>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {robots.map((robot) => {
                  const volts =
                    robot.battery_mv != null && Number(robot.battery_mv) > 0
                      ? `${(Number(robot.battery_mv) / 1000).toFixed(2)}V`
                      : "N/A";
                  const temp =
                    robot.cpu_temp_c != null && Number.isFinite(Number(robot.cpu_temp_c))
                      ? `${Number(robot.cpu_temp_c).toFixed(1)}°C`
                      : "N/A";
                  const isOnline = robot.status === "online";

                  return (
                    <div
                      key={robot.id}
                      className="flex flex-col justify-between gap-3 rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5 transition hover:border-eigenia-orange/40"
                    >
                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="text-sm font-semibold text-white">{robot.name}</div>
                            <div className="font-mono text-[11px] text-eigenia-muted">
                              {robot.model}{" "}
                              {robot.serial_number ? `· ${String(robot.serial_number).slice(0, 12)}` : ""}
                            </div>
                          </div>
                          <Badge variant={isOnline ? "sky" : "amber"}>{robot.status || "unknown"}</Badge>
                        </div>

                        <div className="grid grid-cols-2 gap-1.5 rounded border border-white/5 bg-eigenia-shell p-2 font-mono text-[10px]">
                          <div>
                            <span className="text-eigenia-muted">IP: </span>
                            <span className="text-white">{robot.ip_address}</span>
                          </div>
                          <div>
                            <span className="text-eigenia-muted">MAC: </span>
                            <span className="text-white">{robot.mac_address || "Pending SSH"}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <Battery className="h-3 w-3 text-eigenia-sky" />
                            <span className="text-white">{volts}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <Thermometer className="h-3 w-3 text-eigenia-amber" />
                            <span className="text-white">{temp}</span>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-1.5">
                          <Badge variant="default">
                            {robot.active_ros_distro || "ROS1 Noetic"}
                          </Badge>
                          <Badge variant="neutral">WS :{robot.rosbridge_port}</Badge>
                          <Badge variant="neutral">FPV :{robot.video_port}</Badge>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-1.5 pt-1">
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => {
                            setActiveRobotId(robot.id);
                            router.push("/control");
                          }}
                        >
                          Control
                        </Button>
                        <Button
                          size="sm"
                          variant="sky"
                          onClick={() => {
                            setActiveRobotId(robot.id);
                            router.push("/catalog");
                          }}
                        >
                          Catalogue
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setActiveRobotId(robot.id);
                            router.push("/config");
                          }}
                        >
                          Configure
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Live Top-5 Dark-Zone / Incomplete Priority Alerts */}
        <Card className="xl:col-span-5">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-eigenia-amber" />
                Top-5 Dark-Zone & Incomplete Priority Alerts
              </CardTitle>
              <Badge variant={topAlerts.length > 0 ? "amber" : "sky"}>
                {focusQueue.length} TOTAL
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {topAlerts.length === 0 ? (
              <div className="rounded-lg border border-dashed border-white/10 bg-eigenia-obsidian p-6 text-center font-mono text-xs text-eigenia-muted">
                All scanned regions and pinned assets are currently verified. No active dark-zone alerts.
              </div>
            ) : (
              topAlerts.map((item) => {
                const statusVariant =
                  item.status === "DARK"
                    ? "fault"
                    : item.status === "INCOMPLETE"
                    ? "amber"
                    : "sky";
                return (
                  <div
                    key={item.id}
                    className="rounded-lg border border-white/10 bg-eigenia-obsidian p-3 transition hover:border-white/25"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge variant={statusVariant}>P{Math.round(Number(item.priority_score ?? 0))}</Badge>
                          <Badge variant={statusVariant}>{item.status}</Badge>
                          <span className="truncate text-xs font-semibold text-white">{item.title}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-eigenia-muted">{item.recommended_action}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[10px] text-eigenia-muted">
                          <span>
                            Target ({Number(item.target_x ?? 0).toFixed(2)}m, {Number(item.target_y ?? 0).toFixed(2)}m)
                          </span>
                          <span>· Completeness {item.completeness_pct ?? 0}%</span>
                          {Array.isArray(item.missing_fields) && item.missing_fields.length > 0 && (
                            <span className="text-eigenia-amber">
                              Missing: {item.missing_fields.slice(0, 3).join(", ")}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      <Button
                        size="sm"
                        variant="sky"
                        onClick={() => {
                          setFocusTarget({
                            x: item.target_x,
                            y: item.target_y,
                            label: item.title,
                            equipmentId: item.equipment_id,
                          });
                          if (item.equipment_id) {
                            setSelectedEquipmentId(item.equipment_id);
                          }
                          router.push("/twin");
                        }}
                      >
                        <Layers className="h-3 w-3" /> Inspect in Twin
                      </Button>
                      {item.equipment_id && (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={enrichingId === item.equipment_id}
                          onClick={() => void handleEnrichAsset(item.equipment_id!)}
                        >
                          <Sparkles className="h-3 w-3 text-eigenia-orange" />
                          {enrichingId === item.equipment_id ? "Enriching..." : "Pass-3 Research"}
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
