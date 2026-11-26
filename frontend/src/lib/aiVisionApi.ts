import { API_URL } from "./api";

export type AiVisionMode =
  | "raw"
  | "face_recognition"
  | "object_animal"
  | "track_follow"
  | "line_follow"
  | "apriltag";

export type LineColorPreset = "black" | "red" | "blue" | "green" | "yellow" | "custom";

export interface KnownPerson {
  id: string;
  name: string;
  role: string;
  greeting_phrase: string;
  greet_action: string;
  auto_speak: boolean;
  avatar_file_id?: string | null;
  avatar_url?: string | null;
  embedding_count: number;
  notes: string;
  last_seen_at?: string | null;
  created_at: string;
}

export interface AiDetection {
  id: string;
  kind: "face" | "animal" | "object" | "apriltag" | "line";
  label: string;
  confidence: number;
  is_animal?: boolean;
  person_id?: string | null;
  bbox_norm: [number, number, number, number];
  tracked?: boolean;
}

export interface AiVisionState {
  robot_id: string;
  mode: AiVisionMode;
  follow_enabled: boolean;
  line_follow_enabled: boolean;
  auto_greet_enabled: boolean;
  lidar_stop_m: number;
  line_color: LineColorPreset;
  custom_hsv?: [number, number, number] | null;
  tracked_target?: { label: string; bbox_norm: number[] } | null;
  fps: number;
  models_ready: Record<string, boolean>;
  detections: AiDetection[];
  last_greeting?: string | null;
  camera_connected?: boolean;
  last_error?: string | null;
  target_fps?: number;
  conf_threshold?: number;
  lost_frames?: number;
}

export interface SpatialSighting {
  id: string;
  robot_id: string;
  space_id?: string | null;
  label: string;
  kind: string;
  x_m: number;
  y_m: number;
  confidence: number;
  snapshot_file_id?: string | null;
  snapshot_url?: string | null;
  notes?: string;
  seen_at: string;
}

export interface SentryConfig {
  armed: boolean;
  watch_motion: boolean;
  watch_unknown_faces: boolean;
  watch_animals: boolean;
  speak_challenge: boolean;
  flash_rgb: boolean;
  cooldown_sec: number;
  custom_challenge: string;
}

export interface SentryEvent {
  id: string;
  robot_id: string;
  trigger_type: string;
  label: string;
  severity: string;
  detail: string;
  snapshot_file_id?: string | null;
  snapshot_url?: string | null;
  spoken_alert?: string | null;
  created_at: string;
}

export type SentryStatus = SentryConfig & {
  robot_id: string;
  event_count: number;
  last_alert_at?: string | null;
  last_trigger?: string | null;
};

export interface PatrolWaypoint {
  x: number;
  y: number;
  label?: string;
  pause_sec?: number;
}

export interface PatrolRoute {
  id: string;
  robot_id: string;
  space_id?: string | null;
  name: string;
  waypoints: PatrolWaypoint[];
  loop_enabled: boolean;
  max_speed_cms: number;
  obstacle_clearance_m: number;
  created_at: string;
}

export interface PatrolStatus {
  robot_id: string;
  active: boolean;
  state: string;
  route_name?: string | null;
  current_waypoint_idx: number;
  total_waypoints: number;
  loop_enabled: boolean;
  lidar_live?: boolean;
  lidar_age_sec?: number | null;
  require_lidar?: boolean;
  camera_avoidance_active?: boolean;
  sectors_m: {
    front: number | null;
    front_left: number | null;
    front_right: number | null;
    left: number | null;
    right: number | null;
  };
  visual_obstacle?: string | null;
  last_command?: { vx_cms: number; yaw_rate_rads: number } | null;
  started_at?: string | null;
  error?: string | null;
}

async function requestAiVisionJson<T>(
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
        const err = new Error(`AI Vision API ${path} failed (${res.status}): ${text}`);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[aiVisionApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`AI Vision API ${path} failed`);
}

export function getAiVisionStreamUrl(robotId: string): string {
  return `${API_URL}/api/robots/${encodeURIComponent(robotId)}/ai-vision/stream`;
}

