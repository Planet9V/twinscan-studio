"use client";

import React, { useEffect, useState } from "react";
import {
  Bot,
  CheckCircle2,
  Crosshair,
  HelpCircle,
  Loader2,
  QrCode,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  calibrateOverwatchAprilTag,
  calibrateOverwatchHomography,
  getOverwatchSnapshotUrl,
  recordSelfCalibrationSample,
  solveSelfCalibration,
  startSelfCalibration,
  updateOverwatchCalibration,
  type OverwatchCameraSlot,
  type OverwatchGeometry,
  type SelfCalibrationSessionState,
} from "@/lib/overwatchApi";
import { cn } from "@/lib/utils";

interface CameraCalibrationModalProps {
  open: boolean;
  initialCameraId?: string;
  cameras?: Record<string, OverwatchCameraSlot>;
  robotPose?: { x?: number; y?: number; yaw_deg?: number } | null;
  onClose: () => void;
  onCalibrated: (geometry?: OverwatchGeometry) => void;
}

const DEFAULT_WORLD_POINTS: Array<[number, number]> = [
  [-1.0, 0.5],
  [1.0, 0.5],
  [1.0, 2.5],
  [-1.0, 2.5],
];

type CalTab = "self_cal" | "apriltag" | "homography" | "manual";

export function CameraCalibrationModal({
  open,
  initialCameraId = "usb_4k",
  cameras = {},
  robotPose = null,
  onClose,
  onCalibrated,
}: CameraCalibrationModalProps): React.JSX.Element | null {
  const cameraList = Object.values(cameras);
  const fallbackIds = cameraList.length > 0 ? cameraList.map((c) => c.camera_id) : ["usb_4k", "macbook_cam"];

  const [tab, setTab] = useState<CalTab>("self_cal");
  const [showHelp, setShowHelp] = useState(false);
  const [cameraId, setCameraId] = useState<string>(initialCameraId);
  const [snapshotNonce, setSnapshotNonce] = useState<number>(() => Date.now());

  // 4-point Homography state
  const [pixelPoints, setPixelPoints] = useState<Array<[number, number]>>([]);
  const [worldPoints, setWorldPoints] = useState<Array<[number, number]>>(DEFAULT_WORLD_POINTS);

  // Self-Calibration session state
  const [selfSession, setSelfSession] = useState<SelfCalibrationSessionState | null>(null);
  const [sampleX, setSampleX] = useState("0.0");
  const [sampleY, setSampleY] = useState("1.0");
  const [clickedUv, setClickedUv] = useState<[number, number] | null>(null);

  // AprilTag state
  const [tagSizeCm, setTagSizeCm] = useState("12");
  const [tagWorldX, setTagWorldX] = useState("0.0");
  const [tagWorldY, setTagWorldY] = useState("0.0");
  const [tagWorldZ, setTagWorldZ] = useState("0.0");

  // Manual placement state
  const [manX, setManX] = useState("0.0");
  const [manY, setManY] = useState("-2.2");
  const [manZ, setManZ] = useState("1.45");
  const [manYaw, setManYaw] = useState("90");
  const [manPitch, setManPitch] = useState("-22");
  const [manHfov, setManHfov] = useState("78");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setCameraId(initialCameraId || fallbackIds[0] || "usb_4k");
      setSnapshotNonce(Date.now());
      setError(null);
      setSuccessMsg(null);
    }
  }, [open, initialCameraId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const active = cameras[cameraId]?.calibration;
    if (active) {
      setManX(String(active.x_m));
      setManY(String(active.y_m));
      setManZ(String(active.z_m));
      setManYaw(String(active.yaw_deg));
      setManPitch(String(active.pitch_deg));
      setManHfov(String(active.hfov_deg));
    }
  }, [cameraId, cameras]);

  useEffect(() => {
    if (robotPose && typeof robotPose.x === "number" && typeof robotPose.y === "number") {
      setSampleX(robotPose.x.toFixed(2));
      setSampleY(robotPose.y.toFixed(2));
    }
  }, [robotPose]);

  if (!open) return null;

  const activeSingleCameraId = cameraId === "all" ? fallbackIds[0] || "usb_4k" : cameraId;

  const handleImageClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    const v = Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height)));
    if (tab === "homography") {
      if (pixelPoints.length >= 4) return;
      setPixelPoints((prev) => [...prev, [Number(u.toFixed(4)), Number(v.toFixed(4))]]);
      setError(null);
    } else if (tab === "self_cal") {
      setClickedUv([Number(u.toFixed(4)), Number(v.toFixed(4))]);
      setError(null);
    }
  };

  const handleStartSelfCal = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const ids = cameraId === "all" ? ["all"] : [cameraId];
      const res = await startSelfCalibration(ids);
      setSelfSession(res.session);
      setClickedUv(null);
      setSuccessMsg(
        `Self-calibration started for ${res.session.target_cameras.join(", ")}. Park PuppyPi at 4 spread-out floor spots and capture each point.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start self-calibration.");
    } finally {
      setBusy(false);
    }
  };

  const handleCaptureSelfCalPoint = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const wx = Number(sampleX);
      const wy = Number(sampleY);
      const manualObs = clickedUv ? { [activeSingleCameraId]: clickedUv } : undefined;
      const res = await recordSelfCalibrationSample({
        world_xy: Number.isFinite(wx) && Number.isFinite(wy) ? [wx, wy] : null,
        manual_observations: manualObs,
        source: clickedUv ? "clicked_robot_pose" : "auto_robot_pose",
      });
      setSelfSession(res.session);
      setClickedUv(null);
      setSnapshotNonce(Date.now());
      setSuccessMsg(
        `Captured point #${res.session.sample_count} at (${wx.toFixed(2)}, ${wy.toFixed(2)}) m for ${(res.session.captured_cameras || []).join(", ")}.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not capture calibration point.");
    } finally {
      setBusy(false);
    }
  };

  const handleSolveSelfCal = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await solveSelfCalibration();
      setSelfSession(res.session);
      const summary = Object.entries(res.results)
        .filter(([, r]) => r.ok)
        .map(([cid, r]) => `${cid} (${r.reprojection_error_px?.toFixed(1) ?? "?"} px)`)
        .join(", ");
      setSuccessMsg(`Self-calibration saved! Solved: ${summary}`);
      onCalibrated(res.geometry);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Self-calibration solve failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleSolveHomography = async () => {
    if (pixelPoints.length < 4) {
      setError("Click 4 floor corners on the camera image first (P1 through P4).");
      return;
    }
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await calibrateOverwatchHomography({
        camera_id: activeSingleCameraId,
        pixel_points_norm: pixelPoints,
        world_points_xy: worldPoints,
      });
      setSuccessMsg(
        `Solved 4-Point Homography for ${res.camera_id} (error: ${res.reprojection_error_px.toFixed(2)} px, pos: ${res.calibration.x_m.toFixed(2)}, ${res.calibration.y_m.toFixed(2)}, z=${res.calibration.z_m.toFixed(2)}m)`
      );
      onCalibrated(res.geometry);
    } catch (err) {
      setError(err instanceof Error ? err.message : "4-point homography calibration failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleSolveAprilTag = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await calibrateOverwatchAprilTag({
        camera_id: cameraId,
        tag_size_m: Math.max(0.02, Number(tagSizeCm) / 100),
        tag_world_x: Number(tagWorldX) || 0,
        tag_world_y: Number(tagWorldY) || 0,
        tag_world_z: Number(tagWorldZ) || 0,
      });
      if (!res.ok) {
        const details = Object.entries(res.results)
          .map(([cid, r]) => `${cid}: ${r.error ?? "no tag detected"}`)
          .join(" | ");
        setError(details || "No AprilTag detected in active camera frame.");
      } else {
        const okList = Object.entries(res.results)
          .filter(([, r]) => r.ok)
          .map(([cid, r]) => `${cid} (Tag #${r.tag_id}, ${r.reprojection_error_px?.toFixed(1)}px)`)
          .join(", ");
        setSuccessMsg(`Auto-calibrated via AprilTag solvePnP: ${okList}`);
        onCalibrated(res.geometry);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "AprilTag calibration failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveManual = async () => {
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await updateOverwatchCalibration(
        {
          x_m: Number(manX) || 0,
          y_m: Number(manY) || 0,
          z_m: Math.max(0.1, Number(manZ) || 1.4),
          yaw_deg: Number(manYaw) || 90,
          pitch_deg: Number(manPitch) || -20,
          hfov_deg: Number(manHfov) || 78,
        },
        activeSingleCameraId
      );
      setSuccessMsg(`Saved manual placement for ${activeSingleCameraId} to PostgreSQL.`);
      onCalibrated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save manual calibration.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-3 backdrop-blur-sm">
      <Card className="flex max-h-[92vh] w-full max-w-5xl flex-col border-white/15 bg-slate-950 text-slate-100 shadow-2xl">
        <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <Crosshair className="h-5 w-5 text-cyan-400" />
            <CardTitle className="text-base font-semibold tracking-tight">
              Overwatch Calibration & Self-Calibration Wizard
            </CardTitle>
            <Badge variant="sky" className="font-mono text-[10px]">
              On-Demand Multi-Camera
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={showHelp ? "default" : "outline"}
              size="sm"
              onClick={() => setShowHelp((v) => !v)}
              className="h-7 gap-1.5 text-xs cursor-pointer"
            >
              <HelpCircle className="h-3.5 w-3.5" />
              Calibration Guide
            </Button>
            <Button variant="ghost" size="icon" onClick={onClose} className="cursor-pointer">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="flex-1 space-y-4 overflow-y-auto pt-4">
          {/* Collapsible Calibration Help Menu */}
          {showHelp && (
            <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/25 p-4 text-xs text-slate-200">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-semibold text-cyan-300">How & When to Calibrate Overwatch Cameras</span>
                <span className="text-[11px] text-slate-400">Re-run anytime you move or add a camera</span>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-white/10 bg-slate-950/60 p-2.5">
                  <div className="font-semibold text-emerald-300">1. PuppyPi Self-Calibrate (No Printing!)</div>
                  <p className="mt-1 text-[11px] text-slate-300">
                    Drive or place PuppyPi at 4 spread-out spots on the floor. Click <strong>Capture Point</strong> at
                    each spot (or click where PuppyPi stands on the preview). Solves all cameras seeing PuppyPi at once!
                  </p>
                </div>
                <div className="rounded-lg border border-white/10 bg-slate-950/60 p-2.5">
                  <div className="font-semibold text-cyan-300">2. AprilTag 1-Click (Fastest)</div>
                  <p className="mt-1 text-[11px] text-slate-300">
                    Place a <code>tag36h11</code> AprilTag flat on the floor (or on PuppyPi) at a known coordinate and
                    click <strong>Detect &amp; Auto-Calibrate</strong> to solve 6-DoF pose across all cameras instantly.
                  </p>
                </div>
                <div className="rounded-lg border border-white/10 bg-slate-950/60 p-2.5">
                  <div className="font-semibold text-amber-300">3. Best Stereo Placement Tips</div>
                  <p className="mt-1 text-[11px] text-slate-300">
                    Mount cameras 1.2–2.2 m high angled 15°–30° downward, separated by <strong>60°–120°</strong> around
                    the room for tight triangulation ellipses and rich 3D Room Digital Twins.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Method Tabs + Dynamic Camera Selector */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  { id: "self_cal", label: "Self-Calibrate (PuppyPi)", icon: Bot },
                  { id: "apriltag", label: "1-Click AprilTag", icon: QrCode },
                  { id: "homography", label: "4-Point Floor Click", icon: Crosshair },
                  { id: "manual", label: "Manual Pose", icon: SlidersHorizontal },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <Button
                  key={id}
                  size="sm"
                  variant={tab === id ? "default" : "outline"}
                  onClick={() => {
                    setTab(id);
                    setError(null);
                  }}
                  className={cn(
                    "h-8 gap-1.5 text-xs cursor-pointer",
                    tab === id && "bg-cyan-600 text-white hover:bg-cyan-500"
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </Button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {fallbackIds.map((cid) => {
                const slot = cameras[cid];
                const isCal = Boolean(slot?.calibration?.calibrated);
                return (
                  <button
                    key={cid}
                    type="button"
                    onClick={() => {
                      setCameraId(cid);
                      setPixelPoints([]);
                      setClickedUv(null);
                      setSnapshotNonce(Date.now());
                    }}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium cursor-pointer",
                      cameraId === cid
                        ? "border-cyan-400 bg-cyan-950/60 text-cyan-200"
                        : "border-white/10 bg-slate-900 text-slate-400 hover:text-slate-200"
                    )}
                  >
                    <span>{slot?.camera_name || cid}</span>
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        isCal ? "bg-emerald-400" : "bg-amber-400"
                      )}
                    />
                  </button>
                );
              })}
              {(tab === "apriltag" || tab === "self_cal") && (
                <button
                  type="button"
                  onClick={() => setCameraId("all")}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs font-medium cursor-pointer",
                    cameraId === "all"
                      ? "border-emerald-400 bg-emerald-950/60 text-emerald-200"
                      : "border-white/10 bg-slate-900 text-slate-400 hover:text-slate-200"
                  )}
                >
                  All Cameras
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-950/50 px-3 py-2 text-xs text-red-200">
              {error}
            </div>
          )}
          {successMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/50 px-3 py-2 text-xs text-emerald-200">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* TAB 1: Guided PuppyPi Self-Calibration */}
          {tab === "self_cal" && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
              <div className="space-y-2 lg:col-span-3">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>
                    Optional: click where PuppyPi stands on <strong>{activeSingleCameraId}</strong> (or leave blank for auto-detect)
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setSnapshotNonce(Date.now())}
                    className="h-6 gap-1 text-[11px] cursor-pointer"
                  >
                    <RotateCcw className="h-3 w-3" /> Refresh Frame
                  </Button>
                </div>
                <div
                  onClick={handleImageClick}
                  className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg border border-white/15 bg-black"
                >
                  <img
                    src={`${getOverwatchSnapshotUrl(activeSingleCameraId, false)}&t=${snapshotNonce}`}
                    alt="Self-calibration live preview"
                    className="h-full w-full object-contain"
                  />
                  {clickedUv && (
                    <div
                      style={{ left: `${clickedUv[0] * 100}%`, top: `${clickedUv[1] * 100}%` }}
                      className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-emerald-400 bg-emerald-500/40 px-2 py-0.5 text-[10px] font-bold text-white"
                    >
                      Robot
                    </div>
                  )}
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-white/10 bg-slate-900/60 p-3.5 lg:col-span-2">
                <div className="text-xs font-semibold text-cyan-300">
                  Step-by-Step Self-Calibration Sequence
                </div>
                <ol className="list-decimal space-y-1 pl-4 text-[11px] text-slate-300">
                  <li>Click <strong>Start Sequence</strong> for one or all cameras.</li>
                  <li>Place or drive PuppyPi to 4 spread-out floor positions.</li>
                  <li>At each stop, click <strong>Capture Point</strong> (uses live LiDAR X/Y or your override).</li>
                  <li>Click <strong>Solve &amp; Save Calibration</strong> once 4+ points are captured.</li>
                </ol>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="mb-1 block text-[10px] text-slate-400">Robot Floor X (m)</label>
                    <Input
                      value={sampleX}
                      onChange={(e) => setSampleX(e.target.value)}
                      className="h-8 bg-slate-950 font-mono text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] text-slate-400">Robot Floor Y (m)</label>
                    <Input
                      value={sampleY}
                      onChange={(e) => setSampleY(e.target.value)}
                      className="h-8 bg-slate-950 font-mono text-xs"
                    />
                  </div>
                </div>

                {selfSession && (
                  <div className="space-y-1.5 rounded-md border border-white/10 bg-slate-950/70 p-2.5 text-[11px]">
                    <div className="font-semibold text-slate-200">
                      Captured Points: {selfSession.sample_count}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(selfSession.per_camera_counts).map(([cid, cnt]) => (
                        <Badge
                          key={cid}
                          variant={cnt >= 4 ? "sky" : "neutral"}
                          className="font-mono text-[10px]"
                        >
                          {cid}: {cnt}/4
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex flex-col gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void handleStartSelfCal()}
                    className="h-8 text-xs cursor-pointer"
                  >
                    1. {selfSession ? "Restart Sequence" : "Start Sequence"}
                  </Button>
                  <Button
                    size="sm"
                    disabled={busy || !selfSession}
                    onClick={() => void handleCaptureSelfCalPoint()}
                    className="h-8 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
                  >
                    {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
                    2. Capture Point {(selfSession?.sample_count ?? 0) + 1}
                  </Button>
                  <Button
                    size="sm"
                    disabled={busy || !selfSession || selfSession.ready_cameras.length === 0}
                    onClick={() => void handleSolveSelfCal()}
                    className="h-8 bg-emerald-600 text-xs text-white hover:bg-emerald-500 cursor-pointer"
                  >
                    <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                    3. Solve &amp; Save Calibration
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: 1-Click AprilTag solvePnP */}
          {tab === "apriltag" && (
            <div className="space-y-4 rounded-lg border border-white/10 bg-slate-900/60 p-4">
              <p className="text-xs text-slate-300">
                Place a printed <code>tag36h11</code> AprilTag flat on the floor (or on PuppyPi) at the coordinates
                below, then run 1-click <code>solvePnP</code> across your selected camera or all active cameras.
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Tag Size (cm)</label>
                  <Input value={tagSizeCm} onChange={(e) => setTagSizeCm(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">World X (m)</label>
                  <Input value={tagWorldX} onChange={(e) => setTagWorldX(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">World Y (m)</label>
                  <Input value={tagWorldY} onChange={(e) => setTagWorldY(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">World Z (m)</label>
                  <Input value={tagWorldZ} onChange={(e) => setTagWorldZ(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
              </div>
              <Button
                onClick={() => void handleSolveAprilTag()}
                disabled={busy}
                className="gap-2 bg-emerald-600 text-xs text-white hover:bg-emerald-500 cursor-pointer"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                Detect AprilTag &amp; Auto-Calibrate ({cameraId === "all" ? "All Cameras" : cameraId})
              </Button>
            </div>
          )}

          {/* TAB 3: 4-Point Floor Homography */}
          {tab === "homography" && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
              <div className="space-y-2 lg:col-span-3">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>Click 4 floor corners on <strong>{activeSingleCameraId}</strong> ({pixelPoints.length}/4)</span>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="ghost" onClick={() => setPixelPoints([])} className="h-6 text-[11px] cursor-pointer">
                      Clear Pins
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setSnapshotNonce(Date.now())} className="h-6 gap-1 text-[11px] cursor-pointer">
                      <RotateCcw className="h-3 w-3" /> Refresh
                    </Button>
                  </div>
                </div>
                <div
                  onClick={handleImageClick}
                  className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg border border-white/15 bg-black"
                >
                  <img
                    src={`${getOverwatchSnapshotUrl(activeSingleCameraId, false)}&t=${snapshotNonce}`}
                    alt="4-point floor calibration preview"
                    className="h-full w-full object-contain"
                  />
                  {pixelPoints.map(([u, v], idx) => (
                    <div
                      key={`pin_${idx}`}
                      style={{ left: `${u * 100}%`, top: `${v * 100}%` }}
                      className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-cyan-300 bg-cyan-600 px-1.5 py-0.5 font-mono text-[10px] font-bold text-white shadow"
                    >
                      P{idx + 1}
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-2.5 rounded-lg border border-white/10 bg-slate-900/60 p-3.5 lg:col-span-2">
                <div className="text-xs font-semibold text-cyan-300">Matching Floor Coordinates (meters)</div>
                {worldPoints.map(([wx, wy], idx) => (
                  <div key={`wp_${idx}`} className="grid grid-cols-5 items-center gap-2">
                    <span className="font-mono text-xs text-cyan-300">P{idx + 1}</span>
                    <Input
                      value={wx}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setWorldPoints((prev) =>
                          prev.map((pt, i) => (i === idx ? [Number.isFinite(val) ? val : 0, pt[1]] : pt))
                        );
                      }}
                      className="col-span-2 h-7 bg-slate-950 font-mono text-xs"
                    />
                    <Input
                      value={wy}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setWorldPoints((prev) =>
                          prev.map((pt, i) => (i === idx ? [pt[0], Number.isFinite(val) ? val : 0] : pt))
                        );
                      }}
                      className="col-span-2 h-7 bg-slate-950 font-mono text-xs"
                    />
                  </div>
                ))}
                <Button
                  onClick={() => void handleSolveHomography()}
                  disabled={busy || pixelPoints.length < 4}
                  className="mt-2 w-full gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
                >
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  Solve 4-Point Homography
                </Button>
              </div>
            </div>
          )}

          {/* TAB 4: Quick Manual Pose */}
          {tab === "manual" && (
            <div className="space-y-4 rounded-lg border border-white/10 bg-slate-900/60 p-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Position X (m)</label>
                  <Input value={manX} onChange={(e) => setManX(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Position Y (m)</label>
                  <Input value={manY} onChange={(e) => setManY(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Height Z (m)</label>
                  <Input value={manZ} onChange={(e) => setManZ(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Yaw (deg, 90°=+Y)</label>
                  <Input value={manYaw} onChange={(e) => setManYaw(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Pitch (deg, negative down)</label>
                  <Input value={manPitch} onChange={(e) => setManPitch(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Horizontal FOV (deg)</label>
                  <Input value={manHfov} onChange={(e) => setManHfov(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                </div>
              </div>
              <Button
                onClick={() => void handleSaveManual()}
                disabled={busy}
                className="gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                Save Pose for {activeSingleCameraId}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
