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
