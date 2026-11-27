import { API_URL } from "./api";

export type RoomSurface =
  | "north_wall"
  | "east_wall"
  | "south_wall"
  | "west_wall"
  | "floor"
  | "ceiling"
  | "object_closeup"
  | "overview";

export type SupportType = "WALL_MOUNTED" | "ON_FLOOR" | "ON_SURFACE" | "CEILING";

export type Object3DEngine =
  | "local_depth3d"
  | "fal-ai/trellis-2"
  | "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"
  | "fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d"
  | "tripo3d/tripo/v2.5/image-to-3d";

export interface CameraPose3D {
  x: number;
  y: number;
  z: number;
  yaw_deg: number;
  pitch_deg: number;
}

export interface RoomStudioPhoto {
  id: string;
  file_id: string;
  url: string;
  name: string;
  surface: RoomSurface;
  tags: string[];
  camera_pose: CameraPose3D;
  width: number;
  height: number;
  analyzed: boolean;
  detected_count: number;
  uploaded_at: number;
}

export interface RoomObjectPose {
  x: number;
  y: number;
  z: number;
  rx: number;
  ry: number;
  rz: number;
  scale: number;
}

export interface RoomStudioObject {
  id: string;
  source_photo_id: string | null;
  name: string;
  category: string;
  support_type: SupportType;
  support_surface: string;
  bbox_norm: [number, number, number, number];
  dimensions_m: [number, number, number];
  pose: RoomObjectPose;
  color_hex: string;
  confidence: number;
  mesh_file_id: string | null;
  mesh_url: string | null;
  mesh_engine: string;
  mesh_bytes?: number;
  crop_b64?: string | null;
  notes?: string;
}

export interface RoomWallTexture {
  file_id: string;
  url: string;
  method: string;
  photo_count: number;
}

export interface RoomStudioProject {
  id: string;
  name: string;
  width_m: number;
  length_m: number;
  height_m: number;
  splat_file_id?: string | null;
  splat_url?: string | null;
  splat_filename?: string | null;
  splat_format?: string | null;
  wall_textures: Record<string, RoomWallTexture>;
  photos: RoomStudioPhoto[];
  objects: RoomStudioObject[];
  created_at: number;
  updated_at: number;
}

export interface GhostCameraHint {
  id: string;
  surface: string;
  label: string;
  priority: "high" | "medium" | string;
  pose: CameraPose3D;
  reason: string;
}

export interface RoomCaptureCoach {
  coverage_pct: number;
  photo_count: number;
  object_count: number;
  converted_3d_count: number;
  surface_counts: Record<string, number>;
  ghost_cameras: GhostCameraHint[];
  next_instruction: string;
}

async function reqJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      if (err?.detail) msg = String(err.detail);
    } catch {
      // keep status text
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export async function listRoomProjects(): Promise<{ projects: RoomStudioProject[] }> {
  return reqJson("/api/room-studio/projects");
}

export async function createRoomProject(payload: {
  name: string;
  width_m: number;
  length_m: number;
  height_m: number;
}): Promise<{ project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson("/api/room-studio/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getRoomProject(
  projectId: string
): Promise<{ project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(`/api/room-studio/projects/${encodeURIComponent(projectId)}`);
}

export async function updateRoomProject(
  projectId: string,
  payload: Partial<{ name: string; width_m: number; length_m: number; height_m: number }>
): Promise<{ project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(`/api/room-studio/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function uploadRoomPhoto(
  projectId: string,
  file: File,
  opts: { name: string; surface: RoomSurface; tags: string }
): Promise<{ photo: RoomStudioPhoto; project: RoomStudioProject; coach: RoomCaptureCoach }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("name", opts.name);
  fd.append("surface", opts.surface);
  fd.append("tags", opts.tags);
  return reqJson(`/api/room-studio/projects/${encodeURIComponent(projectId)}/photos`, {
    method: "POST",
    body: fd,
  });
}

export async function deleteRoomPhoto(
  projectId: string,
  photoId: string
): Promise<{ project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/photos/${encodeURIComponent(photoId)}`,
    { method: "DELETE" }
  );
}

export async function analyzeRoomPhoto(
  projectId: string,
  photoId: string
): Promise<{
  ok: boolean;
  summary: string;
  provider: string;
  created_objects: RoomStudioObject[];
  project: RoomStudioProject;
  coach: RoomCaptureCoach;
}> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/photos/${encodeURIComponent(photoId)}/analyze`,
    { method: "POST" }
  );
}

export async function stitchRoomSurface(
  projectId: string,
  surface: string
): Promise<{ ok: boolean; method: string; project: RoomStudioProject }> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/stitch/${encodeURIComponent(surface)}`,
    { method: "POST" }
  );
}

export async function uploadRoomSplat(
  projectId: string,
  file: File
): Promise<{ ok: boolean; project: RoomStudioProject }> {
  const fd = new FormData();
  fd.append("file", file);
  return reqJson(`/api/room-studio/projects/${encodeURIComponent(projectId)}/splat`, {
    method: "POST",
    body: fd,
  });
}

export async function createRoomObject(
  projectId: string,
  payload: {
    source_photo_id?: string | null;
    name: string;
    category?: string;
    support_type: SupportType;
    support_surface: string;
    bbox_norm: [number, number, number, number];
    dimensions_m: [number, number, number];
    color_hex?: string;
    notes?: string;
  }
): Promise<{ object: RoomStudioObject; project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(`/api/room-studio/projects/${encodeURIComponent(projectId)}/objects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateRoomObject(
  projectId: string,
  objectId: string,
  payload: Partial<{
    name: string;
    support_type: SupportType;
    support_surface: string;
    dimensions_m: [number, number, number];
    pose: Partial<RoomObjectPose>;
    color_hex: string;
    notes: string;
  }>
): Promise<{ object: RoomStudioObject; project: RoomStudioProject }> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(objectId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function deleteRoomObject(
  projectId: string,
  objectId: string
): Promise<{ project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(objectId)}`,
    { method: "DELETE" }
  );
}

export async function generateRoomObject3D(
  projectId: string,
  objectId: string,
  engine: Object3DEngine
): Promise<{ object: RoomStudioObject; project: RoomStudioProject; coach: RoomCaptureCoach }> {
  return reqJson(
    `/api/room-studio/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(objectId)}/generate-3d`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engine }),
    }
  );
}
