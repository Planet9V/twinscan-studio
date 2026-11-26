"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BatteryCharging,
  Bot,
  Camera,
  CheckCircle2,
  Compass,
  Eye,
  EyeOff,
  Home,
  Loader2,
  MapPin,
  Navigation,
  Play,
  Radar,
  RefreshCw,
  ScanLine,
  ShieldAlert,
  Sparkles,
  Square,
  Tag,
  Terminal,
  Volume2,
} from "lucide-react";
import { AnimatedMetric } from "@/components/ui/AnimatedMetric";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useStudio } from "@/context/StudioContext";
import {
  getRobotExplorerStatus,
  getRobotVideoStreamUrl,
  startRobotExplorer,
  stopRobotExplorer,
  triggerRobotRth,
  type ExplorerCaptureMode,
  type ExplorerStatus,
  type RobotRecord,
} from "@/lib/robotApi";

export interface AutonomousExplorerPanelProps {
  robot: RobotRecord | null;
}

const MAP_EXTENT_M = 4.0;
const SVG_SIZE = 440;

function worldToSvg(x: number, y: number): { sx: number; sy: number } {
  const sx = ((x + MAP_EXTENT_M) / (2 * MAP_EXTENT_M)) * SVG_SIZE;
  const sy = ((MAP_EXTENT_M - y) / (2 * MAP_EXTENT_M)) * SVG_SIZE;
  return { sx, sy };
}

function getExplorerStateBadge(state: ExplorerStatus["state"] | undefined): {
  label: string;
  variant: "default" | "sky" | "amber" | "fault" | "neutral";
  className: string;
  pulse: boolean;
} {
  switch (state) {
    case "exploring_transit":
      return {
        label: "EXPLORING FRONTIER",
        variant: "sky",
        className: "border-eigenia-sky/50 bg-eigenia-sky/20 text-eigenia-sky",
        pulse: true,
      };
    case "capturing_multi_angle":
      return {
        label: "CAPTURING 3D MULTI-ANGLE",
        variant: "default",
        className: "",
        pulse: true,
      };
    case "returning_home":
      return {
        label: "RETURNING TO HOME BASE (RTH)",
        variant: "amber",
        className: "",
        pulse: true,
      };
    case "parked_home":
      return {
        label: "PARKED AT HOME BASE",
        variant: "sky",
        className: "border-emerald-500/45 bg-emerald-500/20 text-emerald-400",
        pulse: false,
      };
    case "blocked_no_lidar":
      return {
        label: "BLOCKED · NO LIDAR",
        variant: "fault",
        className: "",
        pulse: true,
      };
    case "stopped":
      return {
        label: "STOPPED",
        variant: "neutral",
        className: "",
        pulse: false,
      };
    default:
      return {
        label: "STANDBY · READY",
        variant: "neutral",
        className: "",
        pulse: false,
      };
  }
}

