"use client";

import React, { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { HardwarePartSvgIcon } from "@/components/microbit/ComponentToolbar";
import type {
  BoardProfile,
  MicrobitAccessorySpec,
  MicrobitAttachment,
  MicrobitWiringValidation,
} from "@/lib/microbitApi";

interface ControllerNodeData extends Record<string, unknown> {
  board: BoardProfile;
  usedPins: string[];
}

function ControllerBoardNode({ data }: NodeProps<Node<ControllerNodeData>>): React.JSX.Element {
  const { board, usedPins } = data;
  const dims = board.dimensions_mm || [51.6, 42.0, 11.7];
  return (
    <div className="min-w-[260px] rounded-xl border-2 border-eigenia-orange bg-eigenia-shell p-3 shadow-xl">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 pb-2">
        <div>
          <div className="font-mono text-xs font-bold text-white">{board.name}</div>
          <div className="font-mono text-[10px] text-eigenia-muted">
            {dims[0]}×{dims[1]}×{dims[2]} mm · {board.logic_v}V Logic
          </div>
        </div>
        <Badge variant="default">MCU</Badge>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1.5">
        {board.pins.map((p) => {
          const isUsed = usedPins.includes(p.id);
          return (
            <div
              key={p.id}
              className="relative flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-2 py-1 font-mono text-[10px]"
            >
              <span className={isUsed ? "font-bold text-eigenia-orange" : "text-eigenia-muted"}>
                {p.id}
              </span>
              <span className="text-[9px] text-eigenia-sky">{p.voltage}</span>
              <Handle
                type="source"
                position={Position.Bottom}
                id={`pin-${p.id}`}
                className="!h-2 !w-2 !border-white !bg-eigenia-orange"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface PartNodeData extends Record<string, unknown> {
  attachment: MicrobitAttachment;
  spec?: MicrobitAccessorySpec;
}

function AccessorySchematicNode({ data }: NodeProps<Node<PartNodeData>>): React.JSX.Element {
  const { attachment, spec } = data;
  const dims = spec?.dimensions_mm || [30, 20, 10];
  return (
    <div className="min-w-[210px] rounded-xl border border-eigenia-sky/60 bg-eigenia-shell p-2.5 shadow-lg">
      <Handle
        type="target"
        position={Position.Top}
        id="sig"
        className="!h-2.5 !w-2.5 !border-white !bg-eigenia-sky"
      />
      <div className="flex items-center gap-2">
        <HardwarePartSvgIcon
          kind={spec?.svg_icon_kind}
          color={spec?.color_hex}
          className="h-9 w-12 shrink-0"
        />
        <div className="min-w-0">
          <div className="truncate font-mono text-[11px] font-bold text-white">
            {attachment.label}
          </div>
          <div className="font-mono text-[9px] text-eigenia-muted">
            {dims[0]}×{dims[1]}×{dims[2]} mm {spec?.i2c_address ? `· I2C ${spec.i2c_address}` : ""}
          </div>
        </div>
      </div>
      <div className="mt-2 space-y-1 border-t border-white/10 pt-1.5 font-mono text-[9px]">
        {(spec?.wires || []).map((w, idx) => (
          <div key={idx} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1 text-white">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: w.color }}
              />
              {w.from}
            </span>
            <span className="text-eigenia-sky">
              {w.to_role === "signal"
                ? attachment.pin
                : w.to_role === "secondary"
                ? attachment.secondary_pin || "P20"
                : w.to_role}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const nodeTypes = {
  controller: ControllerBoardNode,
  part: AccessorySchematicNode,
};

interface ElectronicSchematicViewProps {
  board: BoardProfile;
  accessories: MicrobitAccessorySpec[];
  attachments: MicrobitAttachment[];
  wiring: MicrobitWiringValidation;
}

export function ElectronicSchematicView({
  board,
  accessories,
  attachments,
  wiring,
}: ElectronicSchematicViewProps): React.JSX.Element {
  const { nodes, edges } = useMemo(() => {
    const builtNodes: Node[] = [
      {
        id: "board-root",
        type: "controller",
        position: { x: 240, y: 20 },
        data: { board, usedPins: wiring.used_pins || [] },
      },
    ];
    const builtEdges: Edge[] = [];

    attachments.forEach((att, idx) => {
      const spec = accessories.find((a) => a.id === att.accessory_id);
      const col = idx % 3;
      const row = Math.floor(idx / 3);
      builtNodes.push({
        id: att.id,
        type: "part",
        position: { x: 30 + col * 260, y: 310 + row * 195 },
        data: { attachment: att, spec },
      });

      const primaryColor = spec?.wires?.[0]?.color || "#38bdf8";
      builtEdges.push({
        id: `edge-${att.id}-sig`,
        source: "board-root",
        sourceHandle: `pin-${att.pin}`,
        target: att.id,
        targetHandle: "sig",
        label: `${att.pin} (${spec?.protocol || "SIG"})`,
        animated: true,
        style: { stroke: primaryColor, strokeWidth: 2.2 },
        labelStyle: { fill: "#e2e8f0", fontSize: 10, fontFamily: "monospace" },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, color: primaryColor },
      });

      if (att.secondary_pin) {
        builtEdges.push({
          id: `edge-${att.id}-sec`,
          source: "board-root",
          sourceHandle: `pin-${att.secondary_pin}`,
          target: att.id,
          targetHandle: "sig",
          label: `${att.secondary_pin}`,
          style: { stroke: "#facc15", strokeWidth: 1.6, strokeDasharray: "4 3" },
          labelStyle: { fill: "#facc15", fontSize: 9, fontFamily: "monospace" },
          labelBgStyle: { fill: "#0f172a", fillOpacity: 0.9 },
        });
      }
    });

    return { nodes: builtNodes, edges: builtEdges };
  }, [accessories, attachments, board, wiring.used_pins]);

  return (
    <div className="relative flex h-[540px] w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-[#070b14]">
      {/* Schematic Status Overlay */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell/95 px-3 py-1.5 font-mono text-[10px]">
        <div className="flex items-center gap-2">
          {wiring.ok ? (
            <Badge variant="sky">
              <CheckCircle2 className="h-3 w-3" /> NETLIST VERIFIED
            </Badge>
          ) : (
            <Badge variant="fault">
              <AlertTriangle className="h-3 w-3" /> {wiring.conflicts.length} PIN CONFLICT(S)
            </Badge>
          )}
          <span className="text-eigenia-muted">
            {attachments.length} module(s) · {wiring.wiring_steps.length} jumper net(s)
          </span>
        </div>
        {wiring.warnings.length > 0 && (
          <span className="truncate text-eigenia-amber">{wiring.warnings[0]}</span>
        )}
      </div>

      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={18} />
          <Controls className="!bg-eigenia-shell !text-white" />
        </ReactFlow>
      </div>
    </div>
  );
}
