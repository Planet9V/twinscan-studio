"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Battery,
  BookOpen,
  Bot,
  Camera,
  CheckCircle2,
  Cpu,
  Database,
  Loader2,
  Radar,
  RefreshCw,
  Rocket,
  Route,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { fetchHealth, fetchLidarSettings, type LidarSettings } from "@/lib/api";
import { listRobots, type RobotRecord } from "@/lib/robotApi";
import { cn } from "@/lib/utils";

export interface OnboardingWizardProps {
  onOpenWikiPage: (slug: string) => void;
}

type RoleId = "maker" | "operator" | "admin" | "developer";
type HardwareId = "puppypi" | "pi5_workbench" | "microbit" | "local_cameras" | "simulator";

interface ReadinessState {
  probing: boolean;
  probedAt: string | null;
  backendOk: boolean;
  pgStatus: string;
  neo4jStatus: string;
  lidar: LidarSettings | null;
  robots: RobotRecord[];
  error: string | null;
}

const ROLES: Array<{
  id: RoleId;
  title: string;
  tagline: string;
  badge: string;
  recommendedSlug: string;
}> = [
  {
    id: "maker",
    title: "Maker & Robotics Builder",
    tagline: "Prototype with PuppyPi Pro, Raspberry Pi 5, micro:bit v2.21, and 3D room scans.",
    badge: "Flagship",
    recommendedSlug: "00-introduction",
  },
  {
    id: "operator",
    title: "Operator & Field Pilot",
    tagline: "Drive PuppyPi FPV, scan rooms into 3D .glb twins, run autonomous patrol & RTH.",
    badge: "Mission Ops",
    recommendedSlug: "04-user-directions",
  },
  {
    id: "admin",
    title: "Admin & Fleet Operations",
    tagline: "Manage Docker, PostgreSQL 18, Neo4j 5, ROS 2 auto-boot, PMIC power & logs.",
    badge: "Infra",
    recommendedSlug: "05-admin-guide",
  },
  {
    id: "developer",
    title: "Developer & Architect",
    tagline: "Extend FastAPI services, ROSBridge watchdogs, Three.js/Babylon.js twins & pytest.",
    badge: "Code",
    recommendedSlug: "06-developer-guide",
  },
];

const HARDWARE_OPTIONS: Array<{
  id: HardwareId;
  title: string;
  subtitle: string;
  badge: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    id: "puppypi",
    title: "Hiwonder PuppyPi Pro",
    subtitle: "Pi 5 8GB + LD19 360° LiDAR + USB FPV + WonderEcho Pro + ROS 2 Humble",
    badge: "Flagship Example",
    icon: Bot,
  },
  {
    id: "pi5_workbench",
    title: "2nd Raspberry Pi 5 Workbench",
    subtitle: "Dedicated edge compute, camera capture, or sensor hub node",
    badge: "Edge Node",
    icon: Cpu,
  },
  {
    id: "microbit",
    title: "BBC micro:bit v2.21",
    subtitle: "3.3V BLE/USB-serial telemetry, 5×5 LED matrix & accelerometer node",
    badge: "MCU",
    icon: Sparkles,
  },
  {
    id: "local_cameras",
    title: "100% Cloud-Free Local Cameras",
    subtitle: "LAN RTSP/MJPEG cameras + Pi Zero 2 W USB gadget clip harvester",
    badge: "Zero Cloud",
    icon: Camera,
  },
  {
    id: "simulator",
    title: "Simulator / No Hardware Yet",
    subtitle: "Explore full 2D/3D LiDAR twins, AI Co-Design & Spatial Memory in Docker",
    badge: "Sandbox",
    icon: Radar,
  },
];

interface BlueprintStep {
  step: number;
  title: string;
  detail: string;
  href: string;
  cta: string;
  wikiSlug: string;
  wikiLabel: string;
}

