"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Box,
  Camera,
  ChevronDown,
  ChevronRight,
  Compass,
  Cpu,
  Download,
  Eye,
  EyeOff,
  Grid3x3,
  Layers,
  Loader2,
  RotateCw,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { getCombinedRoomGlbUrl, resolveBackendAssetUrl } from "@/lib/api";
import type {
  SceneEnhanceOptions,
  ScenePanelRecord,
  SceneQualityPreset,
  SceneRenderMode,
  SceneResolution,
} from "@/lib/types";

export interface SceneReconstructionBarProps {
  spaceId: string | null;
  activeRobotId: string | null;
  lidarLive: boolean;
  panels: ScenePanelRecord[];
  renderMode: SceneRenderMode;
  hiddenPanelIds: string[];
  capturingWall: boolean;
  capturing360: boolean;
  enhancingPanelId: string | null;
  resolution: SceneResolution;
  depthReliefScale: number;
  fallbackDistanceM: number;
  qualityPreset: SceneQualityPreset;
  enhanceOptions: SceneEnhanceOptions;
  rotationOffsetDeg?: number;
  cardinalM?: {
    front: number | null;
    right: number | null;
    back: number | null;
    left: number | null;
  } | null;
  updatingOrientation?: boolean;
  onRenderModeChange: (mode: SceneRenderMode) => void;
  onResolutionChange: (res: SceneResolution) => void;
  onDepthReliefScaleChange: (scale: number) => void;
  onFallbackDistanceChange: (distM: number) => void;
  onQualityPresetChange: (preset: SceneQualityPreset) => void;
  onEnhanceOptionsChange: (patch: Partial<SceneEnhanceOptions>) => void;
  onRotationOffsetChange?: (deg: number) => void;
  onCaptureWall: () => void;
  onCapture360: () => void;
  onEnhancePanel: (panelId: string) => void;
  onTogglePanelVisibility: (panelId: string) => void;
  onDeletePanel: (panelId: string) => void;
  onClearPanels: () => void;
}

const RENDER_MODES: {
  id: SceneRenderMode;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: "solid", label: "Solid (Shaded)", Icon: Box },
  { id: "translucent", label: "Translucent", Icon: Layers },
  { id: "wireframe", label: "Wireframe", Icon: Grid3x3 },
];

const QUALITY_PRESETS: { id: SceneQualityPreset; label: string }[] = [
  { id: "fast", label: "Fast" },
  { id: "balanced", label: "Balanced" },
  { id: "studio_ultra", label: "Studio Ultra" },
];

const RESOLUTIONS: { id: SceneResolution; label: string }[] = [
  { id: "low", label: "Low (48×36)" },
  { id: "medium", label: "Med (80×60)" },
  { id: "high", label: "High (120×90)" },
];

function formatDepthSource(source: ScenePanelRecord["depth_source"]): string {
  switch (source) {
    case "lidar_depth_anything":
      return "LD19 + Depth Anything V2";
    case "depth_anything":
      return "Depth Anything V2";
    case "lidar_only":
      return "LD19 LiDAR";
    default:
      return "Geometric Relief";
  }
}

