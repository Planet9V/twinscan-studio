"use client";

import React, { useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Bot,
  Crosshair,
  Database,
  EyeOff,
  Filter,
  Network,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { useStudio } from "@/context/StudioContext";
import { searchEquipmentSemantic } from "@/lib/api";
import type { EquipmentAsset, FocusTarget, GraphPayload } from "@/lib/types";

interface KnowledgeGraphPanelProps {
  spaceId: string;
  graph: GraphPayload | null;
  onSelectEquipment: (id: string) => void;
  onFocusTarget?: (t: FocusTarget) => void;
  onEnrich?: (equipmentId: string) => void;
}

type LayerFilter = "all" | "dark_incomplete" | "hide_tags";

interface EquipmentNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  meta: Record<string, unknown>;
  onSelectEquipment: (id: string) => void;
  onFocusTarget?: (t: FocusTarget) => void;
  onEnrich?: (equipmentId: string) => void;
}

interface DarkZoneNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  meta: Record<string, unknown>;
  onFocusTarget?: (t: FocusTarget) => void;
}

interface StandardNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  meta: Record<string, unknown>;
}

const STANDARD_NODE_PALETTE: Record<string, { border: string; bg: string; accent: string; hex: string }> = {
  Facility: {
    border: "border-eigenia-skyLight/50",
    bg: "bg-eigenia-shell",
    accent: "text-eigenia-skyLight",
    hex: "#7dd3fc",
  },
  Space: {
    border: "border-eigenia-sky/60",
    bg: "bg-eigenia-surface",
    accent: "text-eigenia-sky",
    hex: "#38bdf8",
  },
  Manufacturer: {
    border: "border-eigenia-amber/50",
    bg: "bg-eigenia-shell",
    accent: "text-eigenia-amber",
    hex: "#f59e0b",
  },
  ProductModel: {
    border: "border-white/25",
    bg: "bg-eigenia-shell",
    accent: "text-eigenia-ink",
    hex: "#d4d4d8",
  },
  IndustrialTag: {
    border: "border-eigenia-sky/35",
    bg: "bg-eigenia-obsidian",
    accent: "text-eigenia-skyLight",
    hex: "#7dd3fc",
  },
  CyberIdentifier: {
    border: "border-eigenia-sky/50",
    bg: "bg-eigenia-obsidian",
    accent: "text-eigenia-sky",
    hex: "#38bdf8",
  },
  VulnerabilityPosture: {
    border: "border-eigenia-fault/60",
    bg: "bg-eigenia-fault/15",
    accent: "text-eigenia-fault",
    hex: "#ef4444",
  },
  ChangeAnomaly: {
    border: "border-eigenia-fault/60",
    bg: "bg-eigenia-fault/15",
    accent: "text-eigenia-fault",
    hex: "#ef4444",
  },
  Robot: {
    border: "border-eigenia-orange/80",
    bg: "bg-eigenia-surface",
    accent: "text-eigenia-orange",
    hex: "#E05A10",
  },
  HardwareDevice: {
    border: "border-eigenia-amber/50",
    bg: "bg-eigenia-obsidian",
    accent: "text-eigenia-amber",
    hex: "#f59e0b",
  },
  Container: {
    border: "border-eigenia-sky/50",
    bg: "bg-eigenia-obsidian",
    accent: "text-eigenia-sky",
    hex: "#38bdf8",
  },
};

