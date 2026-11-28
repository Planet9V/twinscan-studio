"use client";

import React, { useRef, useState } from "react";
import {
  Box,
  Download,
  ImagePlus,
  Layers,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  Custom3DShape,
  CustomShapeKind,
  EnclosureConfig,
  EnclosureStyle,
  StlExportStats,
} from "@/lib/microbitApi";
import { cn } from "@/lib/utils";

interface EnclosureModelingPanelProps {
  enclosure: EnclosureConfig;
  customShapes: Custom3DShape[];
  stlStats: StlExportStats | null;
  busy: string | null;
  onUpdateEnclosure: (next: EnclosureConfig) => void;
  onAutoFit: () => void;
  onExportStl: () => void;
  onAddShape: (kind: CustomShapeKind, sizeMm: [number, number, number], name: string) => void;
  onRemoveShape: (shapeId: string) => void;
  onCreatePhotoShape: (payload: {
    name: string;
    image_b64: string;
    width_mm: number;
    length_mm: number;
    height_mm: number;
    invert: boolean;
  }) => void;
}

const SHELL_STYLES: Array<{ id: EnclosureStyle; label: string }> = [
  { id: "box_with_lid", label: "Box + Lid" },
  { id: "snap_fit_case", label: "Snap-Fit" },
  { id: "open_tray_cradle", label: "Open Tray" },
  { id: "desk_stand", label: "Desk Stand" },
  { id: "mounting_plate_bracket", label: "Mount Plate" },
];