export async function fetchAiVisionState(robotId: string): Promise<AiVisionState> {
  return requestAiVisionJson<AiVisionState>(
    `/api/robots/${encodeURIComponent(robotId)}/ai-vision/state`,
    undefined,
    2
  );
}

export async function setAiVisionMode(
  robotId: string,
  payload: {
    mode: AiVisionMode;
    follow_enabled?: boolean;
    line_follow_enabled?: boolean;
    auto_greet_enabled?: boolean;
    lidar_stop_m?: number;
    line_color?: LineColorPreset;
    target_fps?: number;
    conf_threshold?: number;
  }
): Promise<AiVisionState> {
  return requestAiVisionJson<AiVisionState>(
    `/api/robots/${encodeURIComponent(robotId)}/ai-vision/mode`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function selectAiVisionTarget(
  robotId: string,
  payload: { norm_x: number; norm_y: number; clear?: boolean }
): Promise<AiVisionState> {
  return requestAiVisionJson<AiVisionState>(
    `/api/robots/${encodeURIComponent(robotId)}/ai-vision/select-target`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function pickLineColor(
  robotId: string,
  payload: { norm_x: number; norm_y: number }
): Promise<AiVisionState> {
  return requestAiVisionJson<AiVisionState>(
    `/api/robots/${encodeURIComponent(robotId)}/ai-vision/pick-color`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function deepIdentifyFrame(
  robotId: string,
  payload: { speak_result?: boolean; prompt?: string } = {}
): Promise<{
  ok: boolean;
  description: string;
  objects: string[];
  animals: string[];
  spoken: boolean;
  model_used?: string;
}> {
  return requestAiVisionJson(
    `/api/robots/${encodeURIComponent(robotId)}/ai-vision/deep-identify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function listKnownPeople(): Promise<{ people: KnownPerson[] }> {
  const data = await requestAiVisionJson<{ people?: KnownPerson[] } | KnownPerson[]>(
    "/api/people",
    undefined,
    2
  );
  if (Array.isArray(data)) {
    return { people: data };
  }
  return { people: Array.isArray(data.people) ? data.people : [] };
}

export async function enrollPersonFromCamera(
  robotId: string,
  payload: {
    name: string;
    role?: string;
    greeting_phrase?: string;
    greet_action?: string;
    auto_speak?: boolean;
    notes?: string;
  }
): Promise<{ ok: boolean; person: KnownPerson; face_detected: boolean }> {
  return requestAiVisionJson(
    `/api/people/enroll-camera/${encodeURIComponent(robotId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function enrollPersonFromUpload(
  formData: FormData
): Promise<{ ok: boolean; person: KnownPerson; face_detected: boolean }> {
  return requestAiVisionJson(
    "/api/people/enroll-upload",
    {
      method: "POST",
      body: formData,
    },
    1
  );
}

export async function updateKnownPerson(
  personId: string,
  payload: Partial<KnownPerson>
): Promise<{ person: KnownPerson }> {
  return requestAiVisionJson(
    `/api/people/${encodeURIComponent(personId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function deleteKnownPerson(personId: string): Promise<{ deleted: boolean }> {
  return requestAiVisionJson(
    `/api/people/${encodeURIComponent(personId)}`,
    { method: "DELETE" },
    1
  );
}

export async function listPatrolRoutes(robotId: string): Promise<{ routes: PatrolRoute[] }> {
  const data = await requestAiVisionJson<{ routes?: PatrolRoute[] } | PatrolRoute[]>(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/routes`,
    undefined,
    2
  );
  if (Array.isArray(data)) {
    return { routes: data };
  }
  return { routes: Array.isArray(data.routes) ? data.routes : [] };
}

export async function savePatrolRoute(
  robotId: string,
  payload: {
    name: string;
    space_id?: string;
    waypoints: PatrolWaypoint[];
    loop_enabled?: boolean;
    max_speed_cms?: number;
    obstacle_clearance_m?: number;
  }
): Promise<{ route: PatrolRoute }> {
  return requestAiVisionJson(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/routes`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function deletePatrolRoute(
  robotId: string,
  routeId: string
): Promise<{ deleted: boolean }> {
  return requestAiVisionJson(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/routes/${encodeURIComponent(routeId)}`,
    { method: "DELETE" },
    1
  );
}

export async function startRobotPatrol(
  robotId: string,
  payload: {
    route_id?: string;
    waypoints?: PatrolWaypoint[];
    loop_enabled?: boolean;
    max_speed_cms?: number;
    obstacle_clearance_m?: number;
    announce_voice?: boolean;
    require_lidar?: boolean;
    camera_avoidance?: boolean;
  }
): Promise<PatrolStatus> {
  return requestAiVisionJson<PatrolStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function startRobotLidarNode(
  robotId: string
): Promise<{ ok: boolean; device_present: boolean; ros_version: string; detail: string }> {
  return requestAiVisionJson<{
    ok: boolean;
    device_present: boolean;
    ros_version: string;
    detail: string;
  }>(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/start-lidar`,
    { method: "POST" },
    1
  );
}

export async function stopRobotPatrol(robotId: string): Promise<PatrolStatus> {
  return requestAiVisionJson<PatrolStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/stop`,
    { method: "POST" },
    1
  );
}

export async function fetchPatrolStatus(robotId: string): Promise<PatrolStatus> {
  return requestAiVisionJson<PatrolStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/patrol/status`,
    undefined,
    2
  );
}

// --- Add-On B: Semantic Spatial Memory ---

export async function fetchSpatialMemory(
  query?: string,
  limit = 30
): Promise<{ sightings: SpatialSighting[] }> {
  const params = new URLSearchParams();
  if (query?.trim()) params.set("query", query.trim());
  params.set("limit", String(limit));
  const data = await requestAiVisionJson<
    { sightings?: SpatialSighting[] } | SpatialSighting[]
  >(`/api/spatial-memory?${params.toString()}`, undefined, 2);
  if (Array.isArray(data)) {
    return { sightings: data };
  }
  return { sightings: Array.isArray(data.sightings) ? data.sightings : [] };
}

export async function captureSpatialMemory(
  robotId: string
): Promise<{ ok: boolean; recorded_count: number; sightings: SpatialSighting[] }> {
  const data = await requestAiVisionJson<{
    ok: boolean;
    recorded_count: number;
    sightings?: SpatialSighting[];
  }>(
    `/api/spatial-memory/capture/${encodeURIComponent(robotId)}`,
    { method: "POST" },
    1
  );
  return {
    ...data,
    sightings: Array.isArray(data.sightings) ? data.sightings : [],
  };
}

export async function deleteSpatialSighting(
  sightingId: string
): Promise<{ deleted: boolean }> {
  return requestAiVisionJson<{ deleted: boolean }>(
    `/api/spatial-memory/${encodeURIComponent(sightingId)}`,
    { method: "DELETE" },
    1
  );
}

// --- Add-On C: Autonomous Sentry Guard Mode ---

export async function fetchSentryStatus(robotId: string): Promise<SentryStatus> {
  return requestAiVisionJson<SentryStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/status`,
    undefined,
    2
  );
}

export async function updateSentryConfig(
  robotId: string,
  payload: Partial<SentryConfig>
): Promise<SentryStatus> {
  return requestAiVisionJson<SentryStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/config`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function armRobotSentry(robotId: string): Promise<SentryStatus> {
  return requestAiVisionJson<SentryStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/arm`,
    { method: "POST" },
    1
  );
}

export async function disarmRobotSentry(robotId: string): Promise<SentryStatus> {
  return requestAiVisionJson<SentryStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/disarm`,
    { method: "POST" },
    1
  );
}

export async function fetchSentryEvents(
  robotId: string,
  limit = 40
): Promise<{ events: SentryEvent[] }> {
  const data = await requestAiVisionJson<{ events?: SentryEvent[] } | SentryEvent[]>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/events?limit=${encodeURIComponent(
      String(limit)
    )}`,
    undefined,
    2
  );
  if (Array.isArray(data)) {
    return { events: data };
  }
  return { events: Array.isArray(data.events) ? data.events : [] };
}

export async function clearSentryEvents(
  robotId: string
): Promise<{ cleared: number }> {
  return requestAiVisionJson<{ cleared: number }>(
    `/api/robots/${encodeURIComponent(robotId)}/sentry/events`,
    { method: "DELETE" },
    1
  );
}
