"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Box,
  Camera,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Download,
  Eye,
  EyeOff,
  HelpCircle,
  LayoutGrid,
  Loader2,
  Map as MapIcon,
  Maximize2,
  Navigation,
  OctagonAlert,
  PanelRightClose,
  PanelRightOpen,
  Radar,
  RefreshCw,
  SlidersHorizontal,
  Star,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Lidar2DCanvas } from "@/components/lidar/Lidar2DCanvas";
import { CameraCalibrationModal } from "@/components/overwatch/CameraCalibrationModal";
import { CameraManagerDrawer } from "@/components/overwatch/CameraManagerDrawer";
import { CameraStageCard } from "@/components/overwatch/CameraStageCard";
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
  type OverwatchCameraSlot,
  type OverwatchDetection,
  type OverwatchGeometry,
  type OverwatchStatus,
  type TaskPointResult,
} from "@/lib/overwatchApi";
import { useBrowserOverwatchBridge } from "@/lib/useBrowserOverwatchBridge";
import { cn } from "@/lib/utils";

type LayoutMode = "spotlight" | "grid" | "map_focus";

interface PersistedLayout {
  layoutMode: LayoutMode;
  mainViewId: string;
  hiddenIds: string[];
  collapsedIds: string[];
  dockCollapsed: boolean;
}

const LAYOUT_STORAGE_KEY = "eigenia.overwatch.layout.v2";

const DEFAULT_LAYOUT: PersistedLayout = {
  layoutMode: "spotlight",
  mainViewId: "usb_4k",
  hiddenIds: [],
  collapsedIds: [],
  dockCollapsed: false,
};

const RATING_BADGE: Record<string, string> = {
  OPTIMAL: "border-emerald-500/50 bg-emerald-950/60 text-emerald-300",
  GOOD: "border-cyan-500/50 bg-cyan-950/60 text-cyan-300",
  FAIR: "border-amber-500/50 bg-amber-950/60 text-amber-300",
  POOR: "border-red-500/50 bg-red-950/60 text-red-300",
  SINGLE_VIEW: "border-slate-600 bg-slate-900 text-slate-300",
};

const CAMERA_ACCENTS = [
  "text-cyan-400",
  "text-violet-400",
  "text-emerald-400",
  "text-amber-400",
  "text-pink-400",
];

