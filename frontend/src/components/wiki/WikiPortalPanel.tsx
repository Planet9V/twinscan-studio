"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Clock,
  Compass,
  HelpCircle,
  Loader2,
  RefreshCw,
  Rocket,
  Search,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SegmentedTabs, type SegmentedTabItem } from "@/components/ui/SegmentedTabs";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { OnboardingWizard } from "@/components/wiki/OnboardingWizard";
import { WikiMarkdownView } from "@/components/wiki/WikiMarkdownView";
import { WikiSiteTreeFlow } from "@/components/wiki/WikiSiteTreeFlow";
import {
  getWikiCatalogue,
  getWikiPage,
  type WikiCatalogueResponse,
  type WikiPageDetail,
  type WikiPageSummary,
} from "@/lib/wikiApi";
import { cn } from "@/lib/utils";

type WikiTab = "wizard" | "docs" | "sitetree" | "support";

const SUPPORT_CARDS: Array<{
  title: string;
  symptom: string;
  fix: string;
  actionHref: string;
  actionLabel: string;
}> = [
  {
    title: "LD19 360° LiDAR Not Showing /dev/ttyUSB0",
    symptom: "USB-A port shows no CP210x serial device or power-cycles continuously.",
    fix: "Verify you are using a 4-wire USB data cable (not a charge-only cable) and check Pi 5 USB total draw (<1600 mA) on /catalog.",
    actionHref: "/catalog?tab=hardware",
    actionLabel: "Inspect 3D Pi 5 USB Bus",
  },
  {
    title: "WonderEcho Pro USB Mic / Speaker Missing",
    symptom: "Voice diagnostics report ALSA card missing or high noise floor.",
    fix: "Keep WonderEcho Pro plugged into Pi 5 USB 2.0 Port 1-2 (black port) and run the 6-Step Diagnostics & 4s Live Mic Test.",
    actionHref: "/voice?tab=diagnostics",
    actionLabel: "Run Voice Diagnostics",
  },
  {
    title: "ROS 2 Humble Container or LD19 Duplicate Node",
    symptom: "Multiple ldlidar_stl_ros2_node processes or stale /scan rate.",
    fix: "Use 1-click Probe / Start LD19 LiDAR on /patrol — Eigenia enforces single-instance PID deduplication automatically.",
    actionHref: "/patrol",
    actionLabel: "Open Patrol & LiDAR",
  },
  {
    title: "Pi 5 MicroSD Disk Usage >= 85%",
    symptom: "Docker or ROS 2 logs fill the SD card during long mapping sessions.",
    fix: "Use the safe 1-click Clean Stale Logs maintenance action on /catalog to prune only >24h rotated *.log files.",
    actionHref: "/catalog?tab=hardware",
    actionLabel: "Clean Stale Logs",
  },
  {
    title: "Low 2S LiPo Battery During Autonomous Mapping",
    symptom: "PuppyPi battery approaches 7.1V during room exploration.",
    fix: "Stage 3 Autonomous Explorer triggers automatic Return-to-Home (RTH) with AprilTag #0 alignment and safe crouch at 7.1V.",
    actionHref: "/patrol?tab=explore",
    actionLabel: "Configure Auto-RTH",
  },
  {
    title: "OpenRouter API Key or 501-Model Selection",
    symptom: "Deep Identify or Lab Architect falls back to deterministic offline synthesis.",
    fix: "Add & test your OpenRouter key in /config?tab=ai (encrypted in PostgreSQL 18; local YOLO11n, Face ID & 3D Depth V2 work 100% offline).",
    actionHref: "/config?tab=ai",
    actionLabel: "Open AI Settings",
  },
];

