import { API_URL } from "./api";
import type { SpatialSighting } from "./robotApi";
import type { TopologyEdgeSpec, TopologyNodeSpec } from "@/components/ui/TopologyFlowCanvas";

// --- Device Profiles, Inventory & Local IoT Bridges ---

export interface DeviceFirmwareTemplate {
  id: string;
  name: string;
  description: string;
  language: string;
  code: string;
}

export interface DeviceProfile {
  profile_id: string;
  display_name: string;
  category: string;
  tagline: string;
  transports: string[];
  voltage_rail_v: number;
  max_gpio_v: number;
  power_budget_ma: number;
  dimensions_mm: [number, number, number];
  color_hex: string;
  interfaces: string[];
  capabilities: string[];
  hard_limits: string[];
  firmware_templates: DeviceFirmwareTemplate[];
}

export type InventoryCategory =
  | "compute"
  | "microcontroller"
  | "camera"
  | "sensor"
  | "actuator"
  | "network"
  | "power"
  | "accessory";

export type InventoryStatus =
  | "available"
  | "deployed"
  | "needs_part"
  | "wishlist"
  | "archived";

export interface InventoryItem {
  id: string;
  name: string;
  profile_id: string | null;
  category: InventoryCategory;
  manufacturer: string;
  model: string;
  quantity: number;
  status: InventoryStatus;
  location: string;
  interfaces: string[];
  voltage_v: number | null;
  current_ma: number | null;
  capabilities: string[];
  notes: string;
  est_cost_usd: number | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryCounts {
  owned: number;
  wishlist: number;
  deployed: number;
  total: number;
}

export interface ManagedDevice {
  id: string;
  name: string;
  profile_id: string;
  space_id: string | null;
  transport: string;
  endpoint: string;
  status: string;
  config: Record<string, unknown>;
  last_seen_at: string | null;
  created_at: string;
}

export interface MicrobitProbeResponse {
  ports: string[];
  volumes: string[];
  detected: boolean;
}

export type MicrobitCommandAction =
  | "show_text"
  | "show_icon"
  | "play_tone"
  | "read_sensors"
  | "set_matrix";

export interface MicrobitCommandResponse {
  ok: boolean;
  detail: string;
  preview_code: string;
  sensor_data?: Record<string, unknown>;
}

export interface PiZeroGadgetScriptResponse {
  filename: string;
  script: string;
  instructions: string[];
}

export interface CameraIngestResponse {
  ok: boolean;
  camera_source: string;
  frames_analyzed: number;
  recorded_count: number;
  sightings: SpatialSighting[];
}

// --- Interactive Human-AI Co-Design Architect ---

export type CreativityLevel = 1 | 2 | 3 | 4 | 5;

export type ArchitectPersona =
  | "systems_architect"
  | "electronics_ee"
  | "robotics_cv"
  | "red_team";

export interface CreativityTierMeta {
  level: CreativityLevel;
  label: string;
  shortLabel: string;
  description: string;
}

export const CREATIVITY_TIERS: CreativityTierMeta[] = [
  {
    level: 1,
    label: "1 · Steady & Proven",
    shortLabel: "Steady",
    description: "Deterministic, low-risk wiring using well-tested interfaces & owned parts.",
  },
  {
    level: 2,
    label: "2 · Practical Upgrade",
    shortLabel: "Practical",
    description: "Smart incremental upgrades with minimal extra hardware & fast bring-up.",
  },
  {
    level: 3,
    label: "3 · Creative Maker",
    shortLabel: "Creative",
    description: "Cross-device sensor fusion, multi-node orchestration & clever local bridges.",
  },
  {
    level: 4,
    label: "4 · Frontier R&D",
    shortLabel: "Frontier",
    description: "Ambitious multi-agent autonomy, distributed edge vision & custom telemetry.",
  },
  {
    level: 5,
    label: "5 · Extreme / Groundbreaking",
    shortLabel: "Extreme",
    description: "Moonshot lab architecture pushing hardware boundaries with bold synthesis.",
  },
];

export const ARCHITECT_PERSONAS: {
  id: ArchitectPersona;
  label: string;
  shortLabel: string;
  focus: string;
}[] = [
  {
    id: "systems_architect",
    label: "Systems Architect",
    shortLabel: "Systems",
    focus: "End-to-end topology, latency budgets, ROS 2 / Docker integration & data flow",
  },
  {
    id: "electronics_ee",
    label: "Electronics EE",
    shortLabel: "Electronics EE",
    focus: "Voltage rails, 3.3V vs 5V logic shifting, USB mA budgets, EMI & wiring safety",
  },
  {
    id: "robotics_cv",
    label: "Robotics & CV",
    shortLabel: "Robotics & CV",
    focus: "Kinematics, LiDAR + camera sensor fusion, edge inference & closed-loop control",
  },
  {
    id: "red_team",
    label: "Red-Team Critic",
    shortLabel: "Red-Team",
    focus: "Failure modes, thermal/power bottlenecks, single points of failure & security",
  },
];

export interface CoDesignPart3D {
  id: string;
  label: string;
  profile_id: string;
  category: string;
  owned: boolean;
  locked?: boolean;
  x: number;
  y: number;
  z: number;
  dims_m: [number, number, number];
  status: "ok" | "warning" | "proposed" | "fault";
  metric?: string;
}

export interface CoDesignLink3D {
  id: string;
  source: string;
  target: string;
  label: string;
  link_type: "power_5v" | "usb" | "uart_i2c" | "wifi" | "ble" | "video";
  status?: "ok" | "warning" | "fault";
}

export interface BlueprintPartUsed {
  inventory_id?: string | null;
  name: string;
  profile_id: string;
  role: string;
  owned: boolean;
}

export interface BlueprintMissingPart {
  name: string;
  profile_id: string;
  category: string;
  reason: string;
  est_cost_usd: number;
  interfaces: string[];
}

export interface BlueprintElectricalCheck {
  topic: string;
  status: "ok" | "warning" | "fault";
  detail: string;
}

export interface BlueprintChatMessage {
  role: "user" | "assistant";
  persona?: string;
  text: string;
  timestamp: string;
}

export interface BlueprintVersion {
  version: number;
  label: string;
  creativity_level: number;
  feasibility_score: number;
  timestamp: string;
  parts_count: number;
  missing_count: number;
}

export interface DesignBlueprint {
  id: string;
  title: string;
  idea: string;
  creativity_level: number;
  persona: string;
  verdict: "buildable_now" | "needs_minor_parts" | "hardware_limit";
  feasibility_score: number;
  summary: string;
  parts_used: BlueprintPartUsed[];
  missing_parts: BlueprintMissingPart[];
  electrical_checks: BlueprintElectricalCheck[];
  architecture_steps: string[];
  build_tonight_vs_moonshot: {
    tonight: string[];
    moonshot: string[];
  };
  wiring_graph: {
    nodes: TopologyNodeSpec[];
    edges: TopologyEdgeSpec[];
  };
  assembly_3d: {
    parts: CoDesignPart3D[];
    links: CoDesignLink3D[];
  };
  locked_part_ids: string[];
  excluded_part_ids: string[];
  chat_history: BlueprintChatMessage[];
  versions: BlueprintVersion[];
  model_used: string;
  created_at: string;
  updated_at: string;
}

export interface ArchitectIdea {
  title: string;
  pitch: string;
  creativity_level: number;
  difficulty: string;
  verdict: "buildable_now" | "needs_minor_parts" | "hardware_limit" | string;
  parts_used: string[];
  missing_parts: string[];
  capabilities: string[];
  estimated_time: string;
}

// --- Resilient Fetch Wrapper (3x Retry on Transient Errors) ---

async function requestArchitectJson<T>(
  path: string,
  init?: RequestInit,
  maxRetries = 3
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(`${API_URL}${path}`, init);
      if (!res.ok) {
        const text = await res.text();
        const err = new Error(`Architect API ${path} failed (${res.status}): ${text}`);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[architectApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`Architect API ${path} failed`);
}

// --- Device Profiles & Managed Devices ---

export async function listDeviceProfiles(): Promise<{ profiles: DeviceProfile[] }> {
  const data = await requestArchitectJson<{ profiles?: DeviceProfile[] }>("/api/devices/profiles");
  return { profiles: Array.isArray(data.profiles) ? data.profiles : [] };
}

export async function listManagedDevices(): Promise<{ devices: ManagedDevice[] }> {
  const data = await requestArchitectJson<{ devices?: ManagedDevice[] } | ManagedDevice[]>(
    "/api/devices"
  );
  if (Array.isArray(data)) {
    return { devices: data };
  }
  return { devices: Array.isArray(data.devices) ? data.devices : [] };
}

export async function createManagedDevice(payload: {
  name: string;
  profile_id: string;
  space_id?: string | null;
  transport: string;
  endpoint: string;
  status?: string;
  config?: Record<string, unknown>;
}): Promise<{ device: ManagedDevice }> {
  const data = await requestArchitectJson<{ device?: ManagedDevice } | ManagedDevice>(
    "/api/devices",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("device" in data && data.device) {
    return { device: data.device };
  }
  return { device: data as ManagedDevice };
}

export async function updateManagedDevice(
  deviceId: string,
  payload: Partial<Pick<ManagedDevice, "name" | "space_id" | "transport" | "endpoint" | "status" | "config">>
): Promise<{ device: ManagedDevice }> {
  const data = await requestArchitectJson<{ device?: ManagedDevice } | ManagedDevice>(
    `/api/devices/${encodeURIComponent(deviceId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("device" in data && data.device) {
    return { device: data.device };
  }
  return { device: data as ManagedDevice };
}

export async function deleteManagedDevice(deviceId: string): Promise<{ deleted: boolean }> {
  return requestArchitectJson<{ deleted: boolean }>(
    `/api/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
    1
  );
}

// --- BBC micro:bit v2.21 Local Bridge ---

export async function probeMicrobitUsb(): Promise<MicrobitProbeResponse> {
  const data = await requestArchitectJson<MicrobitProbeResponse>(
    "/api/devices/microbit/probe",
    undefined,
    2
  );
  return {
    ports: Array.isArray(data.ports) ? data.ports : [],
    volumes: Array.isArray(data.volumes) ? data.volumes : [],
    detected: Boolean(data.detected),
  };
}

export async function sendMicrobitCommand(payload: {
  port?: string | null;
  action: MicrobitCommandAction;
  payload?: unknown;
}): Promise<MicrobitCommandResponse> {
  return requestArchitectJson<MicrobitCommandResponse>(
    "/api/devices/microbit/command",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

// --- Pi Zero 2 W Local USB Gadget Script & Local Camera Media Ingest ---

export async function fetchPiZeroGadgetScript(params?: {
  docker_host?: string;
  device_id?: string;
}): Promise<PiZeroGadgetScriptResponse> {
  const sp = new URLSearchParams();
  if (params?.docker_host) sp.set("docker_host", params.docker_host);
  if (params?.device_id) sp.set("device_id", params.device_id);
  const qs = sp.toString();
  const data = await requestArchitectJson<PiZeroGadgetScriptResponse>(
    `/api/devices/pizero/gadget-script${qs ? `?${qs}` : ""}`,
    undefined,
    2
  );
  return {
    filename: data.filename || "setup_pizero_blink_harvester.sh",
    script: data.script || "",
    instructions: Array.isArray(data.instructions) ? data.instructions : [],
  };
}

export async function ingestLocalCameraMedia(
  input:
    | FormData
    | {
        image_base64?: string;
        stream_url?: string;
        camera_name: string;
        space_id?: string | null;
        robot_id?: string | null;
      }
): Promise<CameraIngestResponse> {
  const isFormData = typeof FormData !== "undefined" && input instanceof FormData;
  const data = await requestArchitectJson<CameraIngestResponse>(
    "/api/devices/cameras/ingest-media",
    isFormData
      ? { method: "POST", body: input }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        },
    1
  );
  return {
    ...data,
    sightings: Array.isArray(data.sightings) ? data.sightings : [],
  };
}

// --- Lab Hardware Inventory & Wishlist ---

export async function listInventory(params?: {
  status?: string;
  category?: string;
  query?: string;
}): Promise<{ items: InventoryItem[]; counts: InventoryCounts }> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.category) sp.set("category", params.category);
  if (params?.query?.trim()) sp.set("query", params.query.trim());
  const qs = sp.toString();
  const data = await requestArchitectJson<{
    items?: InventoryItem[];
    counts?: InventoryCounts;
  }>(`/api/inventory${qs ? `?${qs}` : ""}`, undefined, 2);
  const items = Array.isArray(data.items) ? data.items : [];
  return {
    items,
    counts: data.counts ?? {
      owned: items.filter((i) => i.status === "available" || i.status === "deployed").length,
      wishlist: items.filter((i) => i.status === "wishlist" || i.status === "needs_part").length,
      deployed: items.filter((i) => i.status === "deployed").length,
      total: items.length,
    },
  };
}

export async function createInventoryItem(payload: {
  name: string;
  profile_id?: string | null;
  category: InventoryCategory;
  manufacturer?: string;
  model?: string;
  quantity?: number;
  status?: InventoryStatus;
  location?: string;
  interfaces?: string[];
  voltage_v?: number | null;
  current_ma?: number | null;
  capabilities?: string[];
  notes?: string;
  est_cost_usd?: number | null;
}): Promise<{ item: InventoryItem }> {
  const data = await requestArchitectJson<{ item?: InventoryItem } | InventoryItem>(
    "/api/inventory",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("item" in data && data.item) {
    return { item: data.item };
  }
  return { item: data as InventoryItem };
}

export async function updateInventoryItem(
  itemId: string,
  payload: Partial<Omit<InventoryItem, "id" | "created_at" | "updated_at">>
): Promise<{ item: InventoryItem }> {
  const data = await requestArchitectJson<{ item?: InventoryItem } | InventoryItem>(
    `/api/inventory/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("item" in data && data.item) {
    return { item: data.item };
  }
  return { item: data as InventoryItem };
}

export async function deleteInventoryItem(itemId: string): Promise<{ deleted: boolean }> {
  return requestArchitectJson<{ deleted: boolean }>(
    `/api/inventory/${encodeURIComponent(itemId)}`,
    { method: "DELETE" },
    1
  );
}

export async function seedLabInventory(): Promise<{ seeded: number; items: InventoryItem[] }> {
  const data = await requestArchitectJson<{ seeded?: number; items?: InventoryItem[] }>(
    "/api/inventory/seed-lab",
    { method: "POST" },
    1
  );
  return {
    seeded: Number(data.seeded ?? 0),
    items: Array.isArray(data.items) ? data.items : [],
  };
}

export async function syncFleetHardwareToInventory(probeLive = true): Promise<{
  ok: boolean;
  synced_hosts: number;
  synced_peripherals: number;
  total_inventory_items: number;
  details: Array<{ name: string; ip: string; probe_status: string; peripherals_found: string[] }>;
}> {
  return requestArchitectJson(
    `/api/inventory/sync-fleet?probe_live=${probeLive ? "true" : "false"}`,
    { method: "POST" },
    1
  );
}

// --- Human-AI Co-Design Architect ---

export async function evaluateDesignIdea(payload: {
  idea: string;
  creativity_level?: CreativityLevel;
  persona?: ArchitectPersona;
  locked_part_ids?: string[];
  excluded_part_ids?: string[];
  canvas_part_names?: string[];
  model?: string;
}): Promise<{ ok: boolean; blueprint: DesignBlueprint }> {
  return requestArchitectJson<{ ok: boolean; blueprint: DesignBlueprint }>(
    "/api/architect/evaluate",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        creativity_level: 3,
        persona: "systems_architect",
        locked_part_ids: [],
        excluded_part_ids: [],
        canvas_part_names: [],
        ...payload,
      }),
    },
    1
  );
}

export async function ideateLabProjects(payload: {
  creativity_level?: CreativityLevel;
  focus_area?: string;
  count?: number;
  locked_part_ids?: string[];
  excluded_part_ids?: string[];
  model?: string;
}): Promise<{ ok: boolean; ideas: ArchitectIdea[]; model_used: string }> {
  const data = await requestArchitectJson<{
    ok: boolean;
    ideas?: ArchitectIdea[];
    model_used?: string;
  }>(
    "/api/architect/ideate",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        creativity_level: 3,
        focus_area: "all",
        count: 4,
        locked_part_ids: [],
        excluded_part_ids: [],
        ...payload,
      }),
    },
    1
  );
  return {
    ok: Boolean(data.ok),
    ideas: Array.isArray(data.ideas) ? data.ideas : [],
    model_used: data.model_used || "deterministic-synthesis",
  };
}

export async function refineDesignBlueprint(
  blueprintId: string,
  payload: {
    message: string;
    selected_node_id?: string | null;
    creativity_level?: CreativityLevel;
    persona?: ArchitectPersona;
    locked_part_ids?: string[];
    excluded_part_ids?: string[];
    accept_missing_part?: string | null;
    model?: string;
  }
): Promise<{ ok: boolean; blueprint: DesignBlueprint }> {
  return requestArchitectJson<{ ok: boolean; blueprint: DesignBlueprint }>(
    `/api/architect/blueprints/${encodeURIComponent(blueprintId)}/refine`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function listDesignBlueprints(): Promise<{ blueprints: DesignBlueprint[] }> {
  const data = await requestArchitectJson<{ blueprints?: DesignBlueprint[] }>(
    "/api/architect/blueprints",
    undefined,
    2
  );
  return { blueprints: Array.isArray(data.blueprints) ? data.blueprints : [] };
}

export async function deleteDesignBlueprint(blueprintId: string): Promise<{ deleted: boolean }> {
  return requestArchitectJson<{ deleted: boolean }>(
    `/api/architect/blueprints/${encodeURIComponent(blueprintId)}`,
    { method: "DELETE" },
    1
  );
}