export function EnclosureModelingPanel({
  enclosure,
  customShapes,
  stlStats,
  busy,
  onUpdateEnclosure,
  onAutoFit,
  onExportStl,
  onAddShape,
  onRemoveShape,
  onCreatePhotoShape,
}: EnclosureModelingPanelProps): React.JSX.Element {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [shapeW, setShapeW] = useState(30);
  const [shapeL, setShapeL] = useState(20);
  const [shapeH, setShapeH] = useState(12);
  const [photoName, setPhotoName] = useState("Custom Photo Relief");
  const [photoInvert, setPhotoInvert] = useState(false);

  const patch = (partial: Partial<EnclosureConfig>) => {
    onUpdateEnclosure({ ...enclosure, ...partial });
  };

  const handlePhotoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = typeof reader.result === "string" ? reader.result : "";
      if (!b64) return;
      onCreatePhotoShape({
        name: photoName.trim() || file.name.replace(/\.[^.]+$/, ""),
        image_b64: b64,
        width_mm: shapeW,
        length_mm: shapeL,
        height_mm: Math.max(4, Math.min(40, shapeH)),
        invert: photoInvert,
      });
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  return (
    <div className="space-y-3 rounded-lg border border-white/10 bg-eigenia-obsidian p-3">
      {/* Header + Auto-Fit + Export STL */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Box className="h-4 w-4 text-eigenia-orange" />
          <span className="font-mono text-xs font-bold uppercase tracking-wider text-white">
            3D Printer Enclosure &amp; Shape Modeler
          </span>
          <Badge variant={enclosure.enabled ? "sky" : "neutral"}>
            {enclosure.enabled
              ? `${enclosure.width_mm}×${enclosure.length_mm}×${enclosure.height_mm} mm`
              : "OFF"}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="sm"
            variant="secondary"
            disabled={busy !== null}
            onClick={onAutoFit}
          >
            {busy === "autofit" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5 text-eigenia-orange" />
            )}
            Auto-Fit Around Parts
          </Button>
          <Button
            size="sm"
            variant={enclosure.enabled ? "sky" : "outline"}
            onClick={() => patch({ enabled: !enclosure.enabled })}
          >
            <Layers className="h-3.5 w-3.5" />
            {enclosure.enabled ? "Hide Shell" : "Show Shell"}
          </Button>
          <Button
            size="sm"
            variant="default"
            disabled={busy !== null}
            onClick={onExportStl}
          >
            {busy === "stl" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Export 3D-Print .STL
          </Button>
        </div>
      </div>

      {/* Shell Style Pills */}
      <div className="flex flex-wrap gap-1">
        {SHELL_STYLES.map((st) => (
          <button
            key={st.id}
            type="button"
            onClick={() => patch({ enabled: true, style: st.id })}
            className={cn(
              "rounded border px-2 py-1 font-mono text-[10px] transition",
              enclosure.style === st.id && enclosure.enabled
                ? "border-eigenia-orange bg-eigenia-orange/20 text-eigenia-orange"
                : "border-white/10 bg-eigenia-shell text-eigenia-muted hover:text-white"
            )}
          >
            {st.label}
          </button>
        ))}
      </div>

      {/* Parametric Millimeter Dimensions & Tolerances */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: "Width (mm)", key: "width_mm" as const, min: 24, max: 320, step: 1 },
          { label: "Length (mm)", key: "length_mm" as const, min: 24, max: 320, step: 1 },
          { label: "Height (mm)", key: "height_mm" as const, min: 8, max: 180, step: 1 },
          { label: "Wall (mm)", key: "wall_mm" as const, min: 1.2, max: 6.0, step: 0.2 },
          { label: "Fit Tol (mm)", key: "clearance_mm" as const, min: 0.1, max: 1.0, step: 0.05 },
          { label: "Explode Lid", key: "lid_explode_mm" as const, min: 0, max: 60, step: 2 },
        ].map((ctrl) => (
          <label key={ctrl.key} className="space-y-1 font-mono text-[10px] text-eigenia-muted">
            <span className="flex justify-between">
              <span>{ctrl.label}</span>
              <span className="text-white">{enclosure[ctrl.key]}</span>
            </span>
            <input
              type="range"
              min={ctrl.min}
              max={ctrl.max}
              step={ctrl.step}
              value={enclosure[ctrl.key]}
              onChange={(e) => patch({ enabled: true, [ctrl.key]: Number(e.target.value) })}
              className="w-full accent-eigenia-orange"
            />
          </label>
        ))}
      </div>

      {/* Feature Toggles */}
      <div className="flex flex-wrap gap-2 font-mono text-[10px]">
        {(
          [
            { key: "include_lid", label: "Snap-Fit Lid" },
            { key: "include_standoffs", label: "PCB Standoff Bosses" },
            { key: "include_vent_slots", label: "Cooling Vents" },
            { key: "include_cutouts", label: "Sensor / Port Cutouts" },
          ] as const
        ).map((tog) => (
          <button
            key={tog.key}
            type="button"
            onClick={() => patch({ enabled: true, [tog.key]: !enclosure[tog.key] })}
            className={cn(
              "rounded border px-2 py-1 transition",
              enclosure[tog.key]
                ? "border-eigenia-sky/60 bg-eigenia-sky/15 text-eigenia-sky"
                : "border-white/10 bg-eigenia-shell text-eigenia-muted"
            )}
          >
            {enclosure[tog.key] ? "✓ " : "+ "}
            {tog.label}
          </button>
        ))}
      </div>

      {/* Custom 3D Shapes & Photo-to-3D Shape Builder */}
      <div className="grid grid-cols-1 gap-2 border-t border-white/10 pt-2.5 lg:grid-cols-2">
        <div className="space-y-1.5">
          <div className="font-mono text-[10px] font-semibold uppercase text-eigenia-muted">
            Add 3D-Printable Shape (W × L × H mm)
          </div>
          <div className="flex items-center gap-1.5">
            <Input
              type="number"
              value={shapeW}
              onChange={(e) => setShapeW(Number(e.target.value) || 20)}
              className="h-7 w-16 font-mono text-xs"
              title="Width mm"
            />
            <span className="font-mono text-[10px] text-eigenia-muted">×</span>
            <Input
              type="number"
              value={shapeL}
              onChange={(e) => setShapeL(Number(e.target.value) || 20)}
              className="h-7 w-16 font-mono text-xs"
              title="Length mm"
            />
            <span className="font-mono text-[10px] text-eigenia-muted">×</span>
            <Input
              type="number"
              value={shapeH}
              onChange={(e) => setShapeH(Number(e.target.value) || 10)}
              className="h-7 w-16 font-mono text-xs"
              title="Height mm"
            />
            <span className="font-mono text-[10px] text-eigenia-muted">mm</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {(
              [
                { kind: "box", label: "Block" },
                { kind: "cylinder", label: "Cylinder" },
                { kind: "bracket_l", label: "L-Bracket" },
                { kind: "standoff_post", label: "Standoff" },
              ] as Array<{ kind: CustomShapeKind; label: string }>
            ).map((btn) => (
              <Button
                key={btn.kind}
                size="sm"
                variant="secondary"
                className="h-6 px-2 text-[10px]"
                onClick={() => onAddShape(btn.kind, [shapeW, shapeL, shapeH], btn.label)}
              >
                <Plus className="h-3 w-3" /> {btn.label}
              </Button>
            ))}
          </div>
        </div>

        {/* Photo -> 3D Printable Relief Shape */}
        <div className="space-y-1.5">
          <div className="font-mono text-[10px] font-semibold uppercase text-eigenia-muted">
            Build 3D Shape From Picture (Heightmap STL)
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Input
              value={photoName}
              onChange={(e) => setPhotoName(e.target.value)}
              placeholder="Shape name..."
              className="h-7 flex-1 min-w-[120px] text-xs"
            />
            <button
              type="button"
              onClick={() => setPhotoInvert((v) => !v)}
              className={cn(
                "rounded border px-2 py-1 font-mono text-[10px]",
                photoInvert
                  ? "border-eigenia-orange text-eigenia-orange"
                  : "border-white/10 text-eigenia-muted"
              )}
            >
              {photoInvert ? "Invert: ON" : "Invert: OFF"}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handlePhotoSelect}
            />
            <Button
              size="sm"
              variant="sky"
              className="h-7 text-[10px]"
              disabled={busy !== null}
              onClick={() => fileRef.current?.click()}
            >
              {busy === "photo" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <ImagePlus className="h-3 w-3" />
              )}
              Photo → 3D
            </Button>
          </div>
          {customShapes.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {customShapes.map((s) => (
                <span
                  key={s.id}
                  className="inline-flex items-center gap-1 rounded border border-white/10 bg-eigenia-shell px-2 py-0.5 font-mono text-[10px] text-white"
                >
                  {s.name} ({s.size_mm[0]}×{s.size_mm[1]}×{s.size_mm[2]})
                  <button
                    type="button"
                    onClick={() => onRemoveShape(s.id)}
                    className="text-eigenia-muted hover:text-eigenia-fault"
                  >
                    <Trash2 className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Slicer Printability Telemetry */}
      {stlStats && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-eigenia-sky/30 bg-eigenia-sky/10 px-2.5 py-1.5 font-mono text-[10px] text-eigenia-sky">
          <Badge variant="sky">{stlStats.is_watertight ? "WATERTIGHT" : "MESH READY"}</Badge>
          <span>{stlStats.triangle_count.toLocaleString()} tris</span>
          <span>· {stlStats.volume_cm3} cm³</span>
          <span>· ~{stlStats.estimated_filament_g}g PLA</span>
          <span>· ~{stlStats.estimated_print_min} min print</span>
          <span>
            · {stlStats.bounding_box_mm[0]}×{stlStats.bounding_box_mm[1]}×{stlStats.bounding_box_mm[2]} mm
          </span>
        </div>
      )}
    </div>
  );
}
