"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, Compass, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TopologyFlowCanvas,
  type TopologyEdgeSpec,
  type TopologyNodeSpec,
} from "@/components/ui/TopologyFlowCanvas";

export interface WikiSiteTreeFlowProps {
  onOpenWikiPage?: (slug: string) => void;
}

interface SiteNodeDetail {
  id: string;
  route: string | null;
  label: string;
  subtitle: string;
  category: string;
  metric: string;
  status: "ok" | "warning" | "idle";
  x: number;
  y: number;
  description: string;
  queryTabs: string[];
  apiPrefixes: string[];
  wikiSlug: string;
}

const SITE_NODES: SiteNodeDetail[] = [
  // Column 1: Entry & Discovery
  {
    id: "route-welcome",
    route: "/welcome",
    label: "Maker Showcase",
    subtitle: "/welcome",
    category: "Entry",
    metric: "3D + Early Bird",
    status: "ok",
    x: 20,
    y: 30,
    description:
      "Full-bleed interactive PuppyPi Pro 3D showcase, React Flow architecture explorer, and First-50 Early Bird Maker Founders reservation.",
    queryTabs: [],
    apiPrefixes: ["/api/early-bird/*"],
    wikiSlug: "00-introduction",
  },
  {
    id: "route-home",
    route: "/",
    label: "Mission Control",
    subtitle: "/ (Command Home)",
    category: "Entry",
    metric: "Fleet KPIs",
    status: "ok",
    x: 20,
    y: 175,
    description:
      "Fleet overview, 1-click PuppyPi & LAN discovery, live robot cards, room coverage metrics, and spatial dark-zone priority alerts.",
    queryTabs: [],
    apiPrefixes: ["/api/robots/*", "/api/spaces/*"],
    wikiSlug: "04-user-directions",
  },
  {
    id: "route-wiki",
    route: "/wiki",
    label: "Wiki & Wizard",
    subtitle: "/wiki",
    category: "Entry",
    metric: "4-Step Wizard",
    status: "ok",
    x: 20,
    y: 320,
    description:
      "Interactive Maker Onboarding Wizard with live readiness probe, complete VitePress-grade documentation, site tree, and troubleshooting runbook.",
    queryTabs: ["?tab=wizard", "?tab=docs", "?tab=sitetree", "?tab=support"],
    apiPrefixes: ["/api/wiki/*", "/health"],
    wikiSlug: "08-site-tree",
  },

  // Column 2: Real-Time Robotics & Perception
  {
    id: "route-twin",
    route: "/twin",
    label: "Spatial LiDAR Twin",
    subtitle: "/twin",
    category: "Perception",
    metric: "2D + 3D + .GLB",
    status: "ok",
    x: 290,
    y: 20,
    description:
      "Synchronized 2D LD19 Tactical Radar, 3D Three.js & Babylon.js 9 PBR Twin, Camera+LiDAR+Depth Anything V2 wall fusion, and 1-click Full-Room .glb export.",
    queryTabs: [],
    apiPrefixes: ["/api/lidar/*", "/api/spaces/*/reconstruct/*"],
    wikiSlug: "03-capabilities-guide",
  },
  {
    id: "route-control",
    route: "/control",
    label: "Robot Control & FPV",
    subtitle: "/control",
    category: "Robotics",
    metric: "28 Actions",
    status: "ok",
    x: 290,
    y: 145,
    description:
      "Sticky live FPV camera & dead-man velocity pad paired with 28 verified PuppyPi ActionGroups, gait/servo sliders, RGB LEDs, OLED & buzzer.",
    queryTabs: ["?tab=actions", "?tab=motion", "?tab=peripherals"],
    apiPrefixes: ["/api/robots/*/control/*", "/api/robots/*/video/*"],
    wikiSlug: "04-user-directions",
  },
  {
    id: "route-vision",
    route: "/vision",
    label: "AI Vision & Memory",
    subtitle: "/vision",
    category: "Perception",
    metric: "YOLO + Face ID",
    status: "ok",
    x: 290,
    y: 270,
    description:
      "YuNet + SFace 128-D face recognition, YOLO11n animals/objects, click-to-track, Line Follow v2, Bento/Grid/Line Spatial Memory Pro, and Sentry Guard.",
    queryTabs: ["?tab=live", "?tab=memory", "?tab=sentry"],
    apiPrefixes: ["/api/robots/*/ai-vision/*", "/api/people/*", "/api/spatial-memory/*"],
    wikiSlug: "03-capabilities-guide",
  },
  {
    id: "route-patrol",
    route: "/patrol",
    label: "Patrol & Explorer",
    subtitle: "/patrol",
    category: "Autonomy",
    metric: "VFH + RTH",
    status: "ok",
    x: 290,
    y: 395,
    description:
      "2D waypoint patrol planner + Stage 3 Autonomous Frontier Dark-Zone Explorer, multi-pitch 3D mapper, live FPV PiP, and low-battery Return-to-Home.",
    queryTabs: ["?tab=patrol", "?tab=explore"],
    apiPrefixes: ["/api/robots/*/patrol/*", "/api/robots/*/explore/*"],
    wikiSlug: "04-user-directions",
  },

  // Column 3: Hardware, Voice, Co-Design & Graph
  {
    id: "route-voice",
    route: "/voice",
    label: "Voice & OX",
    subtitle: "/voice",
    category: "Assistant",
    metric: "7-Stage Flow",
    status: "ok",
    x: 560,
    y: 20,
    description:
      "Hands-free Hey OX wake word, Faster-Whisper STT, OpenRouter LLM personas, Piper/Edge neural TTS, WonderEcho Pro ALSA EQ, and 7-stage audio flow.",
    queryTabs: ["?tab=live", "?tab=personas", "?tab=diagnostics"],
    apiPrefixes: ["/api/robots/*/voice/*"],
    wikiSlug: "03-capabilities-guide",
  },
  {
    id: "route-catalog",
    route: "/catalog",
    label: "Fleet BOM & SBOM",
    subtitle: "/catalog",
    category: "Hardware",
    metric: "3D Pi 5 Twin",
    status: "ok",
    x: 560,
    y: 145,
    description:
      "3D Raspberry Pi 5 BOM Twin + React Flow USB/PMIC Bus Graph, CycloneDX SBOM, Safe Updates with Docker rollback, and 1-click Pi 5 log cleanup.",
    queryTabs: ["?tab=hardware", "?tab=bom", "?tab=sbom", "?tab=updates", "?tab=fleet"],
    apiPrefixes: ["/api/robots/*/hardware-diagnostics", "/api/robots/*/updates/*", "/api/robots/*/maintenance/*"],
    wikiSlug: "05-admin-guide",
  },
  {
    id: "route-architect",
    route: "/architect",
    label: "Lab Architect",
    subtitle: "/architect",
    category: "Co-Design",
    metric: "5-Tier AI",
    status: "ok",
    x: 560,
    y: 270,
    description:
      "Human-AI hardware co-design with 5-tier creativity dial, 2D wiring + 3D assembly, Lab Inventory, BBC micro:bit Studio, and 100% cloud-free local camera bridges.",
    queryTabs: ["?tab=studio", "?tab=ideas", "?tab=inventory", "?tab=profiles", "?tab=blueprints"],
    apiPrefixes: ["/api/architect/*", "/api/inventory/*", "/api/devices/*"],
    wikiSlug: "03-capabilities-guide",
  },
  {
    id: "route-graph",
    route: "/graph",
    label: "Knowledge Graph",
    subtitle: "/graph",
    category: "Graph",
    metric: "G_CPDT + Vec",
    status: "ok",
    x: 560,
    y: 395,
    description:
      "Interactive cyber-physical asset & dark-zone graph powered by Neo4j 5 and PostgreSQL 18 halfvec pgvector semantic search.",
    queryTabs: [],
    apiPrefixes: ["/api/spaces/*/graph", "/api/equipment/search"],
    wikiSlug: "01-onboarding-principal",
  },
  {
    id: "route-config",
    route: "/config",
    label: "Config & Admin",
    subtitle: "/config",
    category: "Admin",
    metric: "ROS 1 <-> 2",
    status: "ok",
    x: 560,
    y: 520,
    description:
      "OpenRouter 501-model picker, encrypted API key storage, PuppyPi Wi-Fi/SSH/ROS 1↔2 switching, and PostgreSQL 18 binary storage management.",
    queryTabs: ["?tab=ai", "?tab=robot", "?tab=databases"],
    apiPrefixes: ["/api/admin/*", "/api/robots/*/config/*", "/api/files/*"],
    wikiSlug: "05-admin-guide",
  },

  // Column 4: Backend Core Engines
  {
    id: "engine-rosbridge",
    route: null,
    label: "ROS 2 & SSH Engine",
    subtitle: "ROSBridge + LD19 + FPV",
    category: "Backend",
    metric: "6.9 Hz /scan",
    status: "ok",
    x: 840,
    y: 90,
    description:
      "Auto-attaching ROSBridge WebSocket client with type-mismatch watchdog, stdlib PTY SSH manager, and single-instance LD19 deduplication.",
    queryTabs: [],
    apiPrefixes: ["/api/lidar/stream", "/api/robots/*"],
    wikiSlug: "06-developer-guide",
  },
  {
    id: "engine-ai",
    route: null,
    label: "AI Vision & Depth",
    subtitle: "YOLO11n · SFace · OpenRouter",
    category: "Backend",
    metric: "Local + VLM",
    status: "ok",
    x: 840,
    y: 230,
    description:
      "Local ONNX object/face/depth inference paired with optional OpenRouter VLM and 5-tier Lab Architect synthesis.",
    queryTabs: [],
    apiPrefixes: ["/api/vision/*", "/api/architect/*"],
    wikiSlug: "06-developer-guide",
  },
  {
    id: "engine-pg18",
    route: null,
    label: "PostgreSQL 18",
    subtitle: "pgvector + Blobs + Memory",
    category: "Storage",
    metric: "100% Local",
    status: "ok",
    x: 840,
    y: 370,
    description:
      "Primary relational + vector + binary asset database storing rooms, 3D panels, Spatial Memory snapshots, inventory, blueprints, and Early Bird signups.",
    queryTabs: [],
    apiPrefixes: ["/api/files/*", "/api/spatial-memory/*", "/api/early-bird/*"],
    wikiSlug: "05-admin-guide",
  },
  {
    id: "engine-neo4j",
    route: null,
    label: "Neo4j 5 Graph",
    subtitle: "G_CPDT Spatial Topology",
    category: "Storage",
    metric: "Cypher Sync",
    status: "ok",
    x: 840,
    y: 500,
    description:
      "Maintains Facility → Space → Equipment → Robot → DarkZone topology with vulnerability posture & spatial proximity edges.",
    queryTabs: [],
    apiPrefixes: ["/api/spaces/*/graph", "/api/admin/reconcile-neo4j"],
    wikiSlug: "01-onboarding-principal",
  },
];

