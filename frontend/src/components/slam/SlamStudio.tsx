"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Box,
  CheckCircle2,
  Download,
  Layers,
  Loader2,
  Map as MapIcon,
  OctagonAlert,
  Play,
  Radar,
  Save,
  Square,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useStudio } from "@/context/StudioContext";
import { API_URL } from "@/lib/api";
import { sendRobotVelocity } from "@/lib/robotApi";
import {
  exportSlamToDigitalTwin,
  getSlamMapImageUrl,
  getSlamStatus,
  saveSlamMap,
  startSlam,
  stopSlam,
  type SlamExportResult,
  type SlamStatus,
} from "@/lib/slamApi";
import { cn } from "@/lib/utils";

export function SlamStudio(): React.JSX.Element {
  const { activeRobot, activeRobotId, handleGlobalEstop, estopActive } = useStudio();

  const [status, setStatus] = useState<SlamStatus | null>(null);
  const [imgNonce, setImgNonce] = useState<number>(() => Date.now());
  const [zoom, setZoom] = useState<number>(1.0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mapName, setMapName] = useState("Lab Room SLAM Map");
  const [wallHeight, setWallHeight] = useState("2.5");
  const [exportResult, setExportResult] = useState<SlamExportResult | null>(null);

  const pollStatus = useCallback(async () => {
    try {
      const st = await getSlamStatus();
      setStatus(st);
      if (st.running || st.has_map_data) {
        setImgNonce(st.map_seq || Date.now());
      }
    } catch {
      // Non-fatal background poll
    }
  }, []);

  useEffect(() => {
    void pollStatus();
    const timer = window.setInterval(() => {
      void pollStatus();
    }, 900);
    return () => window.clearInterval(timer);
  }, [pollStatus]);

  const handleStart = async () => {
    setBusy("Launching ROS 2 SLAM (hiwonder_slam / slam_toolbox) on PuppyPi...");
    setError(null);
    setNotice(null);
    try {
      const st = await startSlam(activeRobotId);
      setStatus(st);
      setImgNonce(Date.now());
      setNotice("SLAM is live! Slowly walk PuppyPi around the room to build crisp walls.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start SLAM.");
    } finally {
      setBusy(null);
    }
  };

  const handleStop = async () => {
    setBusy("Stopping ROS 2 SLAM...");
    setError(null);
    try {
      const st = await stopSlam(activeRobotId);
      setStatus(st);
      setNotice("SLAM stopped cleanly.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop SLAM.");
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    setBusy("Saving SLAM map to PostgreSQL 18...");
    setError(null);
    try {
      const res = await saveSlamMap(mapName.trim() || "SLAM Floor Map");
      await pollStatus();
      setNotice(`Saved SLAM map "${res.map.name}" (${res.map.mapped_area_m2} m²).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save SLAM map.");
    } finally {
      setBusy(null);
    }
  };

  const handleExportTwin = async () => {
    setBusy("Extruding SLAM walls into 3D Digital Twin (.glb) & Room Twin Studio...");
    setError(null);
    try {
      const res = await exportSlamToDigitalTwin({
        name: mapName.trim() || "SLAM Scanned Room",
        wall_height_m: Math.max(1.5, Math.min(6.0, Number(wallHeight) || 2.5)),
      });
      setExportResult(res);
      setNotice(
        `Exported ${res.width_m}×${res.length_m}m 3D room (${res.wall_segment_count} walls, ${res.triangle_count} tris) to Room Twin Studio!`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export to 3D Digital Twin failed.");
    } finally {
      setBusy(null);
    }
  };

  const handleNudge = async (vx: number, yawRate: number) => {
    if (!activeRobotId) return;
    try {
      await sendRobotVelocity(activeRobotId, {
        x: vx,
        y: 0,
        yaw_rate: yawRate,
        use_autogait: true,
      });
    } catch {
      // ignore transient drive error
    }
  };

  const isRunning = Boolean(status?.running);
  const sourceLabel =
    status?.map_source === "ros_map"
      ? "ROS 2 /map (slam_toolbox)"
      : status?.map_source === "scan_accumulator"
        ? "Live LD19 Scan Accumulator"
        : status?.map_source === "warming_up"
          ? "Warming up SLAM..."
          : "Idle";

  return (
    <div className="space-y-4">
      {/* Top SLAM Command Bar */}
      <Card className="border-white/10 bg-slate-950/90">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex items-center gap-2">
              <MapIcon className="h-5 w-5 text-cyan-400" />
              <div>
                <h1 className="text-sm font-semibold text-white">SLAM Mapping Studio</h1>
                <p className="text-[11px] text-slate-400">
                  Real-time ROS 2 Humble Occupancy-Grid SLAM on {activeRobot?.name || "PuppyPi Pro"} → 3D Digital Twin
                </p>
              </div>
            </div>
            <Badge variant={isRunning ? "sky" : "neutral"} className="text-[10px]">
              {sourceLabel}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {!isRunning ? (
              <Button
                size="sm"
                disabled={Boolean(busy)}
                onClick={() => void handleStart()}
                className="h-8 gap-1.5 bg-emerald-600 text-xs text-white hover:bg-emerald-500 cursor-pointer"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                Start Live SLAM
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={Boolean(busy)}
                onClick={() => void handleStop()}
                className="h-8 gap-1.5 border-amber-500/50 text-xs text-amber-200 hover:bg-amber-950/50 cursor-pointer"
              >
                <Square className="h-3.5 w-3.5" />
                Stop SLAM
              </Button>
            )}

            <Button
              size="sm"
              variant="outline"
              disabled={Boolean(busy) || !status?.has_map_data}
              onClick={() => void handleSave()}
              className="h-8 gap-1.5 text-xs cursor-pointer"
            >
              <Save className="h-3.5 w-3.5" />
              Save Map
            </Button>

            <Button
              size="sm"
              disabled={Boolean(busy) || !status?.has_map_data}
              onClick={() => void handleExportTwin()}
              className="h-8 gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
            >
              <Box className="h-3.5 w-3.5" />
              Export → 3D Digital Twin
            </Button>

            <Button
              size="sm"
              variant="destructive"
              onClick={() => void handleGlobalEstop()}
              className="h-8 gap-1.5 text-xs font-semibold cursor-pointer"
            >
              <OctagonAlert className="h-3.5 w-3.5" />
              {estopActive ? "E-STOPPED" : "E-STOP"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {(busy || error || notice) && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
            error
              ? "border-red-500/40 bg-red-950/50 text-red-200"
              : busy
                ? "border-cyan-500/40 bg-cyan-950/40 text-cyan-200"
                : "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
          )}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : !error ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
          <span>{busy || error || notice}</span>
        </div>
      )}

      {exportResult && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/35 px-3.5 py-2.5 text-xs text-emerald-100">
          <span>
            3D Room Twin ready: <strong>{exportResult.width_m}×{exportResult.length_m} m</strong> ({exportResult.wall_segment_count} extruded walls, {exportResult.triangle_count} triangles)
          </span>
          <div className="flex items-center gap-2">
            <a
              href={`${API_URL}${exportResult.glb_url}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-emerald-400/50 bg-emerald-900/50 px-2.5 py-1 text-[11px] font-medium text-emerald-200 hover:bg-emerald-800/60"
            >
              <Download className="h-3 w-3" /> Download 3D Walls .glb
            </a>
            <Link
              href="/room-studio"
              className="inline-flex items-center gap-1 rounded-md bg-cyan-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-cyan-500"
            >
              <Layers className="h-3 w-3" /> Open in Room Twin Studio
            </Link>
          </div>
        </div>
      )}

      {/* Main Split Workspace: Live SLAM Occupancy Grid + Telemetry & Slow-Gait Drive Pad */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card className="border-white/10 bg-slate-950/90 lg:col-span-8">
          <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <Radar className="h-4 w-4 text-cyan-400" />
              <CardTitle className="text-xs font-semibold">Live 2D SLAM Occupancy Grid</CardTitle>
              <span className="font-mono text-[10px] text-slate-400">
                {status ? `${status.width}×${status.height} @ ${(status.resolution_m * 100).toFixed(0)}cm/cell` : "waiting"}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.max(0.6, z - 0.25))} className="h-7 px-2 cursor-pointer">
                <ZoomOut className="h-3.5 w-3.5" />
              </Button>
              <span className="font-mono text-[11px] text-slate-300">{Math.round(zoom * 100)}%</span>
              <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.min(3.0, z + 0.25))} className="h-7 px-2 cursor-pointer">
                <ZoomIn className="h-3.5 w-3.5" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-3">
            <div className="relative flex h-[480px] w-full items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-[#0b1018]">
              {status?.has_map_data ? (
                <img
                  src={getSlamMapImageUrl(imgNonce)}
                  alt="Live SLAM Occupancy Grid"
                  style={{ transform: `scale(${zoom})`, imageRendering: "pixelated" }}
                  className="max-h-full max-w-full object-contain transition-transform duration-200"
                />
              ) : (
                <div className="max-w-sm space-y-2 text-center text-xs text-slate-400">
                  <MapIcon className="mx-auto h-8 w-8 text-slate-600" />
                  <p className="font-semibold text-slate-200">Ready to Map Your Room</p>
                  <p>
                    Click <strong>Start Live SLAM</strong> above to launch ROS 2 <code>hiwonder_slam</code> /{" "}
                    <code>slam_toolbox</code> on PuppyPi and stream the real-time occupancy grid.
                  </p>
                </div>
              )}

              <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap gap-1.5">
                <span className="rounded bg-black/75 px-2 py-0.5 font-mono text-[10px] text-cyan-300">
                  Cyan = Walls
                </span>
                <span className="rounded bg-black/75 px-2 py-0.5 font-mono text-[10px] text-slate-300">
                  Slate = Free Floor
                </span>
                <span className="rounded bg-black/75 px-2 py-0.5 font-mono text-[10px] text-emerald-300">
                  Green Dot = PuppyPi
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Right Side: Live Metrics, Slow-Gait SLAM Drive Pad & Export Settings */}
        <div className="space-y-4 lg:col-span-4">
          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold text-cyan-300">Live SLAM Telemetry</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-2.5">
                <div className="text-[10px] text-slate-400">LiDAR Rate</div>
                <div className="font-mono text-sm font-semibold text-emerald-300">
                  {(status?.scan_hz ?? 0).toFixed(1)} Hz
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-2.5">
                <div className="text-[10px] text-slate-400">Mapped Area</div>
                <div className="font-mono text-sm font-semibold text-cyan-300">
                  {(status?.mapped_area_m2 ?? 0).toFixed(2)} m²
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-2.5">
                <div className="text-[10px] text-slate-400">Wall Cells</div>
                <div className="font-mono text-sm font-semibold text-slate-100">
                  {(status?.occupied_cells ?? 0).toLocaleString()}
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-slate-900/60 p-2.5">
                <div className="text-[10px] text-slate-400">Robot Pose</div>
                <div className="font-mono text-xs font-semibold text-slate-100">
                  ({(status?.robot_xy?.[0] ?? 0).toFixed(2)}, {(status?.robot_xy?.[1] ?? 0).toFixed(2)}) m
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold text-emerald-300">
                Carpet-Safe Slow-Gait SLAM Drive Pad
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-[11px] text-slate-400">
                Move slowly (`0.08 m/s`) so SLAM locks sharp walls without leg slip or tilt blur.
              </p>
              <div className="mx-auto grid w-44 grid-cols-3 gap-1.5">
                <div />
                <Button size="sm" variant="outline" onClick={() => void handleNudge(0.08, 0)} className="h-9 cursor-pointer">
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <div />
                <Button size="sm" variant="outline" onClick={() => void handleNudge(0, 0.35)} className="h-9 cursor-pointer">
                  <ArrowLeft className="h-4 w-4" />
                </Button>
                <Button size="sm" variant="destructive" onClick={() => void handleNudge(0, 0)} className="h-9 text-[10px] cursor-pointer">
                  STOP
                </Button>
                <Button size="sm" variant="outline" onClick={() => void handleNudge(0, -0.35)} className="h-9 cursor-pointer">
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <div />
                <Button size="sm" variant="outline" onClick={() => void handleNudge(-0.06, 0)} className="h-9 cursor-pointer">
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <div />
              </div>
            </CardContent>
          </Card>

          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold text-slate-200">
                Map Name &amp; 3D Digital Twin Export
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
              <div>
                <label className="mb-1 block text-[10px] text-slate-400">Room / Map Name</label>
                <Input value={mapName} onChange={(e) => setMapName(e.target.value)} className="h-8 bg-slate-900 text-xs" />
              </div>
              <div>
                <label className="mb-1 block text-[10px] text-slate-400">Extruded 3D Wall Height (m)</label>
                <Input value={wallHeight} onChange={(e) => setWallHeight(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
              </div>
              {(status?.saved_maps?.length ?? 0) > 0 && (
                <div className="space-y-1.5 pt-1">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Saved Maps ({status!.saved_maps.length})
                  </div>
                  {status!.saved_maps.slice(0, 4).map((m) => (
                    <div
                      key={m.id}
                      className="flex items-center justify-between rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-1.5 text-[11px]"
                    >
                      <span className="truncate text-slate-200">{m.name}</span>
                      <a
                        href={`${API_URL}${m.url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-cyan-300 hover:underline"
                      >
                        PNG
                      </a>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
