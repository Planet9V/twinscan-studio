import { API_URL } from "./api";

export type OverwatchMode = "yolo" | "face" | "apriltag" | "triangulate";
export type OverwatchCameraId = "usb_4k" | "macbook_cam" | string;

export interface OverwatchCalibration {
  x_m: number;
  y_m: number;
  z_m: number;
  yaw_deg: number;
  pitch_deg: number;
  hfov_deg: number;
  vfov_deg: number;
  mode: OverwatchMode;
}

export interface OverwatchDetection {
  id?: string;
  label: string;
  kind?: string;
  confidence: number;
  bbox_norm?: [number, number, number, number];
  bbox?: [number, number, number, number];
  world_xy?: [number, number] | null;
  x?: number | null;
  y?: number | null;
}

export interface TriangulatedTarget {
  label: string;
  kind?: string;
  x: number;
  y: number;
  z?: number;
  error_m?: number;
  confidence: number;
  source?: string;
}

export interface OverwatchCameraSlot {
  camera_id: string;
  camera_name: string;
  online: boolean;
  width: number;
  height: number;
  fps: number;
  age_sec: number | null;
  detections_count: number;
}

export interface OverwatchStatus {
  online: boolean;
  camera_id?: string;
  camera_name: string;
  width: number;
  height: number;
  fps: number;
  age_sec: number | null;
  mode: OverwatchMode;
  calibration: OverwatchCalibration;
  detections: OverwatchDetection[];
  triangulated_targets: TriangulatedTarget[];
  puppy_visual_pose?: {
    x: number;
    y: number;
    z?: number;
    confidence?: number;
    seen?: boolean;
  } | null;
  cameras: Record<string, OverwatchCameraSlot>;
}

const DEFAULT_CALIBRATION: OverwatchCalibration = {
  x_m: 0.0,
  y_m: -2.2,
  z_m: 1.4,
  yaw_deg: 0.0,
  pitch_deg: -18.0,
  hfov_deg: 78.0,
  vfov_deg: 48.0,
  mode: "triangulate",
};

function normalizeStatus(raw: Partial<OverwatchStatus> | null | undefined): OverwatchStatus {
  const calRaw = (raw?.calibration ?? {}) as Partial<OverwatchCalibration>;
  const mode = (raw?.mode ?? calRaw.mode ?? "triangulate") as OverwatchMode;
  const rawCameras =
    raw?.cameras && typeof raw.cameras === "object"
      ? (raw.cameras as Record<string, OverwatchCameraSlot>)
      : {};
  return {
    online: Boolean(raw?.online),
    camera_id: raw?.camera_id ?? "usb_4k",
    camera_name: String(raw?.camera_name || "4k Webcam"),
    width: Number(raw?.width ?? 0),
    height: Number(raw?.height ?? 0),
    fps: Number(raw?.fps ?? 0),
    age_sec:
      raw?.age_sec != null && Number.isFinite(Number(raw.age_sec)) ? Number(raw.age_sec) : null,
    mode,
    calibration: {
      x_m: Number(calRaw.x_m ?? DEFAULT_CALIBRATION.x_m),
      y_m: Number(calRaw.y_m ?? DEFAULT_CALIBRATION.y_m),
      z_m: Number(calRaw.z_m ?? DEFAULT_CALIBRATION.z_m),
      yaw_deg: Number(calRaw.yaw_deg ?? DEFAULT_CALIBRATION.yaw_deg),
      pitch_deg: Number(calRaw.pitch_deg ?? DEFAULT_CALIBRATION.pitch_deg),
      hfov_deg: Number(calRaw.hfov_deg ?? DEFAULT_CALIBRATION.hfov_deg),
      vfov_deg: Number(calRaw.vfov_deg ?? DEFAULT_CALIBRATION.vfov_deg),
      mode,
    },
    detections: Array.isArray(raw?.detections) ? raw!.detections : [],
    triangulated_targets: Array.isArray(raw?.triangulated_targets) ? raw!.triangulated_targets : [],
    puppy_visual_pose: raw?.puppy_visual_pose ?? null,
    cameras: rawCameras,
  };
}

