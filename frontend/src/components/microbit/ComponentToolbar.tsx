"use client";

import React, { useMemo, useState } from "react";
import { GripVertical, HelpCircle, Plus, Search, Trash2, Move } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  BoardId,
  MicrobitAccessorySpec,
  MicrobitAttachment,
  MicrobitPinSpec,
} from "@/lib/microbitApi";
import { cn } from "@/lib/utils";

/** Crisp blueprint-style SVG hardware icon for each physical board/sensor module. */
export function HardwarePartSvgIcon({
  kind,
  color = "#38bdf8",
  className = "h-10 w-12",
}: {
  kind?: string;
  color?: string;
  className?: string;
}): React.JSX.Element {
  switch (kind) {
    case "temp_hum":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="4" y="6" width="56" height="32" rx="4" fill="#0f172a" stroke={color} strokeWidth="2" />
          <circle cx="11" cy="22" r="3.5" stroke="#94a3b8" strokeWidth="1.5" />
          <circle cx="53" cy="22" r="3.5" stroke="#94a3b8" strokeWidth="1.5" />
          <rect x="22" y="13" width="16" height="18" rx="2" fill="#e2e8f0" stroke="#38bdf8" strokeWidth="1.5" />
          <line x1="25" y1="18" x2="35" y2="18" stroke="#0284c7" strokeWidth="1.5" />
          <line x1="25" y1="22" x2="35" y2="22" stroke="#0284c7" strokeWidth="1.5" />
          <line x1="25" y1="26" x2="35" y2="26" stroke="#0284c7" strokeWidth="1.5" />
          <rect x="41" y="16" width="6" height="12" rx="1" fill="#f8fafc" />
        </svg>
      );
    case "touch_pad":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="4" y="8" width="56" height="28" rx="4" fill="#0f172a" stroke={color} strokeWidth="2" />
          <circle cx="11" cy="22" r="3.2" stroke="#94a3b8" strokeWidth="1.5" />
          <circle cx="53" cy="22" r="3.2" stroke="#94a3b8" strokeWidth="1.5" />
          <circle cx="30" cy="22" r="9.5" fill="#f59e0b" fillOpacity="0.22" stroke="#f59e0b" strokeWidth="2" />
          <circle cx="30" cy="22" r="4.5" stroke="#fbbf24" strokeWidth="1.5" />
          <circle cx="44" cy="17" r="2" fill="#22c55e" />
        </svg>
      );
    case "ultrasonic":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="4" y="8" width="56" height="28" rx="4" fill="#064e3b" stroke={color} strokeWidth="2" />
          <circle cx="20" cy="22" r="9.5" fill="#cbd5e1" stroke="#10b981" strokeWidth="2.2" />
          <circle cx="20" cy="22" r="5" fill="#0f172a" />
          <circle cx="44" cy="22" r="9.5" fill="#cbd5e1" stroke="#10b981" strokeWidth="2.2" />
          <circle cx="44" cy="22" r="5" fill="#0f172a" />
          <circle cx="32" cy="13" r="2" fill="#94a3b8" />
        </svg>
      );
    case "led_matrix":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="3" y="6" width="58" height="32" rx="3" fill="#0f172a" stroke={color} strokeWidth="2" />
          <rect x="7" y="10" width="23" height="24" rx="1.5" fill="#1e293b" stroke="#475569" strokeWidth="1" />
          <rect x="34" y="10" width="23" height="24" rx="1.5" fill="#1e293b" stroke="#475569" strokeWidth="1" />
          {[0, 1, 2, 3].map((r) =>
            [0, 1, 2, 3].map((c) => (
              <React.Fragment key={`${r}-${c}`}>
                <circle cx={11 + c * 5} cy={14 + r * 5} r="1.4" fill="#ef4444" />
                <circle cx={38 + c * 5} cy={14 + r * 5} r="1.4" fill="#ef4444" />
              </React.Fragment>
            ))
          )}
        </svg>
      );
    case "lidar":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="14" y="6" width="36" height="32" rx="4" fill="#0f172a" stroke={color} strokeWidth="2" />
          <circle cx="32" cy="22" r="11" fill="#1e293b" stroke="#22d3ee" strokeWidth="2" />
          <circle cx="32" cy="22" r="5" fill="#06b6d4" fillOpacity="0.4" />
          <line x1="32" y1="22" x2="41" y2="15" stroke="#22d3ee" strokeWidth="1.8" />
        </svg>
      );
    case "ai_box":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="8" y="6" width="48" height="32" rx="6" fill="#1e1b4b" stroke={color} strokeWidth="2" />
          <circle cx="24" cy="22" r="8" stroke="#a78bfa" strokeWidth="1.5" strokeDasharray="2 2" />
          <circle cx="24" cy="22" r="3" fill="#c4b5fd" />
          <rect x="38" y="14" width="12" height="16" rx="2" fill="#312e81" stroke="#8b5cf6" strokeWidth="1.2" />
          <circle cx="44" cy="19" r="1.5" fill="#22d3ee" />
          <circle cx="44" cy="25" r="1.5" fill="#22d3ee" />
        </svg>
      );
    case "servo":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="14" y="10" width="34" height="24" rx="3" fill="#1d4ed8" stroke={color} strokeWidth="2" />
          <rect x="8" y="16" width="6" height="12" rx="1" fill="#1e40af" />
          <rect x="48" y="16" width="6" height="12" rx="1" fill="#1e40af" />
          <circle cx="24" cy="22" r="5" fill="#f8fafc" stroke="#94a3b8" strokeWidth="1.5" />
          <rect x="22" y="19" width="22" height="6" rx="3" fill="#f8fafc" stroke="#cbd5e1" strokeWidth="1.2" />
        </svg>
      );
    case "neopixel":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="4" y="14" width="56" height="16" rx="3" fill="#0f172a" stroke={color} strokeWidth="2" />
          {["#ef4444", "#f97316", "#facc15", "#22c55e", "#06b6d4", "#3b82f6", "#a855f7"].map((c, i) => (
            <rect key={c} x={8 + i * 7.2} y="18" width="5" height="8" rx="1" fill={c} />
          ))}
        </svg>
      );
    case "speaker":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <circle cx="32" cy="22" r="16" fill="#0f172a" stroke={color} strokeWidth="2" />
          <circle cx="32" cy="22" r="11" stroke="#475569" strokeWidth="1.5" />
          <circle cx="32" cy="22" r="5" fill={color} fillOpacity="0.5" stroke={color} strokeWidth="1.5" />
        </svg>
      );
    case "oled":
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="10" y="6" width="44" height="32" rx="3" fill="#0f172a" stroke={color} strokeWidth="2" />
          <rect x="14" y="12" width="36" height="20" rx="1.5" fill="#020617" stroke="#22d3ee" strokeWidth="1.5" />
          <line x1="18" y1="18" x2="40" y2="18" stroke="#38bdf8" strokeWidth="1.8" />
          <line x1="18" y1="24" x2="32" y2="24" stroke="#38bdf8" strokeWidth="1.5" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 64 44" className={className} fill="none">
          <rect x="8" y="8" width="48" height="28" rx="4" fill="#0f172a" stroke={color} strokeWidth="2" />
          <rect x="22" y="15" width="20" height="14" rx="2" fill="#1e293b" stroke="#94a3b8" strokeWidth="1.5" />
          <circle cx="14" cy="14" r="2" fill="#facc15" />
          <circle cx="50" cy="14" r="2" fill="#facc15" />
          <circle cx="14" cy="30" r="2" fill="#facc15" />
          <circle cx="50" cy="30" r="2" fill="#facc15" />
        </svg>
      );
  }
}

