"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Brain,
  Camera,
  Check,
  CheckSquare,
  Clock,
  Download,
  Edit3,
  Eye,
  Grid2x2,
  LayoutGrid,
  List,
  Loader2,
  MapPin,
  Mic,
  Plus,
  RefreshCw,
  Save,
  Search,
  Square,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SegmentedTabs, type SegmentedTabItem } from "@/components/ui/SegmentedTabs";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import { getFileUrl } from "@/lib/api";
import {
  bulkSpatialSightings,
  captureSpatialMemoryPro,
  deleteSpatialSightingPro,
  listSpatialMemory,
  updateSpatialSighting,
  type SpatialMemoryCounts,
  type SpatialMemoryStatusFilter,
  type SpatialSighting,
} from "@/lib/robotApi";
import { cn } from "@/lib/utils";

export interface SpatialMemoryGalleryProps {
  robotId: string | null;
  activeSpaceId?: string | null;
  spaces?: Array<{ id: string; name: string; facility?: string }>;
  onBanner?: (banner: { kind: "ok" | "error"; text: string }) => void;
  onCountChange?: (counts: SpatialMemoryCounts) => void;
}

type GalleryViewMode = "bento" | "grid" | "list";
type KindFilter = "all" | "face" | "animal" | "object" | "scene";

const KIND_FILTERS: { id: KindFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "face", label: "Face" },
  { id: "animal", label: "Animal" },
  { id: "object", label: "Object" },
  { id: "scene", label: "Scene" },
];

const KIND_OPTIONS = ["face", "animal", "object", "scene"];

function resolveSnapshotSrc(
  snapshotUrl?: string | null,
  snapshotFileId?: string | null
): string | null {
  if (snapshotUrl) return getFileUrl(snapshotUrl);
  if (snapshotFileId) return getFileUrl(`/api/files/${encodeURIComponent(snapshotFileId)}`);
  return null;
}

function kindBadgeVariant(kind: string): "default" | "amber" | "sky" | "neutral" {
  const k = (kind || "").toLowerCase();
  if (k === "face" || k === "person") return "default";
  if (k === "animal") return "amber";
  if (k === "scene") return "neutral";
  return "sky";
}

function formatSourceLabel(source?: string): string {
  if (!source) return "PuppyPi FPV";
  if (source === "puppypi_fpv") return "PuppyPi FPV";
  if (source.startsWith("local_cam:")) return source.replace("local_cam:", "Cam · ");
  return source;
}

