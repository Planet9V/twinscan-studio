"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeftRight,
  Box,
  Camera,
  Crosshair,
  Download,
  Eye,
  Layers,
  Loader2,
  Navigation,
  OctagonAlert,
  Play,
  Radar,
  RefreshCw,
  ShieldAlert,
  Square,
  Target,
  Video,
  ZoomIn,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Lidar2DCanvas } from "@/components/lidar/Lidar2DCanvas";
import { CameraCalibrationModal } from "@/components/overwatch/CameraCalibrationModal";
import { TargetUpscaleLoupe } from "@/components/overwatch/TargetUpscaleLoupe";
import { useStudio } from "@/context/StudioContext";
import { getRobotVideoStreamUrl } from "@/lib/robotApi";
import { API_URL } from "@/lib/api";
import {
  getOverwatchGeometry,
  getOverwatchStatus,
  getOverwatchStreamUrl,
  projectOrDispatchTaskPoint,
  reconstructMulticamDigitalTwin,
  type MulticamFuseResult,
  type OverwatchDetection,
  type OverwatchGeometry,
  type OverwatchStatus,
  type TaskPointResult,
} from "@/lib/overwatchApi";
import {
  useBrowserOverwatchBridge,
  type BrowserResolutionPreset,
} from "@/lib/useBrowserOverwatchBridge";
import { cn } from "@/lib/utils";

const RATING_BADGE: Record<string, string> = {
  OPTIMAL: "border-emerald-500/50 bg-emerald-950/60 text-emerald-300",
  GOOD: "border-cyan-500/50 bg-cyan-950/60 text-cyan-300",
  FAIR: "border-amber-500/50 bg-amber-950/60 text-amber-300",
  POOR: "border-red-500/50 bg-red-950/60 text-red-300",
  SINGLE_VIEW: "border-slate-600 bg-slate-900 text-slate-300",
};

