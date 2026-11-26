"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  PlusCircle,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { OpenRouterModelInfo, OpenRouterPricing } from "@/lib/types";
import { cn } from "@/lib/utils";

export type ModelCategoryKey =
  | "all"
  | "vision"
  | "web_research"
  | "reasoning"
  | "embedding"
  | "text"
  | "audio_video"
  | "free";

export interface OpenRouterModelPickerProps {
  value: string;
  onChange: (modelId: string) => void;
  models: OpenRouterModelInfo[];
  loading?: boolean;
  defaultCategory?: ModelCategoryKey;
  onRefreshModels?: () => void;
  placeholder?: string;
  compact?: boolean;
}

type SortKey =
  | "recommended"
  | "cost_asc"
  | "cost_desc"
  | "context_desc"
  | "name_asc"
  | "provider_asc";

const CATEGORY_META: { key: ModelCategoryKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "vision", label: "Vision" },
  { key: "web_research", label: "Web Research" },
  { key: "reasoning", label: "Reasoning" },
  { key: "embedding", label: "Embedding" },
  { key: "text", label: "Text / Chat" },
  { key: "audio_video", label: "Audio/Video" },
  { key: "free", label: "Free" },
];

const MAX_RENDERED_ROWS = 120;

function formatUsdRate(val: number): string {
  if (!Number.isFinite(val) || val <= 0) return "$0";
  if (val < 0.01) return `$${val.toFixed(4)}`;
  if (val < 1) return `$${val.toFixed(2)}`;
  if (val < 100) return `$${val.toFixed(2)}`;
  return `$${val.toFixed(0)}`;
}

