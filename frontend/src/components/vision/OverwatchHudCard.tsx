"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Camera,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Crosshair,
  Download,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Terminal,
  Video,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getOverwatchSnapshotUrl,
  getOverwatchStatus,
  getOverwatchStreamUrl,
  updateOverwatchCalibration,
  type OverwatchCalibration,
  type OverwatchCameraId,
  type OverwatchMode,
  type OverwatchStatus,
} from "@/lib/overwatchApi";
import { cn } from "@/lib/utils";

export interface OverwatchHudCardProps {
  compact?: boolean;
  defaultVisible?: boolean;
  onStatusChange?: (status: OverwatchStatus | null) => void;
  className?: string;
}

type CameraViewSelection = "usb_4k" | "macbook_cam" | "dual";

const CAMERA_SELECTORS: Array<{ id: CameraViewSelection; label: string }> = [
  { id: "usb_4k", label: "4K USB" },
  { id: "macbook_cam", label: "MacBook Cam" },
  { id: "dual", label: "Dual" },
];

const OVERWATCH_MODES: Array<{ id: OverwatchMode; label: string }> = [
  { id: "yolo", label: "YOLO11n HD" },
  { id: "face", label: "Face ID" },
  { id: "apriltag", label: "AprilTag" },
  { id: "triangulate", label: "Triangulate" },
];

const BRIDGE_COMMAND =
  ".venv/bin/python -m src.bridge.mac_camera_bridge --all-cameras --width 1920 --height 1080";