export function AutonomousExplorerPanel({ robot }: AutonomousExplorerPanelProps) {
  const { frame, space, activeSpaceId, darkZones, activeRosMode } = useStudio();
  const robotId = robot?.id ?? null;

  const [showFpvPip, setShowFpvPip] = useState(true);
  const [fpvNonce, setFpvNonce] = useState(0);
  const [fpvError, setFpvError] = useState(false);
  const fpvImgRef = useRef<HTMLImageElement | null>(null);

  const abortFpvSocket = useCallback(() => {
    if (fpvImgRef.current) {
      fpvImgRef.current.src = "";
    }
  }, []);

  useEffect(() => {
    return () => {
      abortFpvSocket();
    };
  }, [abortFpvSocket]);

  useEffect(() => {
    if (!showFpvPip) {
      abortFpvSocket();
    }
  }, [showFpvPip, abortFpvSocket]);

  const [status, setStatus] = useState<ExplorerStatus | null>(null);
  const [captureMode, setCaptureMode] = useState<ExplorerCaptureMode>("multi_pitch");
  const [qualityPreset, setQualityPreset] = useState<"fast" | "balanced" | "studio_ultra">(
    "balanced"
  );
  const [maxIterations, setMaxIterations] = useState(6);
  const [targetCoveragePct, setTargetCoveragePct] = useState(85);
  const [rthBatteryV, setRthBatteryV] = useState(7.1);
  const [obstacleClearanceM, setObstacleClearanceM] = useState(0.5);
  const [maxSpeedCms, setMaxSpeedCms] = useState(10);
  const [announceVoice, setAnnounceVoice] = useState(true);
  const [requireLidar, setRequireLidar] = useState(true);

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const isActive = Boolean(status?.active);

  const pollStatus = useCallback(async (id: string) => {
    try {
      const st = await getRobotExplorerStatus(id);
      setStatus(st);
    } catch {
      // Non-fatal polling error
    }
  }, []);

  useEffect(() => {
    if (!robotId) {
      setStatus(null);
      return;
    }
    void pollStatus(robotId);
    const intervalMs = isActive ? 1200 : 3000;
    const timer = setInterval(() => {
      void pollStatus(robotId);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [robotId, isActive, pollStatus]);

  const walls = useMemo(() => {
    if (Array.isArray(frame?.walls) && frame.walls.length > 0) return frame.walls;
    if (Array.isArray(space?.walls) && space.walls.length > 0) return space.walls;
    return [];
  }, [frame?.walls, space?.walls]);

  const activeDarkZones = useMemo(() => {
    if (Array.isArray(frame?.dark_zones) && frame.dark_zones.length > 0) {
      return frame.dark_zones;
    }
    return Array.isArray(darkZones) ? darkZones : [];
  }, [frame?.dark_zones, darkZones]);

  const lidarDots = useMemo(() => {
    const pts = Array.isArray(frame?.points) ? frame.points : [];
    const stride = Math.max(1, Math.floor(pts.length / 280));
    const sampled: { sx: number; sy: number }[] = [];
    for (let i = 0; i < pts.length; i += stride) {
      const p = pts[i];
      if (!Array.isArray(p) || p.length < 2) continue;
      const x = Number(p[0]);
      const y = Number(p[1]);
      if (Math.abs(x) <= MAP_EXTENT_M && Math.abs(y) <= MAP_EXTENT_M) {
        sampled.push(worldToSvg(x, y));
      }
    }
    return sampled;
  }, [frame?.points]);

  if (!robot || !robotId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <Bot className="h-10 w-10 text-eigenia-orange/60" />
          <div className="text-sm font-semibold text-white">
            No Robot Selected for Autonomous Exploration
          </div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a PuppyPi robot to launch Stage-3 Autonomous Frontier Exploration, Multi-Angle
            Pitch/Yaw 3D Room Mapping, and Low-Battery Return-to-Home.
          </p>
        </CardContent>
      </Card>
    );
  }

  const handleStartExplore = async () => {
    setBusyAction("start");
    setBanner(null);
    try {
      const st = await startRobotExplorer(robotId, {
        space_id: activeSpaceId || null,
        max_iterations: maxIterations,
        target_coverage_pct: targetCoveragePct,
        capture_mode: captureMode,
        quality_preset: qualityPreset,
        rth_battery_v: rthBatteryV,
        max_speed_cms: maxSpeedCms,
        obstacle_clearance_m: obstacleClearanceM,
        apriltag_home_id: 0,
        announce_voice: announceVoice,
        require_lidar: requireLidar,
      });
      setStatus(st);
      if (st.state === "blocked_no_lidar") {
        setBanner({
          kind: "error",
          text:
            st.error ||
            "Explorer blocked by fail-safe: LD19 LiDAR is offline. Start LD19 first or disable Require LiDAR.",
        });
      } else {
        setBanner({
          kind: "ok",
          text: `Autonomous Frontier Explorer started (${captureMode} · RTH at ${rthBatteryV.toFixed(
            2
          )}V · target ${targetCoveragePct}% coverage).`,
        });
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to start Autonomous Explorer",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleRth = async () => {
    setBusyAction("rth");
    setBanner(null);
    try {
      const st = await triggerRobotRth(robotId);
      setStatus(st);
      setBanner({
        kind: "ok",
        text: "Return-to-Home (RTH) triggered — PuppyPi is navigating back to Home Base (0, 0) + AprilTag #0.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to trigger Return-to-Home",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleStopExplore = async () => {
    setBusyAction("stop");
    setBanner(null);
    try {
      const st = await stopRobotExplorer(robotId);
      setStatus(st);
      setBanner({
        kind: "ok",
        text: "Autonomous Explorer halted cleanly — velocity zeroed & body pitch reset to 0°.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to stop Autonomous Explorer",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const stateBadge = getExplorerStateBadge(status?.state);
  const batteryV =
    typeof status?.battery_v === "number"
      ? status.battery_v
      : typeof frame?.robot_pose?.battery_v === "number"
        ? frame.robot_pose.battery_v
        : typeof robot.battery_mv === "number"
          ? robot.battery_mv > 100
            ? robot.battery_mv / 1000
            : robot.battery_mv
          : null;
  const batteryPct =
    typeof status?.battery_pct === "number"
      ? status.battery_pct
      : batteryV !== null
        ? Math.max(0, Math.min(100, Math.round(((batteryV - 6.4) / 2.0) * 100)))
        : null;
  const activeRthThreshold = status?.rth_battery_v ?? rthBatteryV;
  const rthThresholdPct = Math.max(
    0,
    Math.min(100, Math.round(((activeRthThreshold - 6.4) / 2.0) * 100))
  );
  const batteryLow = batteryV !== null && batteryV <= activeRthThreshold + 0.15;

  const homeXY = status?.home_xy ?? [0, 0];
  const currentXY = status?.current_xy ?? [0, 0];
  const targetXY = status?.target_xy ?? null;
  const pathXY = Array.isArray(status?.path_xy) ? status!.path_xy : [];

  const homeSvg = worldToSvg(homeXY[0], homeXY[1]);
  const robotSvg = worldToSvg(currentXY[0], currentXY[1]);
  const targetSvg = targetXY ? worldToSvg(targetXY[0], targetXY[1]) : null;
  const pathPolyline = pathXY
    .map((pt) => {
      const p = worldToSvg(pt[0], pt[1]);
      return `${p.sx},${p.sy}`;
    })
    .join(" ");

  const coveragePct = Math.round(Number(status?.coverage_pct ?? 0));
  const eventLog = Array.isArray(status?.event_log) ? [...status!.event_log].reverse() : [];

  return (
    <div className="flex flex-col gap-4">
      {banner && (
        <div
          className={`flex items-center justify-between rounded-md border px-3 py-2 font-mono text-xs ${
            banner.kind === "ok"
              ? "border-eigenia-sky/40 bg-eigenia-sky/10 text-eigenia-sky"
              : "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault"
          }`}
        >
          <span>{banner.text}</span>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="ml-2 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 1. LIVE ANIMATED TELEMETRY STRIP + 2S LIPO BATTERY GAUGE */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <AnimatedMetric
          label="Room Coverage"
          value={coveragePct}
          unit="%"
          tone={coveragePct >= targetCoveragePct ? "emerald" : "sky"}
          progressPct={coveragePct}
          hint={`Target ${status?.target_coverage_pct ?? targetCoveragePct}%`}
        />
        <AnimatedMetric
          label="Frontier Iter"
          value={`${status?.iteration ?? 0}/${status?.max_iterations ?? maxIterations}`}
          tone={isActive ? "orange" : "default"}
          pulse={isActive}
          hint={status?.capture_mode || captureMode}
        />
        <AnimatedMetric
          label="Dark Zones"
          value={status?.dark_zones_remaining ?? activeDarkZones.length}
          tone={(status?.dark_zones_remaining ?? activeDarkZones.length) > 0 ? "amber" : "emerald"}
          hint="Remaining frontiers"
        />
        <AnimatedMetric
          label="3D Panels"
          value={status?.panels_captured ?? 0}
          tone="sky"
          hint="Multi-angle fused"
        />
        <AnimatedMetric
          label="Objects Found"
          value={status?.objects_identified ?? 0}
          tone="emerald"
          hint="Spatial Memory"
        />

        {/* 2S LiPo Battery Gauge with Visual RTH Voltage Threshold Marker */}
        <div
          className={`flex flex-col justify-between rounded-lg border p-2.5 transition ${
            batteryLow
              ? "border-eigenia-fault/60 bg-eigenia-fault/15"
              : "border-white/10 bg-eigenia-shell"
          }`}
        >
          <div className="flex items-center justify-between font-mono text-[10px] uppercase text-eigenia-muted">
            <span className="inline-flex items-center gap-1">
              <BatteryCharging
                className={`h-3 w-3 ${batteryLow ? "text-eigenia-fault" : "text-emerald-400"}`}
              />
              2S LiPo
            </span>
            <span className="tabular-nums text-[9px] text-eigenia-amber">
              RTH {activeRthThreshold.toFixed(2)}V
            </span>
          </div>
          <div className="mt-1 flex items-baseline justify-between font-mono">
            <span
              className={`text-base font-bold tabular-nums ${
                batteryLow ? "text-eigenia-fault" : "text-white"
              }`}
            >
              {batteryV !== null ? `${batteryV.toFixed(2)}V` : "--V"}
            </span>
            <span className="text-xs tabular-nums text-eigenia-sky">
              {batteryPct !== null ? `${batteryPct}%` : "--%"}
            </span>
          </div>
          {/* Voltage bar with visual RTH threshold line */}
          <div className="relative mt-1.5 h-2 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full transition-all duration-300 motion-reduce:transition-none ${
                batteryLow
                  ? "bg-eigenia-fault"
                  : (batteryPct ?? 100) < 45
                    ? "bg-eigenia-amber"
                    : "bg-emerald-400"
              }`}
              style={{ width: `${batteryPct ?? 0}%` }}
            />
            <div
              className="absolute bottom-0 top-0 w-0.5 bg-eigenia-orange shadow-[0_0_6px_rgba(224,90,16,0.9)]"
              style={{ left: `${rthThresholdPct}%` }}
              title={`Auto-RTH Threshold: ${activeRthThreshold.toFixed(2)} V`}
            />
          </div>
        </div>
      </div>

      {/* 2. ACTION BAR + LIVE POSE / APRILTAG HOME STATUS */}
      <Card className={isActive ? "border-eigenia-orange/60 bg-eigenia-shell" : "bg-eigenia-shell"}>
        <CardContent className="flex flex-col gap-3 p-3.5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant={stateBadge.variant}
              className={`${stateBadge.className} ${stateBadge.pulse ? "animate-pulse" : ""} font-mono text-[10px]`}
            >
              {stateBadge.label}
            </Badge>
            <Badge variant="neutral" className="font-mono text-[10px] tabular-nums">
              <Compass className="h-3 w-3 text-eigenia-sky" />
              Pitch {Math.round(status?.current_pitch_deg ?? 0)}° · Yaw{" "}
              {Math.round(status?.current_yaw_deg ?? 0)}°
            </Badge>
            <Badge
              variant={status?.apriltag_home_seen ? "sky" : "neutral"}
              className={
                status?.apriltag_home_seen
                  ? "border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
                  : "font-mono text-[10px]"
              }
            >
              <Tag className="h-3 w-3" />
              AprilTag #0 Home: {status?.apriltag_home_seen ? "LOCKED" : "STANDBY"}
            </Badge>
            <Badge
              variant={status?.lidar_live ? "sky" : "fault"}
              className={
                status?.lidar_live
                  ? "border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
                  : "font-mono text-[10px]"
              }
            >
              <Radar className="h-3 w-3" />
              LD19 {status?.lidar_live ? "LIVE" : "OFFLINE"}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="default"
              disabled={busyAction !== null || isActive}
              onClick={() => void handleStartExplore()}
              className="font-semibold"
            >
              {busyAction === "start" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Start Explore &amp; Map
            </Button>

            <Button
              size="sm"
              variant="sky"
              disabled={busyAction !== null}
              onClick={() => void handleRth()}
            >
              {busyAction === "rth" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Home className="h-3.5 w-3.5" />
              )}
              Return to Home Base (RTH)
            </Button>

            <Button
              size="sm"
              variant="destructive"
              disabled={busyAction !== null}
              onClick={() => void handleStopExplore()}
            >
              {busyAction === "stop" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              Stop Explorer
            </Button>
          </div>
        </CardContent>
      </Card>

      {status?.error && (
        <div className="flex items-center gap-2 rounded-md border border-eigenia-fault/50 bg-eigenia-fault/15 px-3 py-2 font-mono text-xs text-eigenia-fault">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{status.error}</span>
        </div>
      )}

      {/* 3. MAIN SPLIT: LIVE FRONTIER & DARK-ZONE MAP + SETTINGS & EVENT LOG */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* Left: Live Frontier & Dark-Zone SVG Map */}
        <InteractiveSurface
          title="Live Frontier, Dark-Zone & Breadcrumb Map (±4.0m)"
          subtitle="LD19 rays · Red Dark Zones · Emerald Home Base · Amber NBV Target · Orange Breadcrumbs"
          accent="orange"
          className="xl:col-span-7"
          contentClassName="space-y-3"
        >
          <div className="mx-auto aspect-square w-full max-w-[460px] overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
            <svg viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`} className="h-full w-full select-none">
              {/* 1m Grid */}
              {[-3, -2, -1, 0, 1, 2, 3].map((m) => {
                const pX = worldToSvg(m, 0).sx;
                const pY = worldToSvg(0, m).sy;
                return (
                  <g key={m}>
                    <line
                      x1={pX}
                      y1={0}
                      x2={pX}
                      y2={SVG_SIZE}
                      stroke={m === 0 ? "rgba(56,189,248,0.28)" : "rgba(255,255,255,0.06)"}
                      strokeWidth={m === 0 ? 1.2 : 1}
                    />
                    <line
                      x1={0}
                      y1={pY}
                      x2={SVG_SIZE}
                      y2={pY}
                      stroke={m === 0 ? "rgba(56,189,248,0.28)" : "rgba(255,255,255,0.06)"}
                      strokeWidth={m === 0 ? 1.2 : 1}
                    />
                  </g>
                );
              })}

              {/* Extracted Walls */}
              {walls.map((w, idx) => {
                const a = worldToSvg(w.x1, w.y1);
                const b = worldToSvg(w.x2, w.y2);
                return (
                  <line
                    key={`w-${idx}`}
                    x1={a.sx}
                    y1={a.sy}
                    x2={b.sx}
                    y2={b.sy}
                    stroke="#38bdf8"
                    strokeWidth={2}
                    strokeOpacity={0.65}
                  />
                );
              })}

              {/* Live LD19 Room Points */}
              {lidarDots.map((pt, idx) => (
                <circle
                  key={`pt-${idx}`}
                  cx={pt.sx}
                  cy={pt.sy}
                  r={1.6}
                  fill="#7dd3fc"
                  fillOpacity={0.55}
                />
              ))}

              {/* Red Spatial Dark Zones */}
              {activeDarkZones.map((dz) => {
                const c = worldToSvg(dz.centroid_x, dz.centroid_y);
                const polyPts =
                  Array.isArray(dz.polygon) && dz.polygon.length >= 3
                    ? dz.polygon
                        .map((p) => {
                          const sp = worldToSvg(Number(p[0]), Number(p[1]));
                          return `${sp.sx},${sp.sy}`;
                        })
                        .join(" ")
                    : null;
                return (
                  <g key={dz.id}>
                    {polyPts ? (
                      <polygon
                        points={polyPts}
                        fill="rgba(239,68,68,0.18)"
                        stroke="#ef4444"
                        strokeWidth={1.3}
                        strokeDasharray="4 3"
                      />
                    ) : (
                      <circle
                        cx={c.sx}
                        cy={c.sy}
                        r={16}
                        fill="rgba(239,68,68,0.18)"
                        stroke="#ef4444"
                        strokeWidth={1.3}
                        strokeDasharray="4 3"
                      />
                    )}
                    <circle cx={c.sx} cy={c.sy} r={3} fill="#ef4444" />
                  </g>
                );
              })}

              {/* Orange Breadcrumb Path */}
              {pathXY.length > 1 && (
                <polyline
                  points={pathPolyline}
                  fill="none"
                  stroke="#E05A10"
                  strokeWidth={2.4}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}
              {pathXY.map((pt, i) => {
                const p = worldToSvg(pt[0], pt[1]);
                return (
                  <circle
                    key={`bc-${i}`}
                    cx={p.sx}
                    cy={p.sy}
                    r={2.5}
                    fill="#E05A10"
                    fillOpacity={0.85}
                  />
                );
              })}

              {/* Emerald Home Base (0, 0) Pin */}
              <g>
                <circle
                  cx={homeSvg.sx}
                  cy={homeSvg.sy}
                  r={11}
                  fill="rgba(16,185,129,0.22)"
                  stroke="#10b981"
                  strokeWidth={2}
                />
                <text
                  x={homeSvg.sx}
                  y={homeSvg.sy + 3.5}
                  textAnchor="middle"
                  fill="#10b981"
                  fontSize="9"
                  fontFamily="JetBrains Mono, monospace"
                  fontWeight="bold"
                >
                  H
                </text>
              </g>

              {/* Amber Pulsing NBV Frontier Target */}
              {targetSvg && (
                <g>
                  <circle
                    cx={targetSvg.sx}
                    cy={targetSvg.sy}
                    r={14}
                    fill="rgba(245,158,11,0.18)"
                    stroke="#f59e0b"
                    strokeWidth={1.8}
                    strokeDasharray="3 3"
                  />
                  <circle cx={targetSvg.sx} cy={targetSvg.sy} r={5} fill="#f59e0b" />
                  <text
                    x={targetSvg.sx}
                    y={targetSvg.sy - 17}
                    textAnchor="middle"
                    fill="#f59e0b"
                    fontSize="9"
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="bold"
                  >
                    NBV
                  </text>
                </g>
              )}

              {/* Live PuppyPi Robot Position */}
              <g>
                <circle
                  cx={robotSvg.sx}
                  cy={robotSvg.sy}
                  r={7.5}
                  fill="rgba(224,90,16,0.3)"
                  stroke="#E05A10"
                  strokeWidth={2}
                />
                <circle cx={robotSvg.sx} cy={robotSvg.sy} r={3} fill="#ffffff" />
              </g>
            </svg>
          </div>

          {/* Map Legend */}
          <div className="flex flex-wrap items-center justify-center gap-3 font-mono text-[10px] text-eigenia-muted">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" /> Home Base (0,0)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-eigenia-fault" /> Dark Zone
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-eigenia-amber" /> Active NBV Target
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-4 rounded-full bg-eigenia-orange" /> Breadcrumb Path
            </span>
          </div>
        </InteractiveSurface>

        {/* Right: Live FPV PiP, Settings, Safety Guardrails & Live Event Log */}
        <div className="flex flex-col gap-4 xl:col-span-5">
          {/* Collapsible Live PuppyPi FPV Camera PiP */}
          <InteractiveSurface
            title="Live PuppyPi FPV Camera PiP"
            accent="sky"
            headerRight={
              <div className="flex items-center gap-1">
                {showFpvPip && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-1.5"
                    title="Reconnect FPV Stream"
                    onClick={() => {
                      abortFpvSocket();
                      setFpvError(false);
                      setFpvNonce((n) => n + 1);
                    }}
                  >
                    <RefreshCw className="h-3 w-3" />
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-6 px-2 font-mono text-[10px]"
                  onClick={() => {
                    if (showFpvPip) abortFpvSocket();
                    setFpvError(false);
                    setShowFpvPip((v) => !v);
                  }}
                >
                  {showFpvPip ? (
                    <>
                      <EyeOff className="h-3 w-3" /> Hide
                    </>
                  ) : (
                    <>
                      <Eye className="h-3 w-3" /> Show FPV
                    </>
                  )}
                </Button>
              </div>
            }
          >
            {showFpvPip ? (
              <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian">
                {!fpvError ? (
                  <img
                    ref={fpvImgRef}
                    key={`explore-fpv-${robotId}-${activeRosMode}-${fpvNonce}`}
                    src={`${getRobotVideoStreamUrl(
                      robotId,
                      activeRosMode === "ros2" ? "/image_raw" : "/usb_cam/image_raw"
                    )}&_epip=${fpvNonce}`}
                    alt="PuppyPi Explorer FPV PiP"
                    className="h-full w-full object-cover"
                    onError={() => setFpvError(true)}
                  />
                ) : (
                  <div className="flex flex-col items-center gap-1.5 p-4 text-center">
                    <Camera className="h-5 w-5 text-eigenia-muted" />
                    <span className="font-mono text-[10px] text-eigenia-muted">
                      FPV stream offline
                    </span>
                    <Button
                      size="sm"
                      variant="sky"
                      className="h-6 px-2 text-[10px]"
                      onClick={() => {
                        abortFpvSocket();
                        setFpvError(false);
                        setFpvNonce((n) => n + 1);
                      }}
                    >
                      Reconnect
                    </Button>
                  </div>
                )}
                <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap items-center gap-1">
                  <span className="rounded bg-eigenia-obsidian/85 px-1.5 py-0.5 font-mono text-[9px] text-eigenia-sky">
                    P:{Math.round(status?.current_pitch_deg ?? 0)}° · Y:
                    {Math.round(status?.current_yaw_deg ?? 0)}°
                  </span>
                  {status?.apriltag_home_seen && (
                    <span className="rounded border border-emerald-500/60 bg-emerald-500/85 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-white">
                      APRILTAG #0 LOCKED
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="font-mono text-[10px] text-eigenia-muted">
                FPV PiP collapsed (MJPEG socket closed). Click &quot;Show FPV&quot; to stream live.
              </div>
            )}
          </InteractiveSurface>

          <InteractiveSurface
            title="Multi-Angle Capture & Safety Settings"
            subtitle="Configure pitch/yaw sweep, 3D fusion preset, and automatic low-battery RTH"
            accent="sky"
            contentClassName="space-y-3"
          >
            {/* Capture Mode */}
            <div className="space-y-1">
              <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                Station Capture Schedule
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    { id: "quick_3", label: "Quick 3-Angle" },
                    { id: "level_360", label: "Level 360°" },
                    { id: "multi_pitch", label: "Multi-Pitch Up/Lvl/Dn" },
                  ] as const
                ).map((m) => (
                  <Button
                    key={m.id}
                    size="sm"
                    variant={captureMode === m.id ? "default" : "secondary"}
                    disabled={isActive}
                    className="h-7 px-2 font-mono text-[10px]"
                    onClick={() => setCaptureMode(m.id)}
                  >
                    {m.label}
                  </Button>
                ))}
              </div>
            </div>

            {/* Quality Preset */}
            <div className="space-y-1">
              <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                3D Fusion Quality Preset
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    { id: "fast", label: "Fast" },
                    { id: "balanced", label: "Balanced" },
                    { id: "studio_ultra", label: "Studio Ultra" },
                  ] as const
                ).map((p) => (
                  <Button
                    key={p.id}
                    size="sm"
                    variant={qualityPreset === p.id ? "sky" : "secondary"}
                    disabled={isActive}
                    className="h-7 px-2 font-mono text-[10px]"
                    onClick={() => setQualityPreset(p.id)}
                  >
                    {p.label}
                  </Button>
                ))}
              </div>
            </div>

            {/* Sliders Grid */}
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[10px]">
                  <span className="text-eigenia-muted">Max Iterations</span>
                  <span className="tabular-nums text-white">{maxIterations}</span>
                </div>
                <Slider
                  min={1}
                  max={12}
                  step={1}
                  disabled={isActive}
                  value={[maxIterations]}
                  onValueChange={([v]) => setMaxIterations(v)}
                />
              </div>

              <div className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[10px]">
                  <span className="text-eigenia-muted">Target Coverage</span>
                  <span className="tabular-nums text-emerald-400">{targetCoveragePct}%</span>
                </div>
                <Slider
                  min={50}
                  max={98}
                  step={2}
                  disabled={isActive}
                  value={[targetCoveragePct]}
                  onValueChange={([v]) => setTargetCoveragePct(v)}
                />
              </div>

              <div className="space-y-1 rounded border border-eigenia-amber/35 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[10px]">
                  <span className="text-eigenia-amber">Auto-RTH Voltage</span>
                  <span className="tabular-nums font-semibold text-eigenia-amber">
                    {rthBatteryV.toFixed(2)} V
                  </span>
                </div>
                <Slider
                  min={6.8}
                  max={7.6}
                  step={0.05}
                  disabled={isActive}
                  value={[rthBatteryV]}
                  onValueChange={([v]) => setRthBatteryV(Number(v.toFixed(2)))}
                />
              </div>

              <div className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[10px]">
                  <span className="text-eigenia-muted">LiDAR Clearance</span>
                  <span className="tabular-nums text-eigenia-orange">
                    {obstacleClearanceM.toFixed(2)} m
                  </span>
                </div>
                <Slider
                  min={0.35}
                  max={1.0}
                  step={0.05}
                  disabled={isActive}
                  value={[obstacleClearanceM]}
                  onValueChange={([v]) => setObstacleClearanceM(Number(v.toFixed(2)))}
                />
              </div>
            </div>

            <div className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
              <div className="flex justify-between font-mono text-[10px]">
                <span className="text-eigenia-muted">Max Exploration Speed</span>
                <span className="tabular-nums text-white">{maxSpeedCms} cm/s</span>
              </div>
              <Slider
                min={6}
                max={18}
                step={1}
                disabled={isActive}
                value={[maxSpeedCms]}
                onValueChange={([v]) => setMaxSpeedCms(v)}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-2">
                <span className="flex items-center gap-1 text-xs text-white">
                  <Volume2 className="h-3 w-3 text-eigenia-sky" /> Voice Callouts
                </span>
                <Switch
                  checked={announceVoice}
                  disabled={isActive}
                  onCheckedChange={setAnnounceVoice}
                />
              </div>
              <div className="flex items-center justify-between rounded border border-eigenia-orange/35 bg-eigenia-orange/10 px-2.5 py-2">
                <span className="flex items-center gap-1 text-xs text-white">
                  <ShieldAlert className="h-3 w-3 text-eigenia-orange" /> Require LD19
                </span>
                <Switch
                  checked={requireLidar}
                  disabled={isActive}
                  onCheckedChange={setRequireLidar}
                />
              </div>
            </div>
          </InteractiveSurface>

          {/* Live Exploration Event Log */}
          <InteractiveSurface
            title={`Live Exploration Event Log (${eventLog.length})`}
            accent="none"
            headerRight={
              <Badge variant="neutral" className="font-mono text-[9px]">
                <Terminal className="h-2.5 w-2.5" /> LIVE
              </Badge>
            }
            contentClassName="max-h-56 space-y-1.5 overflow-y-auto"
          >
            {eventLog.length === 0 ? (
              <div className="rounded border border-dashed border-white/10 p-4 text-center font-mono text-[10px] text-eigenia-muted">
                No exploration events yet. Click{" "}
                <span className="font-semibold text-white">Start Explore &amp; Map</span> above to
                begin autonomous dark-zone frontier mapping.
              </div>
            ) : (
              eventLog.map((ev, idx) => (
                <div
                  key={`ev-${idx}-${ev.ts}`}
                  className={`flex items-start justify-between gap-2 rounded border px-2.5 py-1.5 font-mono text-[10px] ${
                    ev.level === "warn"
                      ? "border-eigenia-amber/40 bg-eigenia-amber/10 text-eigenia-amber"
                      : ev.level === "ok"
                        ? "border-emerald-500/35 bg-emerald-500/10 text-emerald-300"
                        : "border-white/10 bg-eigenia-obsidian text-eigenia-ink"
                  }`}
                >
                  <span className="leading-snug">{ev.message}</span>
                  <span className="shrink-0 text-[9px] opacity-70">
                    {ev.ts ? new Date(ev.ts).toLocaleTimeString() : ""}
                  </span>
                </div>
              ))
            )}
          </InteractiveSurface>
        </div>
      </div>
    </div>
  );
}
