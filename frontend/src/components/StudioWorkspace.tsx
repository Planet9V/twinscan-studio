"use client";

import React, { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  AlertTriangle,
  Archive,
  Box,
  Camera,
  Cpu,
  Download,
  FolderOpen,
  Gauge,
  Grid3x3,
  Layers,
  Loader2,
  Radar,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { FocusQueuePanel } from "@/components/focus/FocusQueuePanel";
import { Lidar2DCanvas } from "@/components/lidar/Lidar2DCanvas";
import { RoomSceneManager } from "@/components/twin3d/RoomSceneManager";
import { SceneReconstructionBar } from "@/components/twin3d/SceneReconstructionBar";
import { VisionNameplatePanel } from "@/components/vision/VisionNameplatePanel";
import { useStudio } from "@/context/StudioContext";
import {
  archiveTwinSnapshot,
  capture360Panels,
  captureBaseline,
  captureWallPanel,
  clearScenePanels,
  deleteEquipmentAsset,
  deleteScenePanel,
  enhanceScenePanel,
  extractAndSaveWalls,
  getExportUrl,
  listScenePanels,
  updateLidarFilters,
  updateLidarMode,
  updateLidarSettings,
} from "@/lib/api";
import type {
  FocusTarget,
  ObjectCluster,
  SceneEnhanceOptions,
  ScenePanelRecord,
  SceneQualityPreset,
  SceneRenderMode,
  SceneResolution,
} from "@/lib/types";

const DigitalTwin3D = dynamic(() => import("@/components/twin3d/DigitalTwin3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[640px] items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian font-mono text-xs text-eigenia-muted">
      Initializing Three.js 3D Spatial Viewport...
    </div>
  ),
});

const BabylonTwinCanvas = dynamic(() => import("@/components/twin3d/BabylonTwinCanvas"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[640px] items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian font-mono text-xs text-eigenia-muted">
      Initializing Babylon.js Direct PBR Engine...
    </div>
  ),
});

const PRESET_PASS_DEFAULTS: Record<SceneQualityPreset, SceneEnhanceOptions> = {
  fast: {
    quality_preset: "fast",
    burst_frames: 1,
    clahe_sharpen: false,
    upscale_2x: false,
    flip_tta: false,
    guided_depth: false,
    normal_map: false,
    taubin_smooth: false,
  },
  balanced: {
    quality_preset: "balanced",
    burst_frames: 3,
    clahe_sharpen: true,
    upscale_2x: false,
    flip_tta: true,
    guided_depth: true,
    normal_map: true,
    taubin_smooth: true,
  },
  studio_ultra: {
    quality_preset: "studio_ultra",
    burst_frames: 5,
    clahe_sharpen: true,
    upscale_2x: true,
    flip_tta: true,
    guided_depth: true,
    normal_map: true,
    taubin_smooth: true,
  },
};

type TwinDrawerId = "rooms" | "fusion" | "assets" | null;