interface ComponentToolbarProps {
  boardId: BoardId;
  accessories: MicrobitAccessorySpec[];
  attachments: MicrobitAttachment[];
  pins: MicrobitPinSpec[];
  selectedAttachmentId: string | null;
  onAddAccessory: (acc: MicrobitAccessorySpec) => void;
  onSelectAttachment: (attId: string | null) => void;
  onRemoveAttachment: (attId: string) => void;
  onChangePin: (attId: string, pin: string) => void;
  onShowInfo: (accId: string | null) => void;
  infoAccId: string | null;
}

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "hiwonder_kit", label: "Hiwonder Kit" },
  { id: "robotics", label: "Robotics" },
  { id: "actuator", label: "Actuators" },
  { id: "display", label: "Displays" },
  { id: "audio", label: "Audio" },
];

export function ComponentToolbar({
  boardId,
  accessories,
  attachments,
  pins,
  selectedAttachmentId,
  onAddAccessory,
  onSelectAttachment,
  onRemoveAttachment,
  onChangePin,
  onShowInfo,
  infoAccId,
}: ComponentToolbarProps): React.JSX.Element {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [subTab, setSubTab] = useState<"library" | "placed">("library");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return accessories.filter((a) => {
      if (category !== "all" && a.category !== category) return false;
      if (!q) return true;
      return (
        a.name.toLowerCase().includes(q) ||
        (a.summary || "").toLowerCase().includes(q) ||
        (a.ic || "").toLowerCase().includes(q) ||
        (a.vendor || "").toLowerCase().includes(q)
      );
    });
  }, [accessories, category, search]);

  return (
    <div className="flex flex-col gap-2.5">
      {/* Mode switcher: Visual Library vs Placed Parts */}
      <div className="grid grid-cols-2 gap-1 rounded-md border border-white/10 bg-eigenia-obsidian p-1">
        <button
          type="button"
          onClick={() => setSubTab("library")}
          className={cn(
            "rounded px-2 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider transition",
            subTab === "library"
              ? "bg-eigenia-orange text-black"
              : "text-eigenia-muted hover:text-white"
          )}
        >
          Part Library ({accessories.length})
        </button>
        <button
          type="button"
          onClick={() => setSubTab("placed")}
          className={cn(
            "rounded px-2 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider transition",
            subTab === "placed"
              ? "bg-eigenia-sky text-black"
              : "text-eigenia-muted hover:text-white"
          )}
        >
          On Canvas ({attachments.length})
        </button>
      </div>

      {subTab === "library" ? (
        <div className="space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Hiwonder, I2C, servo..."
              className="h-7 pl-8 text-xs"
            />
          </div>

          <div className="flex flex-wrap gap-1">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => setCategory(cat.id)}
                className={cn(
                  "rounded border px-2 py-0.5 font-mono text-[10px] transition",
                  category === cat.id
                    ? "border-eigenia-orange bg-eigenia-orange/20 text-eigenia-orange"
                    : "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:text-white"
                )}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="max-h-[460px] space-y-1.5 overflow-y-auto pr-1">
            {filtered.map((acc) => {
              const dims = acc.dimensions_mm;
              const dimText = dims ? `${dims[0]}×${dims[1]}×${dims[2]} mm` : "Metric 3D";
              const isExpanded = infoAccId === acc.id;
              return (
                <div
                  key={acc.id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/plain", acc.id);
                    e.dataTransfer.effectAllowed = "copy";
                  }}
                  className="group rounded-lg border border-white/10 bg-eigenia-obsidian p-2 transition hover:border-eigenia-orange/60"
                >
                  <div className="flex items-start gap-2">
                    <div className="flex shrink-0 flex-col items-center gap-1 rounded border border-white/10 bg-eigenia-shell p-1">
                      <HardwarePartSvgIcon kind={acc.svg_icon_kind} color={acc.color_hex} className="h-9 w-12" />
                      <span className="font-mono text-[8px] text-eigenia-muted">{dimText}</span>
                    </div>

                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-start justify-between gap-1">
                        <div className="flex items-center gap-1 min-w-0">
                          <GripVertical className="h-3 w-3 shrink-0 text-eigenia-muted" />
                          <span className="truncate text-[11px] font-semibold text-white">
                            {acc.name}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => onShowInfo(isExpanded ? null : acc.id)}
                          className="shrink-0 text-eigenia-muted hover:text-eigenia-sky"
                          title="Specs & wiring notes"
                        >
                          <HelpCircle className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      <p className="line-clamp-2 text-[10px] leading-snug text-eigenia-muted">
                        {acc.summary}
                      </p>

                      <div className="flex flex-wrap items-center justify-between gap-1 pt-0.5">
                        <div className="flex flex-wrap gap-1">
                          <Badge variant={acc.requires_5v && boardId === "microbit_v2" ? "amber" : "neutral"}>
                            {acc.requires_5v ? "5V" : "3.3V"}
                          </Badge>
                          {acc.protocol && <Badge variant="sky">{acc.protocol}</Badge>}
                        </div>
                        <Button
                          size="sm"
                          variant="secondary"
                          className="h-6 px-2 text-[10px]"
                          onClick={() => onAddAccessory(acc)}
                        >
                          <Plus className="h-3 w-3" /> Place
                        </Button>
                      </div>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-2 space-y-1 rounded border border-white/10 bg-eigenia-shell p-2 text-[10px] text-eigenia-muted">
                      <div className="font-mono text-white">
                        {acc.ic} · {dimText} {acc.mass_g ? `· ${acc.mass_g}g` : ""}
                      </div>
                      {acc.how_it_works && <p>{acc.how_it_works}</p>}
                      <p className="text-eigenia-amber">{acc.power_note}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="max-h-[480px] space-y-1.5 overflow-y-auto pr-1">
          {attachments.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/15 bg-eigenia-obsidian p-4 text-center text-xs text-eigenia-muted">
              Drag any module from <b>Part Library</b> onto the 3D canvas or click <b>Place</b>.
            </div>
          ) : (
            attachments.map((att) => {
              const spec = accessories.find((a) => a.id === att.accessory_id);
              const isSelected = selectedAttachmentId === att.id;
              const pos = att.position_mm || [0, -35, 0];
              return (
                <div
                  key={att.id}
                  onClick={() => onSelectAttachment(isSelected ? null : att.id)}
                  className={cn(
                    "cursor-pointer rounded-lg border p-2 transition",
                    isSelected
                      ? "border-eigenia-orange bg-eigenia-orange/10"
                      : "border-white/10 bg-eigenia-obsidian hover:border-white/25"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <HardwarePartSvgIcon
                      kind={spec?.svg_icon_kind}
                      color={spec?.color_hex}
                      className="h-7 w-10 shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="truncate text-[11px] font-semibold text-white">
                          {att.label}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveAttachment(att.id);
                          }}
                          className="text-eigenia-muted hover:text-eigenia-fault"
                          title="Remove from canvas"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-1 font-mono text-[10px]">
                        <span className="flex items-center gap-1 text-eigenia-muted">
                          <Move className="h-2.5 w-2.5 text-eigenia-sky" />
                          ({pos[0]}, {pos[1]}) mm
                        </span>
                        <select
                          value={att.pin}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => onChangePin(att.id, e.target.value)}
                          className="rounded border border-white/15 bg-eigenia-shell px-1.5 py-0.5 font-mono text-[10px] text-white"
                        >
                          {pins.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.id}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