export function OverwatchHudCard({
  compact = false,
  defaultVisible = true,
  onStatusChange,
  className,
}: OverwatchHudCardProps): React.JSX.Element {
  const [visible, setVisible] = useState(defaultVisible);
  const [cameraView, setCameraView] = useState<CameraViewSelection>("usb_4k");
  const [status, setStatus] = useState<OverwatchStatus | null>(null);
  const [streamNonce, setStreamNonce] = useState(0);
  const [usbStreamError, setUsbStreamError] = useState(false);
  const [macStreamError, setMacStreamError] = useState(false);
  const [showCalibration, setShowCalibration] = useState(false);
  const [savingCal, setSavingCal] = useState(false);
  const [busyMode, setBusyMode] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const [calDraft, setCalDraft] = useState<OverwatchCalibration>({
    x_m: 0.0,
    y_m: -2.2,
    z_m: 1.4,
    yaw_deg: 0.0,
    pitch_deg: -18.0,
    hfov_deg: 78.0,
    vfov_deg: 48.0,
    mode: "triangulate",
  });
  const editingCalRef = useRef(false);
  const usbImgRef = useRef<HTMLImageElement | null>(null);
  const macImgRef = useRef<HTMLImageElement | null>(null);

  const activeCameraId: OverwatchCameraId = cameraView === "macbook_cam" ? "macbook_cam" : "usb_4k";

  const teardownStreams = useCallback(() => {
    if (usbImgRef.current) {
      usbImgRef.current.src = "";
    }
    if (macImgRef.current) {
      macImgRef.current.src = "";
    }
  }, []);

  useEffect(() => {
    return () => {
      teardownStreams();
    };
  }, [teardownStreams]);

  useEffect(() => {
    if (!visible) {
      teardownStreams();
    }
  }, [visible, teardownStreams]);

  const pollStatus = useCallback(async () => {
    try {
      const next = await getOverwatchStatus(activeCameraId);
      setStatus(next);
      onStatusChange?.(next);
      if (!editingCalRef.current) {
        setCalDraft(next.calibration);
      }
    } catch {
      // Non-fatal while backend restarts or offline
    }
  }, [activeCameraId, onStatusChange]);

  useEffect(() => {
    void pollStatus();
    const timer = setInterval(() => {
      void pollStatus();
    }, visible ? 1800 : 4000);
    return () => clearInterval(timer);
  }, [pollStatus, visible]);

  const handleToggleVisible = () => {
    if (visible) {
      teardownStreams();
      setVisible(false);
    } else {
      setUsbStreamError(false);
      setMacStreamError(false);
      setStreamNonce((n) => n + 1);
      setVisible(true);
    }
  };

  const handleCameraViewChange = (nextView: CameraViewSelection) => {
    if (nextView === cameraView) return;
    teardownStreams();
    setUsbStreamError(false);
    setMacStreamError(false);
    editingCalRef.current = false;
    setCameraView(nextView);
    setStreamNonce((n) => n + 1);
  };

  const handleReconnect = () => {
    teardownStreams();
    setUsbStreamError(false);
    setMacStreamError(false);
    setStreamNonce((n) => n + 1);
    void pollStatus();
  };

  const handleSelectMode = async (mode: OverwatchMode) => {
    setBusyMode(true);
    setFeedback(null);
    try {
      const next = await updateOverwatchCalibration({ mode }, activeCameraId);
      setStatus(next);
      setCalDraft(next.calibration);
      onStatusChange?.(next);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed to switch Overwatch mode");
    } finally {
      setBusyMode(false);
    }
  };

  const handleSaveCalibration = async () => {
    setSavingCal(true);
    setFeedback(null);
    try {
      const next = await updateOverwatchCalibration(
        {
          x_m: Number(calDraft.x_m),
          y_m: Number(calDraft.y_m),
          z_m: Number(calDraft.z_m),
          yaw_deg: Number(calDraft.yaw_deg),
          pitch_deg: Number(calDraft.pitch_deg),
          hfov_deg: Number(calDraft.hfov_deg),
          vfov_deg: Number(calDraft.vfov_deg),
          mode: calDraft.mode,
        },
        activeCameraId
      );
      editingCalRef.current = false;
      setStatus(next);
      setCalDraft(next.calibration);
      onStatusChange?.(next);
      setFeedback(`Saved pose & FOV calibration for ${activeCameraId}.`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Calibration save failed");
    } finally {
      setSavingCal(false);
    }
  };

  const handleCopyCommand = () => {
    void navigator.clipboard?.writeText(BRIDGE_COMMAND);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 1800);
  };

  const usbSlot = status?.cameras?.usb_4k;
  const macSlot = status?.cameras?.macbook_cam;
  const anyOnline = Boolean(status?.online || usbSlot?.online || macSlot?.online);
  const currentMode: OverwatchMode = status?.mode ?? calDraft.mode ?? "triangulate";
  const resText =
    status && status.width > 0 && status.height > 0 ? `${status.width}×${status.height}` : "1080p";
  const fpsText = status && status.fps > 0 ? `${status.fps.toFixed(1)} FPS` : "-- FPS";
  const triangulated = status?.triangulated_targets ?? [];
  const detections = status?.detections ?? [];

  const usbStreamUrl = getOverwatchStreamUrl("usb_4k", streamNonce);
  const macStreamUrl = getOverwatchStreamUrl("macbook_cam", streamNonce);

  const renderFeedBox = (
    camId: "usb_4k" | "macbook_cam",
    label: string,
    url: string,
    hasErr: boolean,
    setErr: (v: boolean) => void,
    refObj: React.RefObject<HTMLImageElement | null>,
    slotOnline?: boolean
  ) => (
    <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian">
      {!hasErr ? (
        <img
          ref={refObj}
          key={url}
          src={url}
          alt={`${label} Overwatch Stream`}
          className="h-full w-full object-contain select-none"
          onError={() => setErr(true)}
        />
      ) : (
        <div className="flex flex-col items-center gap-1.5 p-3 text-center">
          <Camera className="h-5 w-5 text-eigenia-muted" />
          <div className="font-mono text-[10px] text-white">{label} Offline</div>
          <Button size="sm" variant="sky" className="h-6 px-2 text-[10px]" onClick={handleReconnect}>
            <RefreshCw className="h-3 w-3" />
            Reconnect
          </Button>
        </div>
      )}

      <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap items-center gap-1">
        <span
          className={cn(
            "rounded border bg-black/75 px-1.5 py-0.5 font-mono text-[9px] backdrop-blur-sm",
            slotOnline
              ? "border-emerald-400/50 text-emerald-300"
              : "border-eigenia-sky/40 text-eigenia-sky"
          )}
        >
          {label}
        </span>
        {camId === activeCameraId && status?.puppy_visual_pose?.seen && (
          <span className="rounded border border-eigenia-orange/60 bg-black/75 px-1.5 py-0.5 font-mono text-[9px] text-eigenia-orange backdrop-blur-sm">
            PUPPY ({status.puppy_visual_pose.x.toFixed(2)}, {status.puppy_visual_pose.y.toFixed(2)})m
          </span>
        )}
      </div>
    </div>
  );

  return (
    <Card className={cn("border-eigenia-sky/35 bg-eigenia-surface", className)}>
      <CardHeader className={cn("gap-2", compact ? "p-3" : "p-4")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="flex items-center gap-1.5 text-xs">
              <Video className="h-3.5 w-3.5 text-eigenia-sky" />
              HD Overwatch Room Cam (4K/1080p)
            </CardTitle>
            <Badge
              variant={anyOnline ? "sky" : "neutral"}
              className={cn(
                "font-mono text-[9px] tabular-nums",
                anyOnline && "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
              )}
            >
              {anyOnline ? `LIVE · ${resText} · ${fpsText}` : "STANDBY · BRIDGE IDLE"}
            </Badge>
            {triangulated.length > 0 && (
              <Badge variant="default" className="font-mono text-[9px] tabular-nums">
                <Crosshair className="h-2.5 w-2.5" />
                {triangulated.length} Triangulated
              </Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1">
            <Link
              href="/overwatch"
              className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-cyan-500/40 bg-cyan-950/40 px-2 font-mono text-[10px] font-semibold text-cyan-300 transition hover:bg-cyan-900/50"
            >
              <Crosshair className="h-3 w-3" />
              Full Cockpit →
            </Link>
            {/* Compact 4K USB | MacBook Cam | Dual Selector */}
            {visible && (
              <div
                role="group"
                aria-label="Overwatch Camera Source"
                className="inline-flex items-center rounded-md border border-white/10 bg-eigenia-obsidian p-0.5 font-mono text-[10px]"
              >
                {CAMERA_SELECTORS.map((cam) => {
                  const isActive = cameraView === cam.id;
                  const dotOnline =
                    cam.id === "usb_4k"
                      ? Boolean(usbSlot?.online)
                      : cam.id === "macbook_cam"
                        ? Boolean(macSlot?.online)
                        : Boolean(usbSlot?.online && macSlot?.online);
                  return (
                    <button
                      key={cam.id}
                      type="button"
                      onClick={() => handleCameraViewChange(cam.id)}
                      className={cn(
                        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors motion-reduce:transition-none",
                        isActive
                          ? "bg-eigenia-sky/25 text-white ring-1 ring-eigenia-sky/50"
                          : "text-eigenia-muted hover:text-white"
                      )}
                    >
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          dotOnline ? "bg-emerald-400" : "bg-white/20"
                        )}
                      />
                      {cam.label}
                    </button>
                  );
                })}
              </div>
            )}

            {visible && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2"
                  onClick={handleReconnect}
                  title="Reconnect HD Overwatch MJPEG stream"
                >
                  <RefreshCw className="h-3 w-3" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2"
                  asChild
                  title="Download full-resolution annotated snapshot"
                >
                  <a
                    href={getOverwatchSnapshotUrl(activeCameraId, true)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Download className="h-3 w-3" />
                  </a>
                </Button>
              </>
            )}
            <Button
              size="sm"
              variant={visible ? "secondary" : "sky"}
              className="h-7 px-2 font-mono text-[10px]"
              onClick={handleToggleVisible}
            >
              {visible ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              {visible ? "Hide" : "Show"}
            </Button>
          </div>
        </div>

        {/* Mode Pills */}
        {visible && (
          <div className="flex flex-wrap items-center justify-between gap-1.5">
            <div className="flex flex-wrap items-center gap-1">
              {OVERWATCH_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  disabled={busyMode}
                  onClick={() => void handleSelectMode(m.id)}
                  className={cn(
                    "rounded-md border px-2 py-0.5 font-mono text-[10px] font-medium transition-colors motion-reduce:transition-none",
                    currentMode === m.id
                      ? "border-eigenia-orange bg-eigenia-orange/20 text-white"
                      : "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:border-eigenia-sky/40 hover:text-white"
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => setShowCalibration((v) => !v)}
              className="inline-flex items-center gap-1 rounded border border-white/10 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px] text-eigenia-muted hover:border-eigenia-sky/40 hover:text-white"
            >
              <SlidersHorizontal className="h-2.5 w-2.5 text-eigenia-sky" />
              Calibrate ({activeCameraId})
              {showCalibration ? (
                <ChevronUp className="h-2.5 w-2.5" />
              ) : (
                <ChevronDown className="h-2.5 w-2.5" />
              )}
            </button>
          </div>
        )}
      </CardHeader>

      {visible && (
        <CardContent className={cn("space-y-2.5 pt-0", compact ? "p-3 pt-0" : "p-4 pt-0")}>
          {/* Single or Dual Live 1080p Annotated MJPEG Viewports */}
          {cameraView === "dual" ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {renderFeedBox(
                "usb_4k",
                usbSlot?.camera_name || "4K USB Webcam",
                usbStreamUrl,
                usbStreamError,
                setUsbStreamError,
                usbImgRef,
                usbSlot?.online
              )}
              {renderFeedBox(
                "macbook_cam",
                macSlot?.camera_name || "MacBook Pro Camera",
                macStreamUrl,
                macStreamError,
                setMacStreamError,
                macImgRef,
                macSlot?.online
              )}
            </div>
          ) : cameraView === "macbook_cam" ? (
            renderFeedBox(
              "macbook_cam",
              macSlot?.camera_name || "MacBook Pro Camera",
              macStreamUrl,
              macStreamError,
              setMacStreamError,
              macImgRef,
              macSlot?.online ?? status?.online
            )
          ) : (
            renderFeedBox(
              "usb_4k",
              usbSlot?.camera_name || status?.camera_name || "4K USB Webcam",
              usbStreamUrl,
              usbStreamError,
              setUsbStreamError,
              usbImgRef,
              usbSlot?.online ?? status?.online
            )
          )}

          {/* Triangulated (x, y) Coordinate Pills */}
          {triangulated.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {triangulated.slice(0, 6).map((t, idx) => (
                <span
                  key={`${t.label}-${idx}`}
                  className="inline-flex items-center gap-1 rounded border border-eigenia-orange/50 bg-eigenia-orange/15 px-2 py-0.5 font-mono text-[10px] tabular-nums text-white"
                >
                  <Crosshair className="h-2.5 w-2.5 text-eigenia-orange" />
                  <span className="font-semibold">{t.label}</span>
                  <span className="text-eigenia-sky">
                    ({t.x.toFixed(2)}, {t.y.toFixed(2)})m
                  </span>
                  {t.error_m != null && (
                    <span className="text-[9px] text-eigenia-muted">±{t.error_m.toFixed(2)}m</span>
                  )}
                </span>
              ))}
            </div>
          ) : detections.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {detections.slice(0, 6).map((d, idx) => (
                <Badge key={`${d.label}-${idx}`} variant="sky" className="font-mono text-[9px]">
                  {d.label} {Math.round(Number(d.confidence ?? 0) * 100)}%
                </Badge>
              ))}
            </div>
          ) : null}

          {/* Collapsible Pose & FOV Calibration Form */}
          {showCalibration && (
            <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
              <div className="grid grid-cols-3 gap-2">
                {(
                  [
                    { key: "x_m", label: "X (m)", step: "0.1" },
                    { key: "y_m", label: "Y (m)", step: "0.1" },
                    { key: "z_m", label: "Z Height (m)", step: "0.1" },
                    { key: "yaw_deg", label: "Yaw (°)", step: "1" },
                    { key: "pitch_deg", label: "Pitch (°)", step: "1" },
                    { key: "hfov_deg", label: "HFOV (°)", step: "1" },
                  ] as const
                ).map((field) => (
                  <label key={field.key} className="space-y-0.5">
                    <span className="block font-mono text-[9px] uppercase text-eigenia-muted">
                      {field.label}
                    </span>
                    <Input
                      type="number"
                      step={field.step}
                      value={calDraft[field.key]}
                      onChange={(e) => {
                        editingCalRef.current = true;
                        setCalDraft((prev) => ({
                          ...prev,
                          [field.key]: Number(e.target.value),
                        }));
                      }}
                      className="h-7 font-mono text-[11px]"
                    />
                  </label>
                ))}
              </div>
              <div className="flex items-center justify-between gap-2 pt-1">
                <span className="font-mono text-[9px] text-eigenia-muted">
                  Room origin (0,0) = PuppyPi LD19 frame
                </span>
                <Button
                  size="sm"
                  variant="default"
                  className="h-7 px-2.5 text-[10px]"
                  disabled={savingCal}
                  onClick={() => void handleSaveCalibration()}
                >
                  {savingCal ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Save className="h-3 w-3" />
                  )}
                  Save Pose
                </Button>
              </div>
            </div>
          )}

          {feedback && (
            <div className="rounded border border-eigenia-sky/30 bg-eigenia-sky/10 px-2.5 py-1 font-mono text-[10px] text-eigenia-sky">
              {feedback}
            </div>
          )}

          {/* 1-Click Host MacBook Dual-Camera Bridge Command */}
          <div className="flex items-center justify-between gap-2 rounded-md border border-white/10 bg-eigenia-obsidian px-2.5 py-1.5">
            <div className="flex min-w-0 items-center gap-1.5 font-mono text-[10px] text-eigenia-muted">
              <Terminal className="h-3 w-3 shrink-0 text-eigenia-orange" />
              <span className="truncate text-eigenia-ink">{BRIDGE_COMMAND}</span>
            </div>
            <button
              type="button"
              onClick={handleCopyCommand}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-white/15 bg-eigenia-shell px-2 py-0.5 font-mono text-[9px] text-white hover:border-eigenia-orange"
              title="Copy MacBook Dual-Camera Bridge command (4K USB + MacBook Pro Cam)"
            >
              {copiedCmd ? (
                <Check className="h-2.5 w-2.5 text-emerald-400" />
              ) : (
                <Copy className="h-2.5 w-2.5" />
              )}
              {copiedCmd ? "Copied" : "Copy CLI"}
            </button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