export function StudioWorkspace() {
  const {
    spaces,
    activeSpaceId,
    setActiveSpaceId,
    space,
    equipment,
    focusQueue,
    darkZones,
    refreshSpaceData,
    refreshSpaces,
    createNewSpace,
    renameSpace,
    cloneCurrentSpace,
    deleteSpaceById,
    activeRobotId,
    frame,
    visionModels,
    defaultModel,
    openrouterConfigured,
    selectedEquipmentId,
    setSelectedEquipmentId,
    focusTarget,
    setFocusTarget,
    enrichingId,
    handleEnrichAsset,
  } = useStudio();

  const [pendingPin, setPendingPin] = useState<{
    x: number;
    y: number;
    width_m?: number;
    depth_m?: number;
  } | null>(null);

  // Slide-Over Drawer state
  const [activeDrawer, setActiveDrawer] = useState<TwinDrawerId>(null);

  // LiDAR filter controls
  const [maxRange, setMaxRange] = useState(10.0);
  const [minIntensity, setMinIntensity] = useState(15);
  const [outlierFilter, setOutlierFilter] = useState(false);

  const [archiving, setArchiving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [updatingLidarSettings, setUpdatingLidarSettings] = useState(false);
  const [updatingOrientation, setUpdatingOrientation] = useState(false);

  // 3D Real-Room Fusion state (Stages 1 & 2 + 5-Pass Composite Enhancement)
  const [viewportTab, setViewportTab] = useState<string>("lidar2d");
  const [scenePanels, setScenePanels] = useState<ScenePanelRecord[]>([]);
  const [sceneRenderMode, setSceneRenderMode] = useState<SceneRenderMode>("solid");
  const [hiddenPanelIds, setHiddenPanelIds] = useState<string[]>([]);
  const [capturingWall, setCapturingWall] = useState(false);
  const [capturing360, setCapturing360] = useState(false);
  const [enhancingPanelId, setEnhancingPanelId] = useState<string | null>(null);
  const [sceneResolution, setSceneResolution] = useState<SceneResolution>("medium");
  const [depthReliefScale, setDepthReliefScale] = useState<number>(1.0);
  const [fallbackDistanceM, setFallbackDistanceM] = useState<number>(1.8);
  const [qualityPreset, setQualityPreset] = useState<SceneQualityPreset>("balanced");
  const [enhanceOptions, setEnhanceOptions] = useState<SceneEnhanceOptions>(
    PRESET_PASS_DEFAULTS.balanced
  );

  const handleQualityPresetChange = (preset: SceneQualityPreset) => {
    setQualityPreset(preset);
    setEnhanceOptions({ ...PRESET_PASS_DEFAULTS[preset] });
  };

  const handleEnhanceOptionsChange = (patch: Partial<SceneEnhanceOptions>) => {
    setEnhanceOptions((prev) => ({ ...prev, ...patch }));
  };

  const loadSpaceScenePanels = useCallback(async (spaceId: string) => {
    try {
      const resp = await listScenePanels(spaceId);
      setScenePanels(Array.isArray(resp.panels) ? resp.panels : []);
    } catch (err) {
      console.error("[StudioWorkspace] Failed to load 3D scene panels:", err);
    }
  }, []);

  useEffect(() => {
    if (!space?.id) {
      setScenePanels([]);
      setHiddenPanelIds([]);
      return;
    }
    setHiddenPanelIds([]);
    void loadSpaceScenePanels(space.id);
  }, [space?.id, loadSpaceScenePanels]);

  const handleCaptureWall = async () => {
    if (!space?.id || capturingWall || capturing360) return;
    setCapturingWall(true);
    setStatusMessage(null);
    try {
      const resp = await captureWallPanel(space.id, {
        robot_id: activeRobotId,
        resolution: sceneResolution,
        depth_relief_scale: depthReliefScale,
        fallback_distance_m: fallbackDistanceM,
        ...enhanceOptions,
        quality_preset: qualityPreset,
      });
      if (resp.panel) {
        setScenePanels((prev) => [resp.panel, ...prev.filter((p) => p.id !== resp.panel.id)]);
      }
      void refreshSpaces();
      setViewportTab((prev) => (prev === "babylon" ? "babylon" : "twin3d"));
      const qm = resp.panel?.quality_metrics;
      const qualityNote = qm
        ? ` · ${qm.sharpness_gain_pct >= 0 ? "+" : ""}${Math.round(qm.sharpness_gain_pct)}% sharp · ${qm.texture_width}×${qm.texture_height}`
        : "";
      setStatusMessage(
        resp.note ||
          `Captured 3D wall "${resp.panel.label}" (${resp.panel.triangle_count.toLocaleString()} tris · ${
            resp.panel.lidar_calibrated ? "LD19 Metric Locked" : "Camera + Depth Relief"
          }${qualityNote}).`
      );
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to capture 3D front wall");
    } finally {
      setCapturingWall(false);
    }
  };

  const handleCapture360 = async () => {
    if (!space?.id || !activeRobotId || capturingWall || capturing360) return;
    setCapturing360(true);
    setStatusMessage(null);
    try {
      const resp = await capture360Panels(space.id, {
        robot_id: activeRobotId,
        steps: 8,
        resolution: sceneResolution === "high" ? "medium" : sceneResolution,
        depth_relief_scale: depthReliefScale,
        fallback_distance_m: fallbackDistanceM,
        ...enhanceOptions,
        quality_preset: qualityPreset,
      });
      if (Array.isArray(resp.panels) && resp.panels.length > 0) {
        const newIds = new Set(resp.panels.map((p) => p.id));
        setScenePanels((prev) => [...resp.panels, ...prev.filter((p) => !newIds.has(p.id))]);
      }
      void refreshSpaces();
      setViewportTab((prev) => (prev === "babylon" ? "babylon" : "twin3d"));
      setStatusMessage(
        resp.note ||
          `360° scan ${resp.aborted ? "stopped early" : "complete"}: captured ${resp.completed_steps}/${resp.total_steps} 3D room panels.`
      );
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to run 360° room capture");
    } finally {
      setCapturing360(false);
    }
  };

  const handleEnhanceScenePanel = async (panelId: string) => {
    if (!space?.id || enhancingPanelId) return;
    setEnhancingPanelId(panelId);
    setStatusMessage(null);
    try {
      const resp = await enhanceScenePanel(space.id, panelId, {
        ...enhanceOptions,
        quality_preset: qualityPreset,
        resolution: sceneResolution,
        depth_relief_scale: depthReliefScale,
        fallback_distance_m: fallbackDistanceM,
      });
      if (resp.panel) {
        setScenePanels((prev) => prev.map((p) => (p.id === resp.panel.id ? resp.panel : p)));
      }
      const qm = resp.panel?.quality_metrics;
      setStatusMessage(
        resp.note ||
          `Enhanced "${resp.panel.label}" (${
            qm
              ? `${qm.sharpness_gain_pct >= 0 ? "+" : ""}${Math.round(qm.sharpness_gain_pct)}% sharp · ${qm.texture_width}×${qm.texture_height}${qm.has_normal_map ? " · PBR Normal Map" : ""}`
              : "rebuilt"
          }).`
      );
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to enhance 3D panel");
    } finally {
      setEnhancingPanelId(null);
    }
  };

  const handleTogglePanelVisibility = (panelId: string) => {
    setHiddenPanelIds((prev) =>
      prev.includes(panelId) ? prev.filter((id) => id !== panelId) : [...prev, panelId]
    );
  };

  const handleDeleteScenePanel = async (panelId: string) => {
    if (!space?.id) return;
    try {
      await deleteScenePanel(space.id, panelId);
      setScenePanels((prev) => prev.filter((p) => p.id !== panelId));
      setHiddenPanelIds((prev) => prev.filter((id) => id !== panelId));
      void refreshSpaces();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to delete 3D panel");
    }
  };

  const handleClearScenePanels = async () => {
    if (!space?.id) return;
    try {
      const resp = await clearScenePanels(space.id);
      setScenePanels([]);
      setHiddenPanelIds([]);
      void refreshSpaces();
      setStatusMessage(`Cleared ${resp.deleted_count} captured 3D room panel(s).`);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to clear 3D panels");
    }
  };

  const handleRotationOffsetChange = async (deg: number) => {
    setUpdatingOrientation(true);
    try {
      await updateLidarFilters({ rotation_offset_deg: deg });
      setStatusMessage(
        `LD19 forward orientation offset set to ${deg}°. Wave hand in front of camera to verify FRONT jumps inward.`
      );
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Failed to update LD19 rotation offset"
      );
    } finally {
      setUpdatingOrientation(false);
    }
  };

  const pollIntervalMs = frame?.poll_interval_ms ?? 100;
  const analyticsEveryN = frame?.analytics_every_n_scans ?? 2;
  const simulateMoving = Boolean(frame?.simulate_moving_targets);
  const movingTrackCount = (frame?.moving_objects ?? []).filter((t) => t.is_moving).length;
  const actualHz = Number(frame?.actual_hz ?? 0);
  const lidarLive = Boolean(frame?.robot_scan_connected || frame?.hardware_connected);
  const latestPanel = scenePanels.length > 0 ? scenePanels[0] : null;
  const isMetricLocked = latestPanel ? latestPanel.lidar_calibrated : lidarLive;

  const handleLidarSettingChange = async (
    patch: Parameters<typeof updateLidarSettings>[0],
    feedback?: string
  ) => {
    setUpdatingLidarSettings(true);
    try {
      await updateLidarSettings(patch);
      if (feedback) setStatusMessage(feedback);
    } catch (err) {
      console.error("[StudioWorkspace] LiDAR settings update failed:", err);
      setStatusMessage(err instanceof Error ? err.message : "Failed to update LiDAR settings");
    } finally {
      setUpdatingLidarSettings(false);
    }
  };

  const applyFilterUpdate = async (
    nextMaxRange: number,
    nextMinInt: number,
    nextOutlier: boolean
  ) => {
    try {
      await updateLidarFilters({
        min_range_m: 0.08,
        max_range_m: nextMaxRange,
        min_intensity: nextMinInt,
        enable_outlier_filter: nextOutlier,
      });
    } catch (err) {
      console.error("[StudioWorkspace] Filter update failed:", err);
    }
  };

  const handleMapClick = (x: number, y: number, cluster?: ObjectCluster) => {
    setPendingPin({
      x,
      y,
      width_m: cluster?.width_m,
      depth_m: cluster?.depth_m,
    });
    setActiveDrawer("assets");
  };

  const handleDeleteAsset = async (id: string) => {
    try {
      await deleteEquipmentAsset(id);
      await refreshSpaceData();
    } catch (err) {
      console.error("[StudioWorkspace] Delete asset failed:", err);
    }
  };

  const handleFocus = (target: FocusTarget) => {
    setFocusTarget(target);
    if (target.equipmentId) {
      setSelectedEquipmentId(target.equipmentId);
    }
    setActiveDrawer(null);
  };

  const handleArchiveSnapshot = async () => {
    if (!space) return;
    setArchiving(true);
    setStatusMessage(null);
    try {
      const resp = await archiveTwinSnapshot(space.id);
      setStatusMessage(
        `Archived ${resp.archived_files.length} twin snapshot file(s) to PostgreSQL 18 (${resp.storage.unique_blob_count} unique blobs).`
      );
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to archive snapshot");
    } finally {
      setArchiving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* 1. COMPACT WORKSPACE HEADER WITH LIVE ANIMATED KPIs & SLIDE-OVER DRAWER TRIGGERS */}
      <WorkspaceHeader
        badge="SPATIAL TWIN STUDIO"
        title={space?.name || "Spatial Digital Twin"}
        subtitle={
          space?.facility
            ? `${space.facility} · ${Number(frame?.metrics?.area_m2 ?? 0).toFixed(1)} m² · ${darkZones.length} dark zone(s)`
            : "Live 2D LD19 LiDAR + 3D Real-Room Fusion (Three.js & Babylon.js 9)"
        }
        statusTone={lidarLive ? "ok" : "idle"}
        statusLabel={
          frame?.robot_scan_connected
            ? "ROS 2 /scan LIVE"
            : frame?.source_mode === "hardware"
              ? "MAC USB LIDAR"
              : "SIMULATOR"
        }
        sticky
        metrics={[
          {
            label: "Scan Rate",
            value: actualHz > 0 ? actualHz : Number(frame?.rpm ?? 0),
            unit: actualHz > 0 ? "Hz" : "RPM",
            decimals: actualHz > 0 ? 1 : 0,
            tone: "sky",
            compact: true,
          },
          {
            label: "Points",
            value: frame?.point_count ?? 0,
            tone: "sky",
            compact: true,
          },
          {
            label: "Moving",
            value: movingTrackCount,
            tone: movingTrackCount > 0 ? "orange" : "default",
            pulse: movingTrackCount > 0,
            compact: true,
          },
          {
            label: "3D Panels",
            value: scenePanels.length,
            tone: scenePanels.length > 0 ? "emerald" : "default",
            compact: true,
          },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant={activeDrawer === "rooms" ? "default" : "secondary"}
              onClick={() => setActiveDrawer((d) => (d === "rooms" ? null : "rooms"))}
            >
              <FolderOpen className="h-3.5 w-3.5 text-eigenia-sky" />
              Rooms &amp; Scenes ({spaces.length})
            </Button>
            <Button
              size="sm"
              variant={activeDrawer === "fusion" ? "default" : "secondary"}
              onClick={() => setActiveDrawer((d) => (d === "fusion" ? null : "fusion"))}
            >
              <SlidersHorizontal className="h-3.5 w-3.5 text-eigenia-orange" />
              Fusion &amp; LD19 Tuning
            </Button>
            <Button
              size="sm"
              variant={activeDrawer === "assets" ? "default" : "secondary"}
              onClick={() => setActiveDrawer((d) => (d === "assets" ? null : "assets"))}
            >
              <Layers className="h-3.5 w-3.5 text-eigenia-amber" />
              Assets &amp; Filters ({equipment.length})
            </Button>
          </div>
        }
      />

      {/* 2. COMPACT FUSION & LIDAR RIBBON (SINGLE HIGH-DENSITY ACTION ROW) */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-shell px-3.5 py-2">
        {/* Left: Primary Capture + Render Mode + Quality Preset */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="default"
            disabled={!space?.id || capturingWall || capturing360}
            onClick={() => void handleCaptureWall()}
            className="font-semibold"
          >
            {capturingWall ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Camera className="h-3.5 w-3.5" />
            )}
            {capturingWall ? "Fusing 3D Wall..." : "Capture Front Wall"}
          </Button>

          {/* Render Mode Switcher */}
          <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
            {(
              [
                { id: "solid", label: "Solid", Icon: Box },
                { id: "translucent", label: "Translucent", Icon: Layers },
                { id: "wireframe", label: "Wireframe", Icon: Grid3x3 },
              ] as const
            ).map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setSceneRenderMode(id)}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px] font-medium transition motion-reduce:transition-none ${
                  sceneRenderMode === id
                    ? "bg-eigenia-orange text-white shadow-sm"
                    : "text-eigenia-muted hover:text-white"
                }`}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            ))}
          </div>

          {/* Quality Preset Switcher */}
          <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
            {(
              [
                { id: "fast", label: "Fast" },
                { id: "balanced", label: "Balanced" },
                { id: "studio_ultra", label: "Studio Ultra" },
              ] as const
            ).map((preset) => (
              <button
                key={preset.id}
                type="button"
                disabled={capturingWall || capturing360}
                onClick={() => handleQualityPresetChange(preset.id)}
                className={`rounded px-2 py-1 font-mono text-[10px] font-medium transition motion-reduce:transition-none ${
                  qualityPreset === preset.id
                    ? "bg-eigenia-sky text-eigenia-obsidian font-semibold"
                    : "text-eigenia-muted hover:text-white"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {!isMetricLocked && (
            <Link
              href="/catalog?focus=ld19_lidar_module"
              className="inline-flex items-center gap-1 rounded-full border border-eigenia-amber/50 bg-eigenia-amber/15 px-2.5 py-0.5 font-mono text-[10px] font-medium text-eigenia-amber transition hover:border-eigenia-orange hover:bg-eigenia-orange/20 hover:text-white"
            >
              <Cpu className="h-3 w-3" />
              LD19 Offline · Inspect Pi 5
            </Link>
          )}
        </div>

        {/* Right: Quick LiDAR Source, Poll Rate & Baseline */}
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              { id: "robot_ros2", label: "PuppyPi ROS 2" },
              { id: "hardware", label: "Mac USB" },
              { id: "simulator", label: "Simulator" },
            ] as const
          ).map((src) => (
            <Button
              key={src.id}
              size="sm"
              className="h-7 px-2 font-mono text-[10px]"
              disabled={updatingLidarSettings || (src.id === "robot_ros2" && !activeRobotId)}
              variant={frame?.source_mode === src.id ? "sky" : "secondary"}
              onClick={() =>
                void handleLidarSettingChange(
                  {
                    source_mode: src.id,
                    robot_id: src.id === "robot_ros2" ? activeRobotId : undefined,
                  },
                  `Switched LiDAR source to ${src.label}.`
                )
              }
            >
              {src.label}
            </Button>
          ))}

          <div className="inline-flex items-center gap-1 rounded border border-white/15 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px]">
            <Gauge className="h-3 w-3 text-eigenia-sky" />
            <select
              value={pollIntervalMs}
              disabled={updatingLidarSettings}
              onChange={(e) =>
                void handleLidarSettingChange({ poll_interval_ms: Number(e.target.value) })
              }
              className="bg-transparent text-[10px] text-white focus:outline-none"
            >
              <option value={500} className="bg-eigenia-obsidian">
                2 Hz
              </option>
              <option value={200} className="bg-eigenia-obsidian">
                5 Hz
              </option>
              <option value={100} className="bg-eigenia-obsidian">
                10 Hz
              </option>
              <option value={50} className="bg-eigenia-obsidian">
                20 Hz
              </option>
            </select>
          </div>

          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[10px]"
            onClick={() => void captureBaseline()}
          >
            {frame?.baseline_active ? "Recapture Baseline" : "Baseline"}
          </Button>
          {space && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-[10px]"
              onClick={async () => {
                await extractAndSaveWalls(space.id);
                await refreshSpaceData(space.id);
                setStatusMessage("Extracted RANSAC walls saved to space floorplan.");
              }}
            >
              Save Walls
            </Button>
          )}
        </div>
      </div>

      {/* Transient Alerts & Status Banners */}
      {statusMessage && (
        <div className="flex items-center justify-between rounded-lg border border-eigenia-sky/35 bg-eigenia-sky/10 px-4 py-1.5 font-mono text-xs text-eigenia-sky">
          <span>{statusMessage}</span>
          <Button size="sm" variant="ghost" onClick={() => setStatusMessage(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {(frame?.anomalies?.length ?? 0) > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-eigenia-fault/50 bg-eigenia-fault/15 px-4 py-2 text-xs text-white">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-eigenia-fault" />
            <span className="font-mono font-semibold text-eigenia-fault">
              PHYSICAL CHANGE DETECTED:
            </span>
            <span>
              {frame?.anomalies?.length ?? 0} anomalous cluster(s) deviating from room baseline.
            </span>
          </div>
          <Badge variant="fault">LIVE DIFF</Badge>
        </div>
      )}

      {focusTarget && (
        <div className="flex items-center justify-between rounded-lg border border-eigenia-sky/35 bg-eigenia-sky/10 px-3 py-1.5 font-mono text-[11px] text-eigenia-sky">
          <span>
            LOCKED FOCUS: {focusTarget.label} @ ({focusTarget.x.toFixed(2)}m,{" "}
            {focusTarget.y.toFixed(2)}m)
          </span>
          <Button size="sm" variant="ghost" onClick={() => setFocusTarget(null)}>
            Clear Focus
          </Button>
        </div>
      )}

      {/* 3. FULL-WIDTH RECLAIMED HERO VIEWPORT (h-[640px]!) */}
      <div className="flex flex-col gap-3">
        <SegmentedTabs
          value={viewportTab}
          onValueChange={setViewportTab}
          tabs={[
            {
              id: "lidar2d",
              label: "2D Tactical Radar",
              icon: <Radar className="h-3.5 w-3.5" />,
              count: frame?.point_count ?? 0,
            },
            {
              id: "twin3d",
              label: "3D Three.js Twin",
              icon: <Box className="h-3.5 w-3.5" />,
              count: scenePanels.length > 0 ? scenePanels.length : undefined,
            },
            {
              id: "babylon",
              label: "3D Babylon.js PBR",
              icon: <Sparkles className="h-3.5 w-3.5" />,
              count: scenePanels.length > 0 ? scenePanels.length : undefined,
            },
          ]}
          rightSlot={
            <div className="flex flex-wrap items-center gap-2">
              {frame?.source_mode === "simulator" && (
                <Button
                  size="sm"
                  className="h-7 px-2 text-[10px]"
                  variant={frame?.rogue_injected ? "destructive" : "outline"}
                  onClick={() =>
                    void updateLidarMode({ inject_rogue_object: !frame?.rogue_injected })
                  }
                >
                  <ShieldAlert className="h-3 w-3" />
                  {frame?.rogue_injected ? "Clear Rogue Asset" : "Simulate Change"}
                </Button>
              )}
              <div className="flex items-center gap-1.5 rounded border border-white/10 bg-eigenia-obsidian px-2 py-1">
                <span className="font-mono text-[10px] text-eigenia-ink">Moving Sim</span>
                <Switch
                  checked={simulateMoving}
                  disabled={updatingLidarSettings}
                  onCheckedChange={(checked) =>
                    void handleLidarSettingChange({
                      simulate_moving_targets: checked,
                      motion_tracking_enabled: true,
                    })
                  }
                />
              </div>
            </div>
          }
        />

        <div className="min-h-[640px] w-full rounded-xl border border-white/10 bg-eigenia-obsidian/60 p-1.5">
          {viewportTab === "lidar2d" && (
            <div className="h-[640px] w-full [&>div]:h-full">
              <Lidar2DCanvas
                frame={frame}
                equipment={equipment}
                darkZones={darkZones}
                selectedEquipmentId={selectedEquipmentId}
                pendingPin={pendingPin}
                focusTarget={focusTarget}
                onSelectEquipment={setSelectedEquipmentId}
                onMapClick={handleMapClick}
              />
            </div>
          )}

          {viewportTab === "twin3d" && (
            <div className="h-[640px] w-full [&>div]:h-full">
              <DigitalTwin3D
                frame={frame}
                equipment={equipment}
                darkZones={darkZones}
                selectedEquipmentId={selectedEquipmentId}
                focusTarget={focusTarget}
                onSelectEquipment={setSelectedEquipmentId}
                scenePanels={scenePanels}
                sceneRenderMode={sceneRenderMode}
                hiddenPanelIds={hiddenPanelIds}
              />
            </div>
          )}

          {viewportTab === "babylon" && (
            <div className="h-[640px] w-full [&>div]:h-full">
              <BabylonTwinCanvas
                frame={frame}
                equipment={equipment}
                darkZones={darkZones}
                selectedEquipmentId={selectedEquipmentId}
                focusTarget={focusTarget}
                onSelectEquipment={setSelectedEquipmentId}
                scenePanels={scenePanels}
                sceneRenderMode={sceneRenderMode}
                hiddenPanelIds={hiddenPanelIds}
              />
            </div>
          )}
        </div>
      </div>

      {/* SLIDE-OVER DRAWER 1: ROOMS & SAVED SCENES */}
      <SlideOverDrawer
        open={activeDrawer === "rooms"}
        onClose={() => setActiveDrawer(null)}
        title="Rooms & Saved Scenes"
        subtitle="Create blank rooms, save checkpoints, archive snapshots to PostgreSQL 18, and switch scenes"
        badge={`${spaces.length} SAVED`}
        badgeVariant="sky"
        widthClassName="max-w-2xl"
      >
        <RoomSceneManager
          spaces={spaces}
          activeSpaceId={activeSpaceId}
          archiving={archiving}
          onSelectSpace={(id) => {
            setActiveSpaceId(id);
            setActiveDrawer(null);
          }}
          onCreateRoom={async (payload) => {
            const created = await createNewSpace(payload);
            setStatusMessage(`Created and switched to blank room "${created.name}".`);
          }}
          onRenameRoom={async (spaceId, payload) => {
            const updated = await renameSpace(spaceId, payload);
            setStatusMessage(`Renamed room to "${updated.name}".`);
          }}
          onCloneRoom={async (spaceId, payload) => {
            const res = await cloneCurrentSpace(payload, spaceId);
            setStatusMessage(
              `Saved room checkpoint "${res.space.name}" (${res.cloned_panels} panels, ${res.cloned_equipment} assets).`
            );
          }}
          onDeleteRoom={async (spaceId) => {
            await deleteSpaceById(spaceId);
            setStatusMessage("Deleted saved room.");
          }}
          onArchiveSnapshot={() => void handleArchiveSnapshot()}
        />
      </SlideOverDrawer>

      {/* SLIDE-OVER DRAWER 2: 3D FUSION & LD19 ORIENTATION TUNING */}
      <SlideOverDrawer
        open={activeDrawer === "fusion"}
        onClose={() => setActiveDrawer(null)}
        title="3D Real-Room Fusion & LD19 Orientation"
        subtitle="5-pass enhancement pipeline, 360° room scan, LD19 forward angle calibration, and captured panels"
        badge={`${scenePanels.length} PANELS`}
        badgeVariant="default"
        widthClassName="max-w-3xl"
      >
        <div className="space-y-4">
          <SceneReconstructionBar
            spaceId={space?.id ?? null}
            activeRobotId={activeRobotId}
            lidarLive={lidarLive}
            panels={scenePanels}
            renderMode={sceneRenderMode}
            hiddenPanelIds={hiddenPanelIds}
            capturingWall={capturingWall}
            capturing360={capturing360}
            enhancingPanelId={enhancingPanelId}
            resolution={sceneResolution}
            depthReliefScale={depthReliefScale}
            fallbackDistanceM={fallbackDistanceM}
            qualityPreset={qualityPreset}
            enhanceOptions={enhanceOptions}
            rotationOffsetDeg={frame?.rotation_offset_deg ?? 90}
            cardinalM={frame?.cardinal_m ?? null}
            updatingOrientation={updatingOrientation}
            onRenderModeChange={setSceneRenderMode}
            onResolutionChange={setSceneResolution}
            onDepthReliefScaleChange={setDepthReliefScale}
            onFallbackDistanceChange={setFallbackDistanceM}
            onQualityPresetChange={handleQualityPresetChange}
            onEnhanceOptionsChange={handleEnhanceOptionsChange}
            onRotationOffsetChange={(deg) => void handleRotationOffsetChange(deg)}
            onCaptureWall={() => void handleCaptureWall()}
            onCapture360={() => void handleCapture360()}
            onEnhancePanel={(id) => void handleEnhanceScenePanel(id)}
            onTogglePanelVisibility={handleTogglePanelVisibility}
            onDeletePanel={(id) => void handleDeleteScenePanel(id)}
            onClearPanels={() => void handleClearScenePanels()}
          />

          {/* Analytics Cadence & PG18 Snapshot Archive */}
          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3.5">
              <div className="flex items-center gap-2">
                <label className="font-mono text-[11px] text-eigenia-muted">
                  LiDAR Analytics Cadence:
                </label>
                <select
                  value={analyticsEveryN}
                  disabled={updatingLidarSettings}
                  onChange={(e) =>
                    void handleLidarSettingChange({
                      analytics_every_n_scans: Number(e.target.value),
                    })
                  }
                  className="h-7 rounded border border-white/15 bg-eigenia-obsidian px-2 font-mono text-[11px] text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                >
                  <option value={1}>Every 1 scan</option>
                  <option value={2}>Every 2 scans</option>
                  <option value={4}>Every 4 scans</option>
                  <option value={8}>Every 8 scans</option>
                </select>
              </div>
              {space && (
                <Button
                  size="sm"
                  variant="default"
                  disabled={archiving}
                  onClick={() => void handleArchiveSnapshot()}
                >
                  <Archive className="h-3.5 w-3.5" />
                  {archiving ? "Archiving..." : "Archive Twin Snapshot to PG18"}
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </SlideOverDrawer>

      {/* SLIDE-OVER DRAWER 3: ASSETS, VISION PINNING, FOCUS QUEUE & LIDAR FILTERS */}
      <SlideOverDrawer
        open={activeDrawer === "assets"}
        onClose={() => setActiveDrawer(null)}
        title="Assets, Vision Pinning & LiDAR Filters"
        subtitle="Pin equipment from camera nameplates, resolve dark zones, filter LiDAR rays, and export open standards"
        badge={`${equipment.length} ASSETS`}
        badgeVariant="amber"
        widthClassName="max-w-2xl"
      >
        <div className="space-y-4">
          {/* OpenRouter Vision Nameplate Scanner */}
          <VisionNameplatePanel
            spaceId={space?.id ?? ""}
            models={visionModels}
            defaultModel={defaultModel}
            openrouterConfigured={openrouterConfigured}
            pendingPin={pendingPin}
            activeRobotId={activeRobotId}
            onPinUpdated={(p) => setPendingPin(p)}
            onAssetPinned={() => {
              if (space) void refreshSpaceData(space.id);
            }}
          />

          {/* LiDAR Signal Conditioning */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <SlidersHorizontal className="h-3.5 w-3.5 text-eigenia-sky" />
                LiDAR Signal Conditioning
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex justify-between font-mono text-[11px]">
                  <span className="text-eigenia-muted">Max Range</span>
                  <span className="text-white">{maxRange.toFixed(1)} m</span>
                </div>
                <Slider
                  min={1}
                  max={12}
                  step={0.5}
                  value={[maxRange]}
                  onValueChange={([v]) => {
                    setMaxRange(v);
                    void applyFilterUpdate(v, minIntensity, outlierFilter);
                  }}
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between font-mono text-[11px]">
                  <span className="text-eigenia-muted">Min Reflectance Intensity</span>
                  <span className="text-white">{minIntensity} / 255</span>
                </div>
                <Slider
                  min={0}
                  max={240}
                  step={5}
                  value={[minIntensity]}
                  onValueChange={([v]) => {
                    setMinIntensity(v);
                    void applyFilterUpdate(maxRange, v, outlierFilter);
                  }}
                />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-xs text-eigenia-muted">Speckle Outlier Filter</span>
                <Switch
                  checked={outlierFilter}
                  onCheckedChange={(checked) => {
                    setOutlierFilter(checked);
                    void applyFilterUpdate(maxRange, minIntensity, checked);
                  }}
                />
              </div>
            </CardContent>
          </Card>

          {/* Dark-Zone Focus Queue */}
          <FocusQueuePanel
            items={focusQueue}
            onFocus={handleFocus}
            onEnrich={(eqId) => void handleEnrichAsset(eqId)}
            enrichingId={enrichingId}
          />

          {/* Placed Digital Twin Assets & 6 Zero-Lock-In Standards Exports */}
          <Card>
            <CardHeader>
              <CardTitle>Placed Digital Twin Assets ({equipment.length})</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {equipment.length === 0 ? (
                <div className="rounded border border-dashed border-white/10 p-3 font-mono text-[11px] text-eigenia-muted">
                  Click any yellow LiDAR cluster on the 2D radar or scan an equipment nameplate
                  photo above to pin your first asset.
                </div>
              ) : (
                <div className="max-h-60 space-y-2 overflow-y-auto pr-1">
                  {equipment.map((eq) => {
                    const status = eq.completeness?.status ?? "INCOMPLETE";
                    const pct = eq.completeness?.completeness_pct ?? 50;
                    const badgeVariant =
                      status === "DARK" ? "fault" : status === "INCOMPLETE" ? "amber" : "sky";
                    return (
                      <div
                        key={eq.id}
                        onClick={() => {
                          setSelectedEquipmentId(eq.id);
                          setFocusTarget({ x: eq.x, y: eq.y, label: eq.name, equipmentId: eq.id });
                          setActiveDrawer(null);
                        }}
                        className={`cursor-pointer rounded border p-2.5 transition ${
                          selectedEquipmentId === eq.id
                            ? "border-eigenia-orange bg-eigenia-orange/10"
                            : "border-white/10 bg-eigenia-obsidian hover:border-white/25"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="truncate text-xs font-semibold text-white">
                                {eq.name}
                              </span>
                              <Badge variant={badgeVariant}>{pct}%</Badge>
                            </div>
                            <div className="font-mono text-[10px] text-eigenia-muted">
                              {eq.manufacturer} · {eq.model_number}
                            </div>
                            {eq.serial_number && (
                              <div className="font-mono text-[10px] text-eigenia-sky">
                                S/N: {eq.serial_number}
                              </div>
                            )}
                            <div className="mt-1 font-mono text-[10px] text-eigenia-muted">
                              ({eq.x.toFixed(2)}m, {eq.y.toFixed(2)}m) · {eq.dexpi_class}
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button
                              size="icon"
                              variant="ghost"
                              title="Run Pass-3 AI Research & NVD CVE Enrichment"
                              disabled={enrichingId === eq.id}
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleEnrichAsset(eq.id);
                              }}
                            >
                              <Sparkles
                                className={`h-3.5 w-3.5 text-eigenia-orange ${
                                  enrichingId === eq.id ? "animate-spin" : ""
                                }`}
                              />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              title="Remove Asset"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleDeleteAsset(eq.id);
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5 text-eigenia-fault" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {space && (
                <div className="border-t border-white/10 pt-3">
                  <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-eigenia-muted">
                    <Download className="h-3 w-3 text-eigenia-orange" />
                    Standards Exports (Zero Lock-In)
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                    {[
                      { fmt: "cyclonedx", label: "CycloneDX 1.6" },
                      { fmt: "dexpi", label: "DEXPI G_CPDT" },
                      { fmt: "cypher", label: "Neo4j Cypher" },
                      { fmt: "dxf", label: "AutoCAD DXF" },
                      { fmt: "gltf", label: "3D glTF/GLB" },
                      { fmt: "ply", label: "PLY Cloud" },
                    ].map((ex) => (
                      <Button key={ex.fmt} size="sm" variant="secondary" asChild>
                        <a href={getExportUrl(space.id, ex.fmt)} download>
                          {ex.label}
                        </a>
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </SlideOverDrawer>
    </div>
  );
}