export function WikiPortalPanel(): React.JSX.Element {
  const [activeTab, setActiveTab] = useState<WikiTab>("wizard");
  const [catalogue, setCatalogue] = useState<WikiCatalogueResponse | null>(null);
  const [loadingCat, setLoadingCat] = useState(false);
  const [catError, setCatError] = useState<string | null>(null);

  const [selectedSlug, setSelectedSlug] = useState<string>("00-introduction");
  const [pageDetail, setPageDetail] = useState<WikiPageDetail | null>(null);
  const [loadingPage, setLoadingPage] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const syncUrl = useCallback((nextTab: WikiTab, nextSlug?: string) => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    sp.set("tab", nextTab);
    if (nextTab === "docs" && nextSlug) {
      sp.set("page", nextSlug);
    } else if (nextTab !== "docs") {
      sp.delete("page");
    }
    const qs = sp.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, []);

  const loadCatalogue = useCallback(async () => {
    setLoadingCat(true);
    setCatError(null);
    try {
      const res = await getWikiCatalogue();
      setCatalogue(res);
      if (res.pages.length > 0) {
        setSelectedSlug((prev) =>
          res.pages.some((p) => p.slug === prev) ? prev : res.pages[0].slug
        );
      }
    } catch (err) {
      setCatError(err instanceof Error ? err.message : "Failed to load Wiki catalogue");
    } finally {
      setLoadingCat(false);
    }
  }, []);

  const loadPage = useCallback(async (slug: string) => {
    if (!slug) return;
    setLoadingPage(true);
    setPageError(null);
    try {
      const detail = await getWikiPage(slug);
      setPageDetail(detail);
    } catch (err) {
      setPageError(err instanceof Error ? err.message : `Failed to load wiki page "${slug}"`);
    } finally {
      setLoadingPage(false);
    }
  }, []);

  // Safe client-only URL query hydration (Next.js 16 prerender safe)
  useEffect(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      const tab = sp.get("tab");
      const page = sp.get("page");
      if (tab === "wizard" || tab === "docs" || tab === "sitetree" || tab === "support") {
        setActiveTab(tab);
      }
      if (page && /^[a-z0-9-]+$/i.test(page)) {
        setSelectedSlug(page.toLowerCase());
      }
    }
    void loadCatalogue();
  }, [loadCatalogue]);

  useEffect(() => {
    if (activeTab === "docs" && selectedSlug) {
      void loadPage(selectedSlug);
    }
  }, [activeTab, selectedSlug, loadPage]);

  const handleOpenWikiPage = useCallback(
    (slug: string) => {
      const clean = slug.replace(/\.md$/i, "").toLowerCase();
      setSelectedSlug(clean);
      setActiveTab("docs");
      syncUrl("docs", clean);
    },
    [syncUrl]
  );

  const handleTabChange = (next: string) => {
    const t = next as WikiTab;
    setActiveTab(t);
    syncUrl(t, t === "docs" ? selectedSlug : undefined);
  };

  const pages: WikiPageSummary[] = catalogue?.pages ?? [];
  const filteredPages = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return pages;
    return pages.filter((p) =>
      `${p.title} ${p.description} ${p.category} ${p.audience} ${p.excerpt} ${p.slug}`
        .toLowerCase()
        .includes(q)
    );
  }, [pages, searchQuery]);

  const tabs: SegmentedTabItem[] = [
    { id: "wizard", label: "Onboarding Wizard", icon: <Rocket className="h-3.5 w-3.5" /> },
    {
      id: "docs",
      label: "Wiki Docs",
      count: pages.length || undefined,
      icon: <BookOpen className="h-3.5 w-3.5" />,
    },
    { id: "sitetree", label: "Interactive Site Tree", icon: <Compass className="h-3.5 w-3.5" /> },
    { id: "support", label: "Support & FAQ", icon: <HelpCircle className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
      <WorkspaceHeader
        badge="WIKI & WIZARD"
        title="EIGENIA MAKER KNOWLEDGE BASE & ONBOARDING"
        subtitle={`Flagship Example: ${catalogue?.flagship_example ?? "Hiwonder PuppyPi Pro"} · Interactive 4-Step Wizard, Architecture Docs & Site Tree`}
        statusTone={catError ? "warning" : "ok"}
        statusLabel={catError ? "CATALOGUE RETRY" : `${pages.length || 10} WIKI GUIDES`}
        metrics={[
          { label: "Wiki Guides", value: pages.length, tone: "sky", compact: true },
          { label: "Workspaces", value: 12, tone: "orange", compact: true },
          { label: "Flagship", value: "PuppyPi Pro", tone: "emerald", compact: true },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Button size="sm" variant="default" asChild>
              <Link href="/welcome">
                <Rocket className="h-3.5 w-3.5" />
                Maker Showcase
              </Link>
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={loadingCat}
              onClick={() => void loadCatalogue()}
              title="Refresh Wiki Catalogue"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loadingCat && "animate-spin")} />
            </Button>
          </div>
        }
      />

      <SegmentedTabs tabs={tabs} value={activeTab} onValueChange={handleTabChange} />

      {/* TAB 1: ONBOARDING WIZARD */}
      {activeTab === "wizard" && <OnboardingWizard onOpenWikiPage={handleOpenWikiPage} />}

      {/* TAB 2: WIKI DOCS */}
      {activeTab === "docs" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left Sidebar Catalogue */}
          <Card className="h-fit border-white/10 lg:sticky lg:top-24 lg:col-span-3">
            <CardHeader className="space-y-2.5 pb-3">
              <CardTitle className="flex items-center gap-2 text-xs">
                <BookOpen className="h-3.5 w-3.5 text-eigenia-orange" />
                Documentation Catalogue
              </CardTitle>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter guides..."
                  className="h-8 pl-8 text-xs"
                />
              </div>
            </CardHeader>
            <CardContent className="max-h-[65vh] space-y-1 overflow-y-auto pt-0">
              {loadingCat && pages.length === 0 ? (
                <div className="flex items-center gap-2 py-6 font-mono text-xs text-eigenia-muted">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading wiki index...
                </div>
              ) : filteredPages.length === 0 ? (
                <div className="py-6 text-center font-mono text-xs text-eigenia-muted">
                  No wiki guides match &ldquo;{searchQuery}&rdquo;.
                </div>
              ) : (
                filteredPages.map((p) => {
                  const active = p.slug === selectedSlug;
                  return (
                    <button
                      key={p.slug}
                      type="button"
                      onClick={() => handleOpenWikiPage(p.slug)}
                      className={cn(
                        "flex w-full flex-col gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors motion-reduce:transition-none",
                        active
                          ? "border-eigenia-orange/60 bg-eigenia-orange/15 text-white"
                          : "border-transparent text-eigenia-ink hover:bg-white/5 hover:text-white"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-semibold">{p.title}</span>
                        <span className="shrink-0 font-mono text-[9px] text-eigenia-muted">
                          {p.read_minutes}m
                        </span>
                      </div>
                      <span className="truncate font-mono text-[10px] text-eigenia-muted">
                        {p.category} · {p.audience}
                      </span>
                    </button>
                  );
                })
              )}
            </CardContent>
          </Card>

          {/* Right Markdown Reader */}
          <Card className="border-white/10 lg:col-span-9">
            <CardContent className="p-5 sm:p-6">
              {loadingPage ? (
                <div className="flex min-h-[320px] items-center justify-center gap-2 font-mono text-xs text-eigenia-muted">
                  <Loader2 className="h-4 w-4 animate-spin text-eigenia-orange" />
                  Loading documentation article...
                </div>
              ) : pageError ? (
                <div className="space-y-3 rounded-lg border border-eigenia-fault/40 bg-eigenia-fault/15 p-4 font-mono text-xs text-eigenia-fault">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertTriangle className="h-4 w-4" />
                    {pageError}
                  </div>
                  <Button size="sm" variant="secondary" onClick={() => void loadPage(selectedSlug)}>
                    Retry
                  </Button>
                </div>
              ) : pageDetail ? (
                <div className="space-y-5">
                  {/* Meta Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="default">{pageDetail.category}</Badge>
                      <Badge variant="sky">{pageDetail.audience}</Badge>
                      <Badge variant="neutral" className="font-mono text-[10px]">
                        <Clock className="h-3 w-3" />
                        {pageDetail.read_minutes} min read
                      </Badge>
                    </div>
                    <span className="font-mono text-[10px] text-eigenia-muted">
                      docs/wiki/{pageDetail.slug}.md
                    </span>
                  </div>

                  {pageDetail.description && (
                    <p className="rounded-lg border border-white/10 bg-eigenia-obsidian px-3.5 py-2.5 text-xs text-eigenia-muted">
                      {pageDetail.description}
                    </p>
                  )}

                  {/* Rendered Markdown */}
                  <WikiMarkdownView
                    markdown={pageDetail.markdown}
                    onNavigateSlug={handleOpenWikiPage}
                  />

                  {/* Prev / Next Navigation */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 pt-4">
                    {pageDetail.prev_slug ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => handleOpenWikiPage(pageDetail.prev_slug!)}
                      >
                        <ArrowLeft className="h-3.5 w-3.5" />
                        Previous: {pageDetail.prev_slug}
                      </Button>
                    ) : (
                      <div />
                    )}
                    {pageDetail.next_slug && (
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => handleOpenWikiPage(pageDetail.next_slug!)}
                      >
                        Next: {pageDetail.next_slug}
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="py-16 text-center font-mono text-xs text-eigenia-muted">
                  Select a Wiki guide on the left to start reading.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB 3: INTERACTIVE SITE TREE */}
      {activeTab === "sitetree" && <WikiSiteTreeFlow onOpenWikiPage={handleOpenWikiPage} />}

      {/* TAB 4: SUPPORT & FAQ */}
      {activeTab === "support" && (
        <div className="space-y-4">
          <Card className="border-eigenia-amber/40 bg-eigenia-shell">
            <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Wrench className="h-4 w-4 text-eigenia-orange" />
                  PuppyPi Pro &amp; Docker Support Runbook
                </div>
                <p className="text-xs text-eigenia-muted">
                  Battle-tested fixes from real hardware bring-up — or open the complete
                  Troubleshooting Runbook inside Wiki Docs.
                </p>
              </div>
              <Button
                size="sm"
                variant="default"
                onClick={() => handleOpenWikiPage("07-support-troubleshooting")}
              >
                <BookOpen className="h-3.5 w-3.5" />
                Open Full Troubleshooting Wiki
              </Button>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {SUPPORT_CARDS.map((card) => (
              <Card
                key={card.title}
                className="flex flex-col justify-between border-white/10 bg-eigenia-surface"
              >
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-white">{card.title}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-between gap-3">
                  <div className="space-y-2 text-xs">
                    <div className="rounded border border-eigenia-amber/30 bg-eigenia-amber/10 px-2.5 py-1.5 text-eigenia-amber">
                      <span className="font-mono text-[10px] font-bold uppercase">Symptom: </span>
                      {card.symptom}
                    </div>
                    <p className="leading-relaxed text-eigenia-ink">{card.fix}</p>
                  </div>
                  <Button size="sm" variant="secondary" asChild className="w-full">
                    <Link href={card.actionHref}>
                      {card.actionLabel}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