function buildBlueprint(
  role: RoleId,
  hardware: Set<HardwareId>,
  readiness: ReadinessState
): BlueprintStep[] {
  const hasPuppy = hardware.has("puppypi");
  const hasMicrobitOrPi = hardware.has("microbit") || hardware.has("pi5_workbench");
  const hasLocalCam = hardware.has("local_cameras");
  const lidarLive = Boolean(readiness.lidar?.robot_scan_connected);

  if (role === "admin") {
    return [
      {
        step: 1,
        title: "Verify Docker, PostgreSQL 18 & Neo4j 5 Health",
        detail: `Current status: PG18 (${readiness.pgStatus}) · Neo4j (${readiness.neo4jStatus}). Configure OpenRouter keys and inspect blob storage.`,
        href: "/config?tab=databases",
        cta: "Open Config & Storage",
        wikiSlug: "05-admin-guide",
        wikiLabel: "Admin Guide",
      },
      {
        step: 2,
        title: "Lock ROS 2 Humble Persistent Auto-Boot on PuppyPi Pro",
        detail: "Confirm start_node_ros2.service boots cleanly with CycloneDDS, single-instance LD19, and live FPV stream.",
        href: "/config?tab=robot",
        cta: "Manage Robot OS & ROS 2",
        wikiSlug: "05-admin-guide",
        wikiLabel: "ROS 2 Operations",
      },
      {
        step: 3,
        title: "Audit Pi 5 PMIC Rails, USB Power & MicroSD Disk",
        detail: "Check DA9091 EXT5V voltage, USB port draw (<1600 mA), and run 1-click Clean Stale Logs if MicroSD >= 85%.",
        href: "/catalog?tab=hardware",
        cta: "Inspect 3D Pi 5 BOM",
        wikiSlug: "07-support-troubleshooting",
        wikiLabel: "Power & Log Runbook",
      },
      {
        step: 4,
        title: "Verify Safe Updates & CycloneDX SBOM",
        detail: "Export full CycloneDX SBOM and run dry-run host APT / ROS pip checks before applying updates with automatic rollback tags.",
        href: "/catalog?tab=updates",
        cta: "Open Safe Updates",
        wikiSlug: "05-admin-guide",
        wikiLabel: "Update Lifecycle",
      },
      {
        step: 5,
        title: "Reconcile Neo4j Knowledge Graph & Spatial Memory",
        detail: "Inspect G_CPDT asset topology and verify pgvector semantic search across saved spaces.",
        href: "/graph",
        cta: "Open Knowledge Graph",
        wikiSlug: "08-site-tree",
        wikiLabel: "Complete Site Tree",
      },
    ];
  }

  if (role === "developer") {
    return [
      {
        step: 1,
        title: "Read the Principal Architecture Overview",
        detail: "Understand how FastAPI, ROSBridge auto-type watchdogs, PG18 pgvector, Neo4j, and Next.js 16 connect.",
        href: "/wiki?tab=docs&page=01-onboarding-principal",
        cta: "Read Principal Guide",
        wikiSlug: "01-onboarding-principal",
        wikiLabel: "Principal Onboarding",
      },
      {
        step: 2,
        title: "Explore the Interactive Site Tree & API Surface",
        detail: "Inspect all 12 Next.js App Router workspaces and backend route modules visually.",
        href: "/wiki?tab=sitetree",
        cta: "Open Site Tree",
        wikiSlug: "08-site-tree",
        wikiLabel: "Site Tree Spec",
      },
      {
        step: 3,
        title: "Inspect Live 3D Reconstruction & .GLB Pipeline",
        detail: "Test Camera + LD19 + Depth Anything V2 mesh synthesis in Three.js 0.187 & Babylon.js 9 PBR.",
        href: "/twin",
        cta: "Launch Spatial Twin",
        wikiSlug: "03-capabilities-guide",
        wikiLabel: "3D Fusion Deep-Dive",
      },
      {
        step: 4,
        title: "Prototype Hardware Envelopes in Lab Architect",
        detail: "Exercise the 5-Tier Creativity Co-Design engine, 2D React Flow wiring, and 3D assembly generator.",
        href: "/architect?tab=studio",
        cta: "Open Lab Architect",
        wikiSlug: "06-developer-guide",
        wikiLabel: "Developer Guide",
      },
      {
        step: 5,
        title: "Review Testing & Hardening Guardrails",
        detail: "Follow Senior Architect modularity (src/ + tests/), 158+ pytest coverage, and zero-raw-CSS Tailwind standards.",
        href: "/wiki?tab=docs&page=06-developer-guide",
        cta: "Open Dev Standards",
        wikiSlug: "06-developer-guide",
        wikiLabel: "Developer Guide",
      },
    ];
  }

  // Maker & Operator tailored flagship PuppyPi Pro path
  return [
    {
      step: 1,
      title: hasPuppy
        ? lidarLive
          ? "PuppyPi Pro Connected — Verify Live Telemetry & E-STOP"
          : "Discover & Connect PuppyPi Pro on Your LAN"
        : "Launch Command Center & Verify Live Stream",
      detail: hasPuppy
        ? lidarLive
          ? `LD19 LiDAR is streaming live (${Number(readiness.lidar?.actual_hz ?? 0).toFixed(1)} Hz). Confirm live FPV video and test safe stance.`
          : "Run 1-click LAN discovery on Mission Control or verify PuppyPi IP & ROS 2 Humble bridge."
        : "Open Mission Control to inspect live simulator telemetry, fleet status, and dark-zone alerts.",
      href: hasPuppy ? "/control" : "/",
      cta: hasPuppy ? "Open Robot Control" : "Open Mission Control",
      wikiSlug: "04-user-directions",
      wikiLabel: "Operating Directions",
    },
    {
      step: 2,
      title: "Capture Your First 3D Room Twin & Export .GLB",
      detail: "Fuse PuppyPi FPV camera + 360° LD19 LiDAR + Depth Anything V2 into a real-scale textured 3D mesh and download Full Room .glb.",
      href: "/twin",
      cta: "Launch Spatial LiDAR Twin",
      wikiSlug: "03-capabilities-guide",
      wikiLabel: "3D Twin Guide",
    },
    {
      step: 3,
      title: "Run Autonomous Frontier Exploration & Low-Battery RTH",
      detail: "Let PuppyPi map spatial dark zones automatically with live FPV PiP, 5-sector obstacle avoidance, and automatic 2S LiPo Return-to-Home.",
      href: "/patrol?tab=explore",
      cta: "Open Autonomous Explorer",
      wikiSlug: "04-user-directions",
      wikiLabel: "Explorer & RTH Guide",
    },
    {
      step: 4,
      title: hasLocalCam
        ? "Curate Spatial Memory & Add 100% Cloud-Free Local Cameras"
        : "Enroll People, Objects & Voice Commands (Hey OX)",
      detail: hasLocalCam
        ? "Upload local .mp4/.jpg clips or generate the Pi Zero 2 W USB gadget script to feed offline YOLO11n + Face ID straight into Spatial Memory Pro."
        : "Use YuNet + SFace 128-D face recognition, YOLO11n object sightings, and Bento/Grid/Line Spatial Memory Pro.",
      href: hasLocalCam ? "/architect?tab=profiles" : "/vision?tab=memory",
      cta: hasLocalCam ? "Open Local Camera Bridge" : "Open Spatial Memory Pro",
      wikiSlug: "03-capabilities-guide",
      wikiLabel: "Vision & Memory Guide",
    },
    {
      step: 5,
      title: hasMicrobitOrPi
        ? "Co-Design Multi-Device Builds (PuppyPi + Pi 5 + micro:bit)"
        : "Seed Your Lab Inventory & Co-Design Your Next Build",
      detail: "Use the 5-Tier Creativity Dial in Lab Architect to check 3.3V/5V electrical guardrails and generate synchronized 2D wiring + 3D assemblies.",
      href: "/architect?tab=studio",
      cta: "Launch Lab Architect",
      wikiSlug: "02-onboarding-zero-to-hero",
      wikiLabel: "Zero-to-Hero Path",
    },
  ];
}