function loadSavedLayout(): PersistedLayout {
  if (typeof window === "undefined") return DEFAULT_LAYOUT;
  try {
    const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<PersistedLayout>;
    return {
      layoutMode:
        parsed.layoutMode === "grid" || parsed.layoutMode === "map_focus" ? parsed.layoutMode : "spotlight",
      mainViewId: typeof parsed.mainViewId === "string" && parsed.mainViewId ? parsed.mainViewId : "usb_4k",
      hiddenIds: Array.isArray(parsed.hiddenIds) ? parsed.hiddenIds.map(String) : [],
      collapsedIds: Array.isArray(parsed.collapsedIds) ? parsed.collapsedIds.map(String) : [],
      dockCollapsed: Boolean(parsed.dockCollapsed),
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function OverwatchCockpit(): React.JSX.Element {
  const { frame, equipment, darkZones, handleGlobalEstop, estopActive, activeRobot, activeRobotId, activeSpaceId } =
    useStudio();
  const bridge = useBrowserOverwatchBridge();

  const [status, setStatus] = useState<OverwatchStatus | null>(null);
  const [geometry, setGeometry] = useState<OverwatchGeometry | null>(null);
  const [streamNonce, setStreamNonce] = useState<number>(() => Date.now());

  // Modals & Drawers
  const [managerOpen, setManagerOpen] = useState(false);
  const [calModalOpen, setCalModalOpen] = useState(false);
  const [calCameraId, setCalCameraId] = useState<string>("usb_4k");

  // Layout preferences (persisted in localStorage)
  const [layout, setLayout] = useState<PersistedLayout>(DEFAULT_LAYOUT);
  const [layoutHydrated, setLayoutHydrated] = useState(false);

  // Tactical layer toggles
  const [showFrustums, setShowFrustums] = useState(true);
  const [showOverlap, setShowOverlap] = useState(true);
  const [showEllipses, setShowEllipses] = useState(true);
  const [taskMode, setTaskMode] = useState(false);

  // 3D Room Digital Twin Fusion
  const [fusing3d, setFusing3d] = useState(false);
  const [fuseResult, setFuseResult] = useState<MulticamFuseResult | null>(null);
  const [fuseError, setFuseError] = useState<string | null>(null);

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

  useEffect(() => {
    setLayout(loadSavedLayout());
    setLayoutHydrated(true);
  }, []);

  useEffect(() => {
    if (!layoutHydrated || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // Ignore storage quota errors
    }
  }, [layout, layoutHydrated]);

  const pollOverwatch = useCallback(async () => {
    try {
      const [st, geo] = await Promise.all([getOverwatchStatus(), getOverwatchGeometry(6.0)]);
      setStatus(st);
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

  // Keyboard shortcut: Shift+Space = E-STOP
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

  const camerasMap: Record<string, OverwatchCameraSlot> = useMemo(() => {
    return status?.cameras ?? {};
  }, [status]);

  const fixedCameraIds = useMemo(() => {
    const keys = Object.keys(camerasMap);
    return keys.length > 0 ? keys : ["usb_4k", "macbook_cam"];
  }, [camerasMap]);

  const allViewIds = useMemo(() => {
    return ["bev_map", ...fixedCameraIds, "puppypi_fpv"];
  }, [fixedCameraIds]);

  const uncalibratedOnlineCount = useMemo(() => {
    return Object.values(camerasMap).filter((c) => c.online && !c.calibration?.calibrated).length;
  }, [camerasMap]);

  const onlineFixedCount = useMemo(() => {
    return Object.values(camerasMap).filter((c) => c.online).length;
  }, [camerasMap]);

  const toggleHidden = (id: string) => {
    setLayout((prev) => {
      const exists = prev.hiddenIds.includes(id);
      const hiddenIds = exists ? prev.hiddenIds.filter((x) => x !== id) : [...prev.hiddenIds, id];
      let mainViewId = prev.mainViewId;
      if (!exists && prev.mainViewId === id) {
        const nextVisible = allViewIds.find((v) => !hiddenIds.includes(v));
        if (nextVisible) mainViewId = nextVisible;
      }
      return { ...prev, hiddenIds, mainViewId };
    });
  };

  const toggleCollapsed = (id: string) => {
    setLayout((prev) => ({
      ...prev,
      collapsedIds: prev.collapsedIds.includes(id)
        ? prev.collapsedIds.filter((x) => x !== id)
        : [...prev.collapsedIds, id],
    }));
  };

  const promoteToMain = (id: string) => {
    setLayout((prev) => ({
      ...prev,
      layoutMode: prev.layoutMode === "map_focus" ? "spotlight" : prev.layoutMode,
      mainViewId: id,
      hiddenIds: prev.hiddenIds.filter((x) => x !== id),
      collapsedIds: prev.collapsedIds.filter((x) => x !== id),
    }));
  };

  const handleCameraFeedClick = async (cameraId: string, e: React.MouseEvent<HTMLDivElement>) => {
    if (!taskMode) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    const v = Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height)));
    setTaskBusy(true);
    setTaskError(null);
    setLastTaskClick({ kind: "pixel", cameraId, u, v });
    try {
      const proj = await projectOrDispatchTaskPoint({
        camera_id: cameraId,
        u_norm: u,
        v_norm: v,
        dispatch: false,
      });
      setTaskPreview(proj);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "Could not project floor point.");
    } finally {
      setTaskBusy(false);
    }
  };

  const handleBevMapClick = async (x: number, y: number) => {
    if (!taskMode) return;
    setTaskBusy(true);
    setTaskError(null);
    setLastTaskClick({ kind: "bev", x, y });
    try {
      const proj = await projectOrDispatchTaskPoint({
        camera_id: "bev_map",
        target_xy: [x, y],
        dispatch: false,
      });
      setTaskPreview(proj);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "Failed to compute floor waypoint.");
    } finally {
      setTaskBusy(false);
    }
  };

  const handleDispatchTask = async () => {
    if (!lastTaskClick) return;
    setTaskBusy(true);
    setTaskError(null);
    try {
      const res =
        lastTaskClick.kind === "pixel"
          ? await projectOrDispatchTaskPoint({
              camera_id: lastTaskClick.cameraId,
              u_norm: lastTaskClick.u,
              v_norm: lastTaskClick.v,
              dispatch: true,
            })
          : await projectOrDispatchTaskPoint({
              camera_id: "bev_map",
              target_xy: [lastTaskClick.x, lastTaskClick.y],
              dispatch: true,
            });
      setTaskPreview(res);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "Dispatch failed.");
    } finally {
      setTaskBusy(false);
    }
  };

  const handleFuseAllCameras = async () => {
    setFusing3d(true);
    setFuseError(null);
    try {
      const res = await reconstructMulticamDigitalTwin({
        space_id: activeSpaceId,
        robot_id: activeRobotId,
        include_puppypi_fpv: true,
        resolution: "medium",
      });
      setFuseResult(res);
    } catch (err) {
      setFuseError(err instanceof Error ? err.message : "Multi-camera 3D fusion failed.");
    } finally {
      setFusing3d(false);
    }
  };

  const renderMapView = (opts: { isMain?: boolean; compact?: boolean }) => {
    const collapsed = layout.collapsedIds.includes("bev_map");
    const rating = geometry?.placement_advisor?.rating ?? "SINGLE_VIEW";
    return (
      <Card
        className={cn(
          "overflow-hidden border-white/10 bg-slate-950/90",
          opts.isMain && "border-cyan-500/40 ring-1 ring-cyan-500/20"
        )}
      >
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-xs font-semibold text-slate-100">
              2D Tactical Map &amp; Triangulation
            </CardTitle>
            <Badge className={cn("border px-1.5 py-0 text-[9px]", RATING_BADGE[rating] || RATING_BADGE.SINGLE_VIEW)}>
              {rating}
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            {!opts.compact && (
              <>
                <Button
                  size="sm"
                  variant={showFrustums ? "default" : "ghost"}
                  onClick={() => setShowFrustums((v) => !v)}
                  className="h-6 px-2 text-[10px] cursor-pointer"
                >
                  Frustums
                </Button>
                <Button
                  size="sm"
                  variant={showOverlap ? "default" : "ghost"}
                  onClick={() => setShowOverlap((v) => !v)}
                  className="h-6 px-2 text-[10px] cursor-pointer"
                >
                  Overlap
                </Button>
                <Button
                  size="sm"
                  variant={showEllipses ? "default" : "ghost"}
                  onClick={() => setShowEllipses((v) => !v)}
                  className="h-6 px-2 text-[10px] cursor-pointer"
                >
                  2σ
                </Button>
              </>
            )}
            {!opts.isMain && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => promoteToMain("bev_map")}
                title="Promote 2D Map to Main View"
                className="h-6 gap-1 px-1.5 text-[10px] text-cyan-300 hover:bg-cyan-950/60 cursor-pointer"
              >
                {opts.compact ? <Maximize2 className="h-3 w-3" /> : <><Star className="h-3 w-3" /> Main</>}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => toggleCollapsed("bev_map")}
              className="h-6 px-1.5 text-slate-400 hover:text-slate-100 cursor-pointer"
            >
              {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => toggleHidden("bev_map")}
              className="h-6 px-1.5 text-slate-400 hover:text-red-300 cursor-pointer"
            >
              <EyeOff className="h-3 w-3" />
            </Button>
          </div>
        </CardHeader>
        {!collapsed && (
          <CardContent className="p-2">
            <div
              className={cn(
                "w-full overflow-hidden rounded-lg border border-white/10 bg-slate-950",
                opts.compact ? "h-[200px]" : opts.isMain ? "h-[460px]" : "h-[360px]"
              )}
            >
              <Lidar2DCanvas
                frame={frame}
                equipment={equipment}
                darkZones={darkZones}
                selectedEquipmentId={null}
                pendingPin={
                  taskPreview?.waypoint_xy
                    ? { x: taskPreview.waypoint_xy[0], y: taskPreview.waypoint_xy[1] }
                    : null
                }
                focusTarget={null}
                overwatchStatus={status}
                overwatchGeometry={geometry}
                showFrustums={showFrustums}
                showOverlapHeatmap={showOverlap}
                showGdopEllipses={showEllipses}
                onSelectEquipment={() => {}}
                onMapClick={(x, y) => {
                  if (taskMode) void handleBevMapClick(x, y);
                }}
              />
            </div>
            {!opts.compact && geometry?.placement_advisor?.recommendation && (
              <div className="mt-2 rounded-md border border-white/10 bg-slate-900/60 px-2.5 py-1.5 text-[11px] text-slate-300">
                <strong className="text-cyan-300">Stereo Advisor:</strong>{" "}
                {geometry.placement_advisor.recommendation}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    );
  };

  const renderViewTile = (viewId: string, opts: { isMain?: boolean; compact?: boolean }) => {
    if (viewId === "bev_map") {
      return <React.Fragment key="bev_map">{renderMapView(opts)}</React.Fragment>;
    }
    if (viewId === "puppypi_fpv") {
      return (
        <CameraStageCard
          key="puppypi_fpv"
          cameraId="puppypi_fpv"
          cameraName={`${activeRobot?.name || "PuppyPi Pro"} FPV (Mobile)`}
          accentClass="text-emerald-400"
          online={activeRobot?.status === "online"}
          width={640}
          height={480}
          fps={15}
          isMain={opts.isMain}
          compact={opts.compact}
          collapsed={layout.collapsedIds.includes("puppypi_fpv")}
          streamUrl={getRobotVideoStreamUrl(activeRobotId || "")}
          disableCalibrate
          onMakeMain={() => promoteToMain("puppypi_fpv")}
          onToggleCollapse={() => toggleCollapsed("puppypi_fpv")}
          onHide={() => toggleHidden("puppypi_fpv")}
        />
      );
    }

    const slot = camerasMap[viewId];
    const idx = Math.max(0, fixedCameraIds.indexOf(viewId));
    const accent = CAMERA_ACCENTS[idx % CAMERA_ACCENTS.length];
    const liveStream =
      viewId === "usb_4k"
        ? bridge.liveStreams.usb_4k
        : viewId === "macbook_cam"
          ? bridge.liveStreams.macbook_cam
          : null;
    const bindFn =
      viewId === "usb_4k" || viewId === "macbook_cam"
        ? (el: HTMLVideoElement | null) => bridge.bindVideoElement(viewId, el)
        : undefined;

    return (
      <CameraStageCard
        key={viewId}
        cameraId={viewId}
        cameraName={slot?.camera_name || viewId}
        accentClass={accent}
        online={Boolean(slot?.online || liveStream)}
        width={slot?.width || 0}
        height={slot?.height || 0}
        fps={slot?.fps || 0}
        calibrated={Boolean(slot?.calibration?.calibrated)}
        calibrationMethod={slot?.calibration?.calibration_method}
        isMain={opts.isMain}
        compact={opts.compact}
        collapsed={layout.collapsedIds.includes(viewId)}
        taskMode={taskMode}
        streamUrl={getOverwatchStreamUrl(viewId, streamNonce)}
        liveVideoStream={liveStream}
        onBindVideo={bindFn}
        detections={slot?.detections ?? []}
        onMakeMain={() => promoteToMain(viewId)}
        onToggleCollapse={() => toggleCollapsed(viewId)}
        onHide={() => toggleHidden(viewId)}
        onCalibrate={() => {
          setCalCameraId(viewId);
          setCalModalOpen(true);
        }}
        onFeedClick={(e) => void handleCameraFeedClick(viewId, e)}
        onSelectRoi={(det: OverwatchDetection) => {
          if (det.bbox_norm && det.bbox_norm.length === 4) {
            setSelectedRoi({
              cameraId: viewId,
              label: det.label,
              bboxNorm: det.bbox_norm,
            });
          }
        }}
      />
    );
  };

  const visibleViews = allViewIds.filter((id) => !layout.hiddenIds.includes(id));
  const effectiveMainId = visibleViews.includes(layout.mainViewId)
    ? layout.mainViewId
    : visibleViews[0] || "bev_map";
  const miniDockViews = visibleViews.filter((id) => id !== effectiveMainId);

  const labelForView = (id: string) => {
    if (id === "bev_map") return "2D Map";
    if (id === "puppypi_fpv") return "PuppyPi FPV";
    return camerasMap[id]?.camera_name || id;
  };

  const isViewOnline = (id: string) => {
    if (id === "bev_map") return true;
    if (id === "puppypi_fpv") return activeRobot?.status === "online";
    return Boolean(camerasMap[id]?.online);
  };

  return (
    <div className="space-y-4">
      {/* Top Overwatch Studio Command Bar */}
      <Card className="border-white/10 bg-slate-950/90">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => setManagerOpen(true)}
              className="h-8 gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
            >
              <Camera className="h-3.5 w-3.5" />
              Cameras ({onlineFixedCount}/{fixedCameraIds.length})
            </Button>

            {/* Layout Switcher */}
            <div className="flex items-center rounded-md border border-white/10 bg-slate-900 p-0.5">
              {(
                [
                  { id: "spotlight", label: "Main + Mini", icon: Star },
                  { id: "grid", label: "Grid", icon: LayoutGrid },
                  { id: "map_focus", label: "Map Focus", icon: MapIcon },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setLayout((prev) => ({ ...prev, layoutMode: id }))}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer",
                    layout.layoutMode === id
                      ? "bg-cyan-600/80 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>

            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setCalCameraId(effectiveMainId === "bev_map" || effectiveMainId === "puppypi_fpv" ? fixedCameraIds[0] || "usb_4k" : effectiveMainId);
                setCalModalOpen(true);
              }}
              className={cn(
                "h-8 gap-1.5 text-xs cursor-pointer",
                uncalibratedOnlineCount > 0 && "border-amber-500/60 text-amber-200"
              )}
            >
              <Crosshair className="h-3.5 w-3.5" />
              Calibrate &amp; Help
              {uncalibratedOnlineCount > 0 && (
                <span className="h-2 w-2 rounded-full bg-amber-400" />
              )}
            </Button>

            <Button
              size="sm"
              variant={taskMode ? "default" : "outline"}
              onClick={() => setTaskMode((v) => !v)}
              className={cn(
                "h-8 gap-1.5 text-xs cursor-pointer",
                taskMode && "bg-amber-500 text-slate-950 hover:bg-amber-400"
              )}
            >
              <Navigation className="h-3.5 w-3.5" />
              {taskMode ? "Click-to-Task: ON" : "Click-to-Task"}
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleFuseAllCameras()}
              disabled={fusing3d}
              className="h-8 gap-1.5 border-emerald-500/40 text-xs text-emerald-300 hover:bg-emerald-950/60 cursor-pointer"
            >
              {fusing3d ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Box className="h-3.5 w-3.5" />}
              Fuse All → 3D Room Twin
            </Button>

            <Button
              size="sm"
              variant="ghost"
              onClick={() => setStreamNonce(Date.now())}
              title="Refresh camera streams"
              className="h-8 px-2 text-slate-400 hover:text-slate-100 cursor-pointer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
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

        {/* Quick Camera Show/Hide & Promote Pill Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 bg-slate-900/50 px-3 py-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Views:
            </span>
            {allViewIds.map((vid) => {
              const hidden = layout.hiddenIds.includes(vid);
              const isMain = layout.layoutMode === "spotlight" && effectiveMainId === vid;
              const online = isViewOnline(vid);
              return (
                <div
                  key={`pill_${vid}`}
                  className={cn(
                    "inline-flex items-center overflow-hidden rounded-full border text-[11px]",
                    hidden
                      ? "border-white/10 bg-slate-950/50 text-slate-500"
                      : isMain
                        ? "border-cyan-400/70 bg-cyan-950/60 text-cyan-200"
                        : "border-white/15 bg-slate-900 text-slate-200"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => (hidden ? toggleHidden(vid) : promoteToMain(vid))}
                    title={hidden ? "Click to show" : "Click to make Main View"}
                    className="inline-flex items-center gap-1.5 px-2.5 py-0.5 cursor-pointer"
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        hidden ? "bg-slate-600" : online ? "bg-emerald-400" : "bg-slate-500"
                      )}
                    />
                    <span>{labelForView(vid)}</span>
                    {isMain && <Star className="h-2.5 w-2.5 fill-cyan-400 text-cyan-400" />}
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleHidden(vid)}
                    title={hidden ? "Show view" : "Hide view"}
                    className="border-l border-white/10 px-1.5 py-0.5 text-slate-400 hover:bg-white/10 hover:text-white cursor-pointer"
                  >
                    {hidden ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="flex items-center gap-1.5">
            {layout.hiddenIds.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setLayout((prev) => ({ ...prev, hiddenIds: [], collapsedIds: [] }))}
                className="h-6 px-2 text-[10px] text-cyan-300 cursor-pointer"
              >
                Show All ({layout.hiddenIds.length} hidden)
              </Button>
            )}
            {layout.layoutMode === "spotlight" && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setLayout((prev) => ({ ...prev, dockCollapsed: !prev.dockCollapsed }))}
                className="h-6 gap-1 px-2 text-[10px] text-slate-300 cursor-pointer"
              >
                {layout.dockCollapsed ? (
                  <>
                    <PanelRightOpen className="h-3.5 w-3.5" /> Expand Dock
                  </>
                ) : (
                  <>
                    <PanelRightClose className="h-3.5 w-3.5" /> Collapse Dock
                  </>
                )}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Task-Point Dispatch Banner */}
      {(taskPreview || taskError) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/40 bg-amber-950/30 px-3 py-2 text-xs">
          <div className="text-amber-100">
            {taskError ? (
              <span className="text-red-300">{taskError}</span>
            ) : (
              <span>
                Target floor point:{" "}
                <strong className="font-mono">
                  ({taskPreview?.target_xy[0].toFixed(2)}, {taskPreview?.target_xy[1].toFixed(2)}) m
                </strong>{" "}
                — Safe PuppyPi standoff:{" "}
                <strong className="font-mono">
                  ({taskPreview?.waypoint_xy[0].toFixed(2)}, {taskPreview?.waypoint_xy[1].toFixed(2)}) m
                </strong>
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {taskPreview && (
              <Button
                size="sm"
                disabled={taskBusy}
                onClick={() => void handleDispatchTask()}
                className="h-7 bg-amber-500 text-xs font-semibold text-slate-950 hover:bg-amber-400 cursor-pointer"
              >
                {taskBusy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                Send PuppyPi Here
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setTaskPreview(null);
                setTaskError(null);
              }}
              className="h-7 text-xs cursor-pointer"
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* 3D Digital Twin Fusion Status Banner */}
      {(fuseResult || fuseError) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/30 px-3 py-2 text-xs">
          {fuseError ? (
            <span className="text-red-300">{fuseError}</span>
          ) : (
            <span className="text-emerald-100">
              Fused <strong>{fuseResult?.camera_count}</strong> camera(s) + LD19 LiDAR into a{" "}
              <strong className="font-mono">{fuseResult?.total_triangles.toLocaleString()}</strong>-triangle 3D Room
              Digital Twin ({Math.round((fuseResult?.glb_bytes_len || 0) / 1024)} KB).
            </span>
          )}
          <div className="flex items-center gap-2">
            {fuseResult?.download_url && (
              <a
                href={`${API_URL}${fuseResult.download_url}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-emerald-400/50 bg-emerald-900/50 px-2.5 py-1 text-[11px] font-medium text-emerald-200 hover:bg-emerald-800/60"
              >
                <Download className="h-3 w-3" /> Download .glb
              </a>
            )}
            <Link
              href="/twin-3d"
              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-500"
            >
              Open 3D Twin
            </Link>
          </div>
        </div>
      )}

      {/* MAIN WORKSPACE STAGE */}
      {layout.layoutMode === "spotlight" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className={layout.dockCollapsed || miniDockViews.length === 0 ? "lg:col-span-12" : "lg:col-span-8"}>
            {renderViewTile(effectiveMainId, { isMain: true, compact: false })}
          </div>
          {!layout.dockCollapsed && miniDockViews.length > 0 && (
            <div className="space-y-3 lg:col-span-4">
              {miniDockViews.map((vid) => renderViewTile(vid, { isMain: false, compact: true }))}
            </div>
          )}
        </div>
      )}

      {layout.layoutMode === "grid" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleViews.map((vid) => renderViewTile(vid, { isMain: false, compact: false }))}
        </div>
      )}

      {layout.layoutMode === "map_focus" && (
        <div className="space-y-4">
          {renderMapView({ isMain: true, compact: false })}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visibleViews
              .filter((id) => id !== "bev_map")
              .map((vid) => renderViewTile(vid, { isMain: false, compact: true }))}
          </div>
        </div>
      )}

      {/* ROI Target Upscale Loupe */}
      {selectedRoi && (
        <div className="space-y-1">
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelectedRoi(null)}
              className="h-6 text-[11px] text-slate-400 hover:text-slate-100 cursor-pointer"
            >
              Close Loupe
            </Button>
          </div>
          <TargetUpscaleLoupe
            cameraId={selectedRoi.cameraId}
            targetLabel={selectedRoi.label}
            bboxNorm={selectedRoi.bboxNorm}
          />
        </div>
      )}

      {/* Camera Manager Slide-Over Drawer */}
      <CameraManagerDrawer
        open={managerOpen}
        onClose={() => setManagerOpen(false)}
        activeCameras={camerasMap}
        hiddenIds={layout.hiddenIds}
        onToggleHidden={toggleHidden}
        onOpenCalibrate={(cid) => {
          setCalCameraId(cid);
          setCalModalOpen(true);
        }}
        onChanged={() => {
          setStreamNonce(Date.now());
          void pollOverwatch();
        }}
        bridgeRunning={bridge.running}
        bridgePreset={bridge.usbPreset}
        bridgeAutoStart={bridge.autoStart}
        onSetBridgePreset={bridge.setUsbPreset}
        onSetBridgeAutoStart={bridge.setAutoStart}
        onStartBridge={() => void bridge.startAll()}
        onStopBridge={() => bridge.stopAll()}
      />

      {/* On-Demand Calibration & Help Wizard Modal */}
      <CameraCalibrationModal
        open={calModalOpen}
        initialCameraId={calCameraId}
        cameras={camerasMap}
        robotPose={
          status?.puppy_visual_pose
            ? { x: status.puppy_visual_pose.x, y: status.puppy_visual_pose.y }
            : null
        }
        onClose={() => setCalModalOpen(false)}
        onCalibrated={(geo) => {
          if (geo) setGeometry(geo);
          void pollOverwatch();
        }}
      />
    </div>
  );
}
