import { API_URL } from "./api";

export interface SavedSlamMap {
  id: string;
  name: string;
  url: string;
  mapped_area_m2: number;
  occupied_cells: number;
  created_at: number;
}

export interface SlamStatus {
  ok?: boolean;
  running: boolean;
  robot_id: string | null;
  robot_ip: string | null;
  map_source: "ros_map" | "scan_accumulator" | "warming_up" | "idle" | string;
  has_map_data: boolean;
  map_seq: number;
  width: number;
  height: number;
  resolution_m: number;
  origin_xy: [number, number];
  occupied_cells: number;
  free_cells: number;
  mapped_area_m2: number;
  scan_count: number;
  scan_hz: number;
  robot_xy: [number, number];
  trail_count: number;
  uptime_s: number;
  last_error: string | null;
  saved_maps: SavedSlamMap[];
  launch_log?: string;
}

export interface SlamExportResult {
  ok: boolean;
  glb_file_id: string;
  glb_url: string;
  width_m: number;
  length_m: number;
  wall_segment_count: number;
  triangle_count: number;
  room_studio_project_id: string | null;
}

async function slamReq<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      if (err?.detail) msg = String(err.detail);
    } catch {
      // keep status
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export async function getSlamStatus(): Promise<SlamStatus> {
  return slamReq<SlamStatus>("/api/slam/status");
}

export async function startSlam(robotId?: string | null): Promise<SlamStatus> {
  return slamReq<SlamStatus>("/api/slam/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ robot_id: robotId ?? null }),
  });
}

export async function stopSlam(robotId?: string | null): Promise<SlamStatus> {
  return slamReq<SlamStatus>("/api/slam/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ robot_id: robotId ?? null }),
  });
}

export function getSlamMapImageUrl(nonce: number): string {
  return `${API_URL}/api/slam/map-image?t=${nonce}`;
}

export async function saveSlamMap(name: string): Promise<{ ok: boolean; map: SavedSlamMap }> {
  return slamReq("/api/slam/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function exportSlamToDigitalTwin(payload: {
  name: string;
  wall_height_m: number;
}): Promise<SlamExportResult> {
  return slamReq<SlamExportResult>("/api/slam/export-to-twin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