export function OnboardingWizard({ onOpenWikiPage }: OnboardingWizardProps): React.JSX.Element {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [role, setRole] = useState<RoleId>("maker");
  const [hardware, setHardware] = useState<Set<HardwareId>>(
    () => new Set<HardwareId>(["puppypi", "pi5_workbench"])
  );

  const [readiness, setReadiness] = useState<ReadinessState>({
    probing: false,
    probedAt: null,
    backendOk: false,
    pgStatus: "probing",
    neo4jStatus: "probing",
    lidar: null,
    robots: [],
    error: null,
  });

  const runReadinessProbe = useCallback(async () => {
    setReadiness((prev) => ({ ...prev, probing: true, error: null }));
    try {
      const [healthRes, lidarRes, robotsRes] = await Promise.allSettled([
        fetchHealth(),
        fetchLidarSettings(),
        listRobots(),
      ]);

      const health =
        healthRes.status === "fulfilled" ? (healthRes.value as Record<string, unknown>) : null;
      const lidar = lidarRes.status === "fulfilled" ? lidarRes.value : null;
      const robots = robotsRes.status === "fulfilled" ? robotsRes.value.robots : [];

      const pgRaw = health?.postgres ?? health?.database ?? (health ? "connected" : "offline");
      const neoRaw = health?.neo4j ?? "unknown";

      setReadiness({
        probing: false,
        probedAt: new Date().toLocaleTimeString(),
        backendOk: Boolean(health),
        pgStatus: typeof pgRaw === "object" && pgRaw !== null ? String((pgRaw as Record<string, unknown>).status ?? "connected") : String(pgRaw),
        neo4jStatus: typeof neoRaw === "object" && neoRaw !== null ? String((neoRaw as Record<string, unknown>).status ?? "unknown") : String(neoRaw),
        lidar,
        robots,
        error: health ? null : "Backend API unreachable on configured URL — verify Docker stack is up.",
      });
    } catch (err) {
      setReadiness((prev) => ({
        ...prev,
        probing: false,
        error: err instanceof Error ? err.message : "Readiness probe failed",
      }));
    }
  }, []);

  useEffect(() => {
    void runReadinessProbe();
  }, [runReadinessProbe]);

  const toggleHardware = (id: HardwareId) => {
    setHardware((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size > 1) next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const blueprint = useMemo(
    () => buildBlueprint(role, hardware, readiness),
    [role, hardware, readiness]
  );

  const primaryRobot = readiness.robots[0] ?? null;
  const batteryVolts =
    primaryRobot?.battery_mv && primaryRobot.battery_mv > 0
      ? (primaryRobot.battery_mv / 1000).toFixed(2)
      : null;

  return (
    <div className="space-y-4">
      {/* 4-Step Progress Bar */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(
          [
            { n: 1, label: "1. Choose Role" },
            { n: 2, label: "2. Select Hardware" },
            { n: 3, label: "3. Live Readiness Probe" },
            { n: 4, label: "4. Your Blueprint" },
          ] as const
        ).map((item) => {
          const active = step === item.n;
          const completed = step > item.n;
          return (
            <button
              key={item.n}
              type="button"
              onClick={() => setStep(item.n)}
              className={cn(
                "flex items-center justify-between rounded-lg border px-3 py-2.5 text-left font-mono text-xs transition-all motion-reduce:transition-none",
                active
                  ? "border-eigenia-orange bg-eigenia-orange/15 text-white shadow-[0_0_16px_rgba(224,90,16,0.2)]"
                  : completed
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400"
                    : "border-white/10 bg-eigenia-shell text-eigenia-muted hover:border-white/25 hover:text-white"
              )}
            >
              <span className="truncate font-semibold">{item.label}</span>
              {completed ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              ) : (
                <span
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    active ? "bg-eigenia-orange" : "bg-white/20"
                  )}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* STEP 1: Role Selection */}
      {step === 1 && (
        <Card className="border-white/10">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Rocket className="h-4 w-4 text-eigenia-orange" />
              Step 1 — What Are You Building or Operating Today?
            </CardTitle>
            <p className="text-xs text-eigenia-muted">
              We tailor your quickstart blueprint, workspace links, and Wiki reading path around
              your goal (using <span className="font-semibold text-white">Hiwonder PuppyPi Pro</span>{" "}
              as our flagship live maker example).
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {ROLES.map((r) => {
                const selected = role === r.id;
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setRole(r.id)}
                    className={cn(
                      "rounded-xl border p-4 text-left transition-all motion-reduce:transition-none",
                      selected
                        ? "border-eigenia-orange bg-eigenia-orange/15 shadow-[0_0_20px_rgba(224,90,16,0.18)]"
                        : "border-white/10 bg-eigenia-obsidian hover:border-eigenia-sky/50"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-white">{r.title}</span>
                      <Badge variant={selected ? "default" : "neutral"}>{r.badge}</Badge>
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-eigenia-muted">{r.tagline}</p>
                  </button>
                );
              })}
            </div>

            <div className="flex items-center justify-between border-t border-white/10 pt-3">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onOpenWikiPage(ROLES.find((r) => r.id === role)?.recommendedSlug ?? "00-introduction")}
              >
                <BookOpen className="h-3.5 w-3.5" />
                Jump Straight to Role Wiki Guide
              </Button>
              <Button size="sm" variant="default" onClick={() => setStep(2)}>
                Next: Select Hardware
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* STEP 2: Hardware Selection */}
      {step === 2 && (
        <Card className="border-white/10">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-eigenia-sky" />
              Step 2 — Choose Your Hardware Stack (Multi-Select)
            </CardTitle>
            <p className="text-xs text-eigenia-muted">
              Eigenia TwinScan runs 100% locally in Docker and supports 6 hardware envelopes from
              quadruped robots to microcontrollers and cloud-free local cameras.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {HARDWARE_OPTIONS.map((hw) => {
                const Icon = hw.icon;
                const selected = hardware.has(hw.id);
                return (
                  <button
                    key={hw.id}
                    type="button"
                    onClick={() => toggleHardware(hw.id)}
                    className={cn(
                      "flex flex-col justify-between gap-2 rounded-xl border p-3.5 text-left transition-all motion-reduce:transition-none",
                      selected
                        ? "border-eigenia-sky bg-eigenia-sky/15 shadow-[0_0_18px_rgba(56,189,248,0.16)]"
                        : "border-white/10 bg-eigenia-obsidian hover:border-white/25"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon
                          className={cn(
                            "h-4 w-4 shrink-0",
                            selected ? "text-eigenia-sky" : "text-eigenia-muted"
                          )}
                        />
                        <span className="text-xs font-semibold text-white">{hw.title}</span>
                      </div>
                      <Badge variant={selected ? "sky" : "neutral"} className="text-[9px]">
                        {hw.badge}
                      </Badge>
                    </div>
                    <p className="font-mono text-[10px] leading-relaxed text-eigenia-muted">
                      {hw.subtitle}
                    </p>
                  </button>
                );
              })}
            </div>

            <div className="flex items-center justify-between border-t border-white/10 pt-3">
              <Button size="sm" variant="secondary" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button
                size="sm"
                variant="default"
                onClick={() => {
                  setStep(3);
                  void runReadinessProbe();
                }}
              >
                Next: Run Live Readiness Probe
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* STEP 3: Live System Readiness Probe */}
      {step === 3 && (
        <Card className="border-eigenia-sky/35">
          <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-eigenia-sky" />
                Step 3 — Live System Readiness Probe
              </CardTitle>
              <p className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
                Probes live `/health`, `/api/lidar/settings`, and `/api/robots` directly from your
                running Eigenia Docker stack.
                {readiness.probedAt ? ` Last checked: ${readiness.probedAt}` : ""}
              </p>
            </div>
            <Button
              size="sm"
              variant="sky"
              disabled={readiness.probing}
              onClick={() => void runReadinessProbe()}
            >
              {readiness.probing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Re-Probe Live Stack
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            {readiness.error && (
              <div className="flex items-center gap-2 rounded-md border border-eigenia-fault/50 bg-eigenia-fault/15 px-3 py-2 font-mono text-xs text-eigenia-fault">
                <XCircle className="h-4 w-4 shrink-0" />
                <span>{readiness.error}</span>
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {/* Storage & Graph */}
              <InteractiveSurface
                title="Backend & Databases"
                subtitle="FastAPI · Postgres 18 · Neo4j 5"
                accent={readiness.backendOk ? "emerald" : "fault"}
                badge={
                  <Badge variant={readiness.backendOk ? "sky" : "fault"}>
                    {readiness.backendOk ? "ONLINE" : "OFFLINE"}
                  </Badge>
                }
              >
                <div className="space-y-1.5 font-mono text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-eigenia-muted">
                      <Database className="h-3 w-3" /> PostgreSQL 18
                    </span>
                    <span className="text-white">{readiness.pgStatus}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-eigenia-muted">
                      <ShieldCheck className="h-3 w-3" /> Neo4j 5 Graph
                    </span>
                    <span className="text-white">{readiness.neo4jStatus}</span>
                  </div>
                </div>
              </InteractiveSurface>

              {/* LiDAR Telemetry */}
              <InteractiveSurface
                title="360° LD19 LiDAR Stream"
                subtitle="Real-time ROS 2 /scan bridge"
                accent={readiness.lidar?.robot_scan_connected ? "emerald" : "amber"}
                badge={
                  <Badge variant={readiness.lidar?.robot_scan_connected ? "sky" : "amber"}>
                    {readiness.lidar?.robot_scan_connected
                      ? "LIVE ROS 2"
                      : String(readiness.lidar?.source_mode ?? "checking").toUpperCase()}
                  </Badge>
                }
              >
                <div className="space-y-1.5 font-mono text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-eigenia-muted">Source Mode</span>
                    <span className="text-white">{readiness.lidar?.source_mode ?? "--"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-eigenia-muted">Live Rate</span>
                    <span className="tabular-nums text-eigenia-sky">
                      {readiness.lidar?.actual_hz != null
                        ? `${Number(readiness.lidar.actual_hz).toFixed(1)} Hz`
                        : "-- Hz"}
                    </span>
                  </div>
                </div>
              </InteractiveSurface>

              {/* Connected PuppyPi Fleet */}
              <InteractiveSurface
                title="Registered Fleet Robots"
                subtitle="PuppyPi Pro & ROS 2 Nodes"
                accent={readiness.robots.length > 0 ? "orange" : "amber"}
                badge={
                  <Badge variant={readiness.robots.length > 0 ? "default" : "neutral"}>
                    {readiness.robots.length} Unit(s)
                  </Badge>
                }
              >
                {primaryRobot ? (
                  <div className="space-y-1.5 font-mono text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="truncate text-white">{primaryRobot.name}</span>
                      <span className="text-eigenia-sky">{primaryRobot.ip_address}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1 text-eigenia-muted">
                        <Battery className="h-3 w-3" /> 2S LiPo
                      </span>
                      <span className="tabular-nums text-emerald-400">
                        {batteryVolts ? `${batteryVolts} V` : primaryRobot.status}
                      </span>
                    </div>
                  </div>
                ) : (
                  <p className="font-mono text-[10px] text-eigenia-muted">
                    No robots registered yet. Click Auto-Discover on Mission Control or continue in
                    Simulator mode.
                  </p>
                )}
              </InteractiveSurface>
            </div>

            <div className="flex items-center justify-between border-t border-white/10 pt-3">
              <Button size="sm" variant="secondary" onClick={() => setStep(2)}>
                Back
              </Button>
              <Button size="sm" variant="default" onClick={() => setStep(4)}>
                Generate My 5-Step Blueprint
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* STEP 4: Personalized 5-Step Clickable Blueprint */}
      {step === 4 && (
        <Card className="border-eigenia-orange/45">
          <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Route className="h-4 w-4 text-eigenia-orange" />
                Step 4 — Your Personalized 5-Step Launch Blueprint
              </CardTitle>
              <p className="mt-0.5 text-xs text-eigenia-muted">
                Tailored for{" "}
                <span className="font-semibold text-white">
                  {ROLES.find((r) => r.id === role)?.title}
                </span>{" "}
                with {hardware.size} hardware envelope(s) selected.
              </p>
            </div>
            <Button size="sm" variant="secondary" onClick={() => setStep(1)}>
              <Wrench className="h-3.5 w-3.5" />
              Re-Configure Wizard
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {blueprint.map((b) => (
              <div
                key={b.step}
                className="flex flex-col gap-3 rounded-xl border border-white/10 bg-eigenia-obsidian p-3.5 transition-colors hover:border-eigenia-orange/50 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-eigenia-orange/60 bg-eigenia-orange/20 font-mono text-xs font-bold text-eigenia-orange">
                    {b.step}
                  </div>
                  <div className="space-y-1">
                    <div className="text-sm font-semibold text-white">{b.title}</div>
                    <p className="text-xs leading-relaxed text-eigenia-muted">{b.detail}</p>
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onOpenWikiPage(b.wikiSlug)}
                  >
                    <BookOpen className="h-3.5 w-3.5" />
                    {b.wikiLabel}
                  </Button>
                  <Button size="sm" variant="default" asChild>
                    <Link href={b.href}>
                      {b.cta}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
