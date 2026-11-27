"use client";

import React, { useState } from "react";
import { CheckCircle2, Crosshair, Loader2, QrCode, RotateCcw, Sparkles, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  calibrateOverwatchAprilTag,
  calibrateOverwatchHomography,
  getOverwatchSnapshotUrl,
  type OverwatchGeometry,
} from "@/lib/overwatchApi";
import { cn } from "@/lib/utils";

interface CameraCalibrationModalProps {
  open: boolean;
  initialCameraId?: "usb_4k" | "macbook_cam";
  onClose: () => void;
  onCalibrated: (geometry: OverwatchGeometry) => void;
}

const DEFAULT_WORLD_POINTS: Array<[number, number]> = [
  [-1.0, 0.0],
  [1.0, 0.0],
  [1.0, 2.0],
  [-1.0, 2.0],
];

export function CameraCalibrationModal({
  open,
  initialCameraId = "usb_4k",
  onClose,
  onCalibrated,
}: CameraCalibrationModalProps): React.JSX.Element | null {
  const [tab, setTab] = useState<"homography" | "apriltag">("homography");
  const [cameraId, setCameraId] = useState<string>(initialCameraId);
  const [snapshotNonce, setSnapshotNonce] = useState<number>(() => Date.now());
  const [pixelPoints, setPixelPoints] = useState<Array<[number, number]>>([]);
  const [worldPoints, setWorldPoints] = useState<Array<[number, number]>>(DEFAULT_WORLD_POINTS);

  // AprilTag settings
  const [tagSizeCm, setTagSizeCm] = useState("12");
  const [tagWorldX, setTagWorldX] = useState("0.0");
  const [tagWorldY, setTagWorldY] = useState("0.0");
  const [tagWorldZ, setTagWorldZ] = useState("0.0");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  if (!open) return null;

  const handleImageClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (pixelPoints.length >= 4) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    const v = Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height)));
    setPixelPoints((prev) => [...prev, [Number(u.toFixed(4)), Number(v.toFixed(4))]]);
    setError(null);
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
        camera_id: cameraId === "all" ? "usb_4k" : cameraId,
        pixel_points_norm: pixelPoints,
        world_points_xy: worldPoints,
      });
      setSuccessMsg(
        `Solved 4-Point Homography for ${res.camera_id} (reprojection error: ${res.reprojection_error_px.toFixed(2)} px, pos: ${res.calibration.x_m.toFixed(2)}, ${res.calibration.y_m.toFixed(2)}, z=${res.calibration.z_m.toFixed(2)}m)`
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
          .map(([cid, r]) => `${cid}: ${r.error ?? "failed"}`)
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <Card className="w-full max-w-4xl border-white/15 bg-slate-950 text-slate-100 shadow-2xl">
        <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 pb-3">
          <div className="flex items-center gap-2.5">
            <Crosshair className="h-5 w-5 text-cyan-400" />
            <CardTitle className="text-base font-semibold tracking-tight">
              Auto-Extrinsic Camera Calibration
            </CardTitle>
            <Badge variant="sky" className="font-mono text-[10px]">
              6-DOF PnP + Homography
            </Badge>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="cursor-pointer">
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant={tab === "homography" ? "default" : "outline"}
                onClick={() => setTab("homography")}
                className="cursor-pointer"
              >
                <Crosshair className="mr-1.5 h-3.5 w-3.5" />
                4-Point Floor Click (No Tag Needed)
              </Button>
              <Button
                size="sm"
                variant={tab === "apriltag" ? "default" : "outline"}
                onClick={() => setTab("apriltag")}
                className="cursor-pointer"
              >
                <QrCode className="mr-1.5 h-3.5 w-3.5" />
                1-Click AprilTag Auto-Cal
              </Button>
            </div>

            <div className="flex items-center gap-1.5">
              {(["usb_4k", "macbook_cam", ...(tab === "apriltag" ? ["all"] : [])] as const).map((cid) => (
                <Button
                  key={cid}
                  size="sm"
                  variant={cameraId === cid ? "sky" : "outline"}
                  onClick={() => {
                    setCameraId(cid);
                    setPixelPoints([]);
                    setSnapshotNonce(Date.now());
                  }}
                  className="cursor-pointer font-mono text-xs"
                >
                  {cid === "usb_4k" ? "4K USB" : cid === "macbook_cam" ? "MacBook Cam" : "All Active"}
                </Button>
              ))}
            </div>
          </div>

          {tab === "homography" ? (
            <div className="grid gap-4 lg:grid-cols-12">
              <div className="lg:col-span-7 space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>
                    Click <strong className="text-cyan-300">4 known floor corners</strong> on the frame ({pixelPoints.length}/4 placed)
                  </span>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 cursor-pointer px-2 text-xs"
                      onClick={() => setSnapshotNonce(Date.now())}
                    >
                      Refresh Frame
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 cursor-pointer px-2 text-xs"
                      onClick={() => setPixelPoints([])}
                    >
                      <RotateCcw className="mr-1 h-3 w-3" /> Clear
                    </Button>
                  </div>
                </div>
                <div
                  onClick={handleImageClick}
                  className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-lg border border-cyan-500/30 bg-slate-900"
                >
                  <img
                    src={`${getOverwatchSnapshotUrl(cameraId === "all" ? "usb_4k" : cameraId, false)}&t=${snapshotNonce}`}
                    alt="Calibration snapshot"
                    className="h-full w-full object-contain select-none"
                    draggable={false}
                  />
                  {pixelPoints.map(([u, v], idx) => (
                    <div
                      key={idx}
                      style={{ left: `${u * 100}%`, top: `${v * 100}%` }}
                      className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2"
                    >
                      <div className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-cyan-300 bg-slate-950/90 font-mono text-[10px] font-bold text-cyan-300 shadow">
                        P{idx + 1}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="lg:col-span-5 flex flex-col justify-between space-y-3">
                <div className="space-y-2">
                  <div className="text-xs font-medium text-slate-300">
                    Matching Floor Coordinates (meters, z = 0)
                  </div>
                  {worldPoints.map(([wx, wy], idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "grid grid-cols-12 items-center gap-2 rounded-md border px-2.5 py-1.5",
                        idx < pixelPoints.length
                          ? "border-cyan-500/40 bg-cyan-950/20"
                          : "border-white/10 bg-slate-900/60"
                      )}
                    >
                      <span className="col-span-3 font-mono text-xs font-semibold text-cyan-300">
                        P{idx + 1} {idx < pixelPoints.length ? "✓" : ""}
                      </span>
                      <div className="col-span-4">
                        <Input
                          type="number"
                          step="0.1"
                          value={wx}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setWorldPoints((prev) => prev.map((pt, i) => (i === idx ? [val, pt[1]] : pt)));
                          }}
                          className="h-7 font-mono text-xs"
                          aria-label={`P${idx + 1} X meters`}
                        />
                      </div>
                      <div className="col-span-5">
                        <Input
                          type="number"
                          step="0.1"
                          value={wy}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setWorldPoints((prev) => prev.map((pt, i) => (i === idx ? [pt[0], val] : pt)));
                          }}
                          className="h-7 font-mono text-xs"
                          aria-label={`P${idx + 1} Y meters`}
                        />
                      </div>
                    </div>
                  ))}
                  <p className="text-[11px] text-slate-400">
                    Tip: Place tape or use rug/tile corners at known distances around PuppyPi&apos;s origin (0, 0).
                  </p>
                </div>

                <Button
                  onClick={handleSolveHomography}
                  disabled={busy || pixelPoints.length < 4}
                  className="w-full cursor-pointer"
                >
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                  Solve 4-Point Homography & Lock Frustum
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4 rounded-lg border border-white/10 bg-slate-900/50 p-4">
              <p className="text-xs text-slate-300">
                Place one printed <strong className="text-cyan-300">AprilTag (36h11)</strong> flat on the floor at the
                origin (or on PuppyPi&apos;s roof) visible to your camera(s), then click Auto-Calibrate to solve exact
                6-DOF camera position &amp; angles in 2 seconds.
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Tag Side (cm)</label>
                  <Input value={tagSizeCm} onChange={(e) => setTagSizeCm(e.target.value)} className="font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Tag World X (m)</label>
                  <Input value={tagWorldX} onChange={(e) => setTagWorldX(e.target.value)} className="font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Tag World Y (m)</label>
                  <Input value={tagWorldY} onChange={(e) => setTagWorldY(e.target.value)} className="font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Tag World Z (m)</label>
                  <Input value={tagWorldZ} onChange={(e) => setTagWorldZ(e.target.value)} className="font-mono text-xs" />
                </div>
              </div>
              <Button onClick={handleSolveAprilTag} disabled={busy} className="cursor-pointer">
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <QrCode className="mr-2 h-4 w-4" />}
                Auto-Calibrate via AprilTag solvePnP
              </Button>
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-500/40 bg-red-950/40 px-3 py-2 text-xs text-red-200">
              {error}
            </div>
          )}
          {successMsg && (
            <div className="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-200">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{successMsg}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
