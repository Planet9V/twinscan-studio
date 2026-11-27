"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  BookOpen,
  Box,
  Camera,
  Check,
  CheckCircle2,
  ClipboardCopy,
  Code2,
  Cpu,
  Download,
  FileCode2,
  FileText,
  Flame,
  GitBranch,
  HardDrive,
  History,
  LayoutGrid,
  Lightbulb,
  Loader2,
  Lock,
  Music,
  Package,
  Plus,
  Radio,
  RefreshCw,
  Rocket,
  Save,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  Terminal,
  Trash2,
  Unlock,
  Upload,
  Usb,
  Wand2,
  Wrench,
  Zap,
} from "lucide-react";
import { AnimatedMetric } from "@/components/ui/AnimatedMetric";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs, type SegmentedTabItem } from "@/components/ui/SegmentedTabs";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import { TopologyFlowCanvas } from "@/components/ui/TopologyFlowCanvas";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { useStudio } from "@/context/StudioContext";
import {
  ARCHITECT_PERSONAS,
  CREATIVITY_TIERS,
  createInventoryItem,
  createManagedDevice,
  deleteDesignBlueprint,
  deleteInventoryItem,
  deleteManagedDevice,
  evaluateDesignIdea,
  fetchPiZeroGadgetScript,
  ideateLabProjects,
  ingestLocalCameraMedia,
  listDesignBlueprints,
  listDeviceProfiles,
  listInventory,
  listManagedDevices,
  probeMicrobitUsb,
  refineDesignBlueprint,
  seedLabInventory,
  sendMicrobitCommand,
  syncFleetHardwareToInventory,
  updateInventoryItem,
  type ArchitectIdea,
  type ArchitectPersona,
  type BlueprintMissingPart,
  type CameraIngestResponse,
  type CreativityLevel,
  type DesignBlueprint,
  type DeviceProfile,
  type InventoryCategory,
  type InventoryCounts,
  type InventoryItem,
  type InventoryStatus,
  type ManagedDevice,
  type MicrobitCommandResponse,
  type MicrobitProbeResponse,
  type PiZeroGadgetScriptResponse,
} from "@/lib/architectApi";

const CoDesignAssembly3D = dynamic(
  () => import("@/components/architect/CoDesignAssembly3D").then((m) => m.CoDesignAssembly3D),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[480px] items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian font-mono text-xs text-eigenia-muted">
        Initializing Three.js 3D Co-Design Assembly...
      </div>
    ),
  }
);

type ArchitectTabId = "studio" | "ideas" | "inventory" | "profiles" | "blueprints";
type CanvasViewMode = "2d" | "3d" | "split";

const VALID_TABS: ArchitectTabId[] = ["studio", "ideas", "inventory", "profiles", "blueprints"];

const INVENTORY_CATEGORIES: InventoryCategory[] = [
  "compute",
  "microcontroller",
  "camera",
  "sensor",
  "actuator",
  "network",
  "power",
  "accessory",
];

const IDEA_FOCUS_AREAS = [
  { id: "all", label: "All Domains" },
  { id: "robotics", label: "Robotics & Autonomy" },
  { id: "vision_security", label: "Local Vision & Security" },
  { id: "iot_microbit", label: "Edge IoT & micro:bit" },
  { id: "telemetry", label: "Sensors & Telemetry" },
] as const;

const STARTER_PROMPTS = [
  "Fuse PuppyPi ROS 2 + LD19 LiDAR + micro:bit v2 wearable beacon so PuppyPi navigates to me when I press Button A",
  "Build a 100% local cloud-free home perimeter sentry using Pi Zero 2 W Blink Sync clip harvester + PuppyPi AI Vision",
  "Multi-room thermal & motion watchdog combining Pi 5 edge compute, LAN camera array, and micro:bit room display",
] as const;

const LED_PRESETS: Record<string, number[][]> = {
  heart: [
    [0, 1, 0, 1, 0],
    [1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
  ],
  check: [
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 1],
    [0, 0, 0, 1, 0],
    [1, 0, 1, 0, 0],
    [0, 1, 0, 0, 0],
  ],
  alert: [
    [0, 0, 1, 0, 0],
    [0, 0, 1, 0, 0],
    [0, 0, 1, 0, 0],
    [0, 0, 0, 0, 0],
    [0, 0, 1, 0, 0],
  ],
  clear: [
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
  ],
};