async function requestOverwatchJson<T>(
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
        const err = new Error(`Overwatch API ${path} failed (${res.status}): ${text}`);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[overwatchApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`Overwatch API ${path} failed`);
}

export async function getOverwatchStatus(cameraId?: OverwatchCameraId): Promise<OverwatchStatus> {
  const qs = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : "";
  const data = await requestOverwatchJson<Partial<OverwatchStatus>>(
    `/api/overwatch/status${qs}`,
    undefined,
    2
  );
  return normalizeStatus(data);
}

export async function updateOverwatchCalibration(
  payload: Partial<OverwatchCalibration>,
  cameraId?: OverwatchCameraId
): Promise<OverwatchStatus> {
  const qs = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : "";
  const data = await requestOverwatchJson<Partial<OverwatchStatus>>(
    `/api/overwatch/calibration${qs}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  return normalizeStatus(data);
}

export function getOverwatchStreamUrl(
  cameraId: OverwatchCameraId = "usb_4k",
  nonce?: number
): string {
  const sp = new URLSearchParams();
  if (cameraId) sp.set("camera_id", cameraId);
  if (nonce != null) sp.set("_ow", String(nonce));
  return `${API_URL}/api/overwatch/stream?${sp.toString()}`;
}

export function getOverwatchSnapshotUrl(
  cameraId: OverwatchCameraId = "usb_4k",
  annotated = true
): string {
  const sp = new URLSearchParams();
  if (cameraId) sp.set("camera_id", cameraId);
  sp.set("annotated", annotated ? "true" : "false");
  return `${API_URL}/api/overwatch/snapshot?${sp.toString()}`;
}

export interface FrustumEntry {
  camera_id: string;
  camera_name: string;
  online: boolean;
  origin_xy: [number, number];
  yaw_deg: number;
  color: string;
  area_m2: number;
  polygons: number[][][];
}

export interface CoverageZoneTier {
  area_m2: number;
  polygons: number[][][];
}

export interface PlacementAdvisor {
  rating: "OPTIMAL" | "GOOD" | "FAIR" | "POOR" | "SINGLE_VIEW";
  best_angle_deg: number;
  baseline_m: number;
  estimated_gdop: number;
  pair: string[];
  recommendation: string;
}

export interface GlobalTrack {
  track_id: string;
  label: string;
  kind: string;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  confidence: number;
  error_m: number;
  gdop: number;
  gdop_rating: string;
  ellipse_2sigma: {
    semi_major_m: number;
    semi_minor_m: number;
    angle_deg: number;
  };
  cameras: string[];
  sightlines: Array<{
    camera_id: string;
    from_xy: [number, number];
    to_xy: [number, number];
  }>;
  hits: number;
}

export interface OverwatchGeometry {
  room_bounds: [number, number, number, number];
  frustums: FrustumEntry[];
  zones: {
    dead_0: CoverageZoneTier;
    mono_1: CoverageZoneTier;
    stereo_2: CoverageZoneTier;
    fusion_3plus: CoverageZoneTier;
  };
  metrics: {
    arena_area_m2: number;
    dead_area_m2: number;
    mono_area_m2: number;
    stereo_area_m2: number;
    fusion_area_m2: number;
    covered_pct: number;
    overlap_pct: number;
  };
  placement_advisor: PlacementAdvisor;
  tracks: GlobalTrack[];
}

export interface TaskPointResult {
  ok: boolean;
  camera_id: string;
  target_xy: [number, number];
  waypoint_xy: [number, number];
  projection_method: string;
  distance_from_robot_m: number;
  walk_distance_m: number;
  target_heading_deg: number;
  relative_turn_deg: number;
  dispatched: boolean;
  dispatch_note: string;
}

export interface UpscaleRoiResult {
  ok: boolean;
  method: string;
  model: string;
  scale: number;
  raw_size: [number, number];
  enhanced_size: [number, number];
  raw_crop_b64: string;
  enhanced_b64: string;
  latency_ms: number;
  ai_generated_warning: boolean;
  warning_text?: string;
}

export async function getOverwatchGeometry(maxRangeM = 6.0): Promise<OverwatchGeometry> {
  return requestOverwatchJson<OverwatchGeometry>(
    `/api/overwatch/geometry?max_range_m=${encodeURIComponent(String(maxRangeM))}`,
    undefined,
    2
  );
}

export async function calibrateOverwatchAprilTag(payload: {
  camera_id: string;
  tag_size_m: number;
  tag_world_x: number;
  tag_world_y: number;
  tag_world_z: number;
  tag_world_yaw_deg?: number;
  target_tag_id?: number | null;
}): Promise<{ ok: boolean; results: Record<string, { ok: boolean; error?: string; reprojection_error_px?: number; tag_id?: number }>; geometry: OverwatchGeometry }> {
  return requestOverwatchJson(
    "/api/overwatch/calibrate/apriltag",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function calibrateOverwatchHomography(payload: {
  camera_id: string;
  pixel_points_norm: Array<[number, number]>;
  world_points_xy: Array<[number, number]>;
}): Promise<{ ok: boolean; camera_id: string; reprojection_error_px: number; calibration: OverwatchCalibration; geometry: OverwatchGeometry }> {
  return requestOverwatchJson(
    "/api/overwatch/calibrate/homography",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function projectOrDispatchTaskPoint(payload: {
  camera_id: string;
  u_norm?: number;
  v_norm?: number;
  target_xy?: [number, number];
  standoff_m?: number;
  dispatch: boolean;
}): Promise<TaskPointResult> {
  return requestOverwatchJson<TaskPointResult>(
    "/api/overwatch/task-point",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function upscaleOverwatchRoi(payload: {
  camera_id: string;
  bbox_norm: [number, number, number, number];
  mode: "local" | "fal";
  scale?: number;
  model?: string;
}): Promise<UpscaleRoiResult> {
  return requestOverwatchJson<UpscaleRoiResult>(
    "/api/overwatch/upscale-roi",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function ingestOverwatchFrameBlob(
  cameraId: string,
  cameraName: string,
  jpegBlob: Blob,
  fps: number
): Promise<void> {
  const qs = new URLSearchParams({
    camera_id: cameraId,
    camera_name: cameraName,
    fps: fps.toFixed(1),
  });
  const res = await fetch(`${API_URL}/api/overwatch/ingest?${qs.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "image/jpeg" },
    body: jpegBlob,
  });
  if (!res.ok) {
    throw new Error(`Ingest HTTP ${res.status}`);
  }
}

