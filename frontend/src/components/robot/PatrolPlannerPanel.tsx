"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Camera,
  CheckCircle2,
  Compass,
  Eye,
  EyeOff,
  Loader2,
  MapPin,
  Navigation,
  Play,
  Radar,
  RefreshCw,
  Save,
  ShieldAlert,
  Square,
  Trash2,
  Undo2,
  Volume2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { AutonomousExplorerPanel } from "@/components/robot/AutonomousExplorerPanel";
import { OverwatchHudCard } from "@/components/vision/OverwatchHudCard";
import { useStudio } from "@/context/StudioContext";
import {
  deletePatrolRoute,
  fetchPatrolStatus,
  listPatrolRoutes,
  savePatrolRoute,
  startRobotLidarNode,
  startRobotPatrol,
  stopRobotPatrol,
  type PatrolRoute,
  type PatrolStatus,
  type PatrolWaypoint,
} from "@/lib/aiVisionApi";
import { getRobotVideoStreamUrl, type RobotRecord } from "@/lib/robotApi";
import { suggestBlindSpotMappingRoute } from "@/lib/overwatchApi";

interface PatrolPlannerPanelProps {
  robot: RobotRecord | null;
}

const MAP_EXTENT_M = 4.0;
const SVG_SIZE = 440;

function worldToSvg(x: number, y: number): { sx: number; sy: number } {
  const sx = ((x + MAP_EXTENT_M) / (2 * MAP_EXTENT_M)) * SVG_SIZE;
  const sy = ((MAP_EXTENT_M - y) / (2 * MAP_EXTENT_M)) * SVG_SIZE;
  return { sx, sy };
}

function svgToWorld(sx: number, sy: number): { x: number; y: number } {
  const x = (sx / SVG_SIZE) * (2 * MAP_EXTENT_M) - MAP_EXTENT_M;
  const y = MAP_EXTENT_M - (sy / SVG_SIZE) * (2 * MAP_EXTENT_M);
  return {
    x: Number(Math.max(-MAP_EXTENT_M, Math.min(MAP_EXTENT_M, x)).toFixed(2)),
    y: Number(Math.max(-MAP_EXTENT_M, Math.min(MAP_EXTENT_M, y)).toFixed(2)),
  };
}

function getSectorColor(distM: number | null, thresholdM: number): string {
  if (distM === null || !Number.isFinite(distM)) {
    return "border-eigenia-amber/35 bg-eigenia-amber/10 text-eigenia-amber";
  }
  if (distM <= 0) return "border-white/10 bg-eigenia-obsidian text-eigenia-muted";
  if (distM < thresholdM) return "border-eigenia-fault/60 bg-eigenia-fault/15 text-eigenia-fault";
  if (distM < thresholdM * 1.6) return "border-eigenia-amber/50 bg-eigenia-amber/15 text-eigenia-amber";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
}

