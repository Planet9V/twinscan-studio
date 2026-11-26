"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Cpu } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  TopologyFlowCanvas,
  type TopologyEdgeSpec,
  type TopologyNodeSpec,
} from "@/components/ui/TopologyFlowCanvas";

interface ArchNodeDetail {
  id: string;
  layer: string;
  title: string;
  tagline: string;
  route: string;
  routeLabel: string;
  benchmarks: { label: string; value: string }[];
  highlights: string[];
}

const ARCH_DETAILS: Record<string, ArchNodeDetail> = {
  puppypi_hw: {
    id: "puppypi_hw",
    layer: "Layer 1 · Physical Hardware",
    title: "Hiwonder PuppyPi Pro (Pi 5 8GB + LD19 + ROS 2)",
    tagline: "Flagship maker quadruped running Ubuntu 22.04 ROS 2 Humble CycloneDDS on Raspberry Pi 5",
    route: "/control",
    routeLabel: "Open Control Deck",
    benchmarks: [
      { label: "Live LD19 /scan", value: "6.9 Hz" },
      { label: "2S LiPo Telemetry", value: "95% (8.3V)" },
      { label: "Verified Actions", value: "28 Groups" },
    ],
    highlights: [
      "1-click ROS 1 Noetic ↔ ROS 2 Humble switch + persistent auto-boot systemd service",
      "Real DA9091 PMIC power telemetry (EXT5V, Board Watts, 1600 mA USB budget) in 3D BOM Twin",
      "Single-instance LD19 deduplication + WonderEcho Pro offline Piper neural voice",
    ],
  },
  workbench_hw: {
    id: "workbench_hw",
    layer: "Layer 1 · Physical Hardware",
    title: "Pi 5 Workbench + Pi Zero 2 W + BBC micro:bit v2.21",
    tagline: "Universal Hardware Envelope connecting SBCs, wearables, and USB gadgets seamlessly",
    route: "/architect?tab=profiles",
    routeLabel: "Open Board Profiles",
    benchmarks: [
      { label: "Board Profiles", value: "6 Envelopes" },
      { label: "LED Matrix", value: "5×5 Live" },
      { label: "Firmware", value: "MicroPython" },
    ],
    highlights: [
      "Interactive 5×5 Red LED Matrix Painter + USB DAPLink probe for micro:bit v2.21",
      "Pi Zero 2 W USB Mass Storage gadget harvester for local offline video clip ingest",
      "Electrical guardrails auto-check 3.3V vs 5V logic shifting and USB current draw",
    ],
  },
  local_cams: {
    id: "local_cams",
    layer: "Layer 1 · Physical Hardware",
    title: "100% Cloud-Free Local Camera Array",
    tagline: "Ingest LAN RTSP/MJPEG streams and local .mp4/.jpg clips with zero cloud subscriptions",
    route: "/architect?tab=profiles",
    routeLabel: "Configure Local Cams",
    benchmarks: [
      { label: "Cloud Dependency", value: "0% (Local)" },
      { label: "Video Support", value: "RTSP / MP4" },
      { label: "Privacy", value: "On-Premises" },
    ],
    highlights: [
      "Extracts sharpest frames via Laplacian variance and runs offline YOLO11n + YuNet/SFace",
      "Zero Amazon/cloud keys — 100% local Docker inference and PostgreSQL 18 storage",
      "Every detected person, pet, or object is searchable in Semantic Spatial Memory Pro",
    ],
  },
  fusion_3d: {
    id: "fusion_3d",
    layer: "Layer 2 · Perception & Fusion",
    title: "Camera + LD19 + Depth Anything V2 3D Fusion",
    tagline: "5-pass composite enhancement fusing real photography, metric LiDAR, and PBR normals",
    route: "/twin",
    routeLabel: "Open 3D Spatial Twin",
    benchmarks: [
      { label: "LD19 3D RMSE", value: "2.16 cm" },
      { label: "Presets", value: "Fast / Ultra" },
      { label: "Export", value: "Full Room .GLB" },
    ],
    highlights: [
      "Multi-frame burst alignment, LAB CLAHE sharpening, 2× Lanczos upscale & Flip-TTA depth",
      "He et al. O(N) RGB-guided filter + LD19 column residual warp + tangent-space normal map",
      "1-click combined multi-mesh binary glTF 2.0 (.glb) export for Blender & Unity",
    ],
  },
  vision_memory: {
    id: "vision_memory",
    layer: "Layer 2 · Perception & Fusion",
    title: "YOLO11n + SFace Face ID + Spatial Memory Pro",
    tagline: "Real-time object/animal/face recognition paired with searchable room memory & Sentry Mode",
    route: "/vision",
    routeLabel: "Open AI Vision Studio",
    benchmarks: [
      { label: "Face Vectors", value: "128-D SFace" },
      { label: "Gallery Views", value: "Bento / Grid / Line" },
      { label: "Voice Query", value: '"Hey OX"' },
    ],
    highlights: [
      "Ask OX aloud: 'Hey OX, where did you last see my laptop?' answered from PG18 memory",
      "Active / Archived / All lifecycle gallery with bulk actions & Slide-Over detail editor",
      "Autonomous Sentry Guard fuses LiDAR moving tracks, unknown faces & spoken challenges",
    ],
  },
  explorer_rth: {
    id: "explorer_rth",
    layer: "Layer 3 · Autonomous Intelligence",
    title: "Autonomous Frontier Explorer & Low-Battery RTH",
    tagline: "Next-Best-View dark-zone exploration, multi-angle pitch/yaw 3D sweeps & AprilTag #0 home",
    route: "/patrol?tab=explore",
    routeLabel: "Open Frontier Explorer",
    benchmarks: [
      { label: "Auto-RTH Guard", value: "7.10 V 2S" },
      { label: "Avoidance", value: "5-Sector VFH" },
      { label: "Safety Tests", value: "158+ Pytest" },
    ],
    highlights: [
      "Automatically targets highest-priority red Spatial Dark Zones until target room coverage %",
      "Tilts PuppyPi body pitch Up/Level/Down across yaw stops to capture full floor-to-ceiling 3D",
      "Continuous 2S LiPo guard + global E-STOP preemption + LD19 dropout pause fail-safe",
    ],
  },
  lab_architect: {
    id: "lab_architect",
    layer: "Layer 3 · Autonomous Intelligence",
    title: "5-Tier AI Lab Architect Co-Design Canvas",
    tagline: "Turn owned lab parts into grounded or groundbreaking 2D wiring + 3D CAD assemblies",
    route: "/architect",
    routeLabel: "Open Lab Architect",
    benchmarks: [
      { label: "Creativity Dial", value: "Tier 1 → Tier 5" },
      { label: "Specialist Lenses", value: "4 Personas" },
      { label: "Spec Export", value: "Markdown + 3D" },
    ],
    highlights: [
      "Lock or exclude owned inventory parts and watch 2D wiring & 3D assembly adapt live",
      "Red-Team Critic audits voltage rails, USB budgets, and failure modes before you solder",
      "Works with live OpenRouter 500+ models OR deterministic offline engineering synthesis",
    ],
  },
  dual_twin: {
    id: "dual_twin",
    layer: "Layer 4 · Digital Twin & Storage",
    title: "Dual Three.js 0.187 + Babylon.js 9 PBR Twin",
    tagline: "Zero-lock-in dual-engine 3D spatial twin with Solid, Translucent & Wireframe CAD modes",
    route: "/twin",
    routeLabel: "Launch Twin Viewport",
    benchmarks: [
      { label: "3D Engines", value: "Three + Babylon 9" },
      { label: "Render Modes", value: "Solid / X-Ray / Wire" },
      { label: "Exports", value: "6 Open Formats" },
    ],
    highlights: [
      "Real-time 3D PuppyPi Avatar mirroring live IMU roll/pitch/yaw + Kalman moving targets",
      "Instant 1-click export to glTF/GLB, CycloneDX 1.6, DEXPI G_CPDT, Neo4j Cypher, DXF, PLY",
      "Multi-Room & Saved Scenes gallery with wall thumbnails and zero-copy checkpoints",
    ],
  },
  pg_neo4j: {
    id: "pg_neo4j",
    layer: "Layer 4 · Digital Twin & Storage",
    title: "PostgreSQL 18 (pgvector) + Neo4j 5 Knowledge Graph",
    tagline: "Content-addressed SHA-256 blob storage, semantic embeddings & G_CPDT asset topology",
    route: "/graph",
    routeLabel: "Open Knowledge Graph",
    benchmarks: [
      { label: "Vector DB", value: "PG18 pgvector" },
      { label: "Graph DB", value: "Neo4j 5" },
      { label: "Secrets", value: "Fernet Encrypted" },
    ],
    highlights: [
      "Deduplicated SHA-256 storage for every room texture, normal map, .glb, and face portrait",
      "Semantic equipment & spatial search powered by pgvector cosine similarity",
      "Full CycloneDX 1.6 HBOM+SBOM fleet catalog synced bidirectionally with Neo4j",
    ],
  },
};