export interface MulticamFuseResult {
  ok: boolean;
  camera_count: number;
  cameras_fused: Array<{
    camera_id: string;
    camera_name: string;
    resolution_px: string;
    lidar_calibrated: boolean;
    vertex_count: number;
    triangle_count: number;
  }>;
  lidar_points_used: number;
  total_vertices: number;
  total_triangles: number;
  glb_bytes_len: number;
  glb_file_id: string | null;
  download_url: string | null;
}

export async function reconstructMulticamDigitalTwin(payload: {
  space_id?: string | null;
  robot_id?: string | null;
  include_puppypi_fpv?: boolean;
  resolution?: "low" | "medium" | "high";
}): Promise<MulticamFuseResult> {
  return requestOverwatchJson<MulticamFuseResult>(
    "/api/overwatch/reconstruct-multicam",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        space_id: payload.space_id ?? null,
        robot_id: payload.robot_id ?? null,
        include_puppypi_fpv: payload.include_puppypi_fpv ?? true,
        resolution: payload.resolution ?? "medium",
      }),
    },
    1
  );
}

export async function suggestBlindSpotMappingRoute(
  maxWaypoints = 4,
  safeRadiusM = 2.0
): Promise<{
  ok: boolean;
  waypoints: Array<{ x: number; y: number; pause_sec: number; reason: string }>;
  summary: string;
}> {
  return requestOverwatchJson(
    "/api/overwatch/suggest-mapping-route",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_waypoints: maxWaypoints, safe_radius_m: safeRadiusM }),
    },
    1
  );
}