export function SceneReconstructionBar({
  spaceId,
  activeRobotId,
  lidarLive,
  panels,
  renderMode,
  hiddenPanelIds,
  capturingWall,
  capturing360,
  enhancingPanelId,
  resolution,
  depthReliefScale,
  fallbackDistanceM,
  qualityPreset,
  enhanceOptions,
  rotationOffsetDeg = 90,
  cardinalM = null,
  updatingOrientation = false,
  onRenderModeChange,
  onResolutionChange,
  onDepthReliefScaleChange,
  onFallbackDistanceChange,
  onQualityPresetChange,
  onEnhanceOptionsChange,
  onRotationOffsetChange,
  onCaptureWall,
  onCapture360,
  onEnhancePanel,
  onTogglePanelVisibility,
  onDeletePanel,
  onClearPanels,
}: SceneReconstructionBarProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirm360Open, setConfirm360Open] = useState(false);

  const normalizedRotDeg = ((Math.round(rotationOffsetDeg) % 360) + 360) % 360;
  const formatCardinal = (val?: number | null) =>
    typeof val === "number" && Number.isFinite(val) ? `${val.toFixed(2)}m` : "--";

  const busy = capturingWall || capturing360;
  const hiddenSet = new Set(hiddenPanelIds);
  const latestPanel = panels.length > 0 ? panels[0] : null;
  const isMetricLocked = latestPanel ? latestPanel.lidar_calibrated : lidarLive;
  const showLidarInspectLink = !isMetricLocked;

  const burstEnabled = (enhanceOptions.burst_frames ?? 3) > 1;
  const claheEnabled = Boolean(enhanceOptions.clahe_sharpen);
  const upscaleEnabled = Boolean(enhanceOptions.upscale_2x);
  const flipGuidedEnabled = Boolean(enhanceOptions.flip_tta || enhanceOptions.guided_depth);
  const normalMapEnabled = Boolean(enhanceOptions.normal_map);
  const taubinEnabled = Boolean(enhanceOptions.taubin_smooth);

  return (
    <Card className="border-eigenia-orange/35 bg-eigenia-shell">
      <CardContent className="flex flex-col gap-2.5 px-4 py-3">
        {/* Main Compact Industrial Toolbar Row */}
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          {/* Left: Identity, Panel Count, Calibration & Live Sensor Link */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default" className="font-mono text-[10px]">
              3D REAL-ROOM FUSION
            </Badge>
            <Badge variant="neutral" className="font-mono text-[10px] tabular-nums">
              {panels.length} {panels.length === 1 ? "PANEL" : "PANELS"}
            </Badge>
            {isMetricLocked ? (
              <Badge
                variant="sky"
                className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
              >
                LD19 METRIC LOCKED
              </Badge>
            ) : (
              <Badge variant="amber" className="font-mono text-[10px]">
                CAMERA + DEPTH
              </Badge>
            )}
            {showLidarInspectLink && (
              <Link
                href="/catalog?focus=ld19_lidar_module"
                className="inline-flex items-center gap-1 rounded-full border border-eigenia-amber/50 bg-eigenia-amber/15 px-2.5 py-0.5 font-mono text-[10px] font-medium text-eigenia-amber transition hover:border-eigenia-orange hover:bg-eigenia-orange/20 hover:text-white"
              >
                <Cpu className="h-3 w-3" />
                LD19 Offline · Inspect on 3D Pi 5
              </Link>
            )}
            <Badge variant="neutral" className="font-mono text-[10px] tabular-nums">
              <Compass className="h-3 w-3 text-eigenia-sky" />
              LD19 {normalizedRotDeg}°
            </Badge>
          </div>

          {/* Center: Quality Preset + Primary Capture Actions */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Quality Preset Segmented Switcher */}
            <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
              {QUALITY_PRESETS.map((preset) => {
                const active = qualityPreset === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    disabled={busy}
                    onClick={() => onQualityPresetChange(preset.id)}
                    className={`rounded px-2 py-1 font-mono text-[10px] font-medium transition ${
                      active
                        ? "bg-eigenia-sky text-eigenia-obsidian shadow-sm font-semibold"
                        : "text-eigenia-muted hover:text-white"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>

            <Button
              size="sm"
              variant="default"
              disabled={!spaceId || busy}
              onClick={onCaptureWall}
              className="font-semibold"
            >
              {capturingWall ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Camera className="h-3.5 w-3.5" />
              )}
              {capturingWall
                ? "Fusing Camera + LiDAR + 3D Depth..."
                : "Capture Front Wall (Zero Move)"}
            </Button>

            <Button
              size="sm"
              variant="secondary"
              disabled={!spaceId || !activeRobotId || busy}
              onClick={() => setConfirm360Open((v) => !v)}
              title={
                activeRobotId
                  ? "Rotate PuppyPi 360° in 8 stops to capture full room"
                  : "Select an online PuppyPi robot for 360° turn capture"
              }
            >
              {capturing360 ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCw className="h-3.5 w-3.5 text-eigenia-orange" />
              )}
              {capturing360 ? "Scanning 360° (8 Views)..." : "360° Turn Capture (8 Views)"}
            </Button>

            {spaceId && panels.length > 0 && (
              <Button
                size="sm"
                variant="sky"
                asChild
                title="Export all captured 3D room panels into a single binary glTF 2.0 .glb file"
              >
                <a href={getCombinedRoomGlbUrl(spaceId)} download>
                  <Download className="h-3.5 w-3.5" />
                  Download Full Room .glb
                </a>
              </Button>
            )}
          </div>

          {/* Right: Render Mode Segmented Switcher + Tuning Drawer Toggle */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
              {RENDER_MODES.map(({ id, label, Icon }) => {
                const active = renderMode === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onRenderModeChange(id)}
                    className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-mono text-[10px] font-medium transition ${
                      active
                        ? "bg-eigenia-orange text-white shadow-sm"
                        : "text-eigenia-muted hover:text-white"
                    }`}
                  >
                    <Icon className="h-3 w-3" />
                    {label}
                  </button>
                );
              })}
            </div>

            <Button
              size="sm"
              variant="outline"
              onClick={() => setDrawerOpen((v) => !v)}
              className="font-mono text-[10px]"
            >
              <SlidersHorizontal className="h-3 w-3 text-eigenia-sky" />
              Tuning &amp; Panels ({panels.length})
              {drawerOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>

        {/* Inline Safety Confirmation Strip for 360° Turn Capture */}
        {confirm360Open && !capturing360 && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-eigenia-amber/50 bg-eigenia-amber/15 px-3 py-2">
            <div className="flex items-center gap-2 text-xs text-white">
              <AlertTriangle className="h-4 w-4 shrink-0 text-eigenia-amber" />
              <span>
                Robot will rotate <span className="font-mono font-semibold">360°</span> in place (8
                × 45° stops). Clear <span className="font-mono font-semibold">0.5m</span> around
                PuppyPi?
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="default"
                disabled={!spaceId || !activeRobotId || busy}
                onClick={() => {
                  setConfirm360Open(false);
                  onCapture360();
                }}
              >
                <RotateCw className="h-3.5 w-3.5" />
                Start 360° Scan
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm360Open(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Expandable Tuning & Captured Panels Drawer */}
        {drawerOpen && (
          <div className="space-y-3 border-t border-white/10 pt-3">
            {/* Compact Composite Enhancement Pass Toggles */}
            <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[10px] uppercase tracking-wider text-eigenia-sky">
                  5-Pass Composite Enhancement Pipeline ({qualityPreset.replace("_", " ")})
                </span>
                <span className="font-mono text-[10px] text-eigenia-muted">
                  Synced to preset · override any pass individually
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">
                    Burst Denoise
                    <span className="ml-1 text-eigenia-muted">
                      ({enhanceOptions.burst_frames ?? 1}f)
                    </span>
                  </span>
                  <Switch
                    checked={burstEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({
                        burst_frames: checked
                          ? qualityPreset === "studio_ultra"
                            ? 5
                            : 3
                          : 1,
                      })
                    }
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">CLAHE + Sharpen</span>
                  <Switch
                    checked={claheEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({ clahe_sharpen: checked })
                    }
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">2× Texture Upscale</span>
                  <Switch
                    checked={upscaleEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({ upscale_2x: checked })
                    }
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">Flip-TTA + Guided Depth</span>
                  <Switch
                    checked={flipGuidedEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({ flip_tta: checked, guided_depth: checked })
                    }
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">PBR Normal Map</span>
                  <Switch
                    checked={normalMapEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({ normal_map: checked })
                    }
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="font-mono text-[10px] text-white">Taubin Polish</span>
                  <Switch
                    checked={taubinEnabled}
                    onCheckedChange={(checked) =>
                      onEnhanceOptionsChange({ taubin_smooth: checked })
                    }
                  />
                </label>
              </div>
            </div>

            {/* LD19 Forward Orientation Calibrator Strip */}
            <div className="space-y-2 rounded-md border border-eigenia-orange/35 bg-eigenia-obsidian p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-eigenia-orange">
                    <Compass className="h-3.5 w-3.5" />
                    LD19 Forward Orientation Calibrator
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px] tabular-nums">
                    <Badge variant="default" className="px-1.5 py-0 text-[9px]">
                      FRONT: {formatCardinal(cardinalM?.front)}
                    </Badge>
                    <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                      RIGHT: {formatCardinal(cardinalM?.right)}
                    </Badge>
                    <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                      BACK: {formatCardinal(cardinalM?.back)}
                    </Badge>
                    <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                      LEFT: {formatCardinal(cardinalM?.left)}
                    </Badge>
                  </div>
                </div>

                {onRotationOffsetChange && (
                  <div className="flex flex-wrap items-center gap-1">
                    {[
                      { deg: 0, label: "0°" },
                      { deg: 90, label: "90° (Arrow Fwd)" },
                      { deg: 180, label: "180°" },
                      { deg: 270, label: "270°" },
                    ].map((opt) => (
                      <Button
                        key={opt.deg}
                        size="sm"
                        variant={normalizedRotDeg === opt.deg ? "default" : "secondary"}
                        disabled={updatingOrientation}
                        className="h-6 px-2 font-mono text-[10px]"
                        onClick={() => onRotationOffsetChange(opt.deg)}
                      >
                        {opt.label}
                      </Button>
                    ))}
                    <Button
                      size="sm"
                      variant="sky"
                      disabled={updatingOrientation}
                      className="h-6 px-2 font-mono text-[10px]"
                      onClick={() => onRotationOffsetChange((normalizedRotDeg + 90) % 360)}
                    >
                      <RotateCw className="h-3 w-3" />
                      Rotate +90°
                    </Button>
                  </div>
                )}
              </div>
              <p className="font-mono text-[10px] text-eigenia-muted">
                Mount LD19 with top arrow toward PuppyPi&apos;s nose (90° Std). Wave hand in front
                of camera to verify FRONT jumps inward.
              </p>
            </div>

            {/* Mesh Resolution, Depth Relief & Fallback Distance Grid */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {/* Resolution */}
              <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  Mesh Resolution
                </div>
                <div className="grid grid-cols-3 gap-1">
                  {RESOLUTIONS.map((r) => (
                    <Button
                      key={r.id}
                      size="sm"
                      variant={resolution === r.id ? "sky" : "secondary"}
                      className="h-7 px-1.5 font-mono text-[10px]"
                      onClick={() => onResolutionChange(r.id)}
                    >
                      {r.label}
                    </Button>
                  ))}
                </div>
              </div>

              {/* Depth Relief Scale */}
              <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex items-center justify-between font-mono text-[10px]">
                  <span className="uppercase tracking-wider text-eigenia-muted">
                    Depth Relief Scale
                  </span>
                  <span className="tabular-nums font-semibold text-eigenia-orange">
                    {depthReliefScale.toFixed(1)}×
                  </span>
                </div>
                <Slider
                  min={0.3}
                  max={2.0}
                  step={0.1}
                  value={[depthReliefScale]}
                  onValueChange={([v]) => onDepthReliefScaleChange(Number(v.toFixed(1)))}
                />
              </div>

              {/* Reference Wall Distance */}
              <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="flex items-center justify-between font-mono text-[10px]">
                  <span className="uppercase tracking-wider text-eigenia-muted">
                    Ref Wall Distance{" "}
                    <span className="normal-case text-eigenia-ink/70">
                      (Fallback if LD19 offline)
                    </span>
                  </span>
                  <span className="tabular-nums font-semibold text-eigenia-sky">
                    {fallbackDistanceM.toFixed(1)} m
                  </span>
                </div>
                <Slider
                  min={0.6}
                  max={5.0}
                  step={0.1}
                  value={[fallbackDistanceM]}
                  onValueChange={([v]) => onFallbackDistanceChange(Number(v.toFixed(1)))}
                />
              </div>
            </div>

            {/* Captured Panels List */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  Captured 3D Room Panels ({panels.length})
                </span>
                {panels.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {spaceId && (
                      <Button
                        size="sm"
                        variant="sky"
                        className="h-6 px-2 font-mono text-[10px]"
                        asChild
                      >
                        <a href={getCombinedRoomGlbUrl(spaceId)} download>
                          <Download className="h-3 w-3" />
                          Download Full Room .glb
                        </a>
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-6 px-2 text-[10px]"
                      disabled={busy || enhancingPanelId !== null}
                      onClick={onClearPanels}
                    >
                      <Trash2 className="h-3 w-3" />
                      Clear All
                    </Button>
                  </div>
                )}
              </div>

              {panels.length === 0 ? (
                <div className="rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 px-3 py-4 text-center font-mono text-[11px] text-eigenia-muted">
                  No 3D room panels captured yet. Click{" "}
                  <span className="font-semibold text-white">Capture Front Wall (Zero Move)</span>{" "}
                  to fuse PuppyPi&apos;s live camera + monocular 3D depth (+ LD19 LiDAR when
                  online) into Three.js &amp; Babylon.js 9.
                </div>
              ) : (
                <div className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                  {panels.map((panel) => {
                    const isHidden = hiddenSet.has(panel.id);
                    const isEnhancing = enhancingPanelId === panel.id;
                    const thumbUrl = resolveBackendAssetUrl(panel.texture_url);
                    const glbHref = resolveBackendAssetUrl(panel.glb_url);
                    const qm = panel.quality_metrics;
                    const hasNormal = Boolean(qm?.has_normal_map || panel.normal_map_url);
                    return (
                      <div
                        key={panel.id}
                        className={`flex flex-wrap items-center justify-between gap-2 rounded-md border px-2.5 py-2 ${
                          isHidden
                            ? "border-white/5 bg-eigenia-obsidian/40 opacity-60"
                            : "border-white/10 bg-eigenia-obsidian"
                        }`}
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          {thumbUrl ? (
                            <img
                              src={thumbUrl}
                              alt={panel.label}
                              className="h-11 w-16 shrink-0 rounded border border-white/15 object-cover"
                            />
                          ) : (
                            <div className="flex h-11 w-16 shrink-0 items-center justify-center rounded border border-white/15 bg-eigenia-shell">
                              <Camera className="h-4 w-4 text-eigenia-muted" />
                            </div>
                          )}
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="truncate text-xs font-semibold text-white">
                                {panel.label}
                              </span>
                              <Badge
                                variant={panel.lidar_calibrated ? "sky" : "amber"}
                                className={
                                  panel.lidar_calibrated
                                    ? "border-emerald-500/40 bg-emerald-500/15 font-mono text-[9px] text-emerald-400"
                                    : "font-mono text-[9px]"
                                }
                              >
                                {formatDepthSource(panel.depth_source)}
                              </Badge>

                              {/* Live Quality Metrics Chips */}
                              {qm && Number.isFinite(qm.sharpness_gain_pct) && (
                                <Badge
                                  variant="sky"
                                  className="border-emerald-500/35 bg-emerald-500/10 font-mono text-[9px] tabular-nums text-emerald-300"
                                >
                                  {qm.sharpness_gain_pct >= 0 ? "+" : ""}
                                  {Math.round(qm.sharpness_gain_pct)}% Sharp
                                </Badge>
                              )}
                              {qm && qm.texture_width > 0 && qm.texture_height > 0 && (
                                <Badge variant="neutral" className="font-mono text-[9px] tabular-nums">
                                  {qm.texture_width}×{qm.texture_height}
                                </Badge>
                              )}
                              {hasNormal && (
                                <Badge variant="default" className="font-mono text-[9px]">
                                  Normal Map
                                </Badge>
                              )}
                              {qm && typeof qm.lidar_residual_rmse_m === "number" && (
                                <Badge variant="sky" className="font-mono text-[9px] tabular-nums">
                                  LiDAR RMSE {qm.lidar_residual_rmse_m.toFixed(3)}m
                                </Badge>
                              )}
                            </div>
                            <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-[10px] tabular-nums text-eigenia-muted">
                              <span>Avg: {Number(panel.mean_distance_m ?? 0).toFixed(2)} m</span>
                              <span>·</span>
                              <span>
                                {Number(panel.triangle_count ?? 0).toLocaleString()} tris
                              </span>
                              <span>·</span>
                              <span>Yaw {Math.round(Number(panel.pose?.yaw_deg ?? 0))}°</span>
                              {qm?.processing_ms ? (
                                <>
                                  <span>·</span>
                                  <span>{Math.round(qm.processing_ms)} ms</span>
                                </>
                              ) : null}
                            </div>
                          </div>
                        </div>

                        <div className="flex shrink-0 items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="sky"
                            className="h-7 px-2 font-mono text-[10px]"
                            disabled={busy || enhancingPanelId !== null}
                            onClick={() => onEnhancePanel(panel.id)}
                            title="Run post-capture CLAHE/Upscale, Flip-TTA Guided Depth, PBR Normal Map & Taubin polish"
                          >
                            {isEnhancing ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Sparkles className="h-3 w-3" />
                            )}
                            {isEnhancing ? "Enhancing..." : "Enhance"}
                          </Button>

                          <Button
                            size="sm"
                            variant={isHidden ? "secondary" : "ghost"}
                            className="h-7 px-2 font-mono text-[10px]"
                            onClick={() => onTogglePanelVisibility(panel.id)}
                            title={isHidden ? "Show 3D Panel" : "Hide 3D Panel"}
                          >
                            {isHidden ? (
                              <>
                                <EyeOff className="h-3.5 w-3.5 text-eigenia-muted" />
                                Hidden
                              </>
                            ) : (
                              <>
                                <Eye className="h-3.5 w-3.5 text-eigenia-sky" />
                                Visible
                              </>
                            )}
                          </Button>

                          {glbHref && (
                            <Button
                              size="sm"
                              variant="secondary"
                              className="h-7 px-2 font-mono text-[10px]"
                              asChild
                            >
                              <a href={glbHref} download={`${panel.label || panel.id}.glb`}>
                                <Download className="h-3 w-3 text-eigenia-orange" />
                                .glb
                              </a>
                            </Button>
                          )}

                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-7 w-7"
                            title="Delete Panel"
                            disabled={isEnhancing}
                            onClick={() => onDeletePanel(panel.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-eigenia-fault" />
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
