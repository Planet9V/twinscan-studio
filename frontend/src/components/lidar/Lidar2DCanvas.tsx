"use client";

import React, { useEffect, useRef, useState } from "react";
import { Crosshair, Eye, Maximize2, Ruler, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { EquipmentAsset, FocusTarget, LidarFrame, ObjectCluster, SpatialDarkZone } from "@/lib/types";

interface Lidar2DCanvasProps {
  frame: LidarFrame | null;
  equipment: EquipmentAsset[];
  darkZones: SpatialDarkZone[];
  selectedEquipmentId: string | null;
  pendingPin: { x: number; y: number } | null;
  focusTarget: FocusTarget | null;
  onSelectEquipment: (id: string) => void;
  onMapClick: (x: number, y: number, cluster?: ObjectCluster) => void;
}

export function Lidar2DCanvas({
  frame,
  equipment,
  darkZones,
  selectedEquipmentId,
  pendingPin,
  focusTarget,
  onSelectEquipment,
  onMapClick,
}: Lidar2DCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [scalePxPerM, setScalePxPerM] = useState(58);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [colorMode, setColorMode] = useState<"intensity" | "distance">("intensity");
  const [showDarkZones, setShowDarkZones] = useState(true);
  const [toolMode, setToolMode] = useState<"pin" | "ruler">("pin");
  const [rulerPts, setRulerPts] = useState<{ x: number; y: number }[]>([]);
  const [hoverCoord, setHoverCoord] = useState<{ x: number; y: number } | null>(null);

  // Center 2D viewport smoothly on focus target when selected from Focus Queue
  useEffect(() => {
    if (!focusTarget) return;
    setPan({ x: -focusTarget.x * scalePxPerM * 0.6, y: focusTarget.y * scalePxPerM * 0.6 });
  }, [focusTarget, scalePxPerM]);

  const screenToWorld = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2 + pan.x;
    const cy = rect.height / 2 + pan.y;
    return {
      x: (clientX - rect.left - cx) / scalePxPerM,
      y: -(clientY - rect.top - cy) / scalePxPerM,
    };
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
    }

    ctx.save();
    ctx.scale(dpr, dpr);

    ctx.fillStyle = "#0b0d10";
    ctx.fillRect(0, 0, width, height);

    const cx = width / 2 + pan.x;
    const cy = height / 2 + pan.y;
    const toSx = (x: number) => cx + x * scalePxPerM;
    const toSy = (y: number) => cy - y * scalePxPerM;

    // Metric grid & range rings
    ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    ctx.lineWidth = 1;
    for (let m = -10; m <= 10; m += 1) {
      ctx.beginPath();
      ctx.moveTo(toSx(m), 0);
      ctx.lineTo(toSx(m), height);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, toSy(m));
      ctx.lineTo(width, toSy(m));
      ctx.stroke();
    }

    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.fillStyle = "#B4B4BC";
    for (const r of [1, 2, 4, 6, 8]) {
      ctx.strokeStyle = "rgba(56, 189, 248, 0.14)";
      ctx.beginPath();
      ctx.arc(cx, cy, r * scalePxPerM, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillText(`${r}m`, cx + r * scalePxPerM + 4, cy - 4);
    }

    // Spatial Dark Zones (Occlusion Shadows & Unidentified Clusters) + NBV arrows
    if (showDarkZones && darkZones.length > 0) {
      for (const dz of darkZones) {
        if (dz.polygon.length >= 3) {
          ctx.beginPath();
          dz.polygon.forEach(([px, py], i) => {
            if (i === 0) ctx.moveTo(toSx(px), toSy(py));
            else ctx.lineTo(toSx(px), toSy(py));
          });
          ctx.closePath();
          ctx.fillStyle =
            dz.kind === "occlusion_shadow" ? "rgba(239, 68, 68, 0.14)" : "rgba(245, 158, 11, 0.14)";
          ctx.fill();
          ctx.setLineDash([5, 3]);
          ctx.strokeStyle = dz.kind === "occlusion_shadow" ? "#ef4444" : "#f59e0b";
          ctx.lineWidth = 1.4;
          ctx.stroke();
          ctx.setLineDash([]);
        }
        // NBV vantage beacon & direction line
        const nx = toSx(dz.nbv_x);
        const ny = toSy(dz.nbv_y);
        const tx = toSx(dz.centroid_x);
        const ty = toSy(dz.centroid_y);
        ctx.strokeStyle = "rgba(245, 158, 11, 0.65)";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(nx, ny);
        ctx.lineTo(tx, ty);
        ctx.stroke();
        ctx.fillStyle = "#f59e0b";
        ctx.beginPath();
        ctx.arc(nx, ny, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillText(`NBV P${dz.priority_score}`, nx + 6, ny - 4);
      }
    }

    // Extracted RANSAC architectural walls
    if (frame?.walls) {
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2.5;
      for (const w of frame.walls) {
        ctx.beginPath();
        ctx.moveTo(toSx(w.x1), toSy(w.y1));
        ctx.lineTo(toSx(w.x2), toSy(w.y2));
        ctx.stroke();
        const mx = (toSx(w.x1) + toSx(w.x2)) / 2;
        const my = (toSy(w.y1) + toSy(w.y2)) / 2;
        ctx.fillStyle = "#7dd3fc";
        ctx.fillText(`${w.length_m.toFixed(1)}m`, mx + 4, my - 4);
      }
    }

    // Live LD19 points
    if (frame?.points) {
      for (const [x, y, intensity, dist] of frame.points) {
        const t =
          colorMode === "intensity"
            ? Math.max(0, Math.min(1, intensity / 255))
            : Math.max(0, Math.min(1, 1 - dist / 8));
        const r = Math.round(56 + t * (224 - 56));
        const g = Math.round(189 + t * (90 - 189));
        const b = Math.round(248 + t * (16 - 248));
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(toSx(x) - 1.5, toSy(y) - 1.5, 3, 3);
      }
    }

    // Physical change anomalies
    if (frame?.anomalies) {
      for (const a of frame.anomalies) {
        const ax = toSx(a.centroid_x);
        const ay = toSy(a.centroid_y);
        ctx.beginPath();
        ctx.arc(ax, ay, Math.max(16, Math.sqrt(a.area_m2) * scalePxPerM), 0, Math.PI * 2);
        ctx.fillStyle = "rgba(239, 68, 68, 0.16)";
        ctx.fill();
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = "#ef4444";
        ctx.fillText(`ANOMALY (${a.severity.toUpperCase()})`, ax + 14, ay - 6);
      }
    }

    // Placed equipment twins with Completeness color coding
    for (const eq of equipment) {
      const ex = toSx(eq.x);
      const ey = toSy(eq.y);
      const bw = Math.max(14, (eq.width_m || 0.7) * scalePxPerM);
      const bh = Math.max(14, (eq.depth_m || 0.7) * scalePxPerM);
      const isSelected = eq.id === selectedEquipmentId;
      const status = eq.completeness?.status ?? "INCOMPLETE";
      const stroke = isSelected
        ? "#ffffff"
        : status === "DARK"
        ? "#ef4444"
        : status === "INCOMPLETE"
        ? "#f59e0b"
        : "#E05A10";

      ctx.save();
      ctx.translate(ex, ey);
      ctx.rotate((-eq.yaw_deg * Math.PI) / 180);
      ctx.fillStyle = isSelected ? "rgba(56, 189, 248, 0.28)" : "rgba(224, 90, 16, 0.18)";
      ctx.strokeStyle = stroke;
      ctx.lineWidth = isSelected ? 2.4 : 1.7;
      ctx.fillRect(-bw / 2, -bh / 2, bw, bh);
      ctx.strokeRect(-bw / 2, -bh / 2, bw, bh);
      ctx.restore();

      const pct = eq.completeness?.completeness_pct ?? 50;
      ctx.fillStyle = "#ffffff";
      ctx.fillText(`${eq.name} [${pct}%]`, ex + bw / 2 + 5, ey - 2);
      ctx.fillStyle = "#B4B4BC";
      ctx.fillText(`${eq.manufacturer} ${eq.model_number}`, ex + bw / 2 + 5, ey + 10);
    }

    // Active focus target reticle
    if (focusTarget) {
      const fx = toSx(focusTarget.x);
      const fy = toSy(focusTarget.y);
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.arc(fx, fy, 18, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Pending pin reticle
    if (pendingPin) {
      const px = toSx(pendingPin.x);
      const py = toSy(pendingPin.y);
      ctx.strokeStyle = "#E05A10";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(px, py, 10, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Ruler overlay
    if (rulerPts.length === 2) {
      const [a, b] = rulerPts;
      ctx.strokeStyle = "#7dd3fc";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(toSx(a.x), toSy(a.y));
      ctx.lineTo(toSx(b.x), toSy(b.y));
      ctx.stroke();
      ctx.setLineDash([]);
      const dist = Math.hypot(b.x - a.x, b.y - a.y);
      const mx = (toSx(a.x) + toSx(b.x)) / 2;
      const my = (toSy(a.y) + toSy(b.y)) / 2;
      ctx.fillStyle = "#0E1013";
      ctx.fillRect(mx - 28, my - 16, 62, 18);
      ctx.fillStyle = "#7dd3fc";
      ctx.fillText(`${dist.toFixed(2)} m`, mx - 22, my - 4);
    }

    // Moving object tracks (Kalman velocity vectors & fading comet trails)
    const movingObjects = Array.isArray(frame?.moving_objects) ? frame.moving_objects : [];
    const pulse = 0.5 + 0.5 * Math.sin(Date.now() / 220);
    for (const track of movingObjects) {
      const tx = toSx(track.x);
      const ty = toSy(track.y);
      const trail = Array.isArray(track.trail) ? track.trail : [];

      // Fading comet trail
      if (trail.length >= 2) {
        for (let i = 1; i < trail.length; i++) {
          const alpha = (i / trail.length) * (track.is_moving ? 0.85 : 0.3);
          ctx.strokeStyle = track.is_moving
            ? `rgba(16, 185, 129, ${alpha.toFixed(2)})`
            : `rgba(180, 180, 188, ${alpha.toFixed(2)})`;
          ctx.lineWidth = track.is_moving ? 2.4 : 1.2;
          ctx.beginPath();
          ctx.moveTo(toSx(trail[i - 1][0]), toSy(trail[i - 1][1]));
          ctx.lineTo(toSx(trail[i][0]), toSy(trail[i][1]));
          ctx.stroke();
        }
      }

      if (track.is_moving) {
        // Pulsing glowing Eigenia Orange / Emerald ring
        const outerR = 11 + pulse * 6;
        ctx.beginPath();
        ctx.arc(tx, ty, outerR, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(224, 90, 16, ${(0.35 + pulse * 0.45).toFixed(2)})`;
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(tx, ty, 6.5, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(16, 185, 129, 0.32)";
        ctx.fill();
        ctx.strokeStyle = "#10b981";
        ctx.lineWidth = 2;
        ctx.stroke();

        // Velocity vector arrow (vx, vy scaled for visibility)
        const vecScale = 0.9;
        const ex = toSx(track.x + track.vx * vecScale);
        const ey = toSy(track.y + track.vy * vecScale);
        ctx.strokeStyle = "#E05A10";
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(ex, ey);
        ctx.stroke();

        const ang = Math.atan2(ey - ty, ex - tx);
        const headLen = 7;
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(ex - headLen * Math.cos(ang - Math.PI / 6), ey - headLen * Math.sin(ang - Math.PI / 6));
        ctx.lineTo(ex - headLen * Math.cos(ang + Math.PI / 6), ey - headLen * Math.sin(ang + Math.PI / 6));
        ctx.closePath();
        ctx.fillStyle = "#E05A10";
        ctx.fill();

        // Crisp speed label
        ctx.fillStyle = "#10b981";
        ctx.fillText(`T#${track.track_id} · ${Number(track.speed_mps ?? 0).toFixed(2)} m/s`, tx + 14, ty - 6);
      } else {
        ctx.beginPath();
        ctx.arc(tx, ty, 4, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(180, 180, 188, 0.55)";
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
    }

    // Live PuppyPi robot heading arrow + 65° dashed Camera FOV Cone pointing UP along +Y (FRONT ↑)
    const pose = frame?.robot_pose;
    const rx = toSx(pose?.x ?? 0);
    const ry = toSy(pose?.y ?? 0);
    // +Y (canvas -PI/2) is PuppyPi Camera Forward when yaw_deg = 0
    const yawRad = ((pose?.yaw_deg ?? 0) * Math.PI) / 180;
    const fovHalf = (32.5 * Math.PI) / 180; // 65° full horizontal FOV
    const fovReachPx = 2.2 * scalePxPerM;

    ctx.save();
    ctx.translate(rx, ry);
    ctx.rotate(-Math.PI / 2 - yawRad);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, fovReachPx, -fovHalf, fovHalf);
    ctx.closePath();
    ctx.fillStyle = pose?.live ? "rgba(224, 90, 16, 0.14)" : "rgba(224, 90, 16, 0.08)";
    ctx.fill();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = "#E05A10";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);

    // Forward direction arrow along +Y (FRONT ↑)
    ctx.strokeStyle = "#E05A10";
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(28, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(33, 0);
    ctx.lineTo(24, -5);
    ctx.lineTo(24, 5);
    ctx.closePath();
    ctx.fillStyle = "#E05A10";
    ctx.fill();
    ctx.restore();

    // Label "FRONT ↑" cleanly above origin
    ctx.fillStyle = "#E05A10";
    ctx.font = "bold 10px 'JetBrains Mono', monospace";
    ctx.fillText("FRONT ↑", rx - 22, ry - 38);

    // LiDAR / PuppyPi origin marker
    ctx.beginPath();
    ctx.arc(rx, ry, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#E05A10";
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Crisp FRONT / BACK / LEFT / RIGHT edge compass labels (+ live cardinal distances if present)
    const card = frame?.cardinal_m;
    const fmtCard = (val?: number | null) =>
      val != null && Number.isFinite(val) ? ` ${val.toFixed(2)}m` : "";
    const drawEdgeBadge = (text: string, x: number, y: number, accent: string) => {
      ctx.font = "bold 10px 'JetBrains Mono', monospace";
      const tw = ctx.measureText(text).width;
      ctx.fillStyle = "rgba(14, 16, 19, 0.85)";
      ctx.fillRect(x - tw / 2 - 6, y - 9, tw + 12, 16);
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1;
      ctx.strokeRect(x - tw / 2 - 6, y - 9, tw + 12, 16);
      ctx.fillStyle = accent;
      ctx.fillText(text, x - tw / 2, y + 3);
    };

    drawEdgeBadge(`FRONT ↑${fmtCard(card?.front)}`, width / 2, 18, "#E05A10");
    drawEdgeBadge(`BACK ↓${fmtCard(card?.back)}`, width / 2, height - 16, "#B4B4BC");
    drawEdgeBadge(`← LEFT${fmtCard(card?.left)}`, 54, height / 2, "#38bdf8");
    drawEdgeBadge(`RIGHT →${fmtCard(card?.right)}`, width - 58, height / 2, "#38bdf8");

    ctx.restore();
  }, [frame, equipment, darkZones, selectedEquipmentId, pendingPin, focusTarget, scalePxPerM, pan, colorMode, showDarkZones, rulerPts]);

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pt = screenToWorld(e.clientX, e.clientY);
    if (toolMode === "ruler") {
      setRulerPts((prev) => (prev.length >= 2 ? [pt] : [...prev, pt]));
      return;
    }
    const hitEq = equipment.find((eq) => Math.hypot(eq.x - pt.x, eq.y - pt.y) < 0.45);
    if (hitEq) {
      onSelectEquipment(hitEq.id);
      return;
    }
    const hitCluster = frame?.clusters?.find(
      (c) => Math.hypot(c.centroid_x - pt.x, c.centroid_y - pt.y) < 0.55
    );
    if (hitCluster) {
      onMapClick(hitCluster.centroid_x, hitCluster.centroid_y, hitCluster);
      return;
    }
    onMapClick(pt.x, pt.y);
  };

  return (
    <div className="relative flex h-[560px] w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell px-3 py-2">
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={toolMode === "pin" ? "default" : "secondary"}
            onClick={() => {
              setToolMode("pin");
              setRulerPts([]);
            }}
          >
            <Crosshair className="h-3.5 w-3.5" /> Click-to-Place
          </Button>
          <Button
            size="sm"
            variant={toolMode === "ruler" ? "sky" : "secondary"}
            onClick={() => {
              setToolMode("ruler");
              setRulerPts([]);
            }}
          >
            <Ruler className="h-3.5 w-3.5" /> Measure
          </Button>
          <Button
            size="sm"
            variant={showDarkZones ? "sky" : "outline"}
            onClick={() => setShowDarkZones((v) => !v)}
          >
            <Eye className="h-3.5 w-3.5" /> Dark Zones ({darkZones.length})
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setColorMode((m) => (m === "intensity" ? "distance" : "intensity"))}
          >
            {colorMode === "intensity" ? "Intensity" : "Range"}
          </Button>
        </div>

        <div className="flex items-center gap-1.5">
          {hoverCoord && (
            <Badge variant="neutral">
              X {hoverCoord.x.toFixed(2)}m · Y {hoverCoord.y.toFixed(2)}m
            </Badge>
          )}
          <Button size="icon" variant="secondary" onClick={() => setScalePxPerM((s) => Math.min(160, s + 12))}>
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
          <Button size="icon" variant="secondary" onClick={() => setScalePxPerM((s) => Math.max(24, s - 12))}>
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="secondary"
            onClick={() => {
              setScalePxPerM(58);
              setPan({ x: 0, y: 0 });
            }}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        className="h-full w-full cursor-crosshair"
        onClick={handleClick}
        onMouseMove={(e) => setHoverCoord(screenToWorld(e.clientX, e.clientY))}
        onWheel={(e) => {
          e.preventDefault();
          setScalePxPerM((s) => Math.max(24, Math.min(180, s - Math.sign(e.deltaY) * 6)));
        }}
      />

      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-2">
        <Badge variant="sky">Walls: {frame?.walls?.length ?? 0}</Badge>
        <Badge variant="amber">Dark Zones: {darkZones.length}</Badge>
        <Badge variant="default">Assets: {equipment.length}</Badge>
        {(frame?.moving_objects?.filter((t) => t.is_moving).length ?? 0) > 0 && (
          <Badge variant="sky">
            Moving: {frame?.moving_objects?.filter((t) => t.is_moving).length}
          </Badge>
        )}
        {(frame?.anomalies?.length ?? 0) > 0 && (
          <Badge variant="fault">Anomalies: {frame?.anomalies?.length}</Badge>
        )}
      </div>
    </div>
  );
}