function formatTimestamp(ts?: string | null): string {
  if (!ts) return "Unknown time";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function getBentoTileClasses(index: number): string {
  const slot = index % 6;
  if (slot === 0) return "md:col-span-3 md:row-span-2";
  if (slot === 1 || slot === 2) return "md:col-span-3 md:row-span-1";
  return "md:col-span-2 md:row-span-1";
}

export function SpatialMemoryGallery({
  robotId,
  activeSpaceId,
  spaces = [],
  onBanner,
  onCountChange,
}: SpatialMemoryGalleryProps): React.JSX.Element {
  const [statusTab, setStatusTab] = useState<SpatialMemoryStatusFilter>("active");
  const [viewMode, setViewMode] = useState<GalleryViewMode>("bento");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");

  const [sightings, setSightings] = useState<SpatialSighting[]>([]);
  const [counts, setCounts] = useState<SpatialMemoryCounts>({ active: 0, archived: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  // Selection for multi-select bulk actions
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Inline rename in Line View
  const [inlineEditId, setInlineEditId] = useState<string | null>(null);
  const [inlineLabel, setInlineLabel] = useState("");

  // Slide-Over Inspector Drawer
  const [inspectSighting, setInspectSighting] = useState<SpatialSighting | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftKind, setDraftKind] = useState("object");
  const [draftNotes, setDraftNotes] = useState("");
  const [draftTags, setDraftTags] = useState<string[]>([]);
  const [newTagInput, setNewTagInput] = useState("");
  const [savingInspector, setSavingInspector] = useState(false);

  const spaceNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const sp of spaces) {
      map.set(sp.id, sp.name);
    }
    return map;
  }, [spaces]);

  const loadMemory = useCallback(
    async (opts?: {
      status?: SpatialMemoryStatusFilter;
      kind?: KindFilter;
      q?: string;
    }) => {
      const targetStatus = opts?.status ?? statusTab;
      const targetKind = opts?.kind ?? kindFilter;
      const targetQuery = opts?.q ?? appliedQuery;
      setLoading(true);
      try {
        const res = await listSpatialMemory({
          status: targetStatus,
          kind: targetKind === "all" ? undefined : targetKind,
          query: targetQuery,
          limit: 200,
        });
        setSightings(res.sightings);
        setCounts(res.counts);
        onCountChange?.(res.counts);
        // Prune selected IDs that are no longer visible
        setSelectedIds((prev) => {
          if (prev.size === 0) return prev;
          const visible = new Set(res.sightings.map((s) => s.id));
          const next = new Set<string>();
          prev.forEach((id) => {
            if (visible.has(id)) next.add(id);
          });
          return next;
        });
        // Keep drawer synced if open
        setInspectSighting((prev) => {
          if (!prev) return null;
          const refreshed = res.sightings.find((s) => s.id === prev.id);
          return refreshed ?? prev;
        });
      } catch (err) {
        onBanner?.({
          kind: "error",
          text: err instanceof Error ? err.message : "Failed to load Spatial Memory",
        });
      } finally {
        setLoading(false);
      }
    },
    [statusTab, kindFilter, appliedQuery, onBanner, onCountChange]
  );

  useEffect(() => {
    void loadMemory();
  }, [loadMemory]);

  const openInspector = (sighting: SpatialSighting) => {
    setInspectSighting(sighting);
    setDraftLabel(sighting.label);
    setDraftKind(sighting.kind || "object");
    setDraftNotes(sighting.notes || "");
    setDraftTags(Array.isArray(sighting.tags) ? [...sighting.tags] : []);
    setNewTagInput("");
  };

  const toggleSelect = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    if (selectedIds.size === sightings.length && sightings.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(sightings.map((s) => s.id)));
    }
  };

  const handleCapture = async () => {
    if (!robotId) return;
    setCapturing(true);
    try {
      const res = await captureSpatialMemoryPro(robotId);
      onBanner?.({
        kind: "ok",
        text: `Captured & memorized ${res.recorded_count} object/person sighting(s) from PuppyPi camera.`,
      });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : "Spatial memory room capture failed",
      });
    } finally {
      setCapturing(false);
    }
  };

  const handleToggleArchive = async (sighting: SpatialSighting, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setBusyId(sighting.id);
    try {
      const targetArchived = !sighting.archived;
      const res = await updateSpatialSighting(sighting.id, { archived: targetArchived });
      if (inspectSighting?.id === sighting.id) {
        setInspectSighting(res.sighting);
      }
      onBanner?.({
        kind: "ok",
        text: targetArchived
          ? `Archived "${sighting.label}". Switch to Archived tab anytime to retrieve it.`
          : `Retrieved "${sighting.label}" back to Active Spatial Memory.`,
      });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to update archive state",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteOne = async (sighting: SpatialSighting, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setBusyId(sighting.id);
    try {
      await deleteSpatialSightingPro(sighting.id);
      if (inspectSighting?.id === sighting.id) {
        setInspectSighting(null);
      }
      onBanner?.({ kind: "ok", text: `Permanently deleted "${sighting.label}".` });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete spatial sighting",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleBulkAction = async (action: "archive" | "retrieve" | "delete") => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const res = await bulkSpatialSightings({ action, ids });
      setSelectedIds(new Set());
      if (action === "delete" && inspectSighting && ids.includes(inspectSighting.id)) {
        setInspectSighting(null);
      }
      const verb =
        action === "archive"
          ? "Archived"
          : action === "retrieve"
            ? "Retrieved"
            : "Deleted";
      onBanner?.({
        kind: "ok",
        text: `${verb} ${res.affected} spatial sighting(s).`,
      });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : `Bulk ${action} failed`,
      });
    } finally {
      setBulkBusy(false);
    }
  };

  const handleCommitInlineRename = async (sighting: SpatialSighting) => {
    const trimmed = inlineLabel.trim();
    if (!trimmed || trimmed === sighting.label) {
      setInlineEditId(null);
      return;
    }
    setBusyId(sighting.id);
    try {
      await updateSpatialSighting(sighting.id, { label: trimmed });
      setInlineEditId(null);
      onBanner?.({ kind: "ok", text: `Renamed sighting to "${trimmed}".` });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to rename sighting",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleAddDraftTag = () => {
    const parts = newTagInput
      .split(",")
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);
    if (parts.length === 0) return;
    setDraftTags((prev) => Array.from(new Set([...prev, ...parts])));
    setNewTagInput("");
  };

  const handleSaveInspector = async () => {
    if (!inspectSighting) return;
    const trimmed = draftLabel.trim();
    if (!trimmed) {
      onBanner?.({ kind: "error", text: "Label cannot be empty." });
      return;
    }
    setSavingInspector(true);
    try {
      const pendingTags = newTagInput
        .split(",")
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean);
      const mergedTags = Array.from(new Set([...draftTags, ...pendingTags]));
      const res = await updateSpatialSighting(inspectSighting.id, {
        label: trimmed,
        kind: draftKind,
        notes: draftNotes.trim(),
        tags: mergedTags,
        space_id: inspectSighting.space_id ?? activeSpaceId ?? null,
      });
      setInspectSighting(res.sighting);
      setDraftTags(res.sighting.tags);
      setNewTagInput("");
      onBanner?.({ kind: "ok", text: `Saved changes to "${res.sighting.label}".` });
      await loadMemory();
    } catch (err) {
      onBanner?.({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save sighting metadata",
      });
    } finally {
      setSavingInspector(false);
    }
  };

  const handleDownloadSnapshot = (sighting: SpatialSighting, e?: React.MouseEvent) => {
    e?.stopPropagation();
    const src = resolveSnapshotSrc(sighting.snapshot_url, sighting.snapshot_file_id);
    if (!src) return;
    const a = document.createElement("a");
    a.href = src;
    a.download = `${sighting.label.replace(/[^a-zA-Z0-9_-]+/g, "_")}_${sighting.id.slice(0, 8)}.jpg`;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const lifecycleTabs: SegmentedTabItem[] = [
    { id: "active", label: "Active", count: counts.active, icon: <Eye className="h-3.5 w-3.5" /> },
    {
      id: "archived",
      label: "Archived",
      count: counts.archived,
      icon: <Archive className="h-3.5 w-3.5" />,
    },
    { id: "all", label: "All", count: counts.total, icon: <Brain className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-4">
      {/* Top Control Card */}
      <Card className="border-eigenia-sky/35">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-eigenia-sky" />
              Semantic Spatial Memory Pro
              <Badge variant="sky" className="font-mono text-[10px] tabular-nums">
                {counts.active} Active · {counts.archived} Archived
              </Badge>
            </CardTitle>
            <p className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
              Search, tag, archive, retrieve, and inspect snapshots from PuppyPi FPV and local LAN /
              Pi Zero cameras stored in PostgreSQL 18.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {robotId && (
              <Button
                size="sm"
                variant="default"
                disabled={capturing}
                onClick={() => void handleCapture()}
                className="font-semibold"
              >
                {capturing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Camera className="h-3.5 w-3.5" />
                )}
                {capturing ? "Scanning Room..." : "Scan & Remember Room Now"}
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              disabled={loading}
              onClick={() => void loadMemory()}
              title="Refresh Spatial Memory"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Voice Query Tip */}
          <div className="flex items-center gap-2 rounded-md border border-eigenia-orange/35 bg-eigenia-orange/10 px-3 py-2 text-xs text-eigenia-ink">
            <Mic className="h-3.5 w-3.5 shrink-0 text-eigenia-orange" />
            <span>
              Ask OX by voice:{" "}
              <span className="font-mono font-semibold text-white">
                &apos;Hey OX, where did you last see my laptop?&apos;
              </span>
            </span>
          </div>

          {/* Lifecycle Filter Tabs + 3-View Switcher */}
          <SegmentedTabs
            tabs={lifecycleTabs}
            value={statusTab}
            onValueChange={(id) => {
              const nextStatus = id as SpatialMemoryStatusFilter;
              setStatusTab(nextStatus);
              setSelectedIds(new Set());
            }}
            rightSlot={
              <div
                role="group"
                aria-label="Spatial Memory View Mode"
                className="inline-flex items-center rounded-md border border-white/10 bg-eigenia-obsidian p-0.5"
              >
                <button
                  type="button"
                  onClick={() => setViewMode("bento")}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px] font-medium transition-colors motion-reduce:transition-none",
                    viewMode === "bento"
                      ? "bg-eigenia-orange text-white"
                      : "text-eigenia-muted hover:text-white"
                  )}
                  title="Bento Grid View"
                >
                  <LayoutGrid className="h-3 w-3" />
                  Bento Grid
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("grid")}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px] font-medium transition-colors motion-reduce:transition-none",
                    viewMode === "grid"
                      ? "bg-eigenia-orange text-white"
                      : "text-eigenia-muted hover:text-white"
                  )}
                  title="Small Picture Grid View"
                >
                  <Grid2x2 className="h-3 w-3" />
                  Small Grid
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("list")}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px] font-medium transition-colors motion-reduce:transition-none",
                    viewMode === "list"
                      ? "bg-eigenia-orange text-white"
                      : "text-eigenia-muted hover:text-white"
                  )}
                  title="Dense Line View"
                >
                  <List className="h-3 w-3" />
                  Line View
                </button>
              </div>
            }
          />

          {/* Search + Kind Filter Pills */}
          <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center lg:justify-between">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setAppliedQuery(query.trim());
              }}
              className="flex flex-1 flex-wrap items-center gap-2"
            >
              <div className="relative min-w-[210px] flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search label, tag, notes, camera source..."
                  className="pl-8 text-xs"
                />
              </div>
              <Button type="submit" size="sm" variant="sky" disabled={loading}>
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Search className="h-3.5 w-3.5" />
                )}
                Search
              </Button>
              {(query || appliedQuery) && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setQuery("");
                    setAppliedQuery("");
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                  Clear
                </Button>
              )}
            </form>

            {/* Kind Filter Pills */}
            <div className="flex flex-wrap items-center gap-1">
              {KIND_FILTERS.map((kf) => (
                <button
                  key={kf.id}
                  type="button"
                  onClick={() => setKindFilter(kf.id)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 font-mono text-[10px] font-medium transition-colors motion-reduce:transition-none",
                    kindFilter === kf.id
                      ? "border-eigenia-sky/60 bg-eigenia-sky/20 text-white"
                      : "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:border-white/25 hover:text-white"
                  )}
                >
                  {kf.label}
                </button>
              ))}
              {sightings.length > 0 && (
                <button
                  type="button"
                  onClick={selectAllVisible}
                  className="ml-1 inline-flex items-center gap-1 rounded-full border border-white/10 bg-eigenia-obsidian px-2.5 py-1 font-mono text-[10px] text-eigenia-muted hover:border-eigenia-orange/50 hover:text-white"
                >
                  {selectedIds.size === sightings.length && sightings.length > 0 ? (
                    <CheckSquare className="h-3 w-3 text-eigenia-orange" />
                  ) : (
                    <Square className="h-3 w-3" />
                  )}
                  {selectedIds.size === sightings.length && sightings.length > 0
                    ? "Deselect All"
                    : "Select All"}
                </button>
              )}
            </div>
          </div>

          {/* Multi-Select Bulk Action Bar */}
          {selectedIds.size > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-eigenia-orange/50 bg-eigenia-orange/15 px-3 py-2">
              <div className="flex items-center gap-2 font-mono text-xs font-semibold text-white">
                <CheckSquare className="h-4 w-4 text-eigenia-orange" />
                <span>{selectedIds.size} selected</span>
                <button
                  type="button"
                  onClick={() => setSelectedIds(new Set())}
                  className="text-[10px] font-normal text-eigenia-muted underline hover:text-white"
                >
                  Clear
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={bulkBusy}
                  onClick={() => void handleBulkAction("archive")}
                >
                  <Archive className="h-3.5 w-3.5" />
                  Archive
                </Button>
                <Button
                  size="sm"
                  variant="sky"
                  disabled={bulkBusy}
                  onClick={() => void handleBulkAction("retrieve")}
                >
                  <ArchiveRestore className="h-3.5 w-3.5" />
                  Retrieve
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={bulkBusy}
                  onClick={() => void handleBulkAction("delete")}
                >
                  {bulkBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                  Delete
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Empty State */}
      {sightings.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 p-10 text-center">
            <Brain className="h-8 w-8 text-eigenia-muted" />
            <div className="text-sm font-semibold text-white">
              {appliedQuery
                ? `No ${statusTab} sightings matching "${appliedQuery}"`
                : statusTab === "archived"
                  ? "No Archived Sightings"
                  : "No Spatial Sightings Recorded Yet"}
            </div>
            <p className="max-w-md text-xs text-eigenia-muted">
              {statusTab === "archived"
                ? "Archived snapshots stay preserved here until you retrieve or permanently delete them."
                : "Click Scan & Remember Room Now or ingest local camera clips from Lab Architect to build PuppyPi's visual spatial memory."}
            </p>
          </CardContent>
        </Card>
      ) : viewMode === "bento" ? (
        /* VIEW 1: BENTO GRID */
        <div className="grid auto-rows-[205px] grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-6">
          {sightings.map((s, idx) => {
            const snapSrc = resolveSnapshotSrc(s.snapshot_url, s.snapshot_file_id);
            const isSelected = selectedIds.has(s.id);
            const isHero = idx % 6 === 0;
            const roomName = s.space_id ? spaceNameMap.get(s.space_id) : null;
            return (
              <div
                key={s.id}
                onClick={() => openInspector(s)}
                className={cn(
                  "group relative cursor-pointer overflow-hidden rounded-xl border bg-eigenia-obsidian transition-all duration-200 motion-reduce:transition-none",
                  getBentoTileClasses(idx),
                  isSelected
                    ? "border-eigenia-orange ring-2 ring-eigenia-orange/60"
                    : "border-white/10 hover:border-eigenia-sky/50 hover:shadow-[0_12px_32px_rgba(0,0,0,0.5)]"
                )}
              >
                {snapSrc ? (
                  <img
                    src={snapSrc}
                    alt={s.label}
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100"
                  />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-gradient-to-br from-eigenia-surface to-eigenia-obsidian text-eigenia-muted">
                    <Camera className="h-7 w-7 opacity-50" />
                    <span className="font-mono text-[10px]">No Snapshot</span>
                  </div>
                )}

                {/* Gradient Readability Scrim */}
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/90 via-black/35 to-black/20" />

                {/* Top-Left: Checkbox + Badges */}
                <div className="absolute left-2.5 top-2.5 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={(e) => toggleSelect(s.id, e)}
                    aria-label={isSelected ? `Deselect ${s.label}` : `Select ${s.label}`}
                    className={cn(
                      "flex h-6 w-6 items-center justify-center rounded border backdrop-blur-sm transition-colors",
                      isSelected
                        ? "border-eigenia-orange bg-eigenia-orange text-white"
                        : "border-white/25 bg-black/55 text-white/80 hover:border-white"
                    )}
                  >
                    {isSelected ? <Check className="h-3.5 w-3.5" /> : <Square className="h-3 w-3" />}
                  </button>
                  <Badge variant={kindBadgeVariant(s.kind)} className="text-[9px] uppercase">
                    {s.kind || "object"}
                  </Badge>
                  <Badge variant="neutral" className="bg-black/65 font-mono text-[9px] tabular-nums">
                    {Math.round(Number(s.confidence ?? 0) * 100)}%
                  </Badge>
                  {s.archived && (
                    <Badge variant="amber" className="text-[9px] uppercase">
                      Archived
                    </Badge>
                  )}
                </div>

                {/* Top-Right: Floating Quick Actions */}
                <div className="absolute right-2.5 top-2.5 flex items-center gap-1 opacity-90 transition-opacity sm:opacity-0 sm:group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={(e) => void handleToggleArchive(s, e)}
                    disabled={busyId === s.id}
                    title={s.archived ? "Retrieve to Active" : "Archive Sighting"}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-white/20 bg-black/70 text-white backdrop-blur-sm hover:border-eigenia-sky hover:text-eigenia-sky"
                  >
                    {s.archived ? (
                      <ArchiveRestore className="h-3.5 w-3.5" />
                    ) : (
                      <Archive className="h-3.5 w-3.5" />
                    )}
                  </button>
                  {snapSrc && (
                    <button
                      type="button"
                      onClick={(e) => handleDownloadSnapshot(s, e)}
                      title="Download JPEG"
                      className="flex h-7 w-7 items-center justify-center rounded-md border border-white/20 bg-black/70 text-white backdrop-blur-sm hover:border-eigenia-orange hover:text-eigenia-orange"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={(e) => void handleDeleteOne(s, e)}
                    disabled={busyId === s.id}
                    title="Delete Sighting"
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-eigenia-fault/50 bg-eigenia-fault/80 text-white hover:bg-eigenia-fault"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Bottom Overlay Metadata */}
                <div className="absolute inset-x-0 bottom-0 space-y-1 p-3">
                  <div className="flex items-end justify-between gap-2">
                    <div className="min-w-0">
                      <div
                        className={cn(
                          "truncate font-semibold text-white",
                          isHero ? "text-base" : "text-sm"
                        )}
                      >
                        {s.label}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] text-eigenia-ink/85">
                        <span>{formatSourceLabel(s.camera_source)}</span>
                        {roomName && <span>· {roomName}</span>}
                        <span>· {formatTimestamp(s.seen_at)}</span>
                      </div>
                    </div>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded border border-eigenia-sky/40 bg-black/70 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-eigenia-sky backdrop-blur-sm">
                      <MapPin className="h-2.5 w-2.5" />
                      ({s.x_m.toFixed(2)}, {s.y_m.toFixed(2)})
                    </span>
                  </div>

                  {isHero && s.notes && (
                    <p className="line-clamp-2 text-xs text-eigenia-ink/90">{s.notes}</p>
                  )}

                  {s.tags.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 pt-0.5">
                      {s.tags.slice(0, isHero ? 5 : 3).map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-white/15 px-1.5 py-0.5 font-mono text-[9px] text-white backdrop-blur-sm"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : viewMode === "grid" ? (
        /* VIEW 2: SMALL PICTURE GRID */
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
          {sightings.map((s) => {
            const snapSrc = resolveSnapshotSrc(s.snapshot_url, s.snapshot_file_id);
            const isSelected = selectedIds.has(s.id);
            return (
              <div
                key={s.id}
                onClick={() => openInspector(s)}
                className={cn(
                  "group relative cursor-pointer overflow-hidden rounded-lg border bg-eigenia-surface transition-all duration-150 motion-reduce:transition-none",
                  isSelected
                    ? "border-eigenia-orange ring-2 ring-eigenia-orange/60"
                    : "border-white/10 hover:border-eigenia-sky/50"
                )}
              >
                <div className="relative aspect-square w-full overflow-hidden bg-eigenia-obsidian">
                  {snapSrc ? (
                    <img
                      src={snapSrc}
                      alt={s.label}
                      className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-eigenia-muted">
                      <Camera className="h-6 w-6 opacity-50" />
                    </div>
                  )}

                  {/* Corner Checkbox */}
                  <button
                    type="button"
                    onClick={(e) => toggleSelect(s.id, e)}
                    aria-label={isSelected ? `Deselect ${s.label}` : `Select ${s.label}`}
                    className={cn(
                      "absolute left-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded border backdrop-blur-sm",
                      isSelected
                        ? "border-eigenia-orange bg-eigenia-orange text-white"
                        : "border-white/25 bg-black/60 text-white/80 hover:border-white"
                    )}
                  >
                    {isSelected ? <Check className="h-3 w-3" /> : <Square className="h-2.5 w-2.5" />}
                  </button>

                  {/* Hover Pills */}
                  <div className="absolute right-1.5 top-1.5 flex items-center gap-1 opacity-90 sm:opacity-0 sm:group-hover:opacity-100">
                    <button
                      type="button"
                      onClick={(e) => void handleToggleArchive(s, e)}
                      disabled={busyId === s.id}
                      title={s.archived ? "Retrieve" : "Archive"}
                      className="flex h-6 w-6 items-center justify-center rounded border border-white/20 bg-black/75 text-white hover:text-eigenia-sky"
                    >
                      {s.archived ? (
                        <ArchiveRestore className="h-3 w-3" />
                      ) : (
                        <Archive className="h-3 w-3" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => void handleDeleteOne(s, e)}
                      disabled={busyId === s.id}
                      title="Delete"
                      className="flex h-6 w-6 items-center justify-center rounded border border-eigenia-fault/50 bg-eigenia-fault/85 text-white"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>

                  <div className="absolute bottom-1.5 left-1.5 flex items-center gap-1">
                    <Badge variant={kindBadgeVariant(s.kind)} className="px-1.5 py-0 text-[8px] uppercase">
                      {s.kind}
                    </Badge>
                    {s.archived && (
                      <Badge variant="amber" className="px-1 py-0 text-[8px]">
                        ARC
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="space-y-0.5 p-2">
                  <div className="truncate text-xs font-semibold text-white">{s.label}</div>
                  <div className="flex items-center justify-between font-mono text-[9px] text-eigenia-muted">
                    <span className="tabular-nums">
                      ({s.x_m.toFixed(1)}, {s.y_m.toFixed(1)})m
                    </span>
                    <span className="tabular-nums">{Math.round(s.confidence * 100)}%</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* VIEW 3: DENSE LINE VIEW */
        <Card className="overflow-hidden border-white/10">
          <div className="divide-y divide-white/10">
            {sightings.map((s) => {
              const snapSrc = resolveSnapshotSrc(s.snapshot_url, s.snapshot_file_id);
              const isSelected = selectedIds.has(s.id);
              const isEditing = inlineEditId === s.id;
              const roomName = s.space_id ? spaceNameMap.get(s.space_id) : null;
              return (
                <div
                  key={s.id}
                  onClick={() => {
                    if (!isEditing) openInspector(s);
                  }}
                  className={cn(
                    "flex flex-wrap items-center gap-2.5 px-3 py-2 transition-colors motion-reduce:transition-none sm:flex-nowrap",
                    isSelected
                      ? "bg-eigenia-orange/15"
                      : "cursor-pointer bg-eigenia-surface hover:bg-white/[0.04]"
                  )}
                >
                  {/* Checkbox */}
                  <button
                    type="button"
                    onClick={(e) => toggleSelect(s.id, e)}
                    aria-label={isSelected ? `Deselect ${s.label}` : `Select ${s.label}`}
                    className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded border",
                      isSelected
                        ? "border-eigenia-orange bg-eigenia-orange text-white"
                        : "border-white/20 bg-eigenia-obsidian text-eigenia-muted hover:border-white"
                    )}
                  >
                    {isSelected ? <Check className="h-3 w-3" /> : <Square className="h-2.5 w-2.5" />}
                  </button>

                  {/* 48x36 Thumbnail */}
                  <div className="h-9 w-12 shrink-0 overflow-hidden rounded border border-white/15 bg-eigenia-obsidian">
                    {snapSrc ? (
                      <img src={snapSrc} alt={s.label} className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-eigenia-muted">
                        <Camera className="h-3.5 w-3.5 opacity-60" />
                      </div>
                    )}
                  </div>

                  {/* Inline Renameable Label */}
                  <div
                    className="min-w-[140px] flex-1"
                    onClick={(e) => {
                      if (isEditing) e.stopPropagation();
                    }}
                  >
                    {isEditing ? (
                      <div className="flex items-center gap-1">
                        <Input
                          autoFocus
                          value={inlineLabel}
                          onChange={(e) => setInlineLabel(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void handleCommitInlineRename(s);
                            if (e.key === "Escape") setInlineEditId(null);
                          }}
                          className="h-7 text-xs"
                        />
                        <Button
                          size="icon"
                          variant="sky"
                          className="h-7 w-7 shrink-0"
                          onClick={() => void handleCommitInlineRename(s)}
                        >
                          <Check className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 shrink-0"
                          onClick={() => setInlineEditId(null)}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-semibold text-white">{s.label}</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setInlineEditId(s.id);
                            setInlineLabel(s.label);
                          }}
                          title="Inline rename"
                          className="text-eigenia-muted opacity-60 hover:text-eigenia-sky hover:opacity-100"
                        >
                          <Edit3 className="h-3 w-3" />
                        </button>
                        {s.tags.slice(0, 2).map((tag) => (
                          <span
                            key={tag}
                            className="hidden rounded bg-white/10 px-1.5 py-0.5 font-mono text-[9px] text-eigenia-ink md:inline"
                          >
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Badges */}
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Badge variant={kindBadgeVariant(s.kind)} className="text-[9px] uppercase">
                      {s.kind}
                    </Badge>
                    <Badge variant="neutral" className="hidden font-mono text-[9px] sm:inline-flex">
                      {formatSourceLabel(s.camera_source)}
                    </Badge>
                    {s.archived && (
                      <Badge variant="amber" className="text-[9px]">
                        Archived
                      </Badge>
                    )}
                  </div>

                  {/* Room / Coordinates */}
                  <div className="hidden shrink-0 items-center gap-1 font-mono text-[10px] tabular-nums text-eigenia-sky lg:flex">
                    <MapPin className="h-3 w-3" />
                    <span>
                      {roomName ? `${roomName} · ` : ""}({s.x_m.toFixed(2)}, {s.y_m.toFixed(2)})m
                    </span>
                  </div>

                  {/* Timestamp */}
                  <div className="hidden w-36 shrink-0 truncate font-mono text-[10px] text-eigenia-muted xl:block">
                    {formatTimestamp(s.seen_at)}
                  </div>

                  {/* Action Buttons */}
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      title={s.archived ? "Retrieve to Active" : "Archive"}
                      disabled={busyId === s.id}
                      onClick={(e) => void handleToggleArchive(s, e)}
                    >
                      {s.archived ? (
                        <ArchiveRestore className="h-3.5 w-3.5 text-eigenia-sky" />
                      ) : (
                        <Archive className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    {snapSrc && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        title="Download JPEG"
                        onClick={(e) => handleDownloadSnapshot(s, e)}
                      >
                        <Download className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="destructive"
                      className="h-7 w-7"
                      title="Delete Sighting"
                      disabled={busyId === s.id}
                      onClick={(e) => void handleDeleteOne(s, e)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Slide-Over Detail Inspector Drawer */}
      <SlideOverDrawer
        open={Boolean(inspectSighting)}
        onClose={() => setInspectSighting(null)}
        title={inspectSighting?.label || "Sighting Inspector"}
        subtitle={
          inspectSighting
            ? `${formatSourceLabel(inspectSighting.camera_source)} · ${formatTimestamp(inspectSighting.seen_at)}`
            : undefined
        }
        badge={
          inspectSighting
            ? `${(inspectSighting.kind || "object").toUpperCase()}${inspectSighting.archived ? " · ARCHIVED" : ""}`
            : undefined
        }
        badgeVariant={
          inspectSighting
            ? inspectSighting.archived
              ? "amber"
              : kindBadgeVariant(inspectSighting.kind)
            : "sky"
        }
        footer={
          inspectSighting ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busyId === inspectSighting.id}
                  onClick={() => void handleToggleArchive(inspectSighting)}
                >
                  {inspectSighting.archived ? (
                    <ArchiveRestore className="h-3.5 w-3.5" />
                  ) : (
                    <Archive className="h-3.5 w-3.5" />
                  )}
                  {inspectSighting.archived ? "Retrieve" : "Archive"}
                </Button>
                {resolveSnapshotSrc(
                  inspectSighting.snapshot_url,
                  inspectSighting.snapshot_file_id
                ) && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleDownloadSnapshot(inspectSighting)}
                  >
                    <Download className="h-3.5 w-3.5" />
                    JPEG
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busyId === inspectSighting.id}
                  onClick={() => void handleDeleteOne(inspectSighting)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete
                </Button>
              </div>
              <Button
                size="sm"
                variant="default"
                disabled={savingInspector}
                onClick={() => void handleSaveInspector()}
              >
                {savingInspector ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save Metadata
              </Button>
            </div>
          ) : undefined
        }
      >
        {inspectSighting && (
          <div className="space-y-4">
            {/* Full-Resolution Snapshot */}
            <div className="overflow-hidden rounded-lg border border-white/15 bg-eigenia-obsidian">
              {resolveSnapshotSrc(inspectSighting.snapshot_url, inspectSighting.snapshot_file_id) ? (
                <img
                  src={
                    resolveSnapshotSrc(
                      inspectSighting.snapshot_url,
                      inspectSighting.snapshot_file_id
                    )!
                  }
                  alt={inspectSighting.label}
                  className="max-h-72 w-full object-contain bg-black"
                />
              ) : (
                <div className="flex h-44 flex-col items-center justify-center gap-1 text-eigenia-muted">
                  <Camera className="h-8 w-8 opacity-50" />
                  <span className="font-mono text-xs">No snapshot image attached</span>
                </div>
              )}
            </div>

            {/* Telemetry Strip */}
            <div className="grid grid-cols-2 gap-2 rounded-lg border border-white/10 bg-eigenia-obsidian p-3 font-mono text-[11px]">
              <div>
                <div className="text-[9px] uppercase text-eigenia-muted">Coordinates</div>
                <div className="text-eigenia-sky tabular-nums">
                  ({inspectSighting.x_m.toFixed(2)}, {inspectSighting.y_m.toFixed(2)}) m
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-eigenia-muted">Confidence</div>
                <div className="text-white tabular-nums">
                  {Math.round(inspectSighting.confidence * 100)}%
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-eigenia-muted">Camera Source</div>
                <div className="truncate text-white">
                  {formatSourceLabel(inspectSighting.camera_source)}
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-eigenia-muted">Captured</div>
                <div className="flex items-center gap-1 text-eigenia-ink">
                  <Clock className="h-3 w-3 shrink-0 text-eigenia-muted" />
                  <span className="truncate">{formatTimestamp(inspectSighting.seen_at)}</span>
                </div>
              </div>
            </div>

            {/* Editable Metadata Fields */}
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="font-mono text-[10px] uppercase text-eigenia-muted">Label</label>
                <Input
                  value={draftLabel}
                  onChange={(e) => setDraftLabel(e.target.value)}
                  className="text-xs"
                />
              </div>

              <div className="space-y-1">
                <label className="font-mono text-[10px] uppercase text-eigenia-muted">Kind</label>
                <div className="flex flex-wrap gap-1.5">
                  {KIND_OPTIONS.map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setDraftKind(k)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 font-mono text-[10px] uppercase transition-colors",
                        draftKind === k
                          ? "border-eigenia-orange bg-eigenia-orange/20 text-white"
                          : "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:text-white"
                      )}
                    >
                      {k}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-mono text-[10px] uppercase text-eigenia-muted">Notes</label>
                <textarea
                  rows={3}
                  value={draftNotes}
                  onChange={(e) => setDraftNotes(e.target.value)}
                  placeholder="Add location notes, owner info, or inspection details..."
                  className="w-full rounded-md border border-white/15 bg-eigenia-obsidian px-3 py-2 text-xs text-white placeholder:text-eigenia-muted focus:border-eigenia-sky focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className="flex items-center gap-1 font-mono text-[10px] uppercase text-eigenia-muted">
                  <Tag className="h-3 w-3" />
                  Tags
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {draftTags.length === 0 ? (
                    <span className="font-mono text-[10px] text-eigenia-muted">No tags yet</span>
                  ) : (
                    draftTags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 rounded-full border border-eigenia-sky/40 bg-eigenia-sky/15 px-2 py-0.5 font-mono text-[10px] text-eigenia-sky"
                      >
                        #{tag}
                        <button
                          type="button"
                          onClick={() =>
                            setDraftTags((prev) => prev.filter((item) => item !== tag))
                          }
                          aria-label={`Remove tag ${tag}`}
                          className="hover:text-white"
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                      </span>
                    ))
                  )}
                </div>
                <div className="flex gap-1.5">
                  <Input
                    value={newTagInput}
                    onChange={(e) => setNewTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddDraftTag();
                      }
                    }}
                    placeholder="Add tag (comma-separated, press Enter)..."
                    className="h-8 text-xs"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={handleAddDraftTag}
                    className="h-8 shrink-0"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </SlideOverDrawer>
    </div>
  );
}
