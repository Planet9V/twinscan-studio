"use client";

import React, { useMemo } from "react";
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
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type TopologyNodeStatus = "ok" | "warning" | "fault" | "idle" | "empty";

export interface TopologyNodeSpec {
  id: string;
  label: string;
  subtitle?: string;
  metric?: string;
  category?: string;
  status: TopologyNodeStatus;
  x: number;
  y: number;
}

export interface TopologyEdgeSpec {
  id: string;
  source: string;
  target: string;
  label?: string;
  status?: TopologyNodeStatus;
  animated?: boolean;
}

export interface TopologyFlowCanvasProps {
  nodes: TopologyNodeSpec[];
  edges: TopologyEdgeSpec[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
  heightClassName?: string;
  title?: string;
  legend?: boolean;
}

interface TopologyFlowNodeData extends Record<string, unknown> {
  label: string;
  subtitle?: string;
  metric?: string;
  category?: string;
  status: TopologyNodeStatus;
  isSelected: boolean;
}

const STATUS_STYLES: Record<
  TopologyNodeStatus,
  { border: string; dot: string; glow: string; edge: string; text: string }
> = {
  ok: {
    border: "border-emerald-400/60 hover:border-emerald-300",
    dot: "bg-emerald-400",
    glow: "shadow-[0_0_16px_rgba(16,185,129,0.16)]",
    edge: "#10b981",
    text: "text-emerald-300",
  },
  warning: {
    border: "border-eigenia-amber/70 hover:border-eigenia-amber",
    dot: "bg-eigenia-amber",
    glow: "shadow-[0_0_16px_rgba(245,158,11,0.22)]",
    edge: "#f59e0b",
    text: "text-eigenia-amber",
  },
  fault: {
    border: "border-eigenia-fault/80 hover:border-eigenia-fault",
    dot: "bg-eigenia-fault",
    glow: "shadow-[0_0_20px_rgba(239,68,68,0.28)]",
    edge: "#ef4444",
    text: "text-eigenia-fault",
  },
  idle: {
    border: "border-eigenia-sky/50 hover:border-eigenia-sky",
    dot: "bg-eigenia-sky",
    glow: "shadow-[0_0_12px_rgba(56,189,248,0.14)]",
    edge: "#38bdf8",
    text: "text-eigenia-sky",
  },
  empty: {
    border: "border-slate-600/60 hover:border-slate-400",
    dot: "bg-slate-400",
    glow: "",
    edge: "#475569",
    text: "text-slate-400",
  },
};

function TopologyCardNode({ data }: NodeProps<Node<TopologyFlowNodeData>>) {
  const status = data.status ?? "idle";
  const st = STATUS_STYLES[status] ?? STATUS_STYLES.idle;
  const shouldPulse = status === "warning" || status === "fault";

  return (
    <div
      className={cn(
        "min-w-[175px] max-w-[225px] cursor-pointer rounded-lg border bg-eigenia-shell/95 px-3 py-2 text-left transition-all duration-200 hover:ring-1 hover:ring-eigenia-sky/40 motion-reduce:transition-none",
        st.border,
        st.glow,
        data.isSelected &&
          "border-eigenia-orange ring-2 ring-eigenia-orange/50 shadow-[0_0_22px_rgba(224,90,16,0.35)]"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-eigenia-obsidian !bg-eigenia-sky"
      />

      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[9px] uppercase tracking-wider text-eigenia-muted">
          {data.category || "node"}
        </span>
        <span className="relative flex h-2 w-2 shrink-0">
          {shouldPulse && (
            <span
              className={cn(
                "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 motion-reduce:animate-none",
                st.dot
              )}
            />
          )}
          <span className={cn("relative inline-flex h-2 w-2 rounded-full", st.dot)} />
        </span>
      </div>

      <div className="mt-0.5 truncate text-xs font-semibold text-white">{data.label}</div>

      {data.subtitle && (
        <div className="mt-0.5 truncate font-mono text-[10px] text-eigenia-muted">
          {data.subtitle}
        </div>
      )}

      {data.metric && (
        <div className="mt-1.5 inline-flex max-w-full items-center rounded border border-white/10 bg-eigenia-obsidian px-1.5 py-0.5 font-mono text-[10px]">
          <span className={cn("truncate font-semibold", st.text)}>{data.metric}</span>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-eigenia-obsidian !bg-eigenia-orange"
      />
    </div>
  );
}

const NODE_TYPES: NodeTypes = {
  topologyCard: TopologyCardNode,
};

export function TopologyFlowCanvas({
  nodes,
  edges,
  selectedNodeId = null,
  onSelectNode,
  heightClassName = "h-[460px]",
  title,
  legend = true,
}: TopologyFlowCanvasProps): React.JSX.Element {
  const flowNodes = useMemo<Node<TopologyFlowNodeData>[]>(
    () =>
      (Array.isArray(nodes) ? nodes : []).map((n) => ({
        id: n.id,
        type: "topologyCard",
        position: { x: n.x, y: n.y },
        data: {
          label: n.label,
          subtitle: n.subtitle,
          metric: n.metric,
          category: n.category,
          status: n.status,
          isSelected: n.id === selectedNodeId,
        },
        selected: n.id === selectedNodeId,
      })),
    [nodes, selectedNodeId]
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      (Array.isArray(edges) ? edges : []).map((e) => {
        const st = STATUS_STYLES[e.status ?? "idle"] ?? STATUS_STYLES.idle;
        const animated = e.animated ?? e.status !== "empty";
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          animated,
          style: {
            stroke: st.edge,
            strokeWidth: e.status === "fault" ? 2.4 : 1.8,
            strokeDasharray: e.status === "empty" ? "4 4" : undefined,
          },
          labelStyle: {
            fill: "#d4d4d8",
            fontSize: 10,
            fontFamily: "var(--font-jetbrains-mono), monospace",
          },
          labelBgStyle: {
            fill: "#0E1013",
            fillOpacity: 0.9,
          },
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
        };
      }),
    [edges]
  );

  return (
    <div
      className={cn(
        "relative flex w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian",
        heightClassName
      )}
    >
      {(title || legend) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell px-3 py-2">
          <div className="flex items-center gap-2">
            {title && (
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-white">
                {title}
              </span>
            )}
            <Badge variant="neutral">{flowNodes.length} nodes</Badge>
          </div>
          {legend && (
            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px]">
              <span className="inline-flex items-center gap-1 text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> OK
              </span>
              <span className="inline-flex items-center gap-1 text-eigenia-amber">
                <span className="h-2 w-2 rounded-full bg-eigenia-amber" /> Warn
              </span>
              <span className="inline-flex items-center gap-1 text-eigenia-fault">
                <span className="h-2 w-2 rounded-full bg-eigenia-fault" /> Fault
              </span>
              <span className="inline-flex items-center gap-1 text-slate-400">
                <span className="h-2 w-2 rounded-full bg-slate-500" /> Empty
              </span>
            </div>
          )}
        </div>
      )}

      <div className="flex-1">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={NODE_TYPES}
          onNodeClick={(_evt, node) => {
            if (onSelectNode) onSelectNode(node.id);
          }}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          className="dark bg-eigenia-obsidian"
          minZoom={0.35}
          maxZoom={1.75}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#242c38" />
          <Controls
            showInteractive={false}
            className="!border-white/15 !bg-eigenia-shell !text-white"
          />
          <MiniMap
            pannable
            zoomable
            nodeColor={(node) => {
              const d = node.data as TopologyFlowNodeData | undefined;
              const st = STATUS_STYLES[d?.status ?? "idle"] ?? STATUS_STYLES.idle;
              return d?.isSelected ? "#E05A10" : st.edge;
            }}
            maskColor="rgba(11, 13, 16, 0.72)"
            className="!border !border-white/15 !bg-eigenia-shell"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
