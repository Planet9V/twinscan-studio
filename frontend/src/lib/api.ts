import type {
  AdminSettingItem,
  EnrichmentDossier,
  EquipmentAsset,
  EquipmentVisionResult,
  FocusQueueItem,
  GraphPayload,
  LidarFrame,
  OpenRouterCatalogResponse,
  OpenRouterKeyTestResult,
  OpenRouterModelInfo,
  SceneEnhanceOptions,
  ScenePanelRecord,
  SceneResolution,
  SpaceRecord,
  SpatialDarkZone,
  StorageStats,
  StoredFileRecord,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchHealth(): Promise<Record<string, unknown>> {
  return requestJson("/health");
}

export async function fetchSpaces(): Promise<{ active_space_id: string; spaces: SpaceRecord[] }> {
  return requestJson("/api/spaces");
}

export async function createSpace(payload: {
  name: string;
  facility?: string;
  description?: string;
}): Promise<SpaceRecord> {
  return requestJson("/api/spaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      facility: payload.facility?.trim() || "Eigenia Lab",
      description: payload.description ?? "",
    }),
  });
}

export async function updateSpace(
  spaceId: string,
  payload: {
    name?: string;
    facility?: string;
    description?: string;
  }
): Promise<SpaceRecord> {
  return requestJson(`/api/spaces/${encodeURIComponent(spaceId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function cloneSpace(
  spaceId: string,
  payload: {
    name: string;
    facility?: string;
    description?: string;
  }
): Promise<{ space: SpaceRecord; cloned_panels: number; cloned_equipment: number }> {
  return requestJson(`/api/spaces/${encodeURIComponent(spaceId)}/clone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteSpace(
  spaceId: string
): Promise<{ deleted: boolean; active_space_id: string }> {
  return requestJson(`/api/spaces/${encodeURIComponent(spaceId)}`, { method: "DELETE" });
}

export async function fetchSpaceDetail(
  spaceId: string
): Promise<{ space: SpaceRecord; equipment: EquipmentAsset[]; anomalies: unknown[] }> {
  return requestJson(`/api/spaces/${spaceId}`);
}

export async function fetchLidarSnapshot(): Promise<LidarFrame> {
  return requestJson("/api/lidar/snapshot");
}

export async function updateLidarFilters(filters: {
  min_range_m?: number;
  max_range_m?: number;
  min_intensity?: number;
  enable_outlier_filter?: boolean;
  rotation_offset_deg?: number;
  [key: string]: unknown;
}): Promise<unknown> {
  return requestJson("/api/lidar/filters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });
}

export interface LidarSettings {
  source_mode: "simulator" | "hardware" | "robot_ros2";
  robot_id?: string | null;
  poll_interval_ms: number;
  analytics_every_n_scans: number;
  motion_tracking_enabled: boolean;
  simulate_moving_targets: boolean;
  actual_hz?: number;
  robot_scan_connected?: boolean;
}

export async function fetchLidarSettings(): Promise<LidarSettings> {
  return requestJson<LidarSettings>("/api/lidar/settings");
}

export async function updateLidarSettings(payload: {
  source_mode?: "simulator" | "hardware" | "robot_ros2";
  robot_id?: string | null;
  poll_interval_ms?: number;
  analytics_every_n_scans?: number;
  motion_tracking_enabled?: boolean;
  simulate_moving_targets?: boolean;
}): Promise<LidarSettings> {
  return requestJson<LidarSettings>("/api/lidar/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateLidarMode(payload: {
  source_mode?: "simulator" | "hardware" | "robot_ros2";
  inject_rogue_object?: boolean;
}): Promise<unknown> {
  return requestJson("/api/lidar/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function captureBaseline(): Promise<unknown> {
  return requestJson("/api/lidar/baseline", { method: "POST" });
}

export async function extractAndSaveWalls(spaceId: string): Promise<unknown> {
  return requestJson(`/api/lidar/extract-walls?space_id=${encodeURIComponent(spaceId)}`, {
    method: "POST",
  });
}

export async function fetchVisionModels(): Promise<{
  openrouter_configured: boolean;
  default_model: string;
  secondary_model: string;
  research_model: string;
  embedding_model?: string;
  models: OpenRouterModelInfo[];
}> {
  return requestJson("/api/vision/models");
}

export async function analyzeEquipmentImage(params: {
  file: File;
  model: string;
  consensus: boolean;
  contextHint: string;
  cameraYawDeg: number;
}): Promise<{
  extraction: EquipmentVisionResult;
  image_file_id: string;
  enhanced_file_id?: string | null;
  image_url: string;
  enhanced_url?: string | null;
  suggested_pose: {
    x: number;
    y: number;
    distance_m: number;
    bearing_deg: number;
    supporting_points: number;
    confidence: number;
  };
}> {
  const form = new FormData();
  form.append("file", params.file);
  form.append("model", params.model);
  form.append("consensus", String(params.consensus));
  form.append("context_hint", params.contextHint);
  form.append("camera_yaw_deg", String(params.cameraYawDeg));
  return requestJson("/api/vision/analyze", { method: "POST", body: form });
}

export async function pinEquipmentAsset(
  spaceId: string,
  payload: Record<string, unknown>
): Promise<{ equipment: EquipmentAsset; neo4j_synced: boolean }> {
  return requestJson(`/api/spaces/${spaceId}/equipment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteEquipmentAsset(equipmentId: string): Promise<unknown> {
  return requestJson(`/api/equipment/${equipmentId}`, { method: "DELETE" });
}

export async function searchEquipmentSemantic(
  query: string,
  spaceId?: string
): Promise<{ query: string; count: number; results: EquipmentAsset[] }> {
  return requestJson("/api/equipment/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, space_id: spaceId, limit: 10 }),
  });
}

export async function fetchSpaceGraph(spaceId: string): Promise<GraphPayload> {
  return requestJson(`/api/spaces/${spaceId}/graph`);
}

export async function fetchFocusQueue(spaceId: string): Promise<{
  space_id: string;
  dark_zone_count: number;
  queue_count: number;
  dark_zones: SpatialDarkZone[];
  focus_queue: FocusQueueItem[];
}> {
  return requestJson(`/api/spaces/${spaceId}/focus-queue`);
}

export async function enrichEquipmentAsset(
  equipmentId: string,
  includeNvd = true
): Promise<{ equipment: EquipmentAsset; enrichment: EnrichmentDossier; latency_ms: number }> {
  return requestJson(`/api/equipment/${equipmentId}/enrich`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_nvd: includeNvd }),
  });
}

export async function archiveTwinSnapshot(
  spaceId: string
): Promise<{ archived_files: StoredFileRecord[]; storage: StorageStats }> {
  return requestJson(`/api/spaces/${spaceId}/archive-snapshot`, { method: "POST" });
}

// --- Admin Settings & PostgreSQL File Storage ---

function adminHeaders(adminToken?: string): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken?.trim()) h["X-Admin-Token"] = adminToken.trim();
  return h;
}

export async function fetchAdminSettings(): Promise<{
  settings: AdminSettingItem[];
  admin_token_required: boolean;
  storage: StorageStats;
  embedding_drift: { active_model: string; drifted_asset_count: number; total_assets: number };
}> {
  return requestJson("/api/admin/settings");
}

export async function saveAdminSettings(
  settings: Record<string, string>,
  adminToken?: string
): Promise<{ updated_count: number; openrouter_configured: boolean; settings: AdminSettingItem[] }> {
  return requestJson("/api/admin/settings", {
    method: "PUT",
    headers: adminHeaders(adminToken),
    body: JSON.stringify({ settings }),
  });
}

export async function fetchAdminAudit(): Promise<{
  entries: { id: string; key: string; old_preview: string; new_preview: string; source_ip: string; changed_at: string }[];
}> {
  return requestJson("/api/admin/audit");
}

export async function fetchVisionUsage(): Promise<{
  entries: { id: string; operation: string; model: string; latency_ms: number; confidence: number; created_at: string }[];
}> {
  return requestJson("/api/admin/usage");
}

export async function testAllConnections(): Promise<{
  postgres: Record<string, unknown>;
  neo4j: Record<string, unknown>;
  openrouter: Record<string, unknown>;
}> {
  return requestJson("/api/admin/test-connections", { method: "POST" });
}

export async function testOpenRouterKey(payload?: {
  api_key?: string;
  base_url?: string;
}): Promise<OpenRouterKeyTestResult> {
  return requestJson("/api/admin/openrouter/test-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
}

export async function refreshOpenRouterModels(
  forceRefresh = false
): Promise<OpenRouterCatalogResponse> {
  return requestJson(`/api/admin/openrouter-models${forceRefresh ? "?refresh=true" : ""}`);
}

export async function reconcileNeo4j(adminToken?: string): Promise<Record<string, unknown>> {
  return requestJson("/api/admin/reconcile-neo4j", { method: "POST", headers: adminHeaders(adminToken) });
}

export async function reindexEmbeddings(adminToken?: string): Promise<{ reindexed_count: number; embedding_model: string }> {
  return requestJson("/api/admin/reindex-embeddings", { method: "POST", headers: adminHeaders(adminToken) });
}

export async function scrubStorage(adminToken?: string): Promise<{
  verified_blobs: number;
  corrupted_blobs: number;
  pruned_orphans: number;
  stats: StorageStats;
}> {
  return requestJson("/api/admin/storage-scrub", { method: "POST", headers: adminHeaders(adminToken) });
}

export async function listStoredFiles(spaceId?: string): Promise<{ files: StoredFileRecord[]; stats: StorageStats }> {
  const q = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : "";
  return requestJson(`/api/files${q}`);
}

export async function uploadStoredFile(params: {
  file: File;
  category: string;
  spaceId?: string;
  equipmentId?: string;
}): Promise<{ file: StoredFileRecord; stats: StorageStats }> {
  const form = new FormData();
  form.append("file", params.file);
  form.append("category", params.category);
  if (params.spaceId) form.append("space_id", params.spaceId);
  if (params.equipmentId) form.append("equipment_id", params.equipmentId);
  return requestJson("/api/files", { method: "POST", body: form });
}

export async function deleteStoredFile(fileId: string, adminToken?: string): Promise<unknown> {
  const headers: Record<string, string> = {};
  if (adminToken?.trim()) headers["X-Admin-Token"] = adminToken.trim();
  return requestJson(`/api/files/${fileId}`, { method: "DELETE", headers });
}

export function getExportUrl(spaceId: string, fmt: string): string {
  return `${API_URL}/api/spaces/${spaceId}/export/${fmt}`;
}

export function getFileUrl(fileUrlOrPath: string): string {
  return fileUrlOrPath.startsWith("http") ? fileUrlOrPath : `${API_URL}${fileUrlOrPath}`;
}

export function resolveBackendAssetUrl(pathOrUrl: string | null | undefined): string | null {
  if (!pathOrUrl) return null;
  if (
    pathOrUrl.startsWith("http://") ||
    pathOrUrl.startsWith("https://") ||
    pathOrUrl.startsWith("data:") ||
    pathOrUrl.startsWith("blob:")
  ) {
    return pathOrUrl;
  }
  return pathOrUrl.startsWith("/") ? `${API_URL}${pathOrUrl}` : `${API_URL}/${pathOrUrl}`;
}

// --- 3D Real-Room Camera + LiDAR + Depth Fusion ---

export async function listScenePanels(
  spaceId: string
): Promise<{ space_id: string; panels: ScenePanelRecord[] }> {
  const data = await requestJson<{ space_id?: string; panels?: ScenePanelRecord[] }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/panels`
  );
  return {
    space_id: data.space_id ?? spaceId,
    panels: Array.isArray(data.panels) ? data.panels : [],
  };
}

export async function captureWallPanel(
  spaceId: string,
  payload: SceneEnhanceOptions & {
    robot_id?: string | null;
    label?: string;
    yaw_deg?: number;
    pitch_deg?: number;
    roll_deg?: number;
    x?: number;
    y?: number;
    z?: number;
    fallback_distance_m?: number;
    resolution?: SceneResolution;
    depth_relief_scale?: number;
    hfov_deg?: number;
    vfov_deg?: number;
  } = {}
): Promise<{ ok: boolean; panel: ScenePanelRecord; note?: string }> {
  return requestJson(`/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/capture-wall`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function capture360Panels(
  spaceId: string,
  payload: SceneEnhanceOptions & {
    robot_id: string;
    steps?: number;
    fallback_distance_m?: number;
    resolution?: SceneResolution;
    depth_relief_scale?: number;
    turn_duration_s?: number;
    settle_s?: number;
    yaw_rate_rad_s?: number;
  }
): Promise<{
  ok: boolean;
  panels: ScenePanelRecord[];
  aborted: boolean;
  completed_steps: number;
  total_steps: number;
  note?: string;
}> {
  const data = await requestJson<{
    ok: boolean;
    panels?: ScenePanelRecord[];
    aborted: boolean;
    completed_steps: number;
    total_steps: number;
    note?: string;
  }>(`/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/capture-360`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return {
    ...data,
    panels: Array.isArray(data.panels) ? data.panels : [],
  };
}

export async function enhanceScenePanel(
  spaceId: string,
  panelId: string,
  options: SceneEnhanceOptions & {
    resolution?: SceneResolution;
    depth_relief_scale?: number;
    fallback_distance_m?: number;
  } = {}
): Promise<{ ok: boolean; panel: ScenePanelRecord; note?: string }> {
  return requestJson(
    `/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/panels/${encodeURIComponent(panelId)}/enhance`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }
  );
}

export async function deleteScenePanel(
  spaceId: string,
  panelId: string
): Promise<{ deleted: boolean; panel_id: string }> {
  return requestJson(
    `/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/panels/${encodeURIComponent(panelId)}`,
    { method: "DELETE" }
  );
}

export async function clearScenePanels(
  spaceId: string
): Promise<{ deleted_count: number }> {
  return requestJson(`/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/panels`, {
    method: "DELETE",
  });
}

export function getCombinedRoomGlbUrl(spaceId: string): string {
  return `${API_URL}/api/spaces/${encodeURIComponent(spaceId)}/reconstruct/export-room.glb`;
}