function downloadTextFile(filename: string, content: string, mime = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildBlueprintMarkdown(bp: DesignBlueprint): string {
  const lines: string[] = [
    `# ${bp.title}`,
    "",
    `- **Verdict:** ${bp.verdict}`,
    `- **Feasibility Score:** ${bp.feasibility_score}/100`,
    `- **Creativity Tier:** ${bp.creativity_level}/5`,
    `- **Persona:** ${bp.persona}`,
    `- **Model:** ${bp.model_used}`,
    "",
    `## Concept`,
    bp.idea,
    "",
    `## Summary`,
    bp.summary,
    "",
    `## Parts Used (${bp.parts_used.length})`,
    ...bp.parts_used.map(
      (p) => `- **${p.name}** (${p.owned ? "Owned" : "Proposed"}) — ${p.role}`
    ),
    "",
    `## Missing / Suggested Parts (${bp.missing_parts.length})`,
    ...(bp.missing_parts.length === 0
      ? ["- None — 100% buildable with current lab inventory!"]
      : bp.missing_parts.map(
          (m) => `- **${m.name}** (~$${m.est_cost_usd}) [${m.interfaces.join(", ")}] — ${m.reason}`
        )),
    "",
    `## Electrical & Protocol Guardrails`,
    ...bp.electrical_checks.map((c) => `- [${c.status.toUpperCase()}] **${c.topic}:** ${c.detail}`),
    "",
    `## Architecture Steps`,
    ...bp.architecture_steps.map((s, i) => `${i + 1}. ${s}`),
    "",
    `## Prototype Tonight`,
    ...(bp.build_tonight_vs_moonshot?.tonight ?? []).map((t) => `- ${t}`),
    "",
    `## Moonshot Unlocks`,
    ...(bp.build_tonight_vs_moonshot?.moonshot ?? []).map((m) => `- ${m}`),
    "",
  ];
  return lines.join("\n");
}

function getVerdictBadge(verdict: string): {
  label: string;
  variant: "sky" | "amber" | "fault" | "neutral";
  className: string;
} {
  if (verdict === "buildable_now") {
    return {
      label: "BUILDABLE NOW",
      variant: "sky",
      className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
    };
  }
  if (verdict === "needs_minor_parts") {
    return { label: "NEEDS MINOR PARTS", variant: "amber", className: "" };
  }
  if (verdict === "hardware_limit") {
    return { label: "HARDWARE LIMIT", variant: "fault", className: "" };
  }
  return { label: verdict.toUpperCase(), variant: "neutral", className: "" };
}

function getTierButtonClass(level: CreativityLevel, active: boolean): string {
  if (!active) {
    return "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:border-white/25 hover:text-white";
  }
  switch (level) {
    case 1:
      return "border-emerald-500/60 bg-emerald-500/20 text-emerald-300 shadow-sm";
    case 2:
      return "border-eigenia-sky/60 bg-eigenia-sky/20 text-eigenia-sky shadow-sm";
    case 3:
      return "border-eigenia-orange/70 bg-eigenia-orange/25 text-white shadow-sm";
    case 4:
      return "border-eigenia-amber/70 bg-eigenia-amber/25 text-eigenia-amber shadow-sm";
    case 5:
      return "border-fuchsia-500/70 bg-fuchsia-500/25 text-fuchsia-300 shadow-sm";
  }
}

export function LabArchitectStudio() {
  const { activeSpaceId, activeRobotId } = useStudio();

  const [activeTab, setActiveTab] = useState<ArchitectTabId>("studio");
  const [canvasView, setCanvasView] = useState<CanvasViewMode>("split");

  // Core data stores
  const [profiles, setProfiles] = useState<DeviceProfile[]>([]);
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [inventoryCounts, setInventoryCounts] = useState<InventoryCounts>({
    owned: 0,
    wishlist: 0,
    deployed: 0,
    total: 0,
  });
  const [managedDevices, setManagedDevices] = useState<ManagedDevice[]>([]);
  const [blueprints, setBlueprints] = useState<DesignBlueprint[]>([]);
  const [activeBlueprint, setActiveBlueprint] = useState<DesignBlueprint | null>(null);

  // Co-Design Canvas state
  const [creativityLevel, setCreativityLevel] = useState<CreativityLevel>(3);
  const [persona, setPersona] = useState<ArchitectPersona>("systems_architect");
  const [ideaPrompt, setIdeaPrompt] = useState("");
  const [lockedPartIds, setLockedPartIds] = useState<string[]>([]);
  const [excludedPartIds, setExcludedPartIds] = useState<string[]>([]);
  const [canvasPartNames, setCanvasPartNames] = useState<string[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [refineInput, setRefineInput] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const [refining, setRefining] = useState(false);

  // Idea Generator state
  const [ideaFocus, setIdeaFocus] = useState("all");
  const [generatedIdeas, setGeneratedIdeas] = useState<ArchitectIdea[]>([]);
  const [ideasModel, setIdeasModel] = useState<string | null>(null);
  const [ideating, setIdeating] = useState(false);

  // Inventory CRUD state
  const [invSearch, setInvSearch] = useState("");
  const [invStatusFilter, setInvStatusFilter] = useState<"all" | "owned" | "wishlist" | "deployed">(
    "all"
  );
  const [invCategoryFilter, setInvCategoryFilter] = useState<string>("all");
  const [invDrawerOpen, setInvDrawerOpen] = useState(false);
  const [editingInvId, setEditingInvId] = useState<string | null>(null);
  const [invDraft, setInvDraft] = useState<{
    name: string;
    category: InventoryCategory;
    manufacturer: string;
    model: string;
    quantity: number;
    status: InventoryStatus;
    location: string;
    interfaces: string;
    voltage_v: string;
    current_ma: string;
    notes: string;
    est_cost_usd: string;
  }>({
    name: "",
    category: "sensor",
    manufacturer: "",
    model: "",
    quantity: 1,
    status: "available",
    location: "Lab Bench",
    interfaces: "USB, I2C",
    voltage_v: "5",
    current_ma: "150",
    notes: "",
    est_cost_usd: "",
  });

  // Board Profiles, micro:bit & Local Camera Bridge state
  const [inspectedProfile, setInspectedProfile] = useState<DeviceProfile | null>(null);
  const [microbitProbe, setMicrobitProbe] = useState<MicrobitProbeResponse | null>(null);
  const [probingMicrobit, setProbingMicrobit] = useState(false);
  const [ledGrid, setLedGrid] = useState<number[][]>(LED_PRESETS.heart);
  const [mbText, setMbText] = useState("HELLO OX");
  const [mbIcon, setMbIcon] = useState("HEART");
  const [mbFreq, setMbFreq] = useState(880);
  const [mbBusy, setMbBusy] = useState(false);
  const [mbLastResp, setMbLastResp] = useState<MicrobitCommandResponse | null>(null);

  // Local Camera Array & Pi Zero Harvester state
  const [camName, setCamName] = useState("Front Porch LAN Cam");
  const [camUrl, setCamUrl] = useState("http://192.168.1.50/snapshot.jpg");
  const [camTransport, setCamTransport] = useState("http_snapshot");
  const [uploadCamName, setUploadCamName] = useState("Blink Local Clip");
  const [ingestingMedia, setIngestingMedia] = useState(false);
  const [ingestResult, setIngestResult] = useState<CameraIngestResponse | null>(null);
  const [piZeroHost, setPiZeroHost] = useState("http://192.168.1.100:8000");
  const [piZeroScript, setPiZeroScript] = useState<PiZeroGadgetScriptResponse | null>(null);
  const [loadingScript, setLoadingScript] = useState(false);

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Safe client-side ?tab= sync (no useSearchParams Suspense issues)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab") as ArchitectTabId | null;
    if (tabParam && VALID_TABS.includes(tabParam)) {
      setActiveTab(tabParam);
    }
    setPiZeroHost(`${window.location.protocol}//${window.location.hostname}:8000`);
  }, []);

  const handleTabChange = useCallback((nextId: string) => {
    const valid = VALID_TABS.includes(nextId as ArchitectTabId)
      ? (nextId as ArchitectTabId)
      : "studio";
    setActiveTab(valid);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", valid);
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const [profResp, invResp, devResp, bpResp] = await Promise.all([
        listDeviceProfiles().catch(() => ({ profiles: [] })),
        listInventory().catch(() => ({
          items: [],
          counts: { owned: 0, wishlist: 0, deployed: 0, total: 0 },
        })),
        listManagedDevices().catch(() => ({ devices: [] })),
        listDesignBlueprints().catch(() => ({ blueprints: [] })),
      ]);
      setProfiles(profResp.profiles);
      setInventory(invResp.items);
      setInventoryCounts(invResp.counts);
      setManagedDevices(devResp.devices);
      setBlueprints(bpResp.blueprints);
      setActiveBlueprint((prev) => {
        if (prev) {
          const updated = bpResp.blueprints.find((b) => b.id === prev.id);
          return updated ?? prev;
        }
        return bpResp.blueprints[0] ?? null;
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to load Lab Architect data",
      });
    }
  }, []);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const activeTierMeta =
    CREATIVITY_TIERS.find((t) => t.level === creativityLevel) ?? CREATIVITY_TIERS[2];

  const ownedInventory = useMemo(
    () => inventory.filter((i) => i.status === "available" || i.status === "deployed"),
    [inventory]
  );

  const microbitProfile = useMemo(
    () => profiles.find((p) => p.profile_id === "microbit_v2_21") ?? null,
    [profiles]
  );

  const filteredInventory = useMemo(() => {
    const q = invSearch.trim().toLowerCase();
    return inventory.filter((item) => {
      if (invStatusFilter === "owned" && item.status !== "available" && item.status !== "deployed") {
        return false;
      }
      if (
        invStatusFilter === "wishlist" &&
        item.status !== "wishlist" &&
        item.status !== "needs_part"
      ) {
        return false;
      }
      if (invStatusFilter === "deployed" && item.status !== "deployed") {
        return false;
      }
      if (invCategoryFilter !== "all" && item.category !== invCategoryFilter) {
        return false;
      }
      if (!q) return true;
      return `${item.name} ${item.manufacturer} ${item.model} ${item.category} ${item.location} ${item.interfaces.join(" ")} ${item.notes}`
        .toLowerCase()
        .includes(q);
    });
  }, [inventory, invSearch, invStatusFilter, invCategoryFilter]);

  const selectedPartObj = useMemo(() => {
    if (!selectedNodeId || !activeBlueprint) return null;
    const part3d = activeBlueprint.assembly_3d?.parts?.find((p) => p.id === selectedNodeId);
    if (part3d) return { id: part3d.id, label: part3d.label, owned: part3d.owned };
    const node2d = activeBlueprint.wiring_graph?.nodes?.find((n) => n.id === selectedNodeId);
    if (node2d) return { id: node2d.id, label: node2d.label, owned: true };
    return null;
  }, [selectedNodeId, activeBlueprint]);

  // --- Handlers ---

  const handleSyncLiveFleet = async () => {
    setBusyAction("sync_fleet");
    setBanner(null);
    try {
      const res = await syncFleetHardwareToInventory(true);
      await refreshAll();
      setBanner({
        kind: "ok",
        text: `Synced ${res.synced_hosts} live fleet node(s) + ${res.synced_peripherals} attached USB peripheral(s) into Lab Architect.`,
      });
    } catch (err) {
      setBanner({ kind: "error", text: err instanceof Error ? err.message : "Fleet hardware sync failed." });
    } finally {
      setBusyAction(null);
    }
  };

  const handleSeedLab = async () => {
    setBusyAction("seed");
    setBanner(null);
    try {
      const res = await seedLabInventory();
      await refreshAll();
      setBanner({
        kind: "ok",
        text:
          res.seeded > 0
            ? `Seeded ${res.seeded} starter lab hardware part(s) (Pi 5, PuppyPi, LD19, WonderEcho, Pi Zero 2 W, micro:bit v2.21, cameras).`
            : "Starter lab hardware parts are already present in your inventory.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to seed lab inventory",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleEvaluateIdea = async (
    overrideIdea?: string,
    overridePersona?: ArchitectPersona,
    overrideTier?: CreativityLevel
  ) => {
    const idea = (overrideIdea ?? ideaPrompt).trim();
    if (!idea || evaluating) return;
    setEvaluating(true);
    setBanner(null);
    try {
      const res = await evaluateDesignIdea({
        idea,
        creativity_level: overrideTier ?? creativityLevel,
        persona: overridePersona ?? persona,
        locked_part_ids: lockedPartIds,
        excluded_part_ids: excludedPartIds,
        canvas_part_names: canvasPartNames,
      });
      setActiveBlueprint(res.blueprint);
      setBlueprints((prev) => [
        res.blueprint,
        ...prev.filter((b) => b.id !== res.blueprint.id),
      ]);
      setSelectedNodeId(null);
      setBanner({
        kind: "ok",
        text: `Synthesized "${res.blueprint.title}" — Feasibility ${res.blueprint.feasibility_score}/100 (${res.blueprint.parts_used.length} parts, ${res.blueprint.missing_parts.length} suggested).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Co-Design evaluation failed",
      });
    } finally {
      setEvaluating(false);
    }
  };

  const handleRefineBlueprint = async (
    messageOverride?: string,
    opts?: {
      personaOverride?: ArchitectPersona;
      acceptMissingPart?: string;
      selectedNodeOverride?: string | null;
    }
  ) => {
    if (!activeBlueprint || refining) return;
    const msg = (messageOverride ?? refineInput).trim();
    if (!msg && !opts?.acceptMissingPart) return;
    setRefining(true);
    setBanner(null);
    if (!messageOverride) setRefineInput("");
    try {
      const res = await refineDesignBlueprint(activeBlueprint.id, {
        message: msg || `Integrate ${opts?.acceptMissingPart} into the architecture`,
        selected_node_id: opts?.selectedNodeOverride ?? selectedNodeId,
        creativity_level: creativityLevel,
        persona: opts?.personaOverride ?? persona,
        locked_part_ids: lockedPartIds,
        excluded_part_ids: excludedPartIds,
        accept_missing_part: opts?.acceptMissingPart ?? null,
      });
      setActiveBlueprint(res.blueprint);
      setBlueprints((prev) => prev.map((b) => (b.id === res.blueprint.id ? res.blueprint : b)));
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Blueprint refinement failed",
      });
    } finally {
      setRefining(false);
    }
  };

  const handleRedTeam = () => {
    setPersona("red_team");
    if (activeBlueprint) {
      void handleRefineBlueprint(
        "Red-team this design aggressively: expose every voltage mismatch, USB power bottleneck, wireless failure mode, single point of failure, and concrete fix.",
        { personaOverride: "red_team" }
      );
    } else if (ideaPrompt.trim()) {
      void handleEvaluateIdea(ideaPrompt, "red_team");
    } else {
      setBanner({
        kind: "error",
        text: "Enter an idea or load a blueprint first to run a Red-Team critique.",
      });
    }
  };

  const handleIdeate = async (focusOverride?: string) => {
    setIdeating(true);
    setBanner(null);
    try {
      const res = await ideateLabProjects({
        creativity_level: creativityLevel,
        focus_area: focusOverride ?? ideaFocus,
        count: 4,
        locked_part_ids: lockedPartIds,
        excluded_part_ids: excludedPartIds,
      });
      setGeneratedIdeas(res.ideas);
      setIdeasModel(res.model_used);
      setBanner({
        kind: "ok",
        text: `Generated ${res.ideas.length} Tier-${creativityLevel} (${activeTierMeta.shortLabel}) lab project ideas.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Idea generation failed",
      });
    } finally {
      setIdeating(false);
    }
  };

  const handleAdoptIdea = (idea: ArchitectIdea) => {
    const prompt = `${idea.title}: ${idea.pitch}`;
    setIdeaPrompt(prompt);
    const tier = Math.max(1, Math.min(5, Math.round(idea.creativity_level || creativityLevel))) as CreativityLevel;
    setCreativityLevel(tier);
    handleTabChange("studio");
    void handleEvaluateIdea(prompt, persona, tier);
  };

  const handleAddMissingToWishlist = async (part: BlueprintMissingPart) => {
    setBusyAction(`wish-${part.name}`);
    try {
      await createInventoryItem({
        name: part.name,
        profile_id: part.profile_id || null,
        category: INVENTORY_CATEGORIES.includes(part.category as InventoryCategory)
          ? (part.category as InventoryCategory)
          : "sensor",
        status: "wishlist",
        quantity: 1,
        interfaces: part.interfaces,
        est_cost_usd: part.est_cost_usd,
        notes: part.reason,
      });
      await refreshAll();
      setBanner({ kind: "ok", text: `Added "${part.name}" (~$${part.est_cost_usd}) to Wishlist.` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to add to wishlist",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const toggleLockPart = (id: string) => {
    setExcludedPartIds((prev) => prev.filter((x) => x !== id));
    setLockedPartIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleExcludePart = (id: string) => {
    setLockedPartIds((prev) => prev.filter((x) => x !== id));
    setExcludedPartIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // Inventory CRUD
  const openAddInventoryDrawer = () => {
    setEditingInvId(null);
    setInvDraft({
      name: "",
      category: "sensor",
      manufacturer: "",
      model: "",
      quantity: 1,
      status: "available",
      location: "Lab Bench",
      interfaces: "USB, I2C",
      voltage_v: "5",
      current_ma: "150",
      notes: "",
      est_cost_usd: "",
    });
    setInvDrawerOpen(true);
  };

  const openEditInventoryDrawer = (item: InventoryItem) => {
    setEditingInvId(item.id);
    setInvDraft({
      name: item.name,
      category: item.category,
      manufacturer: item.manufacturer,
      model: item.model,
      quantity: item.quantity,
      status: item.status,
      location: item.location,
      interfaces: item.interfaces.join(", "),
      voltage_v: item.voltage_v != null ? String(item.voltage_v) : "",
      current_ma: item.current_ma != null ? String(item.current_ma) : "",
      notes: item.notes,
      est_cost_usd: item.est_cost_usd != null ? String(item.est_cost_usd) : "",
    });
    setInvDrawerOpen(true);
  };

  const handleSaveInventoryItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!invDraft.name.trim()) return;
    setBusyAction("save-inv");
    setBanner(null);
    try {
      const payload = {
        name: invDraft.name.trim(),
        category: invDraft.category,
        manufacturer: invDraft.manufacturer.trim(),
        model: invDraft.model.trim(),
        quantity: Math.max(1, Number(invDraft.quantity) || 1),
        status: invDraft.status,
        location: invDraft.location.trim(),
        interfaces: invDraft.interfaces
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        voltage_v: invDraft.voltage_v.trim() ? Number(invDraft.voltage_v) : null,
        current_ma: invDraft.current_ma.trim() ? Number(invDraft.current_ma) : null,
        notes: invDraft.notes.trim(),
        est_cost_usd: invDraft.est_cost_usd.trim() ? Number(invDraft.est_cost_usd) : null,
      };
      if (editingInvId) {
        await updateInventoryItem(editingInvId, payload);
        setBanner({ kind: "ok", text: `Updated "${payload.name}" in Lab Inventory.` });
      } else {
        await createInventoryItem(payload);
        setBanner({ kind: "ok", text: `Added "${payload.name}" to Lab Inventory.` });
      }
      setInvDrawerOpen(false);
      await refreshAll();
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save inventory part",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleQuickQty = async (item: InventoryItem, delta: number) => {
    const nextQty = Math.max(1, item.quantity + delta);
    try {
      await updateInventoryItem(item.id, { quantity: nextQty });
      setInventory((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, quantity: nextQty } : i))
      );
    } catch {
      // Non-fatal
    }
  };

  const handleCycleStatus = async (item: InventoryItem) => {
    const order: InventoryStatus[] = ["available", "deployed", "wishlist"];
    const next = order[(order.indexOf(item.status) + 1) % order.length];
    try {
      await updateInventoryItem(item.id, { status: next });
      await refreshAll();
    } catch {
      // Non-fatal
    }
  };

  const handleDeleteInventory = async (item: InventoryItem) => {
    try {
      await deleteInventoryItem(item.id);
      await refreshAll();
      setBanner({ kind: "ok", text: `Removed "${item.name}" from Lab Inventory.` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete inventory part",
      });
    }
  };

  // micro:bit handlers
  const handleProbeMicrobit = async () => {
    setProbingMicrobit(true);
    try {
      const res = await probeMicrobitUsb();
      setMicrobitProbe(res);
      setBanner({
        kind: res.detected ? "ok" : "error",
        text: res.detected
          ? `BBC micro:bit detected (${res.ports.join(", ") || res.volumes.join(", ")})`
          : "No micro:bit USB serial/DAPLink volume detected on Docker host — offline MicroPython preview mode ready.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "micro:bit USB probe failed",
      });
    } finally {
      setProbingMicrobit(false);
    }
  };

  const handleMicrobitCmd = async (
    action: "show_text" | "show_icon" | "play_tone" | "read_sensors" | "set_matrix",
    payload?: unknown
  ) => {
    setMbBusy(true);
    try {
      const res = await sendMicrobitCommand({
        port: microbitProbe?.ports?.[0] ?? null,
        action,
        payload,
      });
      setMbLastResp(res);
      setBanner({ kind: "ok", text: res.detail });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "micro:bit command failed",
      });
    } finally {
      setMbBusy(false);
    }
  };

  const toggleLedCell = (r: number, c: number) => {
    setLedGrid((prev) =>
      prev.map((row, ri) => row.map((val, ci) => (ri === r && ci === c ? (val ? 0 : 1) : val)))
    );
  };

  // Local Camera Array & Pi Zero Harvester handlers
  const handleAddLocalCamera = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!camName.trim() || !camUrl.trim()) return;
    setBusyAction("add-cam");
    try {
      await createManagedDevice({
        name: camName.trim(),
        profile_id: "local_camera_array",
        space_id: activeSpaceId || null,
        transport: camTransport,
        endpoint: camUrl.trim(),
        status: "configured",
      });
      await refreshAll();
      setBanner({ kind: "ok", text: `Registered 100% local camera "${camName.trim()}".` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to register local camera",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleIngestFromStream = async (dev: ManagedDevice) => {
    setIngestingMedia(true);
    try {
      const res = await ingestLocalCameraMedia({
        stream_url: dev.endpoint,
        camera_name: dev.name,
        space_id: activeSpaceId || null,
        robot_id: activeRobotId || "local-camera",
      });
      setIngestResult(res);
      setBanner({
        kind: "ok",
        text: `Analyzed ${res.frames_analyzed} frame(s) from "${dev.name}" — logged ${res.recorded_count} Spatial Memory sighting(s) locally.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Local camera snapshot ingest failed",
      });
    } finally {
      setIngestingMedia(false);
    }
  };

  const handleUploadLocalMedia = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIngestingMedia(true);
    setBanner(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("camera_name", uploadCamName.trim() || "Local Clip");
      if (activeSpaceId) fd.append("space_id", activeSpaceId);
      if (activeRobotId) fd.append("robot_id", activeRobotId);
      const res = await ingestLocalCameraMedia(fd);
      setIngestResult(res);
      setBanner({
        kind: "ok",
        text: `Processed "${file.name}" (${res.frames_analyzed} sharpest frames) offline — recorded ${res.recorded_count} sighting(s) in Spatial Memory!`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Local media clip analysis failed",
      });
    } finally {
      setIngestingMedia(false);
      e.target.value = "";
    }
  };

  const handleGeneratePiZeroScript = async () => {
    setLoadingScript(true);
    try {
      const res = await fetchPiZeroGadgetScript({
        docker_host: piZeroHost.trim() || undefined,
        device_id: "pizero-blink-harvester",
      });
      setPiZeroScript(res);
      setBanner({
        kind: "ok",
        text: `Generated 100% cloud-free Pi Zero 2 W USB gadget harvester script (${res.filename}).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to generate Pi Zero gadget script",
      });
    } finally {
      setLoadingScript(false);
    }
  };

  const handleDeleteBlueprint = async (bp: DesignBlueprint) => {
    try {
      await deleteDesignBlueprint(bp.id);
      setBlueprints((prev) => prev.filter((b) => b.id !== bp.id));
      if (activeBlueprint?.id === bp.id) {
        setActiveBlueprint(null);
      }
      setBanner({ kind: "ok", text: `Deleted blueprint "${bp.title}".` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete blueprint",
      });
    }
  };

  const tabs: SegmentedTabItem[] = [
    {
      id: "studio",
      label: "Co-Design Canvas",
      icon: <Wand2 className="h-3.5 w-3.5" />,
      count: activeBlueprint?.parts_used?.length ?? undefined,
    },
    {
      id: "ideas",
      label: "Idea Generator",
      icon: <Lightbulb className="h-3.5 w-3.5" />,
      count: generatedIdeas.length > 0 ? generatedIdeas.length : undefined,
    },
    {
      id: "inventory",
      label: "Lab Inventory & Wishlist",
      icon: <Package className="h-3.5 w-3.5" />,
      count: inventoryCounts.total,
    },
    {
      id: "profiles",
      label: "Board Profiles & IoT",
      icon: <Cpu className="h-3.5 w-3.5" />,
      count: profiles.length,
    },
    {
      id: "blueprints",
      label: "Saved Blueprints",
      icon: <BookOpen className="h-3.5 w-3.5" />,
      count: blueprints.length,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* 1. STICKY WORKSPACE HEADER */}
      <WorkspaceHeader
        badge="LAB ARCHITECT · 100% LOCAL"
        title="Universal Hardware Envelope & Human-AI Co-Design Cockpit"
        subtitle="Combine owned Pi 5, PuppyPi, Pi Zero 2 W, micro:bit v2.21 & local cameras into live 2D wiring + 3D CAD blueprints"
        statusTone={inventoryCounts.owned > 0 ? "ok" : "idle"}
        statusLabel={`TIER ${creativityLevel} · ${activeTierMeta.shortLabel.toUpperCase()}`}
        sticky
        metrics={[
          { label: "Owned Parts", value: inventoryCounts.owned, tone: "emerald", compact: true },
          { label: "Wishlist", value: inventoryCounts.wishlist, tone: "amber", compact: true },
          { label: "Board Profiles", value: profiles.length, tone: "sky", compact: true },
          { label: "Blueprints", value: blueprints.length, tone: "orange", compact: true },
          {
            label: "Creativity",
            value: `T${creativityLevel} ${activeTierMeta.shortLabel}`,
            tone: creativityLevel >= 4 ? "orange" : "sky",
            compact: true,
          },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="sky"
              disabled={busyAction !== null}
              onClick={() => void handleSyncLiveFleet()}
              className="cursor-pointer"
              title="Probe registered Pis/robots over SSH for attached USB devices (micro:bit, webcams, LiDAR) and sync into Lab Architect"
            >
              {busyAction === "sync_fleet" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Sync Live Fleet &amp; USB
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={busyAction !== null}
              onClick={() => void handleSeedLab()}
            >
              {busyAction === "seed" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Package className="h-3.5 w-3.5 text-eigenia-sky" />
              )}
              Seed My Lab Parts
            </Button>
            <Button
              size="sm"
              variant="default"
              disabled={ideating}
              onClick={() => {
                handleTabChange("ideas");
                void handleIdeate();
              }}
            >
              {ideating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              Brainstorm Ideas
            </Button>
          </div>
        }
      />

      {banner && (
        <div
          className={`flex items-center justify-between rounded-md border px-3 py-2 font-mono text-xs ${
            banner.kind === "ok"
              ? "border-eigenia-sky/40 bg-eigenia-sky/10 text-eigenia-sky"
              : "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault"
          }`}
        >
          <span>{banner.text}</span>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="ml-3 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 2. 5 URL-SYNCED SEGMENTED TABS */}
      <SegmentedTabs
        tabs={tabs}
        value={activeTab}
        onValueChange={handleTabChange}
        rightSlot={
          activeTab === "studio" ? (
            <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
              {(
                [
                  { id: "2d", label: "2D Wiring", Icon: GitBranch },
                  { id: "3d", label: "3D Assembly", Icon: Box },
                  { id: "split", label: "Split View", Icon: LayoutGrid },
                ] as const
              ).map(({ id, label, Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setCanvasView(id)}
                  className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-mono text-[10px] font-medium transition motion-reduce:transition-none ${
                    canvasView === id
                      ? "bg-eigenia-orange text-white shadow-sm"
                      : "text-eigenia-muted hover:text-white"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
          ) : undefined
        }
      />

      {/* ===================================================================== */}
      {/* TAB 1: CO-DESIGN CANVAS                                               */}
      {/* ===================================================================== */}
      {activeTab === "studio" && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          {/* LEFT DOCK: OWNED INVENTORY + AI-SUGGESTED MISSING PARTS */}
          <div className="flex flex-col gap-4 xl:col-span-3">
            <InteractiveSurface
              title={`Owned Lab Parts (${ownedInventory.length})`}
              subtitle="Lock required parts, exclude parts, or add to prompt"
              accent="emerald"
              headerRight={
                <Button size="sm" variant="ghost" className="h-6 px-1.5" onClick={openAddInventoryDrawer}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              }
              contentClassName="space-y-2 max-h-[380px] overflow-y-auto pr-1"
            >
              {ownedInventory.length === 0 ? (
                <div className="space-y-2 rounded border border-dashed border-white/10 p-4 text-center text-xs text-eigenia-muted">
                  <p>No owned parts in inventory yet.</p>
                  <Button size="sm" variant="sky" onClick={() => void handleSeedLab()}>
                    Seed My Lab Starter Kit
                  </Button>
                </div>
              ) : (
                ownedInventory.map((item) => {
                  const locked = lockedPartIds.includes(item.id);
                  const excluded = excludedPartIds.includes(item.id);
                  const addedToCanvas = canvasPartNames.includes(item.name);
                  return (
                    <div
                      key={item.id}
                      className={`rounded-md border p-2.5 transition ${
                        locked
                          ? "border-eigenia-sky/60 bg-eigenia-sky/10"
                          : excluded
                            ? "border-eigenia-fault/40 bg-eigenia-obsidian/40 opacity-55"
                            : "border-white/10 bg-eigenia-obsidian hover:border-white/25"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold text-white">
                            {item.name}
                          </div>
                          <div className="font-mono text-[9px] text-eigenia-muted">
                            ×{item.quantity} · {item.category}
                            {item.voltage_v ? ` · ${item.voltage_v}V` : ""}
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => toggleLockPart(item.id)}
                            title={locked ? "Unlock part" : "Lock part (must include)"}
                            className={`rounded border p-1 transition ${
                              locked
                                ? "border-eigenia-sky bg-eigenia-sky/20 text-eigenia-sky"
                                : "border-white/10 text-eigenia-muted hover:text-white"
                            }`}
                          >
                            {locked ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleExcludePart(item.id)}
                            title={excluded ? "Re-include part" : "Exclude part"}
                            className={`rounded border p-1 transition ${
                              excluded
                                ? "border-eigenia-fault bg-eigenia-fault/20 text-eigenia-fault"
                                : "border-white/10 text-eigenia-muted hover:text-white"
                            }`}
                          >
                            <Ban className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setCanvasPartNames((prev) =>
                                prev.includes(item.name)
                                  ? prev.filter((n) => n !== item.name)
                                  : [...prev, item.name]
                              )
                            }
                            title="Pin to concept focus"
                            className={`rounded border px-1.5 py-0.5 font-mono text-[9px] transition ${
                              addedToCanvas
                                ? "border-eigenia-orange bg-eigenia-orange/25 text-white"
                                : "border-white/10 text-eigenia-muted hover:text-white"
                            }`}
                          >
                            {addedToCanvas ? "✓" : "+"}
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </InteractiveSurface>

            {/* AI-Suggested Missing Parts */}
            <InteractiveSurface
              title={`AI-Suggested Parts (${activeBlueprint?.missing_parts?.length ?? 0})`}
              subtitle="Accept into architecture or save to Wishlist"
              accent="amber"
              contentClassName="space-y-2 max-h-[300px] overflow-y-auto pr-1"
            >
              {!activeBlueprint || activeBlueprint.missing_parts.length === 0 ? (
                <div className="rounded border border-dashed border-white/10 p-3 text-center font-mono text-[10px] text-eigenia-muted">
                  {activeBlueprint
                    ? "Zero extra parts required — 100% buildable tonight!"
                    : "Evaluate a design idea to see any recommended adapters or sensors."}
                </div>
              ) : (
                activeBlueprint.missing_parts.map((mp) => (
                  <div
                    key={mp.name}
                    className="space-y-2 rounded-md border border-eigenia-amber/35 bg-eigenia-amber/10 p-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-xs font-semibold text-white">{mp.name}</span>
                      <Badge variant="amber" className="shrink-0 font-mono text-[9px] tabular-nums">
                        ~${mp.est_cost_usd}
                      </Badge>
                    </div>
                    <p className="text-[10px] leading-relaxed text-eigenia-ink">{mp.reason}</p>
                    <div className="flex flex-wrap gap-1">
                      {mp.interfaces.map((iface) => (
                        <Badge key={iface} variant="neutral" className="font-mono text-[8px]">
                          {iface}
                        </Badge>
                      ))}
                    </div>
                    <div className="flex items-center gap-1.5 pt-0.5">
                      <Button
                        size="sm"
                        variant="default"
                        className="h-6 flex-1 px-2 text-[10px]"
                        disabled={refining}
                        onClick={() =>
                          void handleRefineBlueprint(
                            `Accept and wire "${mp.name}" into the design.`,
                            { acceptMissingPart: mp.name }
                          )
                        }
                      >
                        <Check className="h-3 w-3" />
                        Accept
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-6 flex-1 px-2 text-[10px]"
                        disabled={busyAction === `wish-${mp.name}`}
                        onClick={() => void handleAddMissingToWishlist(mp)}
                      >
                        <Plus className="h-3 w-3" />
                        Wishlist
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </InteractiveSurface>
          </div>

          {/* CENTER DUAL CANVAS: 2D WIRING + 3D ASSEMBLY + VERSION HISTORY */}
          <div className="flex flex-col gap-4 xl:col-span-5">
            {!activeBlueprint ? (
              <Card className="border-eigenia-orange/35 bg-eigenia-shell">
                <CardContent className="flex min-h-[500px] flex-col items-center justify-center gap-4 p-6 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-eigenia-orange/50 bg-eigenia-orange/15">
                    <Wand2 className="h-6 w-6 text-eigenia-orange" />
                  </div>
                  <div className="space-y-1">
                    <div className="text-sm font-semibold text-white">
                      Co-Design Your Next Cyber-Physical Build
                    </div>
                    <p className="max-w-md text-xs text-eigenia-muted">
                      Pick a Creativity Tier (`1–5`) on the right and click a starter concept below
                      (or type your own) to generate a live 2D Wiring Graph + 3D CAD Assembly.
                    </p>
                  </div>
                  <div className="flex w-full max-w-lg flex-col gap-2">
                    {STARTER_PROMPTS.map((sp) => (
                      <button
                        key={sp}
                        type="button"
                        disabled={evaluating}
                        onClick={() => {
                          setIdeaPrompt(sp);
                          void handleEvaluateIdea(sp);
                        }}
                        className="rounded-lg border border-white/10 bg-eigenia-obsidian px-3.5 py-2.5 text-left text-xs text-eigenia-ink transition hover:border-eigenia-orange/60 hover:text-white"
                      >
                        &quot;{sp}&quot;
                      </button>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ) : (
              <>
                {/* Blueprint Canvas Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-shell px-3.5 py-2.5">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-white">
                        {activeBlueprint.title}
                      </span>
                      <Badge
                        variant={getVerdictBadge(activeBlueprint.verdict).variant}
                        className={`font-mono text-[9px] ${
                          getVerdictBadge(activeBlueprint.verdict).className
                        }`}
                      >
                        {getVerdictBadge(activeBlueprint.verdict).label}
                      </Badge>
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
                      Model: {activeBlueprint.model_used} · Tier {activeBlueprint.creativity_level}/5 ·{" "}
                      {activeBlueprint.parts_used.length} parts wired
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      downloadTextFile(
                        `${activeBlueprint.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.md`,
                        buildBlueprintMarkdown(activeBlueprint),
                        "text/markdown;charset=utf-8"
                      )
                    }
                  >
                    <Download className="h-3.5 w-3.5 text-eigenia-orange" />
                    Export Markdown Spec
                  </Button>
                </div>

                {/* 2D Wiring / 3D Assembly / Split View */}
                {(canvasView === "2d" || canvasView === "split") && (
                  <TopologyFlowCanvas
                    nodes={activeBlueprint.wiring_graph?.nodes ?? []}
                    edges={activeBlueprint.wiring_graph?.edges ?? []}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={(id) => setSelectedNodeId(id)}
                    heightClassName={canvasView === "split" ? "h-[320px]" : "h-[520px]"}
                    title="2D Wiring & Protocol Topology (Click Any Node to Point & Ask)"
                    legend
                  />
                )}

                {(canvasView === "3d" || canvasView === "split") && (
                  <CoDesignAssembly3D
                    parts={activeBlueprint.assembly_3d?.parts ?? []}
                    links={activeBlueprint.assembly_3d?.links ?? []}
                    selectedPartId={selectedNodeId}
                    onSelectPart={(id) => setSelectedNodeId(id)}
                    heightClassName={canvasView === "split" ? "h-[360px]" : "h-[520px]"}
                    title="3D Co-Design Hardware Assembly (Wireframe / Translucent / Solid + Exploded)"
                  />
                )}

                {/* Prototype Tonight vs Moonshot Unlocks */}
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <InteractiveSurface
                    title="Prototype Tonight"
                    badge={
                      <Badge
                        variant="sky"
                        className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[9px] text-emerald-400"
                      >
                        OWNED PARTS
                      </Badge>
                    }
                    accent="emerald"
                  >
                    <ul className="space-y-1.5 text-xs text-eigenia-ink">
                      {(activeBlueprint.build_tonight_vs_moonshot?.tonight ?? []).map((t, i) => (
                        <li key={`tonight-${i}`} className="flex items-start gap-1.5">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                          <span>{t}</span>
                        </li>
                      ))}
                    </ul>
                  </InteractiveSurface>

                  <InteractiveSurface
                    title="Moonshot Unlocks"
                    badge={
                      <Badge variant="amber" className="font-mono text-[9px]">
                        <Rocket className="h-2.5 w-2.5" /> NEXT PHASE
                      </Badge>
                    }
                    accent="orange"
                  >
                    <ul className="space-y-1.5 text-xs text-eigenia-ink">
                      {(activeBlueprint.build_tonight_vs_moonshot?.moonshot ?? []).map((m, i) => (
                        <li key={`moonshot-${i}`} className="flex items-start gap-1.5">
                          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-eigenia-orange" />
                          <span>{m}</span>
                        </li>
                      ))}
                    </ul>
                  </InteractiveSurface>
                </div>

                {/* Version History Strip */}
                {Array.isArray(activeBlueprint.versions) && activeBlueprint.versions.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-eigenia-shell px-3 py-2">
                    <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase text-eigenia-muted">
                      <History className="h-3 w-3 text-eigenia-sky" />
                      Version History:
                    </span>
                    {activeBlueprint.versions.map((v) => (
                      <Badge
                        key={`v-${v.version}`}
                        variant="neutral"
                        className="font-mono text-[9px] tabular-nums"
                      >
                        v{v.version} · {v.label} · T{v.creativity_level} · {v.feasibility_score}%
                      </Badge>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* RIGHT RAIL: HUMAN-AI PARTNER (5-TIER DIAL, 4 LENSES, GUARDRAILS & CHAT) */}
          <div className="flex flex-col gap-4 xl:col-span-4">
            {/* 5-Tier Creativity Dial + 4 Specialist Lenses + Prompt */}
            <InteractiveSurface
              title="Human-AI Engineering Partner"
              subtitle="Tune creativity ambition & specialist engineering lens"
              accent="orange"
              contentClassName="space-y-3"
            >
              {/* 5-Tier Creativity & Ambition Dial */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between font-mono text-[10px]">
                  <span className="flex items-center gap-1 uppercase text-eigenia-muted">
                    <Flame className="h-3 w-3 text-eigenia-orange" />
                    Creativity &amp; Ambition Dial
                  </span>
                  <span className="font-semibold text-white">{activeTierMeta.label}</span>
                </div>
                <div className="grid grid-cols-5 gap-1">
                  {CREATIVITY_TIERS.map((tier) => (
                    <button
                      key={tier.level}
                      type="button"
                      onClick={() => setCreativityLevel(tier.level)}
                      className={`rounded-md border px-1.5 py-1.5 text-center font-mono text-[10px] font-semibold transition ${getTierButtonClass(
                        tier.level,
                        creativityLevel === tier.level
                      )}`}
                    >
                      <div>T{tier.level}</div>
                      <div className="truncate text-[8px] font-normal opacity-85">
                        {tier.shortLabel}
                      </div>
                    </button>
                  ))}
                </div>
                <div className="rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-1.5 text-[10px] text-eigenia-ink">
                  {activeTierMeta.description}
                </div>
              </div>

              {/* 4 Specialist Lenses */}
              <div className="space-y-1.5">
                <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                  Specialist Lens
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {ARCHITECT_PERSONAS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPersona(p.id)}
                      className={`rounded-md border px-2 py-1.5 text-left font-mono text-[10px] transition ${
                        persona === p.id
                          ? "border-eigenia-sky bg-eigenia-sky/15 font-semibold text-white"
                          : "border-white/10 bg-eigenia-obsidian text-eigenia-muted hover:text-white"
                      }`}
                      title={p.focus}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Pinned Canvas Part Chips */}
              {canvasPartNames.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <span className="font-mono text-[9px] uppercase text-eigenia-muted">Pinned:</span>
                  {canvasPartNames.map((name) => (
                    <Badge
                      key={name}
                      variant="default"
                      className="cursor-pointer font-mono text-[9px]"
                      onClick={() =>
                        setCanvasPartNames((prev) => prev.filter((n) => n !== name))
                      }
                    >
                      {name} ×
                    </Badge>
                  ))}
                </div>
              )}

              {/* Idea Prompt Box */}
              <div className="space-y-2">
                <textarea
                  rows={3}
                  value={ideaPrompt}
                  onChange={(e) => setIdeaPrompt(e.target.value)}
                  placeholder="Describe what you want to build with your lab hardware (e.g. 'Use PuppyPi + micro:bit wearable beacon + local Blink clip harvester')..."
                  className="w-full rounded-md border border-white/15 bg-eigenia-obsidian p-2.5 text-xs text-white placeholder:text-eigenia-muted focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="default"
                    className="flex-1 font-semibold"
                    disabled={evaluating || !ideaPrompt.trim()}
                    onClick={() => void handleEvaluateIdea()}
                  >
                    {evaluating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="h-3.5 w-3.5" />
                    )}
                    {evaluating ? "Synthesizing..." : "Evaluate & Build Canvas"}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={evaluating || refining || (!activeBlueprint && !ideaPrompt.trim())}
                    onClick={handleRedTeam}
                  >
                    <ShieldAlert className="h-3.5 w-3.5" />
                    Red-Team
                  </Button>
                </div>
              </div>
            </InteractiveSurface>

            {/* Feasibility Gauge & Electrical Guardrails */}
            {activeBlueprint && (
              <InteractiveSurface
                title="Feasibility & Electrical Guardrails"
                accent={
                  activeBlueprint.feasibility_score >= 75
                    ? "emerald"
                    : activeBlueprint.feasibility_score >= 50
                      ? "amber"
                      : "fault"
                }
                contentClassName="space-y-3"
              >
                <AnimatedMetric
                  label="Feasibility Score"
                  value={activeBlueprint.feasibility_score}
                  unit="/ 100"
                  tone={
                    activeBlueprint.feasibility_score >= 75
                      ? "emerald"
                      : activeBlueprint.feasibility_score >= 50
                        ? "amber"
                        : "fault"
                  }
                  progressPct={activeBlueprint.feasibility_score}
                  hint={activeBlueprint.summary}
                />

                <div className="space-y-1.5">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                    Electrical &amp; Protocol Checks ({activeBlueprint.electrical_checks.length})
                  </div>
                  {activeBlueprint.electrical_checks.map((chk, idx) => (
                    <div
                      key={`chk-${idx}`}
                      className={`rounded-md border px-2.5 py-2 text-[11px] ${
                        chk.status === "fault"
                          ? "border-eigenia-fault/50 bg-eigenia-fault/15 text-eigenia-fault"
                          : chk.status === "warning"
                            ? "border-eigenia-amber/45 bg-eigenia-amber/10 text-eigenia-amber"
                            : "border-emerald-500/35 bg-emerald-500/10 text-emerald-300"
                      }`}
                    >
                      <div className="font-mono text-[10px] font-semibold uppercase">
                        {chk.status} · {chk.topic}
                      </div>
                      <div className="mt-0.5 text-white">{chk.detail}</div>
                    </div>
                  ))}
                </div>
              </InteractiveSurface>
            )}

            {/* Point & Ask + Multi-Turn Walkthrough Chat */}
            {activeBlueprint && (
              <InteractiveSurface
                title="Interactive Walkthrough & Point-and-Ask"
                accent="sky"
                contentClassName="space-y-2.5"
              >
                {selectedPartObj && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-eigenia-orange/50 bg-eigenia-orange/15 px-2.5 py-1.5 text-[11px]">
                    <span className="font-mono text-white">
                      Selected: <span className="font-semibold">{selectedPartObj.label}</span>
                    </span>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="default"
                        className="h-6 px-2 text-[9px]"
                        disabled={refining}
                        onClick={() =>
                          void handleRefineBlueprint(
                            `Inspect wiring, power budget, and potential failure modes specifically for ${selectedPartObj.label}.`,
                            { selectedNodeOverride: selectedPartObj.id }
                          )
                        }
                      >
                        Point &amp; Ask
                      </Button>
                      <button
                        type="button"
                        onClick={() => setSelectedNodeId(null)}
                        className="px-1 font-mono text-[10px] text-eigenia-muted hover:text-white"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )}

                <div className="max-h-56 space-y-2 overflow-y-auto rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  {(activeBlueprint.chat_history ?? []).length === 0 ? (
                    <div className="py-4 text-center font-mono text-[10px] text-eigenia-muted">
                      Ask a follow-up question or click any 2D/3D hardware node to iterate on the
                      design.
                    </div>
                  ) : (
                    activeBlueprint.chat_history.map((m, idx) => (
                      <div
                        key={`chat-${idx}`}
                        className={`rounded-md border px-2.5 py-2 text-xs ${
                          m.role === "user"
                            ? "ml-6 border-eigenia-orange/40 bg-eigenia-orange/15 text-white"
                            : "mr-4 border-white/10 bg-eigenia-surface text-eigenia-ink"
                        }`}
                      >
                        <div className="mb-0.5 font-mono text-[9px] uppercase text-eigenia-muted">
                          {m.role === "user" ? "You" : m.persona || "Lab Architect"}
                        </div>
                        <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
                      </div>
                    ))
                  )}
                </div>

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleRefineBlueprint();
                  }}
                  className="flex gap-2"
                >
                  <Input
                    value={refineInput}
                    onChange={(e) => setRefineInput(e.target.value)}
                    placeholder={
                      selectedPartObj
                        ? `Ask about ${selectedPartObj.label}...`
                        : "Iterate: e.g. 'Swap to 3.3V logic shifter'..."
                    }
                    className="h-8 text-xs"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    variant="sky"
                    disabled={refining || !refineInput.trim()}
                  >
                    {refining ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </form>
              </InteractiveSurface>
            )}
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 2: IDEA GENERATOR                                                 */}
      {/* ===================================================================== */}
      {activeTab === "ideas" && (
        <div className="space-y-4">
          <InteractiveSurface
            title="5-Tier Hardware Idea Generator"
            subtitle="Brainstorms grounded or groundbreaking builds strictly tailored to your owned lab hardware"
            accent="orange"
            contentClassName="space-y-3"
          >
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="space-y-1.5 lg:col-span-6">
                <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                  Creativity Tier: <span className="text-white">{activeTierMeta.label}</span>
                </div>
                <div className="grid grid-cols-5 gap-1.5">
                  {CREATIVITY_TIERS.map((tier) => (
                    <button
                      key={`idea-t-${tier.level}`}
                      type="button"
                      onClick={() => setCreativityLevel(tier.level)}
                      className={`rounded-md border px-2 py-2 text-center font-mono text-[10px] font-semibold transition ${getTierButtonClass(
                        tier.level,
                        creativityLevel === tier.level
                      )}`}
                    >
                      <div>Tier {tier.level}</div>
                      <div className="truncate text-[9px] font-normal opacity-85">
                        {tier.shortLabel}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5 lg:col-span-6">
                <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                  Focus Domain
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {IDEA_FOCUS_AREAS.map((f) => (
                    <Button
                      key={f.id}
                      size="sm"
                      variant={ideaFocus === f.id ? "sky" : "secondary"}
                      className="h-8 text-xs"
                      onClick={() => setIdeaFocus(f.id)}
                    >
                      {f.label}
                    </Button>
                  ))}
                  <Button
                    size="sm"
                    variant="default"
                    disabled={ideating}
                    onClick={() => void handleIdeate()}
                    className="ml-auto font-semibold"
                  >
                    {ideating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    {ideating ? "Brainstorming..." : "Generate Ideas"}
                  </Button>
                </div>
              </div>
            </div>
          </InteractiveSurface>

          {generatedIdeas.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
                <Lightbulb className="h-9 w-9 text-eigenia-amber/70" />
                <div className="text-sm font-semibold text-white">
                  Ready to Brainstorm for Your Hardware Lab
                </div>
                <p className="max-w-md text-xs text-eigenia-muted">
                  Select a Creativity Tier (`1–5`) and Focus Domain, then click{" "}
                  <span className="font-semibold text-white">Generate Ideas</span> to discover
                  builds tailored to your Pi 5, PuppyPi, Pi Zero 2 W, micro:bit v2.21 &amp; local
                  cameras.
                </p>
                <Button size="sm" onClick={() => void handleIdeate()}>
                  <Sparkles className="h-3.5 w-3.5" />
                  Generate 4 Ideas Now
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {ideasModel && (
                <div className="font-mono text-[10px] text-eigenia-muted">
                  Synthesized via <span className="text-eigenia-sky">{ideasModel}</span>
                </div>
              )}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {generatedIdeas.map((idea, idx) => {
                  const vb = getVerdictBadge(idea.verdict);
                  return (
                    <InteractiveSurface
                      key={`${idea.title}-${idx}`}
                      title={idea.title}
                      subtitle={`Tier ${idea.creativity_level} · ${idea.difficulty} · Est. ${idea.estimated_time}`}
                      badge={
                        <Badge variant={vb.variant} className={`font-mono text-[9px] ${vb.className}`}>
                          {vb.label}
                        </Badge>
                      }
                      accent={idea.creativity_level >= 4 ? "orange" : "sky"}
                      hoverable
                      contentClassName="flex flex-col justify-between gap-3"
                    >
                      <p className="text-xs leading-relaxed text-eigenia-ink">{idea.pitch}</p>

                      <div className="space-y-1.5">
                        <div className="flex flex-wrap gap-1">
                          {idea.parts_used.map((p) => (
                            <Badge key={p} variant="neutral" className="font-mono text-[9px]">
                              {p}
                            </Badge>
                          ))}
                        </div>
                        {idea.missing_parts.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1 font-mono text-[9px] text-eigenia-amber">
                            <span>Needs:</span>
                            {idea.missing_parts.map((m) => (
                              <Badge key={m} variant="amber" className="text-[8px]">
                                + {m}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>

                      <Button
                        size="sm"
                        variant="default"
                        className="w-full"
                        onClick={() => handleAdoptIdea(idea)}
                      >
                        Adopt onto Co-Design Canvas
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </InteractiveSurface>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 3: LAB INVENTORY & WISHLIST                                       */}
      {/* ===================================================================== */}
      {activeTab === "inventory" && (
        <div className="space-y-4">
          <InteractiveSurface
            title={`Lab Hardware Inventory & Wishlist (${filteredInventory.length} / ${inventory.length})`}
            subtitle="Track owned boards, sensors, deployed assets & wishlist parts feeding the AI Co-Design Architect"
            accent="emerald"
            headerRight={
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="secondary" onClick={() => void handleSeedLab()}>
                  <Package className="h-3.5 w-3.5 text-eigenia-sky" />
                  Seed Starter Kit
                </Button>
                <Button size="sm" variant="default" onClick={openAddInventoryDrawer}>
                  <Plus className="h-3.5 w-3.5" />
                  + Add Part
                </Button>
              </div>
            }
            contentClassName="space-y-3"
          >
            {/* Filter Bar */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                {(
                  [
                    { id: "all", label: `All (${inventoryCounts.total})` },
                    { id: "owned", label: `Owned (${inventoryCounts.owned})` },
                    { id: "deployed", label: `Deployed (${inventoryCounts.deployed})` },
                    { id: "wishlist", label: `Wishlist (${inventoryCounts.wishlist})` },
                  ] as const
                ).map((f) => (
                  <Button
                    key={f.id}
                    size="sm"
                    variant={invStatusFilter === f.id ? "default" : "secondary"}
                    className="h-7 px-2.5 font-mono text-[10px]"
                    onClick={() => setInvStatusFilter(f.id)}
                  >
                    {f.label}
                  </Button>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={invCategoryFilter}
                  onChange={(e) => setInvCategoryFilter(e.target.value)}
                  className="h-7 rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-[11px] text-white"
                >
                  <option value="all">All Categories</option>
                  {INVENTORY_CATEGORIES.map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
                <div className="relative w-56">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
                  <Input
                    value={invSearch}
                    onChange={(e) => setInvSearch(e.target.value)}
                    placeholder="Search part, interface, model..."
                    className="h-7 pl-8 font-mono text-[11px]"
                  />
                </div>
              </div>
            </div>

            {filteredInventory.length === 0 ? (
              <div className="rounded-lg border border-dashed border-white/10 p-8 text-center text-xs text-eigenia-muted">
                No inventory items match. Click{" "}
                <span className="font-semibold text-white">Seed Starter Kit</span> or{" "}
                <span className="font-semibold text-white">+ Add Part</span> above.
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                {filteredInventory.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col justify-between gap-2.5 rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5 transition hover:border-eigenia-sky/40"
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold text-white">
                            {item.name}
                          </div>
                          <div className="font-mono text-[10px] text-eigenia-muted">
                            {[item.manufacturer, item.model].filter(Boolean).join(" ") ||
                              item.category}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleCycleStatus(item)}
                          title="Click to cycle status (available → deployed → wishlist)"
                        >
                          <Badge
                            variant={
                              item.status === "wishlist" || item.status === "needs_part"
                                ? "amber"
                                : item.status === "deployed"
                                  ? "default"
                                  : "sky"
                            }
                            className="cursor-pointer font-mono text-[9px] uppercase"
                          >
                            {item.status}
                          </Badge>
                        </button>
                      </div>

                      <div className="flex flex-wrap gap-1 font-mono text-[9px]">
                        <Badge variant="neutral" className="text-[8px] uppercase">
                          {item.category}
                        </Badge>
                        {item.voltage_v != null && (
                          <Badge variant="sky" className="text-[8px]">
                            {item.voltage_v}V
                          </Badge>
                        )}
                        {item.current_ma != null && (
                          <Badge variant="neutral" className="text-[8px]">
                            {item.current_ma} mA
                          </Badge>
                        )}
                        {item.est_cost_usd != null && (
                          <Badge variant="amber" className="text-[8px]">
                            ${item.est_cost_usd}
                          </Badge>
                        )}
                        {item.interfaces.slice(0, 4).map((iface) => (
                          <Badge key={iface} variant="neutral" className="text-[8px]">
                            {iface}
                          </Badge>
                        ))}
                      </div>

                      {item.notes && (
                        <p className="line-clamp-2 text-[11px] text-eigenia-ink">{item.notes}</p>
                      )}
                    </div>

                    <div className="flex items-center justify-between border-t border-white/10 pt-2">
                      <div className="inline-flex items-center gap-1 rounded border border-white/10 bg-eigenia-shell px-1.5 py-0.5 font-mono text-[10px]">
                        <button
                          type="button"
                          onClick={() => void handleQuickQty(item, -1)}
                          className="px-1 text-eigenia-muted hover:text-white"
                        >
                          −
                        </button>
                        <span className="tabular-nums text-white">Qty {item.quantity}</span>
                        <button
                          type="button"
                          onClick={() => void handleQuickQty(item, 1)}
                          className="px-1 text-eigenia-muted hover:text-white"
                        >
                          +
                        </button>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-[10px]"
                          onClick={() => openEditInventoryDrawer(item)}
                        >
                          Edit
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6"
                          onClick={() => void handleDeleteInventory(item)}
                        >
                          <Trash2 className="h-3 w-3 text-eigenia-fault" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </InteractiveSurface>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 4: BOARD PROFILES & IOT (6 PROFILES + MICRO:BIT + LOCAL CAMERAS)  */}
      {/* ===================================================================== */}
      {activeTab === "profiles" && (
        <div className="space-y-4">
          {/* 6 Loadable Universal Hardware Envelope Profile Cards */}
          <InteractiveSurface
            title={`Universal Hardware Envelope Profiles (${profiles.length})`}
            subtitle="Click any board or camera profile to inspect electrical rails, interfaces, hard limits & firmware templates"
            accent="sky"
          >
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {profiles.map((prof) => (
                <div
                  key={prof.profile_id}
                  onClick={() => setInspectedProfile(prof)}
                  className="cursor-pointer rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5 transition-all duration-200 hover:-translate-y-0.5 hover:border-eigenia-sky/50 motion-reduce:transition-none"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-xs font-semibold text-white">
                        {prof.display_name}
                      </div>
                      <div className="mt-0.5 text-[11px] text-eigenia-muted">{prof.tagline}</div>
                    </div>
                    <Badge variant="sky" className="shrink-0 font-mono text-[9px] uppercase">
                      {prof.category}
                    </Badge>
                  </div>
                  <div className="mt-2.5 flex flex-wrap gap-1.5 font-mono text-[9px] tabular-nums">
                    <Badge variant="neutral">{prof.voltage_rail_v}V Rail</Badge>
                    <Badge variant="neutral">GPIO ≤ {prof.max_gpio_v}V</Badge>
                    <Badge variant="neutral">{prof.power_budget_ma} mA</Badge>
                    <Badge variant="neutral">
                      {prof.dimensions_mm[0]}×{prof.dimensions_mm[1]}×{prof.dimensions_mm[2]} mm
                    </Badge>
                  </div>
                  <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-2 font-mono text-[10px] text-eigenia-sky">
                    <span>{prof.firmware_templates.length} firmware template(s)</span>
                    <span>Inspect Specs →</span>
                  </div>
                </div>
              ))}
            </div>
          </InteractiveSurface>

          {/* 2-Column Interactive IoT Studios: micro:bit v2.21 + 100% Local Camera Array */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            {/* BBC micro:bit v2.21 Interactive Studio */}
            <InteractiveSurface
              title="BBC micro:bit v2.21 Interactive Studio"
              subtitle="5×5 Red LED Matrix Painter, USB DAPLink Probe, Serial REPL Commands & MicroPython Templates"
              accent="orange"
              className="xl:col-span-6"
              headerRight={
                <Button
                  size="sm"
                  variant="sky"
                  disabled={probingMicrobit}
                  onClick={() => void handleProbeMicrobit()}
                >
                  {probingMicrobit ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Usb className="h-3.5 w-3.5" />
                  )}
                  Probe USB DAPLink
                </Button>
              }
              contentClassName="space-y-4"
            >
              {microbitProbe && (
                <div
                  className={`rounded-md border px-3 py-2 font-mono text-[11px] ${
                    microbitProbe.detected
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                      : "border-eigenia-amber/40 bg-eigenia-amber/10 text-eigenia-amber"
                  }`}
                >
                  {microbitProbe.detected
                    ? `CONNECTED · Ports: ${microbitProbe.ports.join(", ") || "None"} · Volumes: ${microbitProbe.volumes.join(", ") || "None"}`
                    : "micro:bit USB not attached to Docker host — commands return ready-to-flash MicroPython code."}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-12">
                {/* 5x5 Red LED Matrix Painter */}
                <div className="space-y-2.5 sm:col-span-5">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                    5×5 Red LED Matrix Painter
                  </div>
                  <div className="mx-auto grid w-fit grid-cols-5 gap-1.5 rounded-lg border border-white/15 bg-eigenia-obsidian p-3">
                    {ledGrid.map((row, r) =>
                      row.map((lit, c) => (
                        <button
                          key={`led-${r}-${c}`}
                          type="button"
                          onClick={() => toggleLedCell(r, c)}
                          className={`h-7 w-7 rounded border transition ${
                            lit
                              ? "border-red-400 bg-red-500 shadow-[0_0_12px_rgba(239,68,68,0.8)]"
                              : "border-white/15 bg-zinc-900 hover:border-red-500/50"
                          }`}
                          title={`LED (${r}, ${c})`}
                        />
                      ))
                    )}
                  </div>
                  <div className="flex flex-wrap justify-center gap-1">
                    {(["heart", "check", "alert", "clear"] as const).map((preset) => (
                      <Button
                        key={preset}
                        size="sm"
                        variant="secondary"
                        className="h-6 px-2 font-mono text-[9px] uppercase"
                        onClick={() => setLedGrid(LED_PRESETS[preset])}
                      >
                        {preset}
                      </Button>
                    ))}
                  </div>
                  <Button
                    size="sm"
                    variant="default"
                    className="w-full"
                    disabled={mbBusy}
                    onClick={() => void handleMicrobitCmd("set_matrix", { grid: ledGrid })}
                  >
                    <Zap className="h-3.5 w-3.5" />
                    Send 5×5 Matrix
                  </Button>
                </div>

                {/* Text / Icon / Tone / Sensors Controls */}
                <div className="space-y-3 sm:col-span-7">
                  <div className="space-y-1">
                    <label className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Scroll Text
                    </label>
                    <div className="flex gap-1.5">
                      <Input
                        value={mbText}
                        onChange={(e) => setMbText(e.target.value)}
                        className="h-8 font-mono text-xs"
                      />
                      <Button
                        size="sm"
                        variant="sky"
                        disabled={mbBusy}
                        onClick={() => void handleMicrobitCmd("show_text", { text: mbText })}
                      >
                        Send
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Built-In Icon
                    </label>
                    <div className="flex gap-1.5">
                      <select
                        value={mbIcon}
                        onChange={(e) => setMbIcon(e.target.value)}
                        className="h-8 flex-1 rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white"
                      >
                        {["HEART", "HAPPY", "YES", "NO", "SURPRISED", "GHOST", "DUCK"].map((ic) => (
                          <option key={ic} value={ic}>
                            {ic}
                          </option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={mbBusy}
                        onClick={() => void handleMicrobitCmd("show_icon", { icon: mbIcon })}
                      >
                        Show
                      </Button>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    <div className="flex flex-1 items-center gap-1.5">
                      <Input
                        type="number"
                        value={mbFreq}
                        onChange={(e) => setMbFreq(Number(e.target.value) || 440)}
                        className="h-8 w-24 font-mono text-xs"
                      />
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={mbBusy}
                        onClick={() =>
                          void handleMicrobitCmd("play_tone", { freq: mbFreq, duration_ms: 250 })
                        }
                      >
                        <Music className="h-3.5 w-3.5" />
                        Tone
                      </Button>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={mbBusy}
                      onClick={() => void handleMicrobitCmd("read_sensors")}
                    >
                      <Radio className="h-3.5 w-3.5" />
                      Read Sensors
                    </Button>
                  </div>

                  {mbLastResp?.preview_code && (
                    <div className="space-y-1">
                      <div className="flex items-center justify-between font-mono text-[9px] uppercase text-eigenia-muted">
                        <span>Generated MicroPython Snippet</span>
                        <button
                          type="button"
                          onClick={() => void navigator.clipboard.writeText(mbLastResp.preview_code)}
                          className="text-eigenia-sky hover:underline"
                        >
                          Copy
                        </button>
                      </div>
                      <pre className="max-h-28 overflow-auto rounded border border-white/10 bg-eigenia-obsidian p-2 font-mono text-[10px] text-emerald-300">
                        {mbLastResp.preview_code}
                      </pre>
                    </div>
                  )}
                </div>
              </div>

              {/* 3 Downloadable MicroPython Templates */}
              {microbitProfile && microbitProfile.firmware_templates.length > 0 && (
                <div className="space-y-2 border-t border-white/10 pt-3">
                  <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-eigenia-sky">
                    <FileCode2 className="h-3.5 w-3.5" />
                    Downloadable MicroPython Firmware Templates (
                    {microbitProfile.firmware_templates.length})
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    {microbitProfile.firmware_templates.map((tpl) => (
                      <div
                        key={tpl.id}
                        className="flex flex-col justify-between gap-2 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5"
                      >
                        <div>
                          <div className="text-[11px] font-semibold text-white">{tpl.name}</div>
                          <div className="mt-0.5 text-[10px] text-eigenia-muted">
                            {tpl.description}
                          </div>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-6 flex-1 px-2 text-[9px]"
                            onClick={() => {
                              void navigator.clipboard.writeText(tpl.code);
                              setBanner({ kind: "ok", text: `Copied "${tpl.name}" MicroPython.` });
                            }}
                          >
                            <ClipboardCopy className="h-3 w-3" />
                            Copy
                          </Button>
                          <Button
                            size="sm"
                            variant="sky"
                            className="h-6 flex-1 px-2 text-[9px]"
                            onClick={() =>
                              downloadTextFile(`${tpl.id}.py`, tpl.code, "text/x-python")
                            }
                          >
                            <Download className="h-3 w-3" />
                            .py
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </InteractiveSurface>

            {/* 100% Local Camera Array & Pi Zero Clip Harvester (Zero Cloud!) */}
            <InteractiveSurface
              title="100% Local Camera Array & Pi Zero Clip Harvester"
              subtitle="Zero cloud accounts! Ingest LAN RTSP/MJPEG streams, local .mp4/.jpg clips, or Blink Sync Module 2 USB via Pi Zero 2 W"
              accent="emerald"
              className="xl:col-span-6"
              contentClassName="space-y-4"
            >
              {/* Add LAN Camera Form */}
              <form
                onSubmit={handleAddLocalCamera}
                className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3"
              >
                <div className="font-mono text-[10px] font-semibold uppercase text-eigenia-sky">
                  Register Local LAN RTSP / MJPEG Camera
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <Input
                    value={camName}
                    onChange={(e) => setCamName(e.target.value)}
                    placeholder="Camera Name"
                    className="h-8 text-xs"
                  />
                  <select
                    value={camTransport}
                    onChange={(e) => setCamTransport(e.target.value)}
                    className="h-8 rounded-md border border-white/15 bg-eigenia-shell px-2 font-mono text-xs text-white"
                  >
                    <option value="http_snapshot">HTTP Snapshot</option>
                    <option value="rtsp">RTSP Stream</option>
                    <option value="mjpeg">MJPEG Stream</option>
                  </select>
                  <Button
                    type="submit"
                    size="sm"
                    variant="sky"
                    disabled={busyAction === "add-cam"}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add LAN Camera
                  </Button>
                </div>
                <Input
                  value={camUrl}
                  onChange={(e) => setCamUrl(e.target.value)}
                  placeholder="rtsp://192.168.1.50:554/stream1 or http://.../snapshot.jpg"
                  className="h-8 font-mono text-xs"
                />
              </form>

              {/* Managed Local Devices List */}
              {managedDevices.length > 0 && (
                <div className="space-y-1.5">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                    Registered Local Cameras &amp; IoT Bridges ({managedDevices.length})
                  </div>
                  {managedDevices.map((dev) => (
                    <div
                      key={dev.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/10 bg-eigenia-obsidian px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-xs font-semibold text-white">{dev.name}</div>
                        <div className="truncate font-mono text-[10px] text-eigenia-muted">
                          {dev.transport} · {dev.endpoint}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="default"
                          className="h-6 px-2 text-[10px]"
                          disabled={ingestingMedia}
                          onClick={() => void handleIngestFromStream(dev)}
                        >
                          <Camera className="h-3 w-3" />
                          Analyze
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6"
                          onClick={async () => {
                            await deleteManagedDevice(dev.id);
                            await refreshAll();
                          }}
                        >
                          <Trash2 className="h-3 w-3 text-eigenia-fault" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Upload Local .mp4 / .jpg Clip & Run Offline AI Vision */}
              <div className="space-y-2 rounded-md border border-eigenia-orange/35 bg-eigenia-orange/10 p-3">
                <div className="font-mono text-[10px] font-semibold uppercase text-eigenia-orange">
                  Upload Local .mp4 / .jpg Clip → Offline AI Vision + Spatial Memory
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    value={uploadCamName}
                    onChange={(e) => setUploadCamName(e.target.value)}
                    placeholder="Camera / Source Label"
                    className="h-8 flex-1 text-xs"
                  />
                  <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md bg-eigenia-orange px-3 text-xs font-semibold text-white hover:bg-eigenia-orange/90">
                    {ingestingMedia ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Upload className="h-3.5 w-3.5" />
                    )}
                    {ingestingMedia ? "Analyzing Offline..." : "Upload .mp4 / .jpg"}
                    <input
                      type="file"
                      accept="video/mp4,video/quicktime,image/jpeg,image/png,.mp4,.mov,.jpg,.jpeg,.png"
                      className="hidden"
                      onChange={(e) => void handleUploadLocalMedia(e)}
                    />
                  </label>
                </div>
                {ingestResult && (
                  <div className="rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-1.5 font-mono text-[10px] text-emerald-300">
                    Source: {ingestResult.camera_source} · {ingestResult.frames_analyzed} frames
                    scanned · {ingestResult.recorded_count} Spatial Memory sighting(s) logged.
                  </div>
                )}
              </div>

              {/* 1-Click Pi Zero g_mass_storage Setup Script */}
              <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-mono text-[10px] font-semibold uppercase text-eigenia-sky">
                    Pi Zero 2 W USB Gadget Harvester (Blink Sync Module 2 · Zero Cloud)
                  </div>
                  <Button
                    size="sm"
                    variant="sky"
                    className="h-7 px-2.5 text-[10px]"
                    disabled={loadingScript}
                    onClick={() => void handleGeneratePiZeroScript()}
                  >
                    {loadingScript ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Terminal className="h-3 w-3" />
                    )}
                    Generate Setup Script
                  </Button>
                </div>
                <Input
                  value={piZeroHost}
                  onChange={(e) => setPiZeroHost(e.target.value)}
                  placeholder="Docker backend LAN URL (e.g. http://192.168.1.100:8000)"
                  className="h-7 font-mono text-[11px]"
                />
                {piZeroScript && (
                  <div className="space-y-2 pt-1">
                    {piZeroScript.instructions.length > 0 && (
                      <ol className="list-decimal space-y-0.5 pl-4 text-[10px] text-eigenia-ink">
                        {piZeroScript.instructions.map((step, i) => (
                          <li key={`pz-${i}`}>{step}</li>
                        ))}
                      </ol>
                    )}
                    <pre className="max-h-40 overflow-auto rounded border border-white/10 bg-eigenia-shell p-2.5 font-mono text-[10px] text-eigenia-sky">
                      {piZeroScript.script}
                    </pre>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-7 text-[10px]"
                        onClick={() => {
                          void navigator.clipboard.writeText(piZeroScript.script);
                          setBanner({ kind: "ok", text: "Copied Pi Zero gadget setup script." });
                        }}
                      >
                        <ClipboardCopy className="h-3 w-3" />
                        Copy Script
                      </Button>
                      <Button
                        size="sm"
                        variant="default"
                        className="h-7 text-[10px]"
                        onClick={() =>
                          downloadTextFile(
                            piZeroScript.filename,
                            piZeroScript.script,
                            "text/x-shellscript"
                          )
                        }
                      >
                        <Download className="h-3 w-3" />
                        Download {piZeroScript.filename}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </InteractiveSurface>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TAB 5: SAVED BLUEPRINTS                                               */}
      {/* ===================================================================== */}
      {activeTab === "blueprints" && (
        <div className="space-y-4">
          {blueprints.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
                <BookOpen className="h-9 w-9 text-eigenia-sky/70" />
                <div className="text-sm font-semibold text-white">No Saved Blueprints Yet</div>
                <p className="max-w-md text-xs text-eigenia-muted">
                  Evaluate an idea on the Co-Design Canvas or adopt an idea from the Idea Generator
                  to persist versioned 2D + 3D hardware blueprints into PostgreSQL 18.
                </p>
                <Button size="sm" onClick={() => handleTabChange("studio")}>
                  Open Co-Design Canvas
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {blueprints.map((bp) => {
                const vb = getVerdictBadge(bp.verdict);
                const isLoaded = activeBlueprint?.id === bp.id;
                return (
                  <InteractiveSurface
                    key={bp.id}
                    title={bp.title}
                    subtitle={`Tier ${bp.creativity_level} · ${bp.feasibility_score}/100 Feasibility · ${bp.parts_used.length} parts`}
                    badge={
                      <Badge variant={vb.variant} className={`font-mono text-[9px] ${vb.className}`}>
                        {vb.label}
                      </Badge>
                    }
                    accent={isLoaded ? "orange" : "sky"}
                    hoverable
                    contentClassName="flex flex-col justify-between gap-3"
                  >
                    <p className="line-clamp-3 text-xs leading-relaxed text-eigenia-ink">
                      {bp.summary || bp.idea}
                    </p>
                    <div className="flex flex-wrap gap-1 font-mono text-[9px]">
                      <Badge variant="neutral">v{bp.versions?.length || 1}</Badge>
                      <Badge variant="neutral">{bp.missing_parts.length} missing</Badge>
                      <Badge variant="neutral">
                        {bp.updated_at ? new Date(bp.updated_at).toLocaleDateString() : ""}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-1.5 border-t border-white/10 pt-2">
                      <Button
                        size="sm"
                        variant={isLoaded ? "secondary" : "default"}
                        className="h-7 flex-1 text-[10px]"
                        onClick={() => {
                          setActiveBlueprint(bp);
                          setIdeaPrompt(bp.idea);
                          setCreativityLevel(
                            Math.max(1, Math.min(5, bp.creativity_level || 3)) as CreativityLevel
                          );
                          handleTabChange("studio");
                        }}
                      >
                        Load onto Canvas
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-7 px-2 text-[10px]"
                        onClick={() =>
                          downloadTextFile(
                            `${bp.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.md`,
                            buildBlueprintMarkdown(bp),
                            "text/markdown;charset=utf-8"
                          )
                        }
                      >
                        <FileText className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        onClick={() => void handleDeleteBlueprint(bp)}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-eigenia-fault" />
                      </Button>
                    </div>
                  </InteractiveSurface>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* SLIDE-OVER DRAWER: ADD / EDIT INVENTORY PART */}
      <SlideOverDrawer
        open={invDrawerOpen}
        onClose={() => setInvDrawerOpen(false)}
        title={editingInvId ? "Edit Lab Hardware Part" : "Add Part to Lab Inventory"}
        subtitle="Parts marked available or deployed feed directly into the Co-Design Canvas"
        badge={invDraft.category.toUpperCase()}
        badgeVariant="sky"
      >
        <form onSubmit={handleSaveInventoryItem} className="space-y-3">
          <div className="space-y-1">
            <label className="font-mono text-[10px] uppercase text-eigenia-muted">Part Name</label>
            <Input
              required
              value={invDraft.name}
              onChange={(e) => setInvDraft({ ...invDraft, name: e.target.value })}
              placeholder="e.g. Raspberry Pi Zero 2 W"
              className="text-xs"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="font-mono text-[10px] uppercase text-eigenia-muted">Category</label>
              <select
                value={invDraft.category}
                onChange={(e) =>
                  setInvDraft({ ...invDraft, category: e.target.value as InventoryCategory })
                }
                className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white"
              >
                {INVENTORY_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="font-mono text-[10px] uppercase text-eigenia-muted">Status</label>
              <select
                value={invDraft.status}
                onChange={(e) =>
                  setInvDraft({ ...invDraft, status: e.target.value as InventoryStatus })
                }
                className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white"
              >
                <option value="available">Available (Owned)</option>
                <option value="deployed">Deployed</option>
                <option value="wishlist">Wishlist</option>
                <option value="needs_part">Needs Part</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input
              value={invDraft.manufacturer}
              onChange={(e) => setInvDraft({ ...invDraft, manufacturer: e.target.value })}
              placeholder="Manufacturer"
              className="text-xs"
            />
            <Input
              value={invDraft.model}
              onChange={(e) => setInvDraft({ ...invDraft, model: e.target.value })}
              placeholder="Model"
              className="text-xs"
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Input
              type="number"
              min={1}
              value={invDraft.quantity}
              onChange={(e) => setInvDraft({ ...invDraft, quantity: Number(e.target.value) || 1 })}
              placeholder="Qty"
              className="font-mono text-xs"
            />
            <Input
              value={invDraft.voltage_v}
              onChange={(e) => setInvDraft({ ...invDraft, voltage_v: e.target.value })}
              placeholder="Voltage (V)"
              className="font-mono text-xs"
            />
            <Input
              value={invDraft.current_ma}
              onChange={(e) => setInvDraft({ ...invDraft, current_ma: e.target.value })}
              placeholder="Current (mA)"
              className="font-mono text-xs"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input
              value={invDraft.location}
              onChange={(e) => setInvDraft({ ...invDraft, location: e.target.value })}
              placeholder="Location (e.g. Lab Bench)"
              className="text-xs"
            />
            <Input
              value={invDraft.est_cost_usd}
              onChange={(e) => setInvDraft({ ...invDraft, est_cost_usd: e.target.value })}
              placeholder="Est. Cost ($ USD)"
              className="font-mono text-xs"
            />
          </div>
          <Input
            value={invDraft.interfaces}
            onChange={(e) => setInvDraft({ ...invDraft, interfaces: e.target.value })}
            placeholder="Interfaces (comma-separated: USB, I2C, UART, Wi-Fi)"
            className="font-mono text-xs"
          />
          <textarea
            rows={3}
            value={invDraft.notes}
            onChange={(e) => setInvDraft({ ...invDraft, notes: e.target.value })}
            placeholder="Notes, pinouts, or quirks..."
            className="w-full rounded-md border border-white/15 bg-eigenia-obsidian p-2 text-xs text-white"
          />
          <Button type="submit" className="w-full" disabled={busyAction === "save-inv"}>
            {busyAction === "save-inv" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {editingInvId ? "Update Part" : "Save Part"}
          </Button>
        </form>
      </SlideOverDrawer>

      {/* SLIDE-OVER DRAWER: DEVICE PROFILE SPECS & HARD LIMITS INSPECTOR */}
      <SlideOverDrawer
        open={Boolean(inspectedProfile)}
        onClose={() => setInspectedProfile(null)}
        title={inspectedProfile?.display_name || "Device Profile"}
        subtitle={inspectedProfile?.tagline}
        badge={inspectedProfile?.category?.toUpperCase()}
        badgeVariant="sky"
        widthClassName="max-w-xl"
      >
        {inspectedProfile && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 font-mono text-xs">
              <div className="rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="text-[9px] uppercase text-eigenia-muted">Supply Rail</div>
                <div className="font-semibold text-white">{inspectedProfile.voltage_rail_v} V</div>
              </div>
              <div className="rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="text-[9px] uppercase text-eigenia-muted">Max GPIO Logic</div>
                <div className="font-semibold text-eigenia-amber">
                  {inspectedProfile.max_gpio_v} V
                </div>
              </div>
              <div className="rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="text-[9px] uppercase text-eigenia-muted">Power Budget</div>
                <div className="font-semibold text-eigenia-sky">
                  {inspectedProfile.power_budget_ma} mA
                </div>
              </div>
              <div className="rounded border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="text-[9px] uppercase text-eigenia-muted">Dimensions</div>
                <div className="font-semibold text-white">
                  {inspectedProfile.dimensions_mm.join(" × ")} mm
                </div>
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                Interfaces &amp; Transports
              </div>
              <div className="flex flex-wrap gap-1">
                {inspectedProfile.interfaces.map((i) => (
                  <Badge key={i} variant="sky" className="font-mono text-[9px]">
                    {i}
                  </Badge>
                ))}
                {inspectedProfile.transports.map((t) => (
                  <Badge key={t} variant="neutral" className="font-mono text-[9px]">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="space-y-1.5 rounded-lg border border-eigenia-fault/40 bg-eigenia-fault/10 p-3">
              <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase text-eigenia-fault">
                <AlertTriangle className="h-3.5 w-3.5" />
                Electrical &amp; Architectural Hard Limits
              </div>
              <ul className="list-disc space-y-1 pl-4 text-xs text-white">
                {inspectedProfile.hard_limits.map((lim, i) => (
                  <li key={`lim-${i}`}>{lim}</li>
                ))}
              </ul>
            </div>

            {inspectedProfile.firmware_templates.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-eigenia-sky">
                  <Code2 className="h-3.5 w-3.5" />
                  Firmware Templates ({inspectedProfile.firmware_templates.length})
                </div>
                {inspectedProfile.firmware_templates.map((tpl) => (
                  <div
                    key={tpl.id}
                    className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-white">{tpl.name}</span>
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-6 px-2 text-[9px]"
                        onClick={() =>
                          downloadTextFile(
                            `${tpl.id}.${tpl.language === "bash" ? "sh" : "py"}`,
                            tpl.code
                          )
                        }
                      >
                        <Download className="h-3 w-3" />
                        Download
                      </Button>
                    </div>
                    <pre className="max-h-36 overflow-auto rounded border border-white/10 bg-eigenia-shell p-2 font-mono text-[10px] text-emerald-300">
                      {tpl.code}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </SlideOverDrawer>
    </div>
  );
}