function formatContextLength(ctx?: number): string | null {
  if (!ctx || !Number.isFinite(ctx) || ctx <= 0) return null;
  if (ctx >= 1_000_000) {
    const m = ctx / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (ctx >= 1_000) {
    return `${Math.round(ctx / 1_000)}K`;
  }
  return `${ctx}`;
}

function formatTriggerCost(pricing?: OpenRouterPricing): string | null {
  if (!pricing) return null;
  if (pricing.is_free) return "FREE";
  return `${formatUsdRate(pricing.prompt_per_1m_usd)} / ${formatUsdRate(pricing.completion_per_1m_usd)} / 1M`;
}

function getCostTierVariant(pricing?: OpenRouterPricing): "sky" | "amber" | "default" | "neutral" {
  if (!pricing) return "neutral";
  if (pricing.is_free) return "sky";
  const tier = (pricing.cost_tier || "").toLowerCase();
  if (tier.includes("budget") || tier.includes("($)")) return "sky";
  if (tier.includes("standard") || tier.includes("($$)")) return "amber";
  if (tier.includes("frontier") || tier.includes("($$$)")) return "default";
  return "neutral";
}

function getModelCategories(model: OpenRouterModelInfo): string[] {
  if (Array.isArray(model.categories) && model.categories.length > 0) {
    return model.categories;
  }
  const cats: string[] = [];
  const idLower = (model.id || "").toLowerCase();
  const inMods = model.input_modalities ?? [];
  const outMods = model.output_modalities ?? [];
  if (inMods.includes("image") || idLower.includes("vl") || idLower.includes("vision")) cats.push("vision");
  if (outMods.includes("embeddings") || idLower.includes("embedding")) cats.push("embedding");
  if (idLower.includes(":online") || idLower.includes("sonar") || idLower.startsWith("perplexity/")) {
    cats.push("web_research");
  }
  if (idLower.includes("thinking") || idLower.includes("reason") || idLower.includes("-r1")) {
    cats.push("reasoning");
  }
  if (inMods.includes("audio") || inMods.includes("video")) cats.push("audio_video");
  if (model.pricing?.is_free || idLower.includes(":free")) cats.push("free");
  if (!cats.includes("embedding")) cats.push("text");
  return cats;
}

function getModalityPills(model: OpenRouterModelInfo): string[] {
  const pills: string[] = [];
  const inMods = model.input_modalities ?? [];
  const outMods = model.output_modalities ?? [];
  const cats = getModelCategories(model);

  if (inMods.includes("image") || cats.includes("vision")) pills.push("img");
  if (inMods.includes("text") || cats.includes("text")) pills.push("txt");
  if (cats.includes("web_research")) pills.push("web");
  if (cats.includes("reasoning")) pills.push("reason");
  if (outMods.includes("embeddings") || cats.includes("embedding")) pills.push("embed");
  if (inMods.includes("audio") || inMods.includes("video") || cats.includes("audio_video")) pills.push("a/v");
  return pills;
}

function getModelDisplayName(model: OpenRouterModelInfo): string {
  return model.name || model.label || model.id;
}

function getModelProvider(model: OpenRouterModelInfo): string {
  if (model.provider) return model.provider;
  const parts = (model.id || "").split("/");
  return parts.length > 1 ? parts[0] : "openrouter";
}

function getModelBlendedCost(model: OpenRouterModelInfo): number {
  if (!model.pricing) return Number.POSITIVE_INFINITY;
  if (model.pricing.is_free) return 0;
  return Number.isFinite(model.pricing.blended_per_1m_usd)
    ? model.pricing.blended_per_1m_usd
    : Number.POSITIVE_INFINITY;
}

export function OpenRouterModelPicker({
  value,
  onChange,
  models,
  loading = false,
  defaultCategory = "all",
  onRefreshModels,
  placeholder = "Select OpenRouter model...",
  compact = false,
}: OpenRouterModelPickerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ModelCategoryKey>(defaultCategory);
  const [sortBy, setSortBy] = useState<SortKey>("recommended");

  const safeModels = useMemo(() => (Array.isArray(models) ? models : []), [models]);

  const selectedModel = useMemo(
    () => safeModels.find((m) => m.id === value) ?? null,
    [safeModels, value]
  );

  // Sync defaultCategory if prop changes while closed
  useEffect(() => {
    if (!open) {
      setCategory(defaultCategory);
    }
  }, [defaultCategory, open]);

  // Focus search input when popover opens
  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => searchInputRef.current?.focus(), 20);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  // Close on outside click or Escape key
  useEffect(() => {
    if (!open) return;

    const handleMouseDown = (evt: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(evt.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (evt: KeyboardEvent) => {
      if (evt.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  // Live category counts across entire model list
  const categoryCounts = useMemo(() => {
    const counts: Record<ModelCategoryKey, number> = {
      all: safeModels.length,
      vision: 0,
      web_research: 0,
      reasoning: 0,
      embedding: 0,
      text: 0,
      audio_video: 0,
      free: 0,
    };
    for (const m of safeModels) {
      const cats = getModelCategories(m);
      for (const c of cats) {
        if (c in counts && c !== "all") {
          counts[c as ModelCategoryKey] += 1;
        }
      }
    }
    return counts;
  }, [safeModels]);

  // Filter + sort models
  const filteredModels = useMemo(() => {
    const q = query.trim().toLowerCase();

    const matched = safeModels.filter((m) => {
      if (category !== "all") {
        const cats = getModelCategories(m);
        if (!cats.includes(category)) return false;
      }
      if (!q) return true;
      const haystack = [
        m.id,
        m.name,
        m.label,
        getModelProvider(m),
        m.model_type,
        m.description,
        ...getModelCategories(m),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });

    if (sortBy === "recommended") {
      // Preserve server-recommended order while gently boosting category-recommended entries
      const targetRec =
        defaultCategory === "web_research"
          ? "research"
          : defaultCategory === "embedding"
          ? "embedding"
          : defaultCategory === "vision"
          ? "vision"
          : "";
      if (!targetRec) return matched;
      return [...matched].sort((a, b) => {
        const aBoost = (a.recommended_for ?? []).includes(targetRec) ? 1 : 0;
        const bBoost = (b.recommended_for ?? []).includes(targetRec) ? 1 : 0;
        return bBoost - aBoost;
      });
    }

    const sorted = [...matched];
    if (sortBy === "cost_asc") {
      sorted.sort((a, b) => getModelBlendedCost(a) - getModelBlendedCost(b));
    } else if (sortBy === "cost_desc") {
      sorted.sort((a, b) => {
        const ca = Number.isFinite(getModelBlendedCost(a)) ? getModelBlendedCost(a) : -1;
        const cb = Number.isFinite(getModelBlendedCost(b)) ? getModelBlendedCost(b) : -1;
        return cb - ca;
      });
    } else if (sortBy === "context_desc") {
      sorted.sort((a, b) => (b.context_length ?? 0) - (a.context_length ?? 0));
    } else if (sortBy === "name_asc") {
      sorted.sort((a, b) => getModelDisplayName(a).localeCompare(getModelDisplayName(b)));
    } else if (sortBy === "provider_asc") {
      sorted.sort((a, b) => {
        const pCmp = getModelProvider(a).localeCompare(getModelProvider(b));
        return pCmp !== 0 ? pCmp : getModelDisplayName(a).localeCompare(getModelDisplayName(b));
      });
    }
    return sorted;
  }, [safeModels, category, query, sortBy, defaultCategory]);

  const visibleModels = useMemo(
    () => filteredModels.slice(0, MAX_RENDERED_ROWS),
    [filteredModels]
  );

  const trimmedQuery = query.trim();
  const showCustomApply =
    trimmedQuery.includes("/") &&
    !safeModels.some((m) => m.id.toLowerCase() === trimmedQuery.toLowerCase());

  const triggerCost = formatTriggerCost(selectedModel?.pricing);
  const triggerCtx = formatContextLength(selectedModel?.context_length);

  const handleSelect = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery("");
  };

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-md border border-white/15 bg-eigenia-obsidian text-left transition-colors hover:border-eigenia-orange/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-eigenia-orange",
          compact ? "px-2.5 py-1.5" : "px-3 py-2"
        )}
      >
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "truncate font-medium text-white",
                compact ? "text-[11px]" : "text-xs"
              )}
            >
              {selectedModel
                ? getModelDisplayName(selectedModel)
                : value || placeholder}
            </span>
            {selectedModel?.model_type && (
              <Badge variant="default" className="px-1.5 py-0 text-[9px]">
                {selectedModel.model_type}
              </Badge>
            )}
            {triggerCost && (
              <Badge
                variant={getCostTierVariant(selectedModel?.pricing)}
                className="px-1.5 py-0 text-[9px]"
              >
                {triggerCost}
              </Badge>
            )}
            {triggerCtx && (
              <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                {triggerCtx} ctx
              </Badge>
            )}
          </div>
          {value && (
            <div className="truncate font-mono text-[10px] text-eigenia-muted">
              {value}
            </div>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-eigenia-muted transition-transform",
            open && "rotate-180 text-eigenia-orange"
          )}
        />
      </button>

      {/* Popover Panel */}
      {open && (
        <div
          className={cn(
            "absolute left-0 right-0 z-50 mt-1.5 flex flex-col overflow-hidden rounded-lg border border-eigenia-orange/40 bg-eigenia-shell shadow-2xl",
            compact ? "min-w-[300px]" : "min-w-[340px]"
          )}
        >
          {/* Search + Sort + Refresh Controls */}
          <div className="space-y-2 border-b border-white/10 bg-eigenia-obsidian/90 p-2.5">
            <div className="flex items-center gap-1.5">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-eigenia-muted" />
                <Input
                  ref={searchInputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search models, provider, capability, or paste org/model..."
                  className="h-8 pl-8 pr-7 font-mono text-[11px]"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    aria-label="Clear search"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-eigenia-muted hover:text-white"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {onRefreshModels && (
                <Button
                  type="button"
                  size="icon"
                  variant="secondary"
                  disabled={loading}
                  onClick={() => onRefreshModels()}
                  title="Refresh live OpenRouter catalog"
                >
                  <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin text-eigenia-sky")} />
                </Button>
              )}
            </div>

            {/* Category Filter Chips */}
            <div className="flex flex-wrap gap-1">
              {CATEGORY_META.map((cat) => {
                const count = categoryCounts[cat.key] ?? 0;
                const active = category === cat.key;
                return (
                  <button
                    key={cat.key}
                    type="button"
                    onClick={() =>
                      setCategory((prev) =>
                        prev === cat.key && cat.key !== "all" ? "all" : cat.key
                      )
                    }
                    className={cn(
                      "inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[10px] transition-colors",
                      active
                        ? "border-eigenia-orange bg-eigenia-orange/20 text-white"
                        : "border-white/10 bg-eigenia-surface text-eigenia-muted hover:border-white/25 hover:text-white"
                    )}
                  >
                    <span>{cat.label}</span>
                    <span className={active ? "text-eigenia-orange" : "text-eigenia-muted/80"}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Sort Selector & Result Count */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
              <span className="font-mono text-[10px] text-eigenia-muted">
                {loading
                  ? "Syncing OpenRouter catalog..."
                  : `${filteredModels.length} matching model${filteredModels.length === 1 ? "" : "s"}`}
              </span>
              <div className="flex items-center gap-1.5">
                <label className="font-mono text-[10px] text-eigenia-muted">Sort:</label>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortKey)}
                  className="h-6 rounded border border-white/15 bg-eigenia-surface px-2 font-mono text-[10px] text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                >
                  <option value="recommended" className="bg-eigenia-obsidian">
                    Recommended
                  </option>
                  <option value="cost_asc" className="bg-eigenia-obsidian">
                    Cost: Low → High
                  </option>
                  <option value="cost_desc" className="bg-eigenia-obsidian">
                    Cost: High → Low
                  </option>
                  <option value="context_desc" className="bg-eigenia-obsidian">
                    Context: Largest
                  </option>
                  <option value="name_asc" className="bg-eigenia-obsidian">
                    Name (A → Z)
                  </option>
                  <option value="provider_asc" className="bg-eigenia-obsidian">
                    Provider
                  </option>
                </select>
              </div>
            </div>
          </div>

          {/* Custom Model ID Apply Row */}
          {showCustomApply && (
            <button
              type="button"
              onClick={() => handleSelect(trimmedQuery)}
              className="flex items-center gap-2 border-b border-eigenia-sky/30 bg-eigenia-sky/10 px-3 py-2 text-left font-mono text-[11px] text-eigenia-sky transition hover:bg-eigenia-sky/20"
            >
              <PlusCircle className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">
                Use custom OpenRouter model ID: <strong className="text-white">{trimmedQuery}</strong>
              </span>
            </button>
          )}

          {/* Scrollable Model List */}
          <div className="max-h-80 overflow-y-auto divide-y divide-white/5">
            {visibleModels.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 p-6 text-center">
                <Sparkles className="h-5 w-5 text-eigenia-muted" />
                <div className="font-mono text-xs text-eigenia-muted">
                  No models matched &ldquo;{query}&rdquo; in {category.replace("_", " ")}.
                </div>
                {category !== "all" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => setCategory("all")}
                  >
                    Show All Categories ({categoryCounts.all})
                  </Button>
                )}
              </div>
            ) : (
              visibleModels.map((model) => {
                const isSelected = model.id === value;
                const provider = getModelProvider(model);
                const modalities = getModalityPills(model);
                const ctxLabel = formatContextLength(model.context_length);
                const pricing = model.pricing;

                return (
                  <button
                    key={model.id}
                    type="button"
                    onClick={() => handleSelect(model.id)}
                    className={cn(
                      "flex w-full flex-col gap-1.5 px-3 py-2.5 text-left transition-colors",
                      isSelected
                        ? "bg-eigenia-orange/15"
                        : "hover:bg-white/5"
                    )}
                  >
                    {/* Row Header: Name + Provider + Selected Check */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-xs font-semibold text-white">
                            {getModelDisplayName(model)}
                          </span>
                          <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                            {provider}
                          </Badge>
                          {model.model_type && (
                            <Badge variant="default" className="px-1.5 py-0 text-[9px]">
                              {model.model_type}
                            </Badge>
                          )}
                        </div>
                        <div className="mt-0.5 truncate font-mono text-[10px] text-eigenia-muted">
                          {model.id}
                        </div>
                      </div>
                      {isSelected && (
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-eigenia-orange" />
                      )}
                    </div>

                    {/* Row Footer: Cost, Modality Pills, Context Window */}
                    <div className="flex flex-wrap items-center justify-between gap-1.5">
                      <div className="flex flex-wrap items-center gap-1">
                        {pricing ? (
                          pricing.is_free ? (
                            <Badge variant="sky" className="px-1.5 py-0 text-[9px]">
                              FREE
                            </Badge>
                          ) : (
                            <>
                              <span className="font-mono text-[10px] text-eigenia-ink">
                                In {formatUsdRate(pricing.prompt_per_1m_usd)} · Out{" "}
                                {formatUsdRate(pricing.completion_per_1m_usd)} / 1M
                              </span>
                              {pricing.image_per_1k_usd != null && pricing.image_per_1k_usd > 0 && (
                                <span className="font-mono text-[10px] text-eigenia-sky">
                                  · Img {formatUsdRate(pricing.image_per_1k_usd)}/1K
                                </span>
                              )}
                              {pricing.cost_tier && (
                                <Badge
                                  variant={getCostTierVariant(pricing)}
                                  className="px-1.5 py-0 text-[9px]"
                                >
                                  {pricing.cost_tier}
                                </Badge>
                              )}
                            </>
                          )
                        ) : (
                          <span className="font-mono text-[10px] text-eigenia-muted">
                            {model.tier}
                          </span>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-1">
                        {modalities.map((mod) => (
                          <span
                            key={mod}
                            className="rounded border border-white/10 bg-eigenia-obsidian px-1.5 py-0.5 font-mono text-[9px] uppercase text-eigenia-muted"
                          >
                            {mod}
                          </span>
                        ))}
                        {ctxLabel && (
                          <Badge variant="neutral" className="px-1.5 py-0 text-[9px]">
                            {ctxLabel} ctx
                          </Badge>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {filteredModels.length > MAX_RENDERED_ROWS && (
            <div className="border-t border-white/10 bg-eigenia-obsidian px-3 py-1.5 text-center font-mono text-[10px] text-eigenia-muted">
              Showing {MAX_RENDERED_ROWS} of {filteredModels.length} — refine search to narrow
            </div>
          )}
        </div>
      )}
    </div>
  );
}
