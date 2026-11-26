"use client";

import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  Crosshair,
  EyeOff,
  Loader2,
  Navigation,
  PackageSearch,
  Sparkles,
  Target,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { FocusQueueItem, FocusTarget } from "@/lib/types";

interface FocusQueuePanelProps {
  items: FocusQueueItem[];
  onFocus: (target: FocusTarget) => void;
  onEnrich: (equipmentId: string) => void;
  enrichingId: string | null;
}

type CategoryFilter = "all" | "occlusion_shadow" | "unidentified_cluster" | "incomplete_asset";

function getPriorityVariant(score: number): "fault" | "default" | "amber" | "sky" {
  if (score >= 80) return "fault";
  if (score >= 60) return "default";
  if (score >= 35) return "amber";
  return "sky";
}

function getStatusVariant(status: FocusQueueItem["status"]): "fault" | "amber" | "sky" {
  if (status === "DARK") return "fault";
  if (status === "INCOMPLETE") return "amber";
  return "sky";
}

function getCategoryMeta(category: FocusQueueItem["category"]) {
  switch (category) {
    case "occlusion_shadow":
      return { label: "Dark Zone", icon: EyeOff, accent: "text-eigenia-fault" };
    case "unidentified_cluster":
      return { label: "Cluster", icon: PackageSearch, accent: "text-eigenia-amber" };
    case "incomplete_asset":
    default:
      return { label: "Asset Gap", icon: AlertTriangle, accent: "text-eigenia-orange" };
  }
}

export function FocusQueuePanel({ items, onFocus, onEnrich, enrichingId }: FocusQueuePanelProps) {
  const [filter, setFilter] = useState<CategoryFilter>("all");
  const safeItems = useMemo(() => (Array.isArray(items) ? items : []), [items]);

  const counts = useMemo(() => {
    let shadows = 0;
    let clusters = 0;
    let assets = 0;
    for (const item of safeItems) {
      if (item.category === "occlusion_shadow") shadows += 1;
      else if (item.category === "unidentified_cluster") clusters += 1;
      else assets += 1;
    }
    return { shadows, clusters, assets };
  }, [safeItems]);

  const sortedItems = useMemo(() => {
    const filtered = filter === "all" ? safeItems : safeItems.filter((item) => item.category === filter);
    return [...filtered].sort((a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0));
  }, [safeItems, filter]);

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="gap-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <Target className="h-3.5 w-3.5 text-eigenia-orange" />
            Dark-Zone & Gap Focus Queue
          </CardTitle>
          <Badge variant={safeItems.length > 0 ? "default" : "sky"}>
            {safeItems.length} {safeItems.length === 1 ? "Target" : "Targets"}
          </Badge>
        </div>

        <div className="flex flex-wrap gap-1">
          <Button
            size="sm"
            variant={filter === "all" ? "default" : "secondary"}
            className="h-6 px-2 text-[10px]"
            onClick={() => setFilter("all")}
          >
            All ({safeItems.length})
          </Button>
          <Button
            size="sm"
            variant={filter === "occlusion_shadow" ? "default" : "secondary"}
            className="h-6 px-2 text-[10px]"
            onClick={() => setFilter("occlusion_shadow")}
          >
            Dark Zones ({counts.shadows})
          </Button>
          <Button
            size="sm"
            variant={filter === "unidentified_cluster" ? "default" : "secondary"}
            className="h-6 px-2 text-[10px]"
            onClick={() => setFilter("unidentified_cluster")}
          >
            Clusters ({counts.clusters})
          </Button>
          <Button
            size="sm"
            variant={filter === "incomplete_asset" ? "default" : "secondary"}
            className="h-6 px-2 text-[10px]"
            onClick={() => setFilter("incomplete_asset")}
          >
            Assets ({counts.assets})
          </Button>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-2.5 overflow-y-auto">
        {sortedItems.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center">
            <Target className="mb-2 h-6 w-6 text-eigenia-sky/60" />
            <div className="text-xs font-medium text-white">No Active Focus Alerts</div>
            <p className="mt-1 text-[11px] text-eigenia-muted">
              All scanned sectors and placed assets meet completeness thresholds in this filter.
            </p>
          </div>
        ) : (
          sortedItems.map((item) => {
            const cat = getCategoryMeta(item.category);
            const CategoryIcon = cat.icon;
            const priorityScore = Number(item.priority_score ?? 0);
            const targetX = Number(item.target_x ?? 0);
            const targetY = Number(item.target_y ?? 0);
            const missingFields = Array.isArray(item.missing_fields) ? item.missing_fields : [];
            const pct = Math.max(0, Math.min(100, Math.round(Number(item.completeness_pct ?? 0))));
            const isEnriching = Boolean(item.equipment_id && enrichingId === item.equipment_id);
            const barColor =
              pct >= 80 ? "bg-eigenia-sky" : pct >= 45 ? "bg-eigenia-amber" : "bg-eigenia-fault";

            return (
              <div
                key={item.id}
                className="flex flex-col gap-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3 transition-colors hover:border-eigenia-orange/50"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant={getPriorityVariant(priorityScore)} className="tabular-nums">
                        P{Math.round(priorityScore)}
                      </Badge>
                      <Badge variant={getStatusVariant(item.status)}>{item.status || "DARK"}</Badge>
                      <span className={`inline-flex items-center gap-1 font-mono text-[10px] ${cat.accent}`}>
                        <CategoryIcon className="h-3 w-3" />
                        {cat.label}
                      </span>
                    </div>
                    <div className="mt-1.5 truncate text-xs font-semibold text-white">{item.title}</div>
                  </div>
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-eigenia-muted">
                    ({targetX.toFixed(2)}m, {targetY.toFixed(2)}m)
                  </span>
                </div>

                {/* Completeness Progress Bar */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between font-mono text-[10px]">
                    <span className="text-eigenia-muted">Completeness</span>
                    <span className="tabular-nums text-white">{pct}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                    <div className={`h-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>

                {/* NBV Waypoint Badge */}
                {item.nbv && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="sky" className="tabular-nums">
                      <Navigation className="h-3 w-3" />
                      NBV ({Number(item.nbv.x ?? 0).toFixed(2)}m, {Number(item.nbv.y ?? 0).toFixed(2)}m @{" "}
                      {Math.round(Number(item.nbv.yaw_deg ?? 0))}°)
                    </Badge>
                  </div>
                )}

                {/* Missing Fields */}
                {missingFields.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {missingFields.map((field) => (
                      <span
                        key={field}
                        className="rounded border border-eigenia-amber/25 bg-eigenia-amber/10 px-1.5 py-0.5 font-mono text-[9px] text-eigenia-amber"
                      >
                        missing:{field}
                      </span>
                    ))}
                  </div>
                )}

                {item.recommended_action && (
                  <p className="text-[11px] leading-relaxed text-eigenia-muted">
                    {item.recommended_action}
                  </p>
                )}

                {/* Actions */}
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="sky"
                    className="h-7 flex-1 text-[11px]"
                    onClick={() =>
                      onFocus({
                        x: targetX,
                        y: targetY,
                        label: item.title,
                        equipmentId: item.equipment_id,
                      })
                    }
                  >
                    <Crosshair className="h-3 w-3" />
                    Focus Target
                  </Button>

                  {item.equipment_id && (
                    <Button
                      size="sm"
                      variant="default"
                      className="h-7 flex-1 text-[11px]"
                      disabled={Boolean(enrichingId)}
                      onClick={() => onEnrich(item.equipment_id!)}
                    >
                      {isEnriching ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      {isEnriching ? "Researching..." : "Pass-3 Research"}
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