const SITE_EDGES: TopologyEdgeSpec[] = [
  { id: "e-w-h", source: "route-welcome", target: "route-home", label: "Launch", status: "ok", animated: true },
  { id: "e-w-wk", source: "route-welcome", target: "route-wiki", label: "Wizard", status: "ok" },
  { id: "e-h-twin", source: "route-home", target: "route-twin", status: "ok" },
  { id: "e-h-ctrl", source: "route-home", target: "route-control", status: "ok" },
  { id: "e-h-vis", source: "route-home", target: "route-vision", status: "ok" },
  { id: "e-h-pat", source: "route-home", target: "route-patrol", status: "ok" },
  { id: "e-twin-ros", source: "route-twin", target: "engine-rosbridge", label: "/scan", status: "ok", animated: true },
  { id: "e-twin-ai", source: "route-twin", target: "engine-ai", label: "Depth V2", status: "ok" },
  { id: "e-ctrl-ros", source: "route-control", target: "engine-rosbridge", label: "cmd_vel", status: "ok", animated: true },
  { id: "e-pat-ros", source: "route-patrol", target: "engine-rosbridge", label: "VFH/RTH", status: "ok", animated: true },
  { id: "e-vis-ai", source: "route-vision", target: "engine-ai", label: "YOLO+SFace", status: "ok", animated: true },
  { id: "e-vis-pg", source: "route-vision", target: "engine-pg18", label: "Memory", status: "ok" },
  { id: "e-voi-ai", source: "route-voice", target: "engine-ai", label: "STT/LLM/TTS", status: "ok" },
  { id: "e-cat-ros", source: "route-catalog", target: "engine-rosbridge", label: "Pi 5 SSH", status: "ok" },
  { id: "e-arch-ai", source: "route-architect", target: "engine-ai", label: "Co-Design", status: "ok", animated: true },
  { id: "e-arch-pg", source: "route-architect", target: "engine-pg18", label: "Inventory", status: "ok" },
  { id: "e-gr-neo", source: "route-graph", target: "engine-neo4j", label: "G_CPDT", status: "ok", animated: true },
  { id: "e-gr-pg", source: "route-graph", target: "engine-pg18", label: "pgvector", status: "ok" },
  { id: "e-cfg-pg", source: "route-config", target: "engine-pg18", label: "Secrets/Blobs", status: "ok" },
];