function EquipmentFlowNode({ data }: NodeProps<Node<EquipmentNodeData>>) {
  const meta = data.meta || {};
  const equipmentId = typeof meta.equipment_id === "string" ? meta.equipment_id : "";
  const status = String(meta.status || "INCOMPLETE").toUpperCase();
  const pct = Math.max(0, Math.min(100, Math.round(Number(meta.completeness_pct ?? 0))));
  const cveCount = Number(meta.cve_count ?? 0);
  const maxEpss = Number(meta.max_epss ?? 0);
  const manufacturer = typeof meta.manufacturer === "string" ? meta.manufacturer : "";
  const modelNumber = typeof meta.model_number === "string" ? meta.model_number : "";
  const x = typeof meta.x === "number" ? meta.x : null;
  const y = typeof meta.y === "number" ? meta.y : null;

  const statusVariant = status === "DARK" ? "fault" : status === "VERIFIED" ? "sky" : "amber";
  const borderClass =
    status === "DARK"
      ? "border-eigenia-fault/70"
      : status === "VERIFIED"
        ? "border-eigenia-sky/70"
        : "border-eigenia-orange/80";
  const barColor =
    pct >= 80 ? "bg-eigenia-sky" : pct >= 45 ? "bg-eigenia-amber" : "bg-eigenia-fault";

  return (
    <div
      className={`w-[245px] rounded-md border ${borderClass} bg-eigenia-surface p-2.5 text-left shadow-md`}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-eigenia-orange !bg-eigenia-obsidian" />

      <div className="flex items-start justify-between gap-1.5">
        <div className="min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-wider text-eigenia-orange">
            Equipment
          </div>
          <div className="truncate text-xs font-semibold text-white">{data.label}</div>
        </div>
        <Badge variant={statusVariant} className="shrink-0 px-1.5 py-0 text-[9px]">
          {status}
        </Badge>
      </div>

      {(manufacturer || modelNumber) && (
        <div className="mt-1 truncate font-mono text-[10px] text-eigenia-muted">
          {[manufacturer, modelNumber].filter(Boolean).join(" · ")}
        </div>
      )}

      {/* Completeness Bar */}
      <div className="mt-2 space-y-1">
        <div className="flex items-center justify-between font-mono text-[9px]">
          <span className="text-eigenia-muted">Completeness</span>
          <span className="tabular-nums text-white">{pct}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
          <div className={`h-full ${barColor}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Cyber Posture Badge */}
      {cveCount > 0 && (
        <div className="mt-2 flex items-center gap-1">
          <Badge variant="fault" className="px-1.5 py-0 text-[9px] tabular-nums">
            <ShieldAlert className="h-2.5 w-2.5" />
            {cveCount} CVEs · EPSS {maxEpss.toFixed(2)}
          </Badge>
        </div>
      )}

      {/* Quick Actions */}
      <div className="mt-2 flex items-center gap-1.5 border-t border-white/10 pt-2">
        {data.onFocusTarget && x !== null && y !== null && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onFocusTarget?.({ x, y, label: data.label, equipmentId });
            }}
            className="inline-flex flex-1 items-center justify-center gap-1 rounded border border-eigenia-sky/35 bg-eigenia-sky/10 px-1.5 py-1 font-mono text-[9px] font-medium text-eigenia-sky hover:bg-eigenia-sky/20"
          >
            <Crosshair className="h-2.5 w-2.5" />
            Focus
          </button>
        )}
        {data.onEnrich && equipmentId && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onEnrich?.(equipmentId);
            }}
            className="inline-flex flex-1 items-center justify-center gap-1 rounded border border-eigenia-orange/50 bg-eigenia-orange/15 px-1.5 py-1 font-mono text-[9px] font-medium text-eigenia-orange hover:bg-eigenia-orange/25"
          >
            <Sparkles className="h-2.5 w-2.5" />
            Enrich
          </button>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-eigenia-sky !bg-eigenia-obsidian" />
    </div>
  );
}

function DarkZoneFlowNode({ data }: NodeProps<Node<DarkZoneNodeData>>) {
  const meta = data.meta || {};
  const priority = Math.round(Number(meta.priority_score ?? 0));
  const nbvX = typeof meta.nbv_x === "number" ? meta.nbv_x : null;
  const nbvY = typeof meta.nbv_y === "number" ? meta.nbv_y : null;
  const targetX = typeof meta.x === "number" ? meta.x : nbvX;
  const targetY = typeof meta.y === "number" ? meta.y : nbvY;
  const action = typeof meta.recommended_action === "string" ? meta.recommended_action : "";

  return (
    <div className="w-[225px] rounded-md border border-eigenia-fault/70 bg-eigenia-obsidian p-2.5 text-left shadow-md">
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-eigenia-fault !bg-eigenia-obsidian" />

      <div className="flex items-start justify-between gap-1.5">
        <div className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider text-eigenia-fault">
          <EyeOff className="h-3 w-3" />
          Dark Zone
        </div>
        <Badge variant="fault" className="px-1.5 py-0 text-[9px] tabular-nums">
          P{priority}
        </Badge>
      </div>

      <div className="mt-1 truncate text-xs font-semibold text-white">{data.label}</div>

      {nbvX !== null && nbvY !== null && (
        <div className="mt-1.5 rounded border border-eigenia-sky/30 bg-eigenia-sky/10 px-1.5 py-0.5 font-mono text-[9px] tabular-nums text-eigenia-sky">
          NBV: ({nbvX.toFixed(2)}m, {nbvY.toFixed(2)}m)
        </div>
      )}

      {action && (
        <div className="mt-1 line-clamp-2 text-[10px] text-eigenia-muted">{action}</div>
      )}

      {data.onFocusTarget && targetX !== null && targetY !== null && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            data.onFocusTarget?.({ x: targetX, y: targetY, label: data.label });
          }}
          className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded border border-eigenia-fault/40 bg-eigenia-fault/15 px-1.5 py-1 font-mono text-[9px] font-medium text-eigenia-fault hover:bg-eigenia-fault/25"
        >
          <Crosshair className="h-2.5 w-2.5" />
          Focus Blind Spot
        </button>
      )}

      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-eigenia-fault !bg-eigenia-obsidian" />
    </div>
  );
}

function StandardFlowNode({ data }: NodeProps<Node<StandardNodeData>>) {
  const palette = STANDARD_NODE_PALETTE[data.nodeType] ?? STANDARD_NODE_PALETTE.ProductModel;
  const isRobot = data.nodeType === "Robot";
  const isRisk = data.nodeType === "VulnerabilityPosture" || data.nodeType === "ChangeAnomaly";

  return (
    <div className={`w-[196px] rounded-md border ${palette.border} ${palette.bg} px-2.5 py-2 text-left`}>
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-white/40 !bg-eigenia-obsidian" />
      <div className={`flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider ${palette.accent}`}>
        {isRobot && <Bot className="h-3 w-3" />}
        {isRisk && <ShieldAlert className="h-3 w-3" />}
        {data.nodeType}
      </div>
      <div className="mt-0.5 truncate font-mono text-[11px] font-medium text-white">{data.label}</div>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-white/40 !bg-eigenia-obsidian" />
    </div>
  );
}

const NODE_TYPES: NodeTypes = {
  equipment: EquipmentFlowNode,
  darkzone: DarkZoneFlowNode,
  standard: StandardFlowNode,
};

export function KnowledgeGraphPanel({
  spaceId,
  graph,
  onSelectEquipment,
  onFocusTarget,
  onEnrich,
}: KnowledgeGraphPanelProps) {
  const { space, refreshSpaceData } = useStudio();
  const [refreshingGraph, setRefreshingGraph] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<EquipmentAsset[]>([]);
  const [layerFilter, setLayerFilter] = useState<LayerFilter>("all");

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!graph || !Array.isArray(graph.nodes)) return { flowNodes: [] as Node[], flowEdges: [] as Edge[] };

    const keptNodes = graph.nodes.filter((n) => {
      if (layerFilter === "hide_tags" && n.node_type === "IndustrialTag") {
        return false;
      }
      if (layerFilter === "dark_incomplete") {
        if (n.node_type === "Equipment") {
          const status = String(n.meta?.status ?? "INCOMPLETE").toUpperCase();
          return status !== "VERIFIED";
        }
        return [
          "Facility",
          "Space",
          "DarkZone",
          "ChangeAnomaly",
          "VulnerabilityPosture",
          "Robot",
        ].includes(n.node_type);
      }
      return true;
    });

    const keptIds = new Set(keptNodes.map((n) => n.id));

    const tierY: Record<string, number> = {
      Facility: 15,
      Space: 115,
      Robot: 115,
      DarkZone: 245,
      ChangeAnomaly: 245,
      Equipment: 245,
      HardwareDevice: 430,
      Container: 430,
      Manufacturer: 455,
      ProductModel: 455,
      VulnerabilityPosture: 455,
      IndustrialTag: 565,
      CyberIdentifier: 565,
    };

    const rowCounts: Record<number, number> = {};

    const nodes: Node[] = keptNodes.map((n) => {
      const y = tierY[n.node_type] ?? 360;
      const col = rowCounts[y] ?? 0;
      rowCounts[y] = col + 1;

      const spacingX = n.node_type === "Equipment" || n.node_type === "DarkZone" ? 270 : 220;

      if (n.node_type === "Equipment") {
        return {
          id: n.id,
          type: "equipment",
          position: { x: 40 + col * spacingX, y },
          data: {
            label: n.label,
            nodeType: n.node_type,
            meta: n.meta,
            onSelectEquipment,
            onFocusTarget,
            onEnrich,
          },
        };
      }

      if (n.node_type === "DarkZone") {
        return {
          id: n.id,
          type: "darkzone",
          position: { x: 40 + col * spacingX, y },
          data: {
            label: n.label,
            nodeType: n.node_type,
            meta: n.meta,
            onFocusTarget,
          },
        };
      }

      return {
        id: n.id,
        type: "standard",
        position: { x: 40 + col * spacingX, y },
        data: {
          label: n.label,
          nodeType: n.node_type,
          meta: n.meta,
        },
      };
    });

    const rawEdges = Array.isArray(graph.edges) ? graph.edges : [];
    const edges: Edge[] = rawEdges
      .filter((e) => keptIds.has(e.source) && keptIds.has(e.target))
      .map((e) => {
        const edgeLabel = String(e.label ?? "");
        const isNear = edgeLabel.startsWith("NEAR");
        const isRisk = edgeLabel.startsWith("EXPOSES") || edgeLabel.startsWith("BLIND_SPOT");
        const stroke = isRisk ? "#ef4444" : isNear ? "#E05A10" : "#38bdf8";
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: edgeLabel,
          animated: isNear || isRisk,
          style: { stroke, strokeWidth: 1.4 },
          labelStyle: { fill: "#B4B4BC", fontSize: 9, fontFamily: "JetBrains Mono, monospace" },
          labelBgStyle: { fill: "#0b0d10", fillOpacity: 0.88 },
        };
      });

    return { flowNodes: nodes, flowEdges: edges };
  }, [graph, layerFilter, onSelectEquipment, onFocusTarget, onEnrich]);

  const handleSemanticSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const resp = await searchEquipmentSemantic(query, spaceId);
      setResults(Array.isArray(resp?.results) ? resp.results : []);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Semantic search failed");
    } finally {
      setSearching(false);
    }
  };

  const handleRefreshGraph = async () => {
    setRefreshingGraph(true);
    try {
      await refreshSpaceData();
    } finally {
      setRefreshingGraph(false);
    }
  };

  const neo4jStatus = graph?.neo4j?.status ?? "unknown";
  const neo4jConnected = neo4jStatus === "connected";
  const activeSpaceName = space ? `${space.facility} / ${space.name}` : spaceId || "Active Space";

  return (
    <div className="flex flex-col gap-3">
      <WorkspaceHeader
        badge="G_CPDT GRAPH"
        title="SPATIAL KNOWLEDGE GRAPH & PGVECTOR"
        subtitle={`Active Space: ${activeSpaceName} · Cyber-physical topology, dark zones & semantic asset search`}
        statusTone={neo4jConnected ? "ok" : "warning"}
        statusLabel={`NEO4J ${String(neo4jStatus).toUpperCase()}`}
        metrics={[
          {
            label: "Active Space",
            value: space?.name || "Default",
            tone: "sky",
            compact: true,
          },
          {
            label: "Graph Nodes",
            value: graph?.stats?.node_count ?? flowNodes.length,
            tone: "orange",
            compact: true,
          },
          {
            label: "Graph Edges",
            value: graph?.stats?.edge_count ?? flowEdges.length,
            tone: "emerald",
            compact: true,
          },
          {
            label: "Dark Zones",
            value: graph?.stats?.dark_zone_count ?? 0,
            tone: (graph?.stats?.dark_zone_count ?? 0) > 0 ? "fault" : "default",
            compact: true,
          },
        ]}
        actions={
          <Button
            size="sm"
            variant="secondary"
            disabled={refreshingGraph}
            onClick={() => void handleRefreshGraph()}
            title="Refresh Knowledge Graph & Space Data"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshingGraph ? "animate-spin" : ""}`} />
            {refreshingGraph ? "Refreshing..." : "Refresh Graph"}
          </Button>
        }
      />

      {/* PostgreSQL 18 pgvector Semantic Search */}
      <div className="flex flex-col gap-2 rounded-lg border border-white/10 bg-eigenia-surface p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white">
            <Database className="h-3.5 w-3.5 text-eigenia-sky" />
            PostgreSQL 18 + pgvector Semantic Equipment Search (halfvec HNSW)
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {graph?.stats && (
              <Badge variant="neutral" className="tabular-nums">
                {graph.stats.node_count ?? 0} Nodes · {graph.stats.edge_count ?? 0} Edges
              </Badge>
            )}
            <Badge variant={graph?.neo4j?.status === "connected" ? "sky" : "amber"}>
              <Network className="h-3 w-3" /> Neo4j: {graph?.neo4j?.status ?? "unknown"}
            </Badge>
          </div>
        </div>

        <div className="flex gap-2">
          <Input
            placeholder="Search by make, model, voltage, CPE, or description (e.g. 'Siemens 24V PLC' or 'Cisco switch')..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch()}
          />
          <Button variant="sky" disabled={searching} onClick={handleSemanticSearch}>
            <Search className="h-3.5 w-3.5" />
            {searching ? "Searching..." : "Vector Search"}
          </Button>
        </div>

        {searchError && (
          <div className="rounded border border-eigenia-fault/40 bg-eigenia-fault/15 px-2.5 py-1.5 font-mono text-[11px] text-eigenia-fault">
            {searchError}
          </div>
        )}

        {results.length > 0 && (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {results.map((eq) => (
              <button
                key={eq.id}
                type="button"
                onClick={() => {
                  onSelectEquipment(eq.id);
                  onFocusTarget?.({ x: eq.x, y: eq.y, label: eq.name, equipmentId: eq.id });
                }}
                className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-3 py-2 text-left transition-colors hover:border-eigenia-orange"
              >
                <div className="min-w-0">
                  <div className="truncate text-xs font-semibold text-white">{eq.name}</div>
                  <div className="truncate font-mono text-[10px] text-eigenia-muted">
                    {eq.manufacturer} · {eq.model_number} · ({Number(eq.x ?? 0).toFixed(1)}m, {Number(eq.y ?? 0).toFixed(1)}m)
                  </div>
                </div>
                <Badge variant="default" className="shrink-0 tabular-nums">
                  {((eq.similarity ?? 0) * 100).toFixed(1)}%
                </Badge>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Layer Filters & Telemetry Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-shell px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
            <Filter className="h-3 w-3 text-eigenia-orange" />
            Graph Layers:
          </span>
          <Button
            size="sm"
            variant={layerFilter === "all" ? "default" : "secondary"}
            className="h-7 text-[11px]"
            onClick={() => setLayerFilter("all")}
          >
            All
          </Button>
          <Button
            size="sm"
            variant={layerFilter === "dark_incomplete" ? "default" : "secondary"}
            className="h-7 text-[11px]"
            onClick={() => setLayerFilter("dark_incomplete")}
          >
            Dark & Incomplete Only
          </Button>
          <Button
            size="sm"
            variant={layerFilter === "hide_tags" ? "default" : "secondary"}
            className="h-7 text-[11px]"
            onClick={() => setLayerFilter("hide_tags")}
          >
            Hide Tags
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] text-eigenia-muted">
          <span>Visible: {flowNodes.length} nodes</span>
          <span>·</span>
          <span>Equipment: {graph?.stats?.equipment_count ?? 0}</span>
          <span>·</span>
          <span>Dark Zones: {graph?.stats?.dark_zone_count ?? 0}</span>
        </div>
      </div>

      {/* Eigenia Dot-Grid Knowledge Graph Canvas */}
      <div className="h-[520px] w-full overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.25}
          maxZoom={1.75}
          onNodeClick={(_, node) => {
            const meta = (node.data as { meta?: { equipment_id?: string; x?: number; y?: number } })?.meta;
            if (meta?.equipment_id) {
              onSelectEquipment(meta.equipment_id);
            } else if (
              onFocusTarget &&
              typeof meta?.x === "number" &&
              typeof meta?.y === "number"
            ) {
              onFocusTarget({
                x: meta.x,
                y: meta.y,
                label: String((node.data as { label?: string })?.label ?? "Target"),
              });
            }
          }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgba(255,255,255,0.08)" />
          <Controls className="!border-white/10 !bg-eigenia-shell !text-white" />
          <MiniMap
            className="!rounded-md !border !border-white/15 !bg-eigenia-shell"
            maskColor="rgba(11, 13, 16, 0.72)"
            nodeColor={(node) => {
              if (node.type === "equipment") return "#E05A10";
              if (node.type === "darkzone") return "#ef4444";
              const nt = String((node.data as { nodeType?: string })?.nodeType ?? "");
              return STANDARD_NODE_PALETTE[nt]?.hex ?? "#38bdf8";
            }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
