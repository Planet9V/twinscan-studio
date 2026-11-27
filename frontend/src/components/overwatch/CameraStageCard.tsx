"use client";

import React from "react";
import {
  Camera,
  ChevronDown,
  ChevronUp,
  Crosshair,
  EyeOff,
  Maximize2,
  Star,
  ZoomIn,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OverwatchDetection } from "@/lib/overwatchApi";
import { cn } from "@/lib/utils";

interface CameraStageCardProps {
  cameraId: string;
  cameraName: string;
  accentClass?: string;
  online: boolean;
  width?: number;
  height?: number;
  fps?: number;
  calibrated?: boolean;
  calibrationMethod?: string;
  isMain?: boolean;
  compact?: boolean;
  collapsed?: boolean;
  taskMode?: boolean;
  streamUrl: string;
  liveVideoStream?: MediaStream | null;
  onBindVideo?: (el: HTMLVideoElement | null) => void;
  detections?: OverwatchDetection[];
  onMakeMain?: () => void;
  onToggleCollapse?: () => void;
  onHide?: () => void;
  onCalibrate?: () => void;
  onFeedClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
  onSelectRoi?: (det: OverwatchDetection) => void;
  disableCalibrate?: boolean;
}

export function CameraStageCard({
  cameraId,
  cameraName,
  accentClass = "text-cyan-400",
  online,
  width = 0,
  height = 0,
  fps = 0,
  calibrated = false,
  calibrationMethod,
  isMain = false,
  compact = false,
  collapsed = false,
  taskMode = false,
  streamUrl,
  liveVideoStream = null,
  onBindVideo,
  detections = [],
  onMakeMain,
  onToggleCollapse,
  onHide,
  onCalibrate,
  onFeedClick,
  onSelectRoi,
  disableCalibrate = false,
}: CameraStageCardProps): React.JSX.Element {
  return (
    <Card
      className={cn(
        "overflow-hidden border-white/10 bg-slate-950/90 transition-all",
        isMain && "border-cyan-500/40 ring-1 ring-cyan-500/20"
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Camera className={cn("h-3.5 w-3.5 shrink-0", accentClass)} />
          <CardTitle className="truncate text-xs font-semibold text-slate-100">
            {cameraName}
          </CardTitle>
          {!compact && (
            <span className="hidden font-mono text-[10px] text-slate-500 sm:inline">
              ({cameraId})
            </span>
          )}
          <Badge variant={online ? "sky" : "neutral"} className="px-1.5 py-0 text-[9px]">
            {online ? (width > 0 ? `${width}×${height}` : "LIVE") : "OFFLINE"}
          </Badge>
          {!disableCalibrate && !compact && (
            <Badge
              variant="neutral"
              className={cn(
                "px-1.5 py-0 text-[9px]",
                calibrated
                  ? "border-emerald-500/40 text-emerald-300"
                  : "border-amber-500/40 text-amber-300"
              )}
            >
              {calibrated ? (calibrationMethod === "robot_self_cal" ? "Self-Cal" : "Calibrated") : "Needs Cal"}
            </Badge>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {!isMain && onMakeMain && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onMakeMain}
              title="Promote to Main View"
              className="h-6 gap-1 px-1.5 text-[10px] text-cyan-300 hover:bg-cyan-950/60 cursor-pointer"
            >
              {compact ? <Maximize2 className="h-3 w-3" /> : <><Star className="h-3 w-3" /> Main</>}
            </Button>
          )}
          {!disableCalibrate && onCalibrate && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onCalibrate}
              title="Calibrate camera position"
              className="h-6 px-1.5 text-[10px] text-slate-300 hover:bg-white/10 cursor-pointer"
            >
              <Crosshair className="h-3 w-3" />
            </Button>
          )}
          {onToggleCollapse && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onToggleCollapse}
              title={collapsed ? "Expand feed" : "Collapse feed"}
              className="h-6 px-1.5 text-slate-400 hover:bg-white/10 hover:text-slate-100 cursor-pointer"
            >
              {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
            </Button>
          )}
          {onHide && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onHide}
              title="Hide camera from view"
              className="h-6 px-1.5 text-slate-400 hover:bg-white/10 hover:text-red-300 cursor-pointer"
            >
              <EyeOff className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>

      {!collapsed && (
        <CardContent className="p-0">
          <div
            onClick={(e) => {
              if (compact && onMakeMain && !taskMode) {
                onMakeMain();
              } else if (onFeedClick) {
                onFeedClick(e);
              }
            }}
            className={cn(
              "relative aspect-video w-full overflow-hidden bg-black",
              taskMode ? "cursor-crosshair" : compact && onMakeMain ? "cursor-pointer" : "cursor-default"
            )}
          >
            {onBindVideo && (
              <video
                ref={onBindVideo}
                autoPlay
                playsInline
                muted
                className={cn(
                  "h-full w-full object-contain",
                  liveVideoStream ? "block" : "hidden"
                )}
              />
            )}
            {!liveVideoStream && (
              <img
                src={streamUrl}
                alt={cameraName}
                className="h-full w-full object-contain"
              />
            )}

            {liveVideoStream &&
              detections.map((det, idx) => {
                const bb = det.bbox_norm;
                if (!bb || bb.length !== 4) return null;
                return (
                  <div
                    key={`${cameraId}_box_${idx}`}
                    style={{
                      left: `${bb[0] * 100}%`,
                      top: `${bb[1] * 100}%`,
                      width: `${Math.max(1, (bb[2] - bb[0]) * 100)}%`,
                      height: `${Math.max(1, (bb[3] - bb[1]) * 100)}%`,
                    }}
                    className="pointer-events-none absolute rounded border border-cyan-400/90 bg-cyan-500/10"
                  >
                    <span className="absolute -top-4 left-0 rounded bg-slate-950/90 px-1 py-0.5 font-mono text-[9px] font-semibold text-cyan-200">
                      {det.label} {Math.round((det.confidence ?? 0) * 100)}%
                    </span>
                  </div>
                );
              })}

            <div className="pointer-events-none absolute bottom-1.5 left-1.5 flex items-center gap-1.5">
              {fps > 0 && (
                <span className="rounded bg-black/70 px-1.5 py-0.5 font-mono text-[9px] text-slate-300">
                  {fps.toFixed(0)} fps
                </span>
              )}
              {taskMode && !disableCalibrate && (
                <span className="rounded bg-amber-500/90 px-1.5 py-0.5 text-[9px] font-semibold text-slate-950">
                  Click floor to task PuppyPi
                </span>
              )}
              {compact && !taskMode && (
                <span className="rounded bg-black/70 px-1.5 py-0.5 text-[9px] text-cyan-300">
                  Click to promote
                </span>
              )}
            </div>
          </div>

          {!compact && detections.length > 0 && onSelectRoi && (
            <div className="flex flex-wrap gap-1.5 border-t border-white/10 bg-slate-950/80 px-3 py-2">
              {detections.slice(0, 6).map((det, idx) => (
                <button
                  key={`${cameraId}_chip_${idx}`}
                  type="button"
                  onClick={() => onSelectRoi(det)}
                  className="inline-flex items-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-950/40 px-2 py-0.5 text-[10px] text-cyan-200 hover:bg-cyan-900/60 cursor-pointer"
                >
                  <ZoomIn className="h-2.5 w-2.5" />
                  <span>{det.label}</span>
                  <span className="font-mono text-cyan-400">{Math.round((det.confidence ?? 0) * 100)}%</span>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