export function WikiSiteTreeFlow({ onOpenWikiPage }: WikiSiteTreeFlowProps): React.JSX.Element {
  const [selectedId, setSelectedId] = useState<string>("route-twin");

  const flowNodes = useMemo<TopologyNodeSpec[]>(
    () =>
      SITE_NODES.map((n) => ({
        id: n.id,
        label: n.label,
        subtitle: n.subtitle,
        category: n.category,
        metric: n.metric,
        status: n.status,
        x: n.x,
        y: n.y,
      })),
    []
  );

  const selected = useMemo(
    () => SITE_NODES.find((n) => n.id === selectedId) ?? SITE_NODES[0],
    [selectedId]
  );

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <div className="xl:col-span-8">
        <TopologyFlowCanvas
          title="Eigenia TwinScan — 12 Workspaces & 4 Live Perception/Storage Engines"
          nodes={flowNodes}
          edges={SITE_EDGES}
          selectedNodeId={selectedId}
          onSelectNode={setSelectedId}
          heightClassName="h-[620px]"
          legend={false}
        />
      </div>

      <div className="xl:col-span-4">
        <Card className="h-full border-eigenia-sky/35">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <Badge variant="default">{selected.category}</Badge>
              <Badge variant="sky">{selected.metric}</Badge>
            </div>
            <CardTitle className="mt-2 flex items-center gap-2 text-base">
              <Compass className="h-4 w-4 text-eigenia-orange" />
              {selected.label}
            </CardTitle>
            <div className="font-mono text-xs text-eigenia-sky">{selected.subtitle}</div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs leading-relaxed text-eigenia-ink">{selected.description}</p>

            {selected.queryTabs.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  <Layers className="h-3 w-3 text-eigenia-orange" />
                  Deep-Link Tabs
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {selected.queryTabs.map((qt) => (
                    <Link
                      key={qt}
                      href={`${selected.route ?? "/"}${qt}`}
                      className="rounded border border-white/15 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px] text-eigenia-sky hover:border-eigenia-orange hover:text-white"
                    >
                      {qt}
                    </Link>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                Backend API Prefixes
              </div>
              <div className="flex flex-wrap gap-1.5">
                {selected.apiPrefixes.map((api) => (
                  <span
                    key={api}
                    className="rounded border border-white/10 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px] text-eigenia-ink"
                  >
                    {api}
                  </span>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-white/10 pt-3">
              {selected.route && (
                <Button size="sm" variant="default" asChild className="flex-1">
                  <Link href={selected.route}>
                    Launch Workspace
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              )}
              {onOpenWikiPage && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onOpenWikiPage(selected.wikiSlug)}
                  className="flex-1"
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  Open Wiki Doc
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