export function OverwatchCockpit(): React.JSX.Element {
  const { frame, equipment, darkZones, handleGlobalEstop, estopActive, activeRobot, activeRobotId, activeSpaceId } = useStudio();
  const bridge = useBrowserOverwatchBridge();

  const [usbStatus, setUsbStatus] = useState<OverwatchStatus | null>(null);
  const [macStatus, setMacStatus] = useState<OverwatchStatus | null>(null);
  const [geometry, setGeometry] = useState<OverwatchGeometry | null>(null);
  const [streamNonce, setStreamNonce] = useState<number>(() => Date.now());
  const [calModalOpen, setCalModalOpen] = useState(false);
  const [calCameraId, setCalCameraId] = useState<"usb_4k" | "macbook_cam">("usb_4k");
  const [fusing3d, setFusing3d] = useState(false);
  const [fuseResult, setFuseResult] = useState<MulticamFuseResult | null>(null);
  const [fuseError, setFuseError] = useState<string | null>(null);

  // Tactical layer toggles
  const [showFrustums, setShowFrustums] = useState(true);
  const [showOverlap, setShowOverlap] = useState(true);
  const [showEllipses, setShowEllipses] = useState(true);
  const [taskMode, setTaskMode] = useState(false);

  // Selected target for ROI Loupe or Click-to-Task preview
  const [selectedRoi, setSelectedRoi] = useState<{
    cameraId: string;
    label: string;
    bboxNorm: [number, number, number, number];
  } | null>(null);
  const [taskPreview, setTaskPreview] = useState<TaskPointResult | null>(null);
  const [lastTaskClick, setLastTaskClick] = useState<
    | { kind: "pixel"; cameraId: string; u: number; v: number }
    | { kind: "bev"; x: number; y: number }
    | null
  >(null);
  const [taskBusy, setTaskBusy] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  const pollOverwatch = useCallback(async () => {
    try {
      const [sUsb, sMac, geo] = await Promise.all([
        getOverwatchStatus("usb_4k"),
        getOverwatchStatus("macbook_cam"),
        getOverwatchGeometry(6.0),
      ]);
      setUsbStatus(sUsb);
      setMacStatus(sMac);
      setGeometry(geo);
    } catch {
      // Non-fatal background poll
    }
  }, []);

  useEffect(() => {
    void pollOverwatch();
    const timer = window.setInterval(() => {
      void pollOverwatch();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [pollOverwatch]);

  // Auto-start browser cameras on load if user opted in AND background LaunchAgent isn't already streaming
  const autoStartAttemptedRef = React.useRef(false);
  useEffect(() => {
    if (autoStartAttemptedRef.current) return;
    if (!bridge.autoStart || bridge.running) return;
    if (usbStatus === null) return; // wait for first status poll
    autoStartAttemptedRef.current = true;
    if (!usbStatus.online && !macStatus?.online) {
      void bridge.startAll();
    }
  }, [bridge, macStatus, usbStatus]);

  // Keyboard shortcut: Space = E-STOP (when not typing in an input)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.code === "Space" && e.shiftKey) {
        e.preventDefault();
        void handleGlobalEstop();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleGlobalEstop]);

  const handleCameraFeedClick = async (
    cameraId: "usb_4k" | "macbook_cam",
    e: React.MouseEvent<HTMLDivElement>
  ) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    const v = Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height)));

    if (taskMode) {
      setTaskBusy(true);
      setTaskError(null);
      setLastTaskClick({ kind: "pixel", cameraId, u, v });
      try {
        const proj = await projectOrDispatchTaskPoint({
          camera_id: cameraId,
          u_norm: u,
          v_norm: v,
          standoff_m: 0.3,
          dispatch: false,
        });
        setTaskPreview(proj);
      } catch (err) {
        setTaskError(err instanceof Error ? err.message : "Failed to project floor point.");
      } finally {
        setTaskBusy(false);
      }
      return;
    }

    // Otherwise open a 24%x24% ROI loupe centered where the operator clicked
    const x1 = Math.max(0, u - 0.12);
    const y1 = Math.max(0, v - 0.12);
    const x2 = Math.min(1, u + 0.12);
    const y2 = Math.min(1, v + 0.12);
    setSelectedRoi({
      cameraId,
      label: `Custom ROI (${(u * 100).toFixed(0)}%, ${(v * 100).toFixed(0)}%)`,
      bboxNorm: [x1, y1, x2, y2],
    });
  };

  const handleDispatchPreview = async () => {
    if (!taskPreview) return;
    setTaskBusy(true);
    setTaskError(null);
    try {
      const payload =
        lastTaskClick?.kind === "pixel"
          ? {
              camera_id: lastTaskClick.cameraId,
              u_norm: lastTaskClick.u,
              v_norm: lastTaskClick.v,
              standoff_m: 0.3,
              dispatch: true,
            }
          : {
              camera_id: "bev_map",
              target_xy: [taskPreview.target_xy[0], taskPreview.target_xy[1]] as [number, number],
              standoff_m: 0.3,
              dispatch: true,
            };
      const res = await projectOrDispatchTaskPoint(payload);
      setTaskPreview(res);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "PuppyPi dispatch failed.");
    } finally {
      setTaskBusy(false);
    }
  };

  const advisor = geometry?.placement_advisor;
  const metrics = geometry?.metrics;
  const tracks = geometry?.tracks ?? [];
  const activeCamCount = [
    usbStatus?.online,
    macStatus?.online,
    Boolean(activeRobot?.status === "online" || frame?.robot_pose?.live),
  ].filter(Boolean).length;

  const renderDetectionChips = (cameraId: string, dets: OverwatchDetection[]) => {
    if (!dets.length) return null;
    return (
      <div className="flex flex-wrap gap-1.5 px-2.5 py-1.5 border-t border-white/10 bg-slate-950/90">
        {dets.slice(0, 6).map((d, idx) => {
          const bbox = (d.bbox_norm ?? [0.25, 0.25, 0.75, 0.75]) as [number, number, number, number];
          return (
            <button
              key={`${cameraId}-${d.id ?? idx}`}
              type="button"
              onClick={() =>
                setSelectedRoi({
                  cameraId,
                  label: `${d.label} (${Math.round(d.confidence * 100)}%)`,
                  bboxNorm: bbox,
                })
              }
              className="flex cursor-pointer items-center gap-1 rounded border border-cyan-500/30 bg-cyan-950/30 px-2 py-0.5 font-mono text-[10px] text-cyan-200 transition hover:border-cyan-400 hover:bg-cyan-900/50"
              title="Click to inspect & upscale ROI"
            >
              <ZoomIn className="h-2.5 w-2.5 text-cyan-400" />
              <span>{d.label}</span>
              {d.x != null && d.y != null && (
                <span className="text-slate-400">
                  ({d.x.toFixed(1)},{d.y.toFixed(1)}m)
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-4 p-4 lg:p-5">
      {/* Top Tactical Command Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-slate-950/95 px-4 py-3 shadow-lg">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Radar className="h-5 w-5 text-cyan-400" />
            <div>
              <h1 className="text-sm font-bold uppercase tracking-wider text-slate-100">
                Tactical Multi-Camera Overwatch Cockpit
              </h1>
              <p className="font-mono text-[11px] text-slate-400">
                Unified BEV Sensor Fusion · Frustum Overlap · N-Ray GDOP · 4-Pt Homography
              </p>
            </div>
          </div>

          <Badge variant="neutral" className="font-mono text-[11px] tabular-nums">
            SENSORS {activeCamCount}/3
          </Badge>
          {metrics && (
            <Badge variant="neutral" className="border-emerald-500/40 bg-emerald-950/30 font-mono text-[11px] text-emerald-300 tabular-nums">
              OVERLAP {metrics.overlap_pct}% ({metrics.stereo_area_m2 + metrics.fusion_area_m2} m²)
            </Badge>
          )}
          {advisor && (
            <Badge
              variant="neutral"
              className={cn("font-mono text-[11px] tabular-nums", RATING_BADGE[advisor.rating] ?? "")}
            >
              STEREO {advisor.best_angle_deg}° · GDOP {advisor.estimated_gdop} ({advisor.rating})
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {!bridge.running ? (
            <Button
              size="sm"
              variant="sky"
              onClick={() => {
                bridge.setAutoStart(true);
                void bridge.startAll();
              }}
              className="cursor-pointer font-semibold"
            >
              <Play className="mr-1.5 h-3.5 w-3.5" />
              Enable Local Cameras
            </Button>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                bridge.setAutoStart(false);
                bridge.stopAll();
              }}
              className="cursor-pointer border border-emerald-500/40 text-emerald-300"
            >
              <Square className="mr-1.5 h-3 w-3 fill-current" />
              Stop Browser Capture
            </Button>
          )}

          <Button
            size="sm"
            variant={bridge.autoStart ? "sky" : "outline"}
            onClick={() => bridge.setAutoStart(!bridge.autoStart)}
            className="cursor-pointer text-[11px]"
            title="Automatically start browser cameras when opening /overwatch (if background service isn't already streaming)"
          >
            Auto-Start: {bridge.autoStart ? "ON" : "OFF"}
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={bridge.swapCameras}
            className="cursor-pointer"
            title="Swap which physical webcam feeds 4K USB vs MacBook Cam"
          >
            <ArrowLeftRight className="mr-1.5 h-3.5 w-3.5" />
            Swap Cams
          </Button>

          <Button
            size="sm"
            variant={taskMode ? "default" : "outline"}
            onClick={() => setTaskMode((v) => !v)}
            className="cursor-pointer"
          >
            <Navigation className="mr-1.5 h-3.5 w-3.5" />
            {taskMode ? "Click-to-Task: ON" : "Click-to-Task"}
          </Button>

          <Button
            size="sm"
            variant="outline"
            disabled={fusing3d}
            onClick={() => {
              setFusing3d(true);
              setFuseError(null);
              void reconstructMulticamDigitalTwin({
                space_id: activeSpaceId,
                robot_id: activeRobotId,
                include_puppypi_fpv: true,
                resolution: "medium",
              })
                .then((res) => setFuseResult(res))
                .catch((err) => setFuseError(err instanceof Error ? err.message : "3D fusion failed."))
                .finally(() => setFusing3d(false));
            }}
            className="cursor-pointer border-cyan-500/40 text-cyan-200 hover:bg-cyan-950/50"
            title="Fuse all active cameras (4K USB + MacBook + PuppyPi FPV + LD19 LiDAR) into a textured 3D .glb Digital Twin"
          >
            {fusing3d ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Box className="mr-1.5 h-3.5 w-3.5 text-cyan-400" />}
            Fuse 3D Room Twin
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setCalCameraId("usb_4k");
              setCalModalOpen(true);
            }}
            className="cursor-pointer"
          >
            <Crosshair className="mr-1.5 h-3.5 w-3.5 text-cyan-400" />
            Auto-Calibrate
          </Button>

          <Button
            size="sm"
            variant="destructive"
            onClick={() => void handleGlobalEstop()}
            className="cursor-pointer font-mono font-bold"
            title="Emergency Stop (Shift+Space)"
          >
            <OctagonAlert className="mr-1.5 h-4 w-4" />
            {estopActive ? "E-STOP ACTIVE" : "E-STOP"}
          </Button>
        </div>
      </div>

      {/* Browser-Native Device Assignment & Resolution Bar (Fixes wrong camera labeling & 4K sharpness!) */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 bg-slate-900/70 px-3.5 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] font-semibold text-cyan-300">4K USB Slot:</span>
            <select
              value={bridge.usbDeviceId}
              onChange={(e) => bridge.setUsbDeviceId(e.target.value)}
              className="h-7 max-w-[200px] rounded border border-white/15 bg-slate-950 px-2 font-mono text-[11px] text-slate-200"
              aria-label="Select 4K USB physical camera"
            >
              {bridge.devices.length === 0 ? (
                <option value="">Click Enable Local Cameras to detect…</option>
              ) : (
                bridge.devices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label}
                  </option>
                ))
              )}
            </select>
            <select
              value={bridge.usbPreset}
              onChange={(e) => bridge.setUsbPreset(e.target.value as BrowserResolutionPreset)}
              className="h-7 rounded border border-white/15 bg-slate-950 px-1.5 font-mono text-[11px] text-cyan-200"
              aria-label="4K USB resolution preset"
            >
              <option value="4k">QHD (2560×1440)</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] font-semibold text-violet-300">MacBook Slot:</span>
            <select
              value={bridge.macDeviceId}
              onChange={(e) => bridge.setMacDeviceId(e.target.value)}
              className="h-7 max-w-[200px] rounded border border-white/15 bg-slate-950 px-2 font-mono text-[11px] text-slate-200"
              aria-label="Select MacBook physical camera"
            >
              <option value="">(None / Disabled)</option>
              {bridge.devices.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label}
                </option>
              ))}
            </select>
            <select
              value={bridge.macPreset}
              onChange={(e) => bridge.setMacPreset(e.target.value as BrowserResolutionPreset)}
              className="h-7 rounded border border-white/15 bg-slate-950 px-1.5 font-mono text-[11px] text-violet-200"
              aria-label="MacBook camera resolution preset"
            >
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
          {bridge.slotStats.usb_4k.active && (
            <span className="text-cyan-300">
              USB {bridge.slotStats.usb_4k.w}×{bridge.slotStats.usb_4k.h}
            </span>
          )}
          {bridge.slotStats.macbook_cam.active && (
            <span className="text-violet-300">
              MAC {bridge.slotStats.macbook_cam.w}×{bridge.slotStats.macbook_cam.h}
            </span>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              void bridge.refreshDevices(true);
              setStreamNonce(Date.now());
            }}
            className="h-7 cursor-pointer px-2 text-[11px]"
          >
            <RefreshCw className="mr-1 h-3 w-3" /> Refresh
          </Button>
        </div>
      </div>

      {bridge.bridgeError && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          <ShieldAlert className="h-4 w-4 shrink-0 text-amber-400" />
          <span>{bridge.bridgeError}</span>
        </div>
      )}

      {(fuseResult || fuseError) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/40 bg-cyan-950/30 px-3.5 py-2 text-xs">
          {fuseError ? (
            <span className="text-red-300">{fuseError}</span>
          ) : fuseResult ? (
            <>
              <div className="flex flex-wrap items-center gap-2 text-cyan-100">
                <Box className="h-4 w-4 text-cyan-400" />
                <span className="font-semibold">
                  Fused {fuseResult.camera_count} Cameras into 3D Digital Twin:
                </span>
                <span className="font-mono text-[11px] text-cyan-300 tabular-nums">
                  {fuseResult.cameras_fused.map((c) => `${c.camera_id} (${c.resolution_px})`).join(" + ")} ·{" "}
                  {fuseResult.total_triangles.toLocaleString()} tris · {(fuseResult.glb_bytes_len / 1024).toFixed(0)} KB .glb
                </span>
              </div>
              <div className="flex items-center gap-2">
                {fuseResult.download_url && (
                  <a
                    href={`${API_URL}${fuseResult.download_url}`}
                    download="multicam_digital_twin.glb"
                    className="inline-flex h-7 cursor-pointer items-center gap-1 rounded border border-cyan-400/50 bg-cyan-900/50 px-2.5 font-mono text-[11px] font-semibold text-cyan-200 hover:bg-cyan-800/60"
                  >
                    <Download className="h-3 w-3" /> Download .GLB
                  </a>
                )}
                <Link
                  href="/twin"
                  className="inline-flex h-7 cursor-pointer items-center rounded border border-white/15 bg-slate-900 px-2.5 font-mono text-[11px] text-slate-200 hover:bg-slate-800"
                >
                  Open in /twin →
                </Link>
              </div>
            </>
          ) : null}
        </div>
      )}

      {advisor && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-slate-950/80 px-3.5 py-2 text-xs text-slate-300">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-cyan-400" />
            <span className="font-semibold text-slate-100">Placement Advisor:</span>
            <span>{advisor.recommendation}</span>
          </div>
          {metrics && (
            <span className="font-mono text-[11px] text-slate-400 tabular-nums">
              Blind: {metrics.dead_area_m2}m² · Mono: {metrics.mono_area_m2}m² · Stereo: {metrics.stereo_area_m2}m² · 3+ Fusion: {metrics.fusion_area_m2}m²
            </span>
          )}
        </div>
      )}

      {/* Main Split Tactical Cockpit: Left 55% Multi-Cam Matrix | Right 45% Unified BEV Tactical Map */}
      <div className="grid gap-4 xl:grid-cols-12">
        {/* Left Column: Synchronized Multi-Perspective Feed Matrix */}
        <div className="space-y-4 xl:col-span-7">
          <div className="grid gap-3 md:grid-cols-2">
            {/* Slot 1: 4K USB Overwatch */}
            <Card className="overflow-hidden border-cyan-500/25 bg-slate-950">
              <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Camera className="h-4 w-4 text-cyan-400" />
                  <CardTitle className="text-xs font-semibold text-slate-100">
                    {usbStatus?.camera_name || "4k Webcam"} (usb_4k)
                  </CardTitle>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge
                    variant={usbStatus?.online ? "sky" : "neutral"}
                    className="font-mono text-[10px] tabular-nums"
                  >
                    {usbStatus?.online ? `LIVE ${usbStatus.width}×${usbStatus.height}` : "STANDBY"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 cursor-pointer px-1.5 text-[10px]"
                    onClick={() => {
                      setCalCameraId("usb_4k");
                      setCalModalOpen(true);
                    }}
                  >
                    Cal
                  </Button>
                </div>
              </CardHeader>
              <div
                onClick={(e) => void handleCameraFeedClick("usb_4k", e)}
                className={cn(
                  "relative aspect-video w-full bg-black",
                  taskMode ? "cursor-crosshair" : "cursor-zoom-in"
                )}
              >
                <video
                  ref={(el) => bridge.bindVideoElement("usb_4k", el)}
                  autoPlay
                  muted
                  playsInline
                  className={cn(
                    "h-full w-full object-contain",
                    bridge.liveStreams.usb_4k ? "block" : "hidden"
                  )}
                />
                {!bridge.liveStreams.usb_4k && (
                  <img
                    src={getOverwatchStreamUrl("usb_4k", streamNonce)}
                    alt="4K USB Overwatch Feed"
                    className="h-full w-full object-contain"
                  />
                )}
                {/* Live detection bounding-box overlay directly on top of zero-latency video */}
                {bridge.liveStreams.usb_4k &&
                  (usbStatus?.detections ?? []).map((d, idx) => {
                    const b = d.bbox_norm;
                    if (!b || b.length < 4) return null;
                    return (
                      <div
                        key={`usb-box-${idx}`}
                        style={{
                          left: `${b[0] * 100}%`,
                          top: `${b[1] * 100}%`,
                          width: `${Math.max(2, (b[2] - b[0]) * 100)}%`,
                          height: `${Math.max(2, (b[3] - b[1]) * 100)}%`,
                        }}
                        className="pointer-events-none absolute border-2 border-cyan-400/90"
                      >
                        <span className="absolute -top-4 left-0 whitespace-nowrap rounded bg-cyan-950/90 px-1 font-mono text-[9px] text-cyan-200">
                          {d.label} {Math.round(d.confidence * 100)}%
                        </span>
                      </div>
                    );
                  })}
                <div className="pointer-events-none absolute bottom-1.5 left-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                  {taskMode ? "CLICK FLOOR TO TASK PUPPYPI" : "CLICK ANY AREA TO UPSCALE ROI"}
                </div>
              </div>
              {renderDetectionChips("usb_4k", usbStatus?.detections ?? [])}
            </Card>

            {/* Slot 2: MacBook Pro Cross-Angle */}
            <Card className="overflow-hidden border-violet-500/25 bg-slate-950">
              <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Video className="h-4 w-4 text-violet-400" />
                  <CardTitle className="text-xs font-semibold text-slate-100">
                    {macStatus?.camera_name || "MacBook Pro Camera"} (macbook_cam)
                  </CardTitle>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge
                    variant={macStatus?.online ? "sky" : "neutral"}
                    className="font-mono text-[10px] tabular-nums"
                  >
                    {macStatus?.online ? `LIVE ${macStatus.width}×${macStatus.height}` : "STANDBY"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 cursor-pointer px-1.5 text-[10px]"
                    onClick={() => {
                      setCalCameraId("macbook_cam");
                      setCalModalOpen(true);
                    }}
                  >
                    Cal
                  </Button>
                </div>
              </CardHeader>
              <div
                onClick={(e) => void handleCameraFeedClick("macbook_cam", e)}
                className={cn(
                  "relative aspect-video w-full bg-black",
                  taskMode ? "cursor-crosshair" : "cursor-zoom-in"
                )}
              >
                <video
                  ref={(el) => bridge.bindVideoElement("macbook_cam", el)}
                  autoPlay
                  muted
                  playsInline
                  className={cn(
                    "h-full w-full object-contain",
                    bridge.liveStreams.macbook_cam ? "block" : "hidden"
                  )}
                />
                {!bridge.liveStreams.macbook_cam && (
                  <img
                    src={getOverwatchStreamUrl("macbook_cam", streamNonce)}
                    alt="MacBook Pro Cross-Angle Feed"
                    className="h-full w-full object-contain"
                  />
                )}
                {bridge.liveStreams.macbook_cam &&
                  (macStatus?.detections ?? []).map((d, idx) => {
                    const b = d.bbox_norm;
                    if (!b || b.length < 4) return null;
                    return (
                      <div
                        key={`mac-box-${idx}`}
                        style={{
                          left: `${b[0] * 100}%`,
                          top: `${b[1] * 100}%`,
                          width: `${Math.max(2, (b[2] - b[0]) * 100)}%`,
                          height: `${Math.max(2, (b[3] - b[1]) * 100)}%`,
                        }}
                        className="pointer-events-none absolute border-2 border-violet-400/90"
                      >
                        <span className="absolute -top-4 left-0 whitespace-nowrap rounded bg-violet-950/90 px-1 font-mono text-[9px] text-violet-200">
                          {d.label} {Math.round(d.confidence * 100)}%
                        </span>
                      </div>
                    );
                  })}
                <div className="pointer-events-none absolute bottom-1.5 left-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-violet-300">
                  {taskMode ? "CLICK FLOOR TO TASK PUPPYPI" : "CLICK ANY AREA TO UPSCALE ROI"}
                </div>
              </div>
              {renderDetectionChips("macbook_cam", macStatus?.detections ?? [])}
            </Card>
          </div>

          {/* Slot 3: PuppyPi Mobile FPV + Persistent Global Track Roster */}
          <div className="grid gap-3 md:grid-cols-12">
            <Card className="overflow-hidden border-emerald-500/25 bg-slate-950 md:col-span-6">
              <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Eye className="h-4 w-4 text-emerald-400" />
                  <CardTitle className="text-xs font-semibold text-slate-100">
                    PuppyPi Mobile UGV FPV (640×480)
                  </CardTitle>
                </div>
                <Badge variant="neutral" className="border-emerald-500/40 font-mono text-[10px] text-emerald-300">
                  GROUND SCOUT
                </Badge>
              </CardHeader>
              <div className="relative aspect-video w-full bg-black">
                {activeRobotId ? (
                  <img
                    src={`${getRobotVideoStreamUrl(activeRobotId)}&_ow=${streamNonce}`}
                    alt="PuppyPi Pro Mobile FPV"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center font-mono text-xs text-slate-400">
                    No active robot selected — pick PuppyPi in top bar
                  </div>
                )}
              </div>
            </Card>

            <Card className="border-white/10 bg-slate-950 md:col-span-6">
              <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-3 py-2">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                  Fused Global Tracks ({tracks.length})
                </CardTitle>
                <Badge variant="neutral" className="font-mono text-[10px]">
                  N-RAY + RE-ID
                </Badge>
              </CardHeader>
              <CardContent className="max-h-[210px] space-y-2 overflow-y-auto p-3">
                {tracks.length === 0 ? (
                  <p className="text-xs text-slate-400">
                    No active fused tracks yet. Enable local cameras to start real-time N-ray triangulation and
                    cross-view Re-ID tracking.
                  </p>
                ) : (
                  tracks.map((t) => (
                    <div
                      key={t.track_id}
                      className="flex items-center justify-between rounded-md border border-white/10 bg-slate-900/80 px-2.5 py-1.5 text-xs"
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-cyan-300">{t.track_id}</span>
                          <span className="font-medium text-slate-100">{t.label}</span>
                          <Badge variant="neutral" className="font-mono text-[9px]">
                            {t.cameras.join(" + ")}
                          </Badge>
                        </div>
                        <div className="font-mono text-[10px] text-slate-400 tabular-nums">
                          ({t.x.toFixed(2)}, {t.y.toFixed(2)}, z={t.z.toFixed(2)}m) · 2σ ±{t.ellipse_2sigma.semi_major_m.toFixed(2)}m
                        </div>
                      </div>
                      <Badge
                        variant="neutral"
                        className={cn(
                          "font-mono text-[10px]",
                          RATING_BADGE[t.gdop_rating] ?? "border-slate-700 text-slate-300"
                        )}
                      >
                        GDOP {t.gdop}
                      </Badge>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          {/* Click-to-Task Dispatch Preview Banner */}
          {(taskPreview || taskError) && (
            <Card className="border-cyan-500/40 bg-cyan-950/20">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3 text-xs">
                {taskError ? (
                  <span className="text-red-300">{taskError}</span>
                ) : taskPreview ? (
                  <>
                    <div className="space-y-0.5">
                      <div className="font-semibold text-cyan-200">
                        Projected Floor Target ({taskPreview.projection_method}): ({taskPreview.target_xy[0].toFixed(2)}m,{" "}
                        {taskPreview.target_xy[1].toFixed(2)}m)
                      </div>
                      <div className="font-mono text-[11px] text-slate-300 tabular-nums">
                        Turn {taskPreview.relative_turn_deg > 0 ? "+" : ""}
                        {taskPreview.relative_turn_deg.toFixed(0)}° · Walk {taskPreview.walk_distance_m.toFixed(2)}m ·{" "}
                        {taskPreview.dispatch_note}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="sky"
                      disabled={taskBusy || estopActive}
                      onClick={() => void handleDispatchPreview()}
                      className="cursor-pointer"
                    >
                      <Navigation className="mr-1.5 h-3.5 w-3.5" />
                      Dispatch PuppyPi Here
                    </Button>
                  </>
                ) : null}
              </CardContent>
            </Card>
          )}

          {/* Target ROI Super-Resolution Loupe (Local + fal.ai) */}
          {selectedRoi && (
            <TargetUpscaleLoupe
              cameraId={selectedRoi.cameraId}
              targetLabel={selectedRoi.label}
              bboxNorm={selectedRoi.bboxNorm}
            />
          )}
        </div>

        {/* Right Column: Unified Live BEV Tactical Map */}
        <div className="space-y-3 xl:col-span-5">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-slate-950/90 px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Layers className="h-4 w-4 text-cyan-400" />
              Unified BEV Tactical Map
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                size="sm"
                variant={showFrustums ? "sky" : "outline"}
                onClick={() => setShowFrustums((v) => !v)}
                className="h-7 cursor-pointer px-2 text-[11px]"
              >
                Frustums
              </Button>
              <Button
                size="sm"
                variant={showOverlap ? "sky" : "outline"}
                onClick={() => setShowOverlap((v) => !v)}
                className="h-7 cursor-pointer px-2 text-[11px]"
              >
                Overlap 0/1/2/3+
              </Button>
              <Button
                size="sm"
                variant={showEllipses ? "sky" : "outline"}
                onClick={() => setShowEllipses((v) => !v)}
                className="h-7 cursor-pointer px-2 text-[11px]"
              >
                2σ GDOP
              </Button>
            </div>
          </div>

          <Lidar2DCanvas
            frame={frame}
            equipment={equipment}
            darkZones={darkZones}
            selectedEquipmentId={null}
            pendingPin={
              taskPreview
                ? { x: taskPreview.target_xy[0], y: taskPreview.target_xy[1] }
                : null
            }
            focusTarget={null}
            overwatchStatus={usbStatus}
            overwatchGeometry={geometry}
            showFrustums={showFrustums}
            showOverlapHeatmap={showOverlap}
            showGdopEllipses={showEllipses}
            onSelectEquipment={() => {}}
            onMapClick={(x, y) => {
              setLastTaskClick({ kind: "bev", x, y });
              setTaskPreview({
                ok: true,
                camera_id: "bev_map",
                target_xy: [Number(x.toFixed(3)), Number(y.toFixed(3))],
                waypoint_xy: [Number(x.toFixed(3)), Number(y.toFixed(3))],
                projection_method: "bev_direct_click",
                distance_from_robot_m: Math.hypot(x, y),
                walk_distance_m: Math.max(0, Math.hypot(x, y) - 0.3),
                target_heading_deg: (Math.atan2(y, x) * 180) / Math.PI,
                relative_turn_deg: (Math.atan2(y, x) * 180) / Math.PI,
                dispatched: false,
                dispatch_note: "Selected directly on BEV map.",
              });
            }}
          />

          {/* Compact Coverage Legend */}
          <div className="grid grid-cols-4 gap-2 rounded-lg border border-white/10 bg-slate-950/90 p-2.5 font-mono text-[10px]">
            <div className="flex items-center gap-1.5 text-red-300">
              <span className="h-2.5 w-2.5 rounded-sm bg-red-500/50 border border-red-400" />
              0-Cam Blind
            </div>
            <div className="flex items-center gap-1.5 text-amber-300">
              <span className="h-2.5 w-2.5 rounded-sm bg-amber-500/40 border border-amber-400" />
              1-Cam Mono
            </div>
            <div className="flex items-center gap-1.5 text-emerald-300">
              <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500/40 border border-emerald-400" />
              2-Cam Stereo
            </div>
            <div className="flex items-center gap-1.5 text-cyan-300">
              <span className="h-2.5 w-2.5 rounded-sm bg-cyan-500/45 border border-cyan-400" />
              3+ Fusion
            </div>
          </div>
        </div>
      </div>

      <CameraCalibrationModal
        open={calModalOpen}
        initialCameraId={calCameraId}
        onClose={() => setCalModalOpen(false)}
        onCalibrated={(geo) => {
          setGeometry(geo);
          void pollOverwatch();
        }}
      />
    </div>
  );
}
