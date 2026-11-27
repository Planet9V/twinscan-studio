"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Camera,
  CheckCircle2,
  Crosshair,
  Eye,
  EyeOff,
  Loader2,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Square,
  Trash2,
  Video,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  deleteRemoteOverwatchSource,
  discoverOverwatchCameras,
  upsertRemoteOverwatchSource,
  type DiscoveredFleetCamera,
  type OverwatchCameraSlot,
  type RemoteOverwatchSource,
} from "@/lib/overwatchApi";
import type { BrowserResolutionPreset } from "@/lib/useBrowserOverwatchBridge";

interface CameraManagerDrawerProps {
  open: boolean;
  onClose: () => void;
  activeCameras: Record<string, OverwatchCameraSlot>;
  hiddenIds: string[];
  onToggleHidden: (cameraId: string) => void;
  onOpenCalibrate: (cameraId: string) => void;
  onChanged: () => void;
  bridgeRunning: boolean;
  bridgePreset: BrowserResolutionPreset;
  bridgeAutoStart: boolean;
  onSetBridgePreset: (preset: BrowserResolutionPreset) => void;
  onSetBridgeAutoStart: (enabled: boolean) => void;
  onStartBridge: () => void;
  onStopBridge: () => void;
}

export function CameraManagerDrawer({
  open,
  onClose,
  activeCameras,
  hiddenIds,
  onToggleHidden,
  onOpenCalibrate,
  onChanged,
  bridgeRunning,
  bridgePreset,
  bridgeAutoStart,
  onSetBridgePreset,
  onSetBridgeAutoStart,
  onStartBridge,
  onStopBridge,
}: CameraManagerDrawerProps): React.JSX.Element | null {
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredFleetCamera[]>([]);
  const [remoteSources, setRemoteSources] = useState<RemoteOverwatchSource[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // Manual IP / MJPEG add form
  const [customId, setCustomId] = useState("pi4_cam");
  const [customName, setCustomName] = useState("Raspberry Pi 4 Camera");
  const [customUrl, setCustomUrl] = useState("http://192.168.1.142:8090/stream.mjpg");
  const [customFps, setCustomFps] = useState("15");

  const runDiscovery = useCallback(async () => {
    setDiscovering(true);
    setError(null);
    try {
      const res = await discoverOverwatchCameras();
      setDiscovered(res.discovered || []);
      setRemoteSources(res.remote_sources || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Camera discovery failed.");
    } finally {
      setDiscovering(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void runDiscovery();
    }
  }, [open, runDiscovery]);

  if (!open) return null;

  const handleAddDiscovered = async (cam: DiscoveredFleetCamera) => {
    setBusyId(cam.id);
    setError(null);
    setStatusMsg(null);
    try {
      await upsertRemoteOverwatchSource({
        camera_id: cam.suggested_camera_id,
        stream_url: cam.stream_url,
        camera_name: cam.camera_name,
        fps: cam.fps || 15,
        enabled: true,
      });
      setStatusMsg(`Added ${cam.camera_name} into Overwatch slot "${cam.suggested_camera_id}".`);
      await runDiscovery();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add camera.");
    } finally {
      setBusyId(null);
    }
  };

  const handleAddCustom = async () => {
    setBusyId("custom");
    setError(null);
    setStatusMsg(null);
    try {
      const res = await upsertRemoteOverwatchSource({
        camera_id: customId.trim().toLowerCase(),
        stream_url: customUrl.trim(),
        camera_name: customName.trim() || customId.trim(),
        fps: Math.max(1, Math.min(60, Number(customFps) || 15)),
        enabled: true,
      });
      setStatusMsg(`Registered remote camera "${res.source.camera_name}" (${res.source.camera_id}).`);
      await runDiscovery();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register custom camera.");
    } finally {
      setBusyId(null);
    }
  };

  const handleRemoveRemote = async (cameraId: string) => {
    setBusyId(`del_${cameraId}`);
    setError(null);
    try {
      await deleteRemoteOverwatchSource(cameraId);
      setStatusMsg(`Removed remote stream for "${cameraId}".`);
      await runDiscovery();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove remote camera.");
    } finally {
      setBusyId(null);
    }
  };

  const remoteIdSet = new Set(remoteSources.map((s) => s.camera_id));
  const activeList = Object.values(activeCameras);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/75 backdrop-blur-sm">
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-white/15 bg-slate-950 text-slate-100 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <Camera className="h-5 w-5 text-cyan-400" />
            <div>
              <h2 className="text-base font-semibold">Overwatch Camera Manager</h2>
              <p className="text-xs text-slate-400">
                Discover Raspberry Pi / robot cameras, toggle host webcams, or add any HTTP MJPEG stream.
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="cursor-pointer">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-950/50 px-3 py-2 text-xs text-red-200">
              {error}
            </div>
          )}
          {statusMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/50 px-3 py-2 text-xs text-emerald-200">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{statusMsg}</span>
            </div>
          )}

          {/* 1. Discovered Fleet & Pi Cameras */}
          <Card className="border-white/10 bg-slate-900/60">
            <CardHeader className="flex flex-row items-center justify-between pb-2.5">
              <div className="flex items-center gap-2">
                <Radio className="h-4 w-4 text-emerald-400" />
                <CardTitle className="text-sm">Discovered Fleet Cameras (Pi 5 / Pi 4 / PuppyPi)</CardTitle>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void runDiscovery()}
                disabled={discovering}
                className="h-7 gap-1.5 text-xs cursor-pointer"
              >
                {discovering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Scan Fleet
              </Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {discovered.length === 0 ? (
                <div className="rounded-lg border border-dashed border-white/10 p-3 text-xs text-slate-400">
                  No fleet camera services found yet. Click <strong>Scan Fleet</strong> or add a custom stream below.
                </div>
              ) : (
                discovered.map((cam) => (
                  <div
                    key={cam.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-slate-100">{cam.camera_name}</span>
                        <Badge variant={cam.online ? "sky" : "neutral"} className="text-[10px]">
                          {cam.online ? "ONLINE" : "STANDBY"}
                        </Badge>
                        <span className="font-mono text-[10px] text-slate-400">{cam.resolution}</span>
                      </div>
                      <div className="truncate font-mono text-[10px] text-slate-500">{cam.stream_url}</div>
                    </div>
                    {cam.already_added ? (
                      <Badge variant="sky" className="text-[10px]">
                        Active ({cam.active_camera_id})
                      </Badge>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => void handleAddDiscovered(cam)}
                        disabled={busyId === cam.id}
                        className="h-7 gap-1 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
                      >
                        {busyId === cam.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                        Add to Overwatch
                      </Button>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          {/* 2. Local Host / Browser Webcams */}
          <Card className="border-white/10 bg-slate-900/60">
            <CardHeader className="pb-2.5">
              <div className="flex items-center gap-2">
                <Video className="h-4 w-4 text-violet-400" />
                <CardTitle className="text-sm">Local Host / MacBook Browser Cameras</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Host camera resolution"
                  value={bridgePreset}
                  onChange={(e) => onSetBridgePreset(e.target.value as BrowserResolutionPreset)}
                  className="h-8 rounded-md border border-white/15 bg-slate-950 px-2 text-xs text-slate-200"
                >
                  <option value="720p">720p HD</option>
                  <option value="1080p">1080p Full HD</option>
                  <option value="qhd">2K QHD (1440p)</option>
                  <option value="4k">4K / 5MP Max</option>
                </select>
                <Button
                  size="sm"
                  variant={bridgeRunning ? "destructive" : "default"}
                  onClick={() => (bridgeRunning ? onStopBridge() : onStartBridge())}
                  className="h-8 gap-1.5 text-xs cursor-pointer"
                >
                  {bridgeRunning ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  {bridgeRunning ? "Stop Host Cams" : "Start Host Cams"}
                </Button>
              </div>
              <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={bridgeAutoStart}
                  onChange={(e) => onSetBridgeAutoStart(e.target.checked)}
                  className="h-3.5 w-3.5 accent-cyan-400"
                />
                Auto-start on load
              </label>
            </CardContent>
          </Card>

          {/* 3. Active Overwatch Slots (Visibility, Calibration & Remove) */}
          <Card className="border-white/10 bg-slate-900/60">
            <CardHeader className="pb-2.5">
              <CardTitle className="text-sm">Active Overwatch Cameras ({activeList.length})</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {activeList.map((cam) => {
                const isHidden = hiddenIds.includes(cam.camera_id);
                const isCalibrated = Boolean(cam.calibration?.calibrated);
                const isRemote = remoteIdSet.has(cam.camera_id);
                return (
                  <div
                    key={cam.camera_id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-slate-950/70 px-3 py-2"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-slate-100">{cam.camera_name}</span>
                        <span className="font-mono text-[10px] text-slate-400">({cam.camera_id})</span>
                        <Badge variant={cam.online ? "sky" : "neutral"} className="text-[10px]">
                          {cam.online ? `${cam.width}×${cam.height}` : "OFFLINE"}
                        </Badge>
                        <Badge
                          variant="neutral"
                          className={
                            isCalibrated
                              ? "border-emerald-500/40 text-[10px] text-emerald-300"
                              : "border-amber-500/40 text-[10px] text-amber-300"
                          }
                        >
                          {isCalibrated ? `Calibrated (${cam.calibration?.calibration_method || "ok"})` : "Needs Cal"}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onToggleHidden(cam.camera_id)}
                        className="h-7 gap-1 text-[11px] cursor-pointer"
                      >
                        {isHidden ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                        {isHidden ? "Show" : "Hide"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          onClose();
                          onOpenCalibrate(cam.camera_id);
                        }}
                        className="h-7 gap-1 border-cyan-500/30 text-[11px] text-cyan-300 cursor-pointer"
                      >
                        <Crosshair className="h-3.5 w-3.5" />
                        Calibrate
                      </Button>
                      {isRemote && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busyId === `del_${cam.camera_id}`}
                          onClick={() => void handleRemoveRemote(cam.camera_id)}
                          className="h-7 px-2 text-red-400 hover:bg-red-950/50 hover:text-red-300 cursor-pointer"
                          title="Remove remote camera source"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* 4. Add Custom IP / MJPEG / Pi Camera */}
          <Card className="border-white/10 bg-slate-900/60">
            <CardHeader className="pb-2.5">
              <CardTitle className="text-sm">Add Custom Pi / IP / MJPEG Camera</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Camera Slot ID</label>
                  <Input
                    value={customId}
                    onChange={(e) => setCustomId(e.target.value)}
                    placeholder="pi4_cam"
                    className="h-8 bg-slate-950 font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Display Name</label>
                  <Input
                    value={customName}
                    onChange={(e) => setCustomName(e.target.value)}
                    placeholder="Hallway Pi 4 Cam"
                    className="h-8 bg-slate-950 text-xs"
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                <div className="sm:col-span-3">
                  <label className="mb-1 block text-[11px] text-slate-400">HTTP MJPEG or Snapshot URL</label>
                  <Input
                    value={customUrl}
                    onChange={(e) => setCustomUrl(e.target.value)}
                    placeholder="http://192.168.1.142:8090/stream.mjpg"
                    className="h-8 bg-slate-950 font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">FPS</label>
                  <Input
                    value={customFps}
                    onChange={(e) => setCustomFps(e.target.value)}
                    className="h-8 bg-slate-950 font-mono text-xs"
                  />
                </div>
              </div>
              <Button
                size="sm"
                onClick={() => void handleAddCustom()}
                disabled={busyId === "custom" || !customId.trim() || !customUrl.trim()}
                className="gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
              >
                {busyId === "custom" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                Add & Connect Camera
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