export function PatrolPlannerPanel({ robot }: PatrolPlannerPanelProps) {
  const { frame, space, activeSpaceId, activeRosMode } = useStudio();
  const robotId = robot?.id ?? null;

  const [activeTab, setActiveTab] = useState<"patrol" | "explore">("patrol");
  const [showFpvPip, setShowFpvPip] = useState(true);
  const [fpvNonce, setFpvNonce] = useState(0);
  const [fpvError, setFpvError] = useState(false);
  const fpvImgRef = useRef<HTMLImageElement | null>(null);

  const abortFpvSocket = useCallback(() => {
    if (fpvImgRef.current) {
      fpvImgRef.current.src = "";
    }
  }, []);

  // Strict Chromium MJPEG socket cleanup on unmount or when hiding/switching tab
  useEffect(() => {
    return () => {
      abortFpvSocket();
    };
  }, [abortFpvSocket]);

  useEffect(() => {
    if (!showFpvPip || activeTab !== "patrol") {
      abortFpvSocket();
    }
  }, [showFpvPip, activeTab, abortFpvSocket]);

  // URL-synced ?tab=patrol|explore (reacts to sidebar clicks between /patrol and /patrol?tab=explore)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncTabFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      setActiveTab(tab === "explore" ? "explore" : "patrol");
    };
    syncTabFromUrl();
    window.addEventListener("popstate", syncTabFromUrl);
    return () => window.removeEventListener("popstate", syncTabFromUrl);
  }, []);

  const handleTabChange = useCallback((nextId: string) => {
    const valid = nextId === "explore" ? "explore" : "patrol";
    setActiveTab(valid);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", valid);
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  const [waypoints, setWaypoints] = useState<PatrolWaypoint[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem("eigenia_patrol_waypoints_v1");
      if (raw !== null) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed as PatrolWaypoint[];
      }
    } catch {
      // ignore corrupted storage
    }
    return [];
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem("eigenia_patrol_waypoints_v1", JSON.stringify(waypoints));
    } catch {
      // ignore storage quota errors
    }
  }, [waypoints]);
  const [routeName, setRouteName] = useState("Lab Perimeter Patrol");
  const [loopEnabled, setLoopEnabled] = useState(true);
  const [maxSpeedCms, setMaxSpeedCms] = useState(7);
  const [stabilityPreset, setStabilityPreset] = useState<"carpet_lidar" | "hardwood_lidar" | "ultra_safe">("carpet_lidar");
  const [capture3dAtWaypoints, setCapture3dAtWaypoints] = useState(true);
  const [obstacleClearanceM, setObstacleClearanceM] = useState(0.4);
  const [announceVoice, setAnnounceVoice] = useState(true);
  const [requireLidar, setRequireLidar] = useState(true);
  const [cameraAvoidance, setCameraAvoidance] = useState(true);

  const [savedRoutes, setSavedRoutes] = useState<PatrolRoute[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [patrolStatus, setPatrolStatus] = useState<PatrolStatus | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const loadRoutes = useCallback(async (id: string) => {
    try {
      const resp = await listPatrolRoutes(id);
      setSavedRoutes(Array.isArray(resp.routes) ? resp.routes : []);
    } catch {
      // Non-fatal
    }
  }, []);

  useEffect(() => {
    if (!robotId) {
      setSavedRoutes([]);
      setPatrolStatus(null);
      return;
    }
    void loadRoutes(robotId);
    let cancelled = false;
    const poll = () => {
      fetchPatrolStatus(robotId)
        .then((st) => {
          if (!cancelled && st) setPatrolStatus(st);
        })
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 1200);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [robotId, loadRoutes]);

  const walls = useMemo(() => {
    if (Array.isArray(frame?.walls) && frame.walls.length > 0) return frame.walls;
    if (Array.isArray(space?.walls) && space.walls.length > 0) return space.walls;
    return [];
  }, [frame?.walls, space?.walls]);

  const lidarDots = useMemo(() => {
    const pts = Array.isArray(frame?.points) ? frame.points : [];
    const stride = Math.max(1, Math.floor(pts.length / 260));
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
          <div className="text-sm font-semibold text-white">No Robot Selected for Autonomous Patrol</div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a PuppyPi robot to plan 2D LiDAR waypoint routes and monitor 5-sector obstacle avoidance.
          </p>
        </CardContent>
      </Card>
    );
  }

  const handleSvgClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const sx = ((e.clientX - rect.left) / rect.width) * SVG_SIZE;
    const sy = ((e.clientY - rect.top) / rect.height) * SVG_SIZE;
    const { x, y } = svgToWorld(sx, sy);
    setSelectedRouteId(null);
    setWaypoints((prev) => [
      ...prev,
      { x, y, label: `WP-${prev.length + 1}`, pause_sec: 1.5 },
    ]);
  };

  const handleSaveRoute = async () => {
    if (!routeName.trim() || waypoints.length === 0) return;
    setBusyAction("save");
    setBanner(null);
    try {
      const res = await savePatrolRoute(robotId, {
        name: routeName.trim(),
        space_id: activeSpaceId || undefined,
        waypoints,
        loop_enabled: loopEnabled,
        max_speed_cms: maxSpeedCms,
        obstacle_clearance_m: obstacleClearanceM,
      });
      setSelectedRouteId(res.route.id);
      await loadRoutes(robotId);
      setBanner({ kind: "ok", text: `Saved patrol route "${res.route.name}" (${waypoints.length} waypoints).` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save patrol route",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleDeleteRoute = async (route: PatrolRoute) => {
    setBusyAction(`del-${route.id}`);
    setBanner(null);
    try {
      await deletePatrolRoute(robotId, route.id);
      if (selectedRouteId === route.id) setSelectedRouteId(null);
      await loadRoutes(robotId);
      setBanner({ kind: "ok", text: `Deleted patrol route "${route.name}".` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete route",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleProbeStartLidar = async () => {
    setBusyAction("lidar");
    setBanner(null);
    try {
      const res = await startRobotLidarNode(robotId);
      setBanner({
        kind: res.ok ? "ok" : "error",
        text: `${res.detail} (${res.ros_version}, device_present=${res.device_present ? "yes" : "no"})`,
      });
      const st = await fetchPatrolStatus(robotId).catch(() => null);
      if (st) setPatrolStatus(st);
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to probe/start LD19 LiDAR node",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleStartPatrol = async () => {
    if (waypoints.length === 0) {
      setBanner({ kind: "error", text: "Click on the 2D LiDAR map to place at least 1 waypoint." });
      return;
    }
    setBusyAction("start");
    setBanner(null);
    try {
      const st = await startRobotPatrol(robotId, {
        route_id: selectedRouteId || undefined,
        waypoints,
        loop_enabled: loopEnabled,
        max_speed_cms: maxSpeedCms,
        obstacle_clearance_m: obstacleClearanceM,
        announce_voice: announceVoice,
        require_lidar: requireLidar,
        camera_avoidance: cameraAvoidance,
        stability_preset: stabilityPreset,
        capture_3d_at_waypoints: capture3dAtWaypoints,
      });
      setPatrolStatus(st);
      if (st.state === "blocked_no_lidar") {
        setBanner({
          kind: "error",
          text:
            st.error ||
            "Patrol blocked by fail-safe: LD19 LiDAR is offline. Plug in / start LD19 or turn off 'Require Live LD19 LiDAR' for Camera-Only Avoidance.",
        });
      } else {
        setBanner({
          kind: "ok",
          text: `Autonomous patrol started (${st.total_waypoints} waypoints · clearance ${obstacleClearanceM.toFixed(2)}m · ${
            st.lidar_live ? "LiDAR + Camera" : "Camera-Only Avoidance"
          }).`,
        });
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to start patrol",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleStopPatrol = async () => {
    setBusyAction("stop");
    setBanner(null);
    try {
      const st = await stopRobotPatrol(robotId);
      setPatrolStatus(st);
      setBanner({ kind: "ok", text: "Autonomous patrol stopped — robot halted cleanly." });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to stop patrol",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const sectors = patrolStatus?.sectors_m ?? {
    front: null,
    front_left: null,
    front_right: null,
    left: null,
    right: null,
  };
  const lidarLive = patrolStatus?.lidar_live === true;

  const polylinePoints = waypoints
    .map((wp) => {
      const { sx, sy } = worldToSvg(wp.x, wp.y);
      return `${sx},${sy}`;
    })
    .join(" ");

  return (
    <div className="flex flex-col gap-4">
      {/* Compact WorkspaceHeader + 2 URL-Synced Tabs (Waypoint Patrol | Autonomous Explore & Map) */}
      <WorkspaceHeader
        badge="AUTONOMOUS NAVIGATION"
        title="Autonomous Patrol & Frontier Explorer"
        subtitle={`${robot.name} (${robot.ip_address}) · 5-sector LD19 obstacle avoidance, dark-zone 3D mapping & low-battery RTH`}
        statusTone={lidarLive ? "ok" : "fault"}
        statusLabel={lidarLive ? "LD19 /scan LIVE" : "LD19 OFFLINE"}
        sticky
        metrics={[
          {
            label: "Waypoints",
            value: waypoints.length,
            tone: "sky",
            compact: true,
          },
          {
            label: "Clearance",
            value: obstacleClearanceM,
            unit: "m",
            decimals: 2,
            tone: "orange",
            compact: true,
          },
          {
            label: "Front Sector",
            value:
              sectors.front !== null && sectors.front > 0 ? sectors.front : "NO LIDAR",
            unit: sectors.front !== null && sectors.front > 0 ? "m" : undefined,
            decimals: 2,
            tone:
              sectors.front === null
                ? "amber"
                : sectors.front < obstacleClearanceM
                  ? "fault"
                  : "emerald",
            compact: true,
          },
        ]}
        actions={
          <Button
            size="sm"
            variant={lidarLive ? "secondary" : "default"}
            disabled={busyAction !== null}
            onClick={() => void handleProbeStartLidar()}
          >
            {busyAction === "lidar" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Radar className="h-3.5 w-3.5" />
            )}
            {busyAction === "lidar" ? "Probing LD19..." : "Probe / Start LD19 LiDAR"}
          </Button>
        }
      />

      <SegmentedTabs
        value={activeTab}
        onValueChange={handleTabChange}
        tabs={[
          {
            id: "patrol",
            label: "Waypoint Patrol",
            icon: <Navigation className="h-3.5 w-3.5" />,
            count: waypoints.length,
            alertTone: patrolStatus?.active ? "ok" : null,
          },
          {
            id: "explore",
            label: "Autonomous Explore & Map",
            icon: <Compass className="h-3.5 w-3.5" />,
            alertTone: lidarLive ? "ok" : "warning",
          },
        ]}
      />

      {activeTab === "explore" ? (
        <AutonomousExplorerPanel robot={robot} />
      ) : (
        <>
      {/* Prominent LD19 LiDAR Sensor Status Banner */}
      <div
        className={`flex flex-col gap-2.5 rounded-lg border p-3.5 sm:flex-row sm:items-center sm:justify-between ${
          lidarLive
            ? "border-emerald-500/45 bg-emerald-500/10"
            : "border-eigenia-fault/50 bg-eigenia-fault/15"
        }`}
      >
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            {lidarLive ? (
              <Badge
                variant="sky"
                className="border-emerald-500/50 bg-emerald-500/20 font-semibold text-emerald-400"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                LD19 LiDAR: LIVE (/scan)
              </Badge>
            ) : (
              <Badge variant="fault" className="font-semibold">
                <ShieldAlert className="h-3.5 w-3.5" />
                LD19 LiDAR: OFFLINE (No /scan stream)
              </Badge>
            )}
            {lidarLive && typeof patrolStatus?.lidar_age_sec === "number" && (
              <Badge variant="neutral" className="font-mono text-[10px] tabular-nums">
                Age: {patrolStatus.lidar_age_sec.toFixed(1)}s
              </Badge>
            )}
            {patrolStatus?.camera_avoidance_active && (
              <Badge variant="sky" className="text-[10px]">
                <Camera className="h-3 w-3" /> Camera Avoidance Active
              </Badge>
            )}
          </div>
          <p className="text-xs text-eigenia-ink">
            {lidarLive
              ? "360° LD19 LiDAR obstacle sectors streaming live — full fail-safe autonomous navigation ready."
              : "Check LD19 USB cable & battery, or disable 'Require Live LD19 LiDAR' below to use Camera-Only Avoidance."}
          </p>
        </div>
        <Button
          size="sm"
          variant={lidarLive ? "secondary" : "default"}
          disabled={busyAction !== null}
          onClick={() => void handleProbeStartLidar()}
          className="shrink-0"
        >
          {busyAction === "lidar" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Radar className="h-3.5 w-3.5" />
          )}
          {busyAction === "lidar" ? "Probing LD19..." : "Probe / Start LD19 LiDAR"}
        </Button>
      </div>

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

      {/* Patrol Status & 5-Sector LiDAR Clearance Telemetry */}
      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Navigation className="h-4 w-4 text-eigenia-orange" />
              Autonomous Waypoint Patrol & LD19 LiDAR Obstacle Avoidance
            </CardTitle>
            <p className="mt-1 font-mono text-[10px] text-eigenia-muted">
              State:{" "}
              <span className="text-white">{patrolStatus?.state || "idle"}</span> · Waypoint{" "}
              {patrolStatus?.active
                ? `${patrolStatus.current_waypoint_idx + 1}/${patrolStatus.total_waypoints}`
                : `0/${waypoints.length}`}
              {patrolStatus?.last_command && (
                <>
                  {" "}
                  · Cmd vx={patrolStatus.last_command.vx_cms.toFixed(1)} cm/s, yaw=
                  {patrolStatus.last_command.yaw_rate_rads.toFixed(2)} rad/s
                </>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={stabilityPreset}
              onChange={(e) => {
                const next = e.target.value as "carpet_lidar" | "hardwood_lidar" | "ultra_safe";
                setStabilityPreset(next);
                setMaxSpeedCms(next === "ultra_safe" ? 5 : next === "carpet_lidar" ? 7 : 9);
              }}
              className="h-8 rounded-md border border-white/15 bg-slate-950 px-2 font-mono text-[11px] text-cyan-200"
              aria-label="Stability surface preset"
            >
              <option value="carpet_lidar">Carpet + LiDAR Safe</option>
              <option value="hardwood_lidar">Hardwood + LiDAR</option>
              <option value="ultra_safe">Ultra-Safe Slow</option>
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={busyAction !== null}
              onClick={() => {
                setBusyAction("plan");
                void suggestBlindSpotMappingRoute(4, 1.8)
                  .then((res) => {
                    setWaypoints(res.waypoints.map((w) => ({ x: w.x, y: w.y, pause_sec: w.pause_sec })));
                    setBanner({ kind: "ok", text: res.summary });
                  })
                  .catch((err) =>
                    setBanner({
                      kind: "error",
                      text: err instanceof Error ? err.message : "Failed to suggest blind-spot route.",
                    })
                  )
                  .finally(() => setBusyAction(null));
              }}
              className="cursor-pointer"
            >
              <Compass className="h-3.5 w-3.5 text-cyan-400" />
              Auto-Plan Blind-Spot Route
            </Button>
            <Button
              size="sm"
              variant={capture3dAtWaypoints ? "sky" : "outline"}
              onClick={() => setCapture3dAtWaypoints((v) => !v)}
              className="cursor-pointer text-[11px]"
            >
              3D Capture: {capture3dAtWaypoints ? "ON" : "OFF"}
            </Button>
            <Badge variant={patrolStatus?.active ? "default" : "neutral"}>
              {patrolStatus?.active ? "PATROL ACTIVE" : "STANDBY"}
            </Badge>
            <Button
              size="sm"
              variant="default"
              disabled={busyAction !== null || waypoints.length === 0}
              onClick={() => void handleStartPatrol()}
            >
              {busyAction === "start" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Start Autonomous Patrol
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={busyAction !== null}
              onClick={() => void handleStopPatrol()}
            >
              <Square className="h-3.5 w-3.5" />
              Stop Patrol
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* 5-Sector LD19 LiDAR Clearance Display */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {(
              [
                { key: "left", label: "Left", val: sectors.left },
                { key: "front_left", label: "Front-Left", val: sectors.front_left },
                { key: "front", label: "Front", val: sectors.front },
                { key: "front_right", label: "Front-Right", val: sectors.front_right },
                { key: "right", label: "Right", val: sectors.right },
              ] as const
            ).map((s) => (
              <div
                key={s.key}
                className={`rounded-md border p-2.5 text-center font-mono ${getSectorColor(
                  s.val,
                  obstacleClearanceM
                )}`}
              >
                <div className="text-[9px] uppercase opacity-80">{s.label}</div>
                <div className="mt-0.5 text-sm font-semibold tabular-nums">
                  {s.val === null ? "NO LIDAR" : s.val > 0 ? `${s.val.toFixed(2)} m` : "—"}
                </div>
              </div>
            ))}
          </div>

          {patrolStatus?.visual_obstacle && (
            <div className="flex items-center gap-2 rounded-md border border-eigenia-fault/50 bg-eigenia-fault/15 px-3 py-2 font-mono text-xs text-eigenia-fault">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>Front-Camera Visual Obstacle Alert: {patrolStatus.visual_obstacle}</span>
            </div>
          )}

          {patrolStatus?.error && (
            <div className="rounded-md border border-eigenia-amber/40 bg-eigenia-amber/10 px-3 py-1.5 font-mono text-[11px] text-eigenia-amber">
              {patrolStatus.error}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Interactive 2D LiDAR Patrol Map + Route Configuration */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* Interactive SVG 2D Map */}
        <Card className="xl:col-span-7">
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2">
              <Radar className="h-3.5 w-3.5 text-eigenia-sky" />
              2D LiDAR Patrol Map (±4.0m · Click to Drop Waypoints)
            </CardTitle>
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant="secondary"
                className="h-7 px-2 text-[10px]"
                disabled={waypoints.length === 0}
                onClick={() => {
                  setSelectedRouteId(null);
                  setWaypoints((prev) => prev.slice(0, -1));
                }}
              >
                <Undo2 className="h-3 w-3" />
                Undo
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-[10px]"
                disabled={waypoints.length === 0}
                onClick={() => {
                  setSelectedRouteId(null);
                  setWaypoints([]);
                  setBanner({ kind: "ok", text: "Cleared all waypoints. Click the map or use Auto-Plan Blind-Spot Route to add new ones." });
                }}
              >
                Clear ({waypoints.length})
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="mx-auto aspect-square w-full max-w-[460px] overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian">
              <svg
                viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
                onClick={handleSvgClick}
                className="h-full w-full cursor-crosshair select-none"
              >
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
                        stroke={m === 0 ? "rgba(56,189,248,0.28)" : "rgba(255,255,255,0.07)"}
                        strokeWidth={m === 0 ? 1.2 : 1}
                      />
                      <line
                        x1={0}
                        y1={pY}
                        x2={SVG_SIZE}
                        y2={pY}
                        stroke={m === 0 ? "rgba(56,189,248,0.28)" : "rgba(255,255,255,0.07)"}
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
                      key={idx}
                      x1={a.sx}
                      y1={a.sy}
                      x2={b.sx}
                      y2={b.sy}
                      stroke="#38bdf8"
                      strokeWidth={2.2}
                      strokeOpacity={0.7}
                    />
                  );
                })}

                {/* Live LiDAR Points */}
                {lidarDots.map((pt, idx) => (
                  <circle
                    key={idx}
                    cx={pt.sx}
                    cy={pt.sy}
                    r={1.6}
                    fill="#7dd3fc"
                    fillOpacity={0.55}
                  />
                ))}

                {/* Robot Origin */}
                <g>
                  <circle
                    cx={SVG_SIZE / 2}
                    cy={SVG_SIZE / 2}
                    r={7}
                    fill="rgba(56,189,248,0.2)"
                    stroke="#38bdf8"
                    strokeWidth={1.5}
                  />
                  <circle cx={SVG_SIZE / 2} cy={SVG_SIZE / 2} r={2.5} fill="#38bdf8" />
                </g>

                {/* Patrol Route Path */}
                {waypoints.length > 1 && (
                  <polyline
                    points={polylinePoints}
                    fill="none"
                    stroke="#E05A10"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                )}
                {loopEnabled && waypoints.length > 2 && (() => {
                  const first = worldToSvg(waypoints[0].x, waypoints[0].y);
                  const last = worldToSvg(
                    waypoints[waypoints.length - 1].x,
                    waypoints[waypoints.length - 1].y
                  );
                  return (
                    <line
                      x1={last.sx}
                      y1={last.sy}
                      x2={first.sx}
                      y2={first.sy}
                      stroke="#E05A10"
                      strokeWidth={1.4}
                      strokeOpacity={0.45}
                      strokeDasharray="3 4"
                    />
                  );
                })()}

                {/* Numbered Waypoints */}
                {waypoints.map((wp, idx) => {
                  const { sx, sy } = worldToSvg(wp.x, wp.y);
                  const isCurrent =
                    Boolean(patrolStatus?.active) && patrolStatus?.current_waypoint_idx === idx;
                  return (
                    <g key={`${idx}-${wp.x}-${wp.y}`}>
                      <circle
                        cx={sx}
                        cy={sy}
                        r={isCurrent ? 12 : 9.5}
                        fill={isCurrent ? "#E05A10" : "#15171b"}
                        stroke="#E05A10"
                        strokeWidth={2}
                      />
                      <text
                        x={sx}
                        y={sy + 3.5}
                        textAnchor="middle"
                        fill="#ffffff"
                        fontSize="10"
                        fontFamily="JetBrains Mono, monospace"
                        fontWeight="bold"
                      >
                        {idx + 1}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          </CardContent>
        </Card>

        {/* Route Parameters, Live FPV PiP, Waypoint List & Saved Routes */}
        <div className="flex flex-col gap-4 xl:col-span-5">
          {/* Collapsible Live PuppyPi FPV Camera PiP */}
          <Card className="border-eigenia-sky/30">
            <CardHeader className="flex flex-row items-center justify-between gap-2 py-2.5">
              <CardTitle className="flex items-center gap-2 text-xs">
                <Camera className="h-3.5 w-3.5 text-eigenia-orange" />
                Live PuppyPi FPV PiP
              </CardTitle>
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
            </CardHeader>
            {showFpvPip && (
              <CardContent className="pt-0">
                <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian">
                  {!fpvError ? (
                    <img
                      ref={fpvImgRef}
                      key={`patrol-fpv-${robotId}-${activeRosMode}-${fpvNonce}`}
                      src={`${getRobotVideoStreamUrl(
                        robotId,
                        activeRosMode === "ros2" ? "/image_raw" : "/usb_cam/image_raw"
                      )}&_pip=${fpvNonce}`}
                      alt="PuppyPi Live FPV PiP"
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
                      {activeRosMode === "ros2" ? "/image_raw" : "/usb_cam/image_raw"}
                    </span>
                    {patrolStatus?.visual_obstacle && (
                      <span className="rounded border border-eigenia-fault/60 bg-eigenia-fault/85 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-white">
                        OBSTACLE: {patrolStatus.visual_obstacle}
                      </span>
                    )}
                  </div>
                </div>
              </CardContent>
            )}
          </Card>

          {/* Collapsible HD Overwatch Room Cam (4K/1080p) */}
          <OverwatchHudCard compact defaultVisible={false} />

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Compass className="h-3.5 w-3.5 text-eigenia-orange" />
                Patrol Parameters & Save Route
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <Input
                  value={routeName}
                  onChange={(e) => setRouteName(e.target.value)}
                  placeholder="Route name..."
                  className="text-xs"
                />
                <Button
                  size="sm"
                  variant="sky"
                  disabled={busyAction !== null || !routeName.trim() || waypoints.length === 0}
                  onClick={() => void handleSaveRoute()}
                >
                  {busyAction === "save" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Save
                </Button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-2">
                  <span className="text-xs text-white">Loop Patrol</span>
                  <Switch checked={loopEnabled} onCheckedChange={setLoopEnabled} />
                </div>
                <div className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-2">
                  <span className="flex items-center gap-1 text-xs text-white">
                    <Volume2 className="h-3 w-3 text-eigenia-sky" /> Voice
                  </span>
                  <Switch checked={announceVoice} onCheckedChange={setAnnounceVoice} />
                </div>
              </div>

              {/* Explicit Safety Toggles: Require Live LD19 LiDAR + Active Front-Camera Avoidance */}
              <div className="space-y-2">
                <div className="flex items-center justify-between rounded border border-eigenia-orange/35 bg-eigenia-orange/10 px-2.5 py-2">
                  <div className="pr-2">
                    <div className="text-xs font-medium text-white">
                      Require Live LD19 LiDAR (Fail-Safe)
                    </div>
                    <div className="text-[10px] text-eigenia-muted">
                      Refuses blind driving if `/scan` is offline or unplugged
                    </div>
                  </div>
                  <Switch checked={requireLidar} onCheckedChange={setRequireLidar} />
                </div>
                <div className="flex items-center justify-between rounded border border-eigenia-sky/35 bg-eigenia-sky/10 px-2.5 py-2">
                  <div className="pr-2">
                    <div className="text-xs font-medium text-white">
                      Active Front-Camera Obstacle Avoidance
                    </div>
                    <div className="text-[10px] text-eigenia-muted">
                      Scans live `/image_raw` frames for close objects & walls
                    </div>
                  </div>
                  <Switch checked={cameraAvoidance} onCheckedChange={setCameraAvoidance} />
                </div>
              </div>

              <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[11px]">
                  <span className="text-eigenia-muted">Max Patrol Speed</span>
                  <span className="tabular-nums text-white">{maxSpeedCms} cm/s</span>
                </div>
                <Slider
                  min={6}
                  max={20}
                  step={1}
                  value={[maxSpeedCms]}
                  onValueChange={([v]) => setMaxSpeedCms(v)}
                />
              </div>

              <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex justify-between font-mono text-[11px]">
                  <span className="text-eigenia-muted">LiDAR Obstacle Clearance</span>
                  <span className="tabular-nums text-eigenia-orange">
                    {obstacleClearanceM.toFixed(2)} m
                  </span>
                </div>
                <Slider
                  min={0.25}
                  max={1.0}
                  step={0.05}
                  value={[obstacleClearanceM]}
                  onValueChange={([v]) => setObstacleClearanceM(v)}
                />
              </div>

              {/* Active Waypoints List */}
              <div className="max-h-36 space-y-1 overflow-y-auto border-t border-white/10 pt-2">
                {waypoints.map((wp, idx) => (
                  <div
                    key={`${idx}-${wp.x}-${wp.y}`}
                    className="flex items-center justify-between rounded bg-eigenia-obsidian px-2.5 py-1 font-mono text-[10px]"
                  >
                    <span className="text-white">
                      #{idx + 1} ({wp.x.toFixed(2)}m, {wp.y.toFixed(2)}m)
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                    setSelectedRouteId(null);
                    setWaypoints((prev) => prev.filter((_, i) => i !== idx));
                  }}
                      className="text-eigenia-muted hover:text-eigenia-fault"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Saved Routes */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <MapPin className="h-3.5 w-3.5 text-eigenia-sky" />
                Saved Routes ({savedRoutes.length})
              </CardTitle>
              <Button size="sm" variant="ghost" onClick={() => void loadRoutes(robotId)}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </CardHeader>
            <CardContent className="max-h-48 space-y-2 overflow-y-auto">
              {savedRoutes.length === 0 ? (
                <div className="text-xs text-eigenia-muted">No saved patrol routes yet.</div>
              ) : (
                savedRoutes.map((rt) => (
                  <div
                    key={rt.id}
                    className={`flex items-center justify-between gap-2 rounded border p-2 ${
                      selectedRouteId === rt.id
                        ? "border-eigenia-orange bg-eigenia-orange/10"
                        : "border-white/10 bg-eigenia-obsidian"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs font-semibold text-white">{rt.name}</div>
                      <div className="font-mono text-[10px] text-eigenia-muted">
                        {rt.waypoints.length} pts · {rt.max_speed_cms} cm/s ·{" "}
                        {rt.loop_enabled ? "Loop" : "Once"}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-6 px-2 text-[10px]"
                        onClick={() => {
                          setSelectedRouteId(rt.id);
                          setRouteName(rt.name);
                          setWaypoints(rt.waypoints);
                          setLoopEnabled(rt.loop_enabled);
                          setMaxSpeedCms(rt.max_speed_cms);
                          setObstacleClearanceM(rt.obstacle_clearance_m);
                        }}
                      >
                        Load
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-6 px-2 text-[10px]"
                        disabled={busyAction !== null}
                        onClick={() => void handleDeleteRoute(rt)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
        </>
      )}
    </div>
  );
}