export function LandingArchitectureFlow() {
  const [selectedId, setSelectedId] = useState<string>("puppypi_hw");

  const { nodes, edges } = useMemo(() => {
    const builtNodes: TopologyNodeSpec[] = [
      // Layer 1: Hardware
      {
        id: "puppypi_hw",
        label: "PuppyPi Pro (Pi 5 + LD19)",
        subtitle: "ROS 2 Humble · 6.9 Hz /scan",
        metric: "95% 2S LiPo",
        category: "HARDWARE",
        status: "ok",
        x: 20,
        y: 25,
      },
      {
        id: "workbench_hw",
        label: "Pi 5 + micro:bit v2.21",
        subtitle: "6 Hardware Envelopes",
        metric: "USB / BLE / GPIO",
        category: "HARDWARE",
        status: "ok",
        x: 20,
        y: 170,
      },
      {
        id: "local_cams",
        label: "100% Cloud-Free Cams",
        subtitle: "LAN RTSP + Pi Zero Clips",
        metric: "0% Cloud",
        category: "HARDWARE",
        status: "ok",
        x: 20,
        y: 315,
      },

      // Layer 2: Perception
      {
        id: "fusion_3d",
        label: "Camera + LD19 + Depth V2",
        subtitle: "5-Pass 3D Room Fusion",
        metric: "2.16 cm RMSE",
        category: "PERCEPTION",
        status: "ok",
        x: 330,
        y: 85,
      },
      {
        id: "vision_memory",
        label: "YOLO11n + Face ID + Memory",
        subtitle: "Spatial Memory Pro & Sentry",
        metric: "128-D SFace",
        category: "PERCEPTION",
        status: "ok",
        x: 330,
        y: 250,
      },

      // Layer 3: Intelligence
      {
        id: "explorer_rth",
        label: "Autonomous Explorer & RTH",
        subtitle: "Dark-Zone NBV + AprilTag #0",
        metric: "7.10V Guard",
        category: "AUTONOMY",
        status: "ok",
        x: 650,
        y: 85,
      },
      {
        id: "lab_architect",
        label: "5-Tier AI Lab Architect",
        subtitle: "2D Wiring + 3D Co-Design",
        metric: "T1 → T5 Dial",
        category: "CO-DESIGN",
        status: "ok",
        x: 650,
        y: 250,
      },

      // Layer 4: Digital Twin & Persistence
      {
        id: "dual_twin",
        label: "Three.js + Babylon.js 9",
        subtitle: "Solid / X-Ray / Wire + .GLB",
        metric: "6 Open Exports",
        category: "DIGITAL TWIN",
        status: "ok",
        x: 970,
        y: 85,
      },
      {
        id: "pg_neo4j",
        label: "PG18 pgvector + Neo4j 5",
        subtitle: "SHA-256 Blobs & G_CPDT",
        metric: "158+ Tests",
        category: "STORAGE",
        status: "ok",
        x: 970,
        y: 250,
      },
    ];

    const builtEdges: TopologyEdgeSpec[] = [
      { id: "e1", source: "puppypi_hw", target: "fusion_3d", label: "/image_raw + /scan", status: "ok", animated: true },
      { id: "e2", source: "puppypi_hw", target: "vision_memory", label: "FPV + Voice", status: "ok", animated: true },
      { id: "e3", source: "workbench_hw", target: "lab_architect", label: "Envelopes", status: "ok", animated: true },
      { id: "e4", source: "local_cams", target: "vision_memory", label: "Local Clips", status: "ok", animated: true },
      { id: "e5", source: "fusion_3d", target: "explorer_rth", label: "Dark Zones", status: "ok", animated: true },
      { id: "e6", source: "fusion_3d", target: "dual_twin", label: "PBR Mesh + .GLB", status: "ok", animated: true },
      { id: "e7", source: "vision_memory", target: "explorer_rth", label: "AprilTag #0", status: "ok", animated: true },
      { id: "e8", source: "vision_memory", target: "pg_neo4j", label: "128-D Vectors", status: "ok", animated: true },
      { id: "e9", source: "explorer_rth", target: "dual_twin", label: "Live Pose", status: "ok", animated: true },
      { id: "e10", source: "lab_architect", target: "pg_neo4j", label: "Blueprints", status: "ok", animated: true },
      { id: "e11", source: "dual_twin", target: "pg_neo4j", label: "Snapshots", status: "ok" },
    ];

    return { nodes: builtNodes, edges: builtEdges };
  }, []);

  const activeDetail = ARCH_DETAILS[selectedId] ?? ARCH_DETAILS.puppypi_hw;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <div className="xl:col-span-8">
        <TopologyFlowCanvas
          nodes={nodes}
          edges={edges}
          selectedNodeId={selectedId}
          onSelectNode={setSelectedId}
          heightClassName="h-[460px]"
          title="Interactive Cyber-Physical Pipeline — Click Any Stage to Inspect Live PuppyPi Pro Benchmarks"
          legend
        />
      </div>

      {/* Live Selected Stage Spec & Benchmark Inspector */}
      <div className="flex flex-col justify-between gap-4 rounded-xl border border-eigenia-orange/35 bg-eigenia-surface p-5 xl:col-span-4">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Badge variant="default" className="font-mono text-[10px]">
              <Cpu className="h-3 w-3" />
              {activeDetail.layer}
            </Badge>
            <h3 className="text-base font-bold tracking-tight text-white">{activeDetail.title}</h3>
            <p className="text-xs leading-relaxed text-eigenia-muted">{activeDetail.tagline}</p>
          </div>

          <div className="grid grid-cols-3 gap-2">
            {activeDetail.benchmarks.map((b) => (
              <div
                key={b.label}
                className="rounded-lg border border-white/10 bg-eigenia-obsidian p-2.5 text-center"
              >
                <div className="font-mono text-[9px] uppercase text-eigenia-muted">{b.label}</div>
                <div className="mt-1 font-mono text-xs font-bold tabular-nums text-eigenia-sky">
                  {b.value}
                </div>
              </div>
            ))}
          </div>

          <ul className="space-y-2 text-xs text-eigenia-ink">
            {activeDetail.highlights.map((h, i) => (
              <li key={`arch-hl-${i}`} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <span className="leading-relaxed">{h}</span>
              </li>
            ))}
          </ul>
        </div>

        <Button asChild className="w-full font-semibold">
          <Link href={activeDetail.route}>
            {activeDetail.routeLabel}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
