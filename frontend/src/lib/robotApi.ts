import { API_URL, WS_URL } from "./api";
import type { EquipmentVisionResult } from "./types";

export interface RobotRecord {
  id: string;
  name: string;
  model: string;
  serial_number?: string | null;
  ip_address: string;
  mac_address?: string | null;
  ssh_user: string;
  rosbridge_port: number;
  video_port: number;
  active_ros_distro?: string | null;
  status: string;
  battery_mv?: number | null;
  cpu_temp_c?: number | null;
  capabilities: Record<string, unknown>;
  hbom_sbom: Record<string, unknown>;
  last_seen_at?: string | null;
}

export interface RobotDevice {
  id: string;
  robot_id: string;
  subsystem: string;
  make: string;
  model: string;
  bus_type: string;
  device_path?: string | null;
  usb_id?: string | null;
  status: string;
  metadata: Record<string, unknown>;
}

export interface RobotSbomPackage {
  id: string;
  robot_id: string;
  layer: string;
  name: string;
  version: string;
  purl?: string | null;
}

export interface RosProfile {
  id: "ros1" | "ros2" | string;
  name: string;
  distro: string;
  os: string;
  middleware: string;
  support_status: string;
  eol?: string;
  slam_nav: string[];
  camera_topic: string;
  camera_topics?: string[];
  puppy_py_path: string;
  env_file: string;
  container_name?: string;
  message_types: Record<string, string>;
  service_types: Record<string, string>;
  highlights?: string[];
  [key: string]: unknown;
}

export interface RosComparisonRow {
  dimension: string;
  ros1: string;
  ros2: string;
  advantage?: "ros1" | "ros2" | "tie" | string;
}

export interface RosComparisonPayload {
  profiles: Record<string, RosProfile>;
  comparison_rows?: RosComparisonRow[];
  rows?: RosComparisonRow[];
  recommended?: "ros1" | "ros2" | string;
  summary?: string;
  [key: string]: unknown;
}

export interface NetworkInterfaceInfo {
  ifname: string;
  enabled: boolean;
  state: string;
  mode?: string | null;
  ssid?: string | null;
  ipv4?: string | null;
  mac?: string | null;
  freq_mhz?: number | null;
  signal_pct?: number | null;
  connection?: string | null;
  kind?: string | null;
}

export interface RobotNetworkTelemetry {
  robot_id?: string;
  active_ip?: string | null;
  wifi: NetworkInterfaceInfo | null;
  ethernet: NetworkInterfaceInfo[];
  interfaces: NetworkInterfaceInfo[];
  active_ros_distro?: string | null;
  ros_containers?: Array<{
    name: string;
    state: string;
    status: string;
    ros_distro: string;
  }>;
  collected_at?: string | null;
  source?: string;
  error?: string | null;
}

export interface SmokeTestCheck {
  id: string;
  name: string;
  status: "pass" | "warn" | "fail";
  detail: string;
  latency_ms?: number;
}

export interface SmokeTestReport {
  passed: boolean;
  passed_count: number;
  total_count: number;
  checks: SmokeTestCheck[];
}

export interface RobotUpdateSnapshot {
  tag: string;
  created?: string;
  size?: string;
}

export interface RobotUpdateJobRecord {
  id: string;
  robot_id: string;
  track: string;
  action: string;
  status: string;
  packages: string[];
  rollback_tag?: string | null;
  smoke_tests?: SmokeTestReport | null;
  stdout_tail?: string;
  stderr_tail?: string;
  created_at: string;
}

export interface UpdateActionResponse {
  ok: boolean;
  track: string;
  action: string;
  status?: string;
  container?: string;
  upgradable_count?: number;
  packages?: Array<{
    name: string;
    current_version?: string;
    candidate_version?: string;
    is_security?: boolean;
  }>;
  abi_sensitive_packages?: string[];
  protected_blocked?: string[];
  rollback_tag?: string | null;
  smoke_tests?: SmokeTestReport | null;
  stdout_tail?: string;
  stderr_tail?: string;
  error?: string | null;
  job?: RobotUpdateJobRecord | null;
}

export interface UpdateHistoryResponse {
  robot_id: string;
  jobs: RobotUpdateJobRecord[];
  snapshots: RobotUpdateSnapshot[];
}

export type Pi5ComponentStatus = "ok" | "warning" | "fault" | "empty";

export interface Pi5PmicRail {
  name: string;
  volts: number | null;
  amps: number | null;
  watts: number | null;
}

export interface Pi5UsbPortInfo {
  port_path: string;
  bus_label: string;
  speed_mbps: number | null;
  max_power_ma: number;
  vid_pid: string | null;
  product: string | null;
  driver: string | null;
  device_nodes: string[];
  flap_count: number;
  status: Pi5ComponentStatus;
}

export interface Pi5HardwareComponentState {
  component_id: string;
  name: string;
  category: "soc" | "power" | "usb" | "interface" | "network" | "storage" | "peripheral";
  status: Pi5ComponentStatus;
  summary: string;
  metrics: Record<string, string | number | boolean | null>;
  bom_match_keywords: string[];
  troubleshooting?: string | null;
}

export interface Pi5HardwareDiagnostics {
  robot_id: string;
  robot_name: string;
  ip_address: string;
  collected_at: string;
  board_model: string;
  cpu_model: string;
  cpu_temp_c: number | null;
  arm_freq_mhz: number | null;
  load_avg: number[];
  uptime_text: string;
  ram_used_mb: number | null;
  ram_total_mb: number | null;
  disk_used_gb: number | null;
  disk_total_gb: number | null;
  disk_used_pct: number | null;
  throttled_hex: string;
  throttled_flags: string[];
  ext5v_volts: number | null;
  total_pmic_watts: number | null;
  pmic_rails: Pi5PmicRail[];
  usb_max_current_enable: boolean;
  usb_budget_ma: number;
  usb_total_draw_ma: number;
  usb_over_current: boolean;
  usb_ports: Pi5UsbPortInfo[];
  ld19_verdict: {
    detected: boolean;
    device_path: string | null;
    summary: string;
    likely_causes: string[];
  };
  interfaces: {
    pcie: string[];
    uarts: string[];
    i2c_buses: string[];
    spi_devices: string[];
    video_devices: string[];
    audio_cards: string[];
    pinctrl_active: string[];
    network: string[];
    docker_containers: string[];
  };
  components: Pi5HardwareComponentState[];
}

export interface LibraryUpdateItem {
  name: string;
  scope?: string;
  installed?: string | null;
  latest?: string | null;
  status: "up_to_date" | "update_available" | "not_installed" | "unknown" | string;
  notes?: string | null;
}

export interface FeatureReadinessItem {
  feature: string;
  subsystem?: string;
  status: "ready" | "warning" | "missing" | string;
  detail: string;
  fix_hint?: string | null;
}

export interface UpdateCheckReport {
  robot_id?: string;
  checked_at?: string;
  ros_lifecycle?: {
    active_mode?: "ros1" | "ros2" | string;
    active_distro?: string;
    status?: string;
    warning?: string | null;
    recommendation?: string | null;
    ubuntu_or_debian?: string | null;
    apt_upgradable_count?: number | null;
    newer_ros_distros?: string[];
    [key: string]: unknown;
  };
  twinscan_stack?: Record<string, unknown>;
  libraries?: LibraryUpdateItem[];
  features?: FeatureReadinessItem[];
  summary?: {
    updates_available?: number;
    features_ready?: number;
    features_warning?: number;
    features_missing?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface DiscoveredRobotCandidate {
  ip: string;
  serial_number?: string | null;
  rosbridge_open: boolean;
  video_open: boolean;
  ssh_open: boolean;
  ssh_banner?: string | null;
  model_guess?: string | null;
}

export interface RobotDetailResponse {
  robot: RobotRecord;
  devices: RobotDevice[];
  sbom: RobotSbomPackage[];
}

export interface SnapToVisionParams {
  topic?: string;
  model?: string;
  consensus?: boolean;
  contextHint?: string;
  context_hint?: string;
  cameraYawDeg?: number;
  camera_yaw_deg?: number;
}

export interface SnapToVisionResponse {
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
}

async function requestRobotJson<T>(path: string, init?: RequestInit, maxRetries = 3): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(`${API_URL}${path}`, init);
      if (!res.ok) {
        const text = await res.text();
        const err = new Error(`Robot API ${path} failed (${res.status}): ${text}`);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[robotApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`Robot API ${path} failed`);
}

export async function listRobots(): Promise<{ robots: RobotRecord[]; count: number }> {
  const data = await requestRobotJson<RobotRecord[] | { robots?: RobotRecord[]; count?: number }>(
    "/api/robots"
  );
  if (Array.isArray(data)) {
    return { robots: data, count: data.length };
  }
  const robots = Array.isArray(data.robots) ? data.robots : [];
  return { robots, count: data.count ?? robots.length };
}

export async function discoverRobots(cidrs?: string[]): Promise<{
  discovered: DiscoveredRobotCandidate[];
  robots: RobotRecord[];
  count: number;
}> {
  const data = await requestRobotJson<{
    discovered?: DiscoveredRobotCandidate[];
    candidates?: DiscoveredRobotCandidate[];
    robots?: RobotRecord[];
    registered?: RobotRecord[];
    count?: number;
  }>("/api/robots/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cidrs && cidrs.length > 0 ? { cidrs } : {}),
  });
  const discovered = data.discovered ?? data.candidates ?? [];
  const robots = data.robots ?? data.registered ?? [];
  return {
    discovered,
    robots,
    count: data.count ?? robots.length,
  };
}

export async function registerRobot(payload: {
  ip_address: string;
  name?: string;
  model?: string;
  serial_number?: string;
  ssh_user?: string;
  ssh_password?: string;
  rosbridge_port?: number;
  video_port?: number;
}): Promise<{ robot: RobotRecord }> {
  const data = await requestRobotJson<RobotRecord | { robot: RobotRecord }>("/api/robots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if ("robot" in data && data.robot) {
    return data;
  }
  return { robot: data as RobotRecord };
}

export async function getRobotDetail(robotId: string): Promise<RobotDetailResponse> {
  return requestRobotJson<RobotDetailResponse>(`/api/robots/${encodeURIComponent(robotId)}`);
}

export async function catalogueRobot(robotId: string): Promise<
  RobotDetailResponse & {
    neo4j_synced?: boolean;
    device_count?: number;
    sbom_count?: number;
  }
> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/catalogue`,
    { method: "POST" },
    1
  );
}

export async function deleteRobot(
  robotId: string
): Promise<{ deleted: boolean; robot_id?: string }> {
  return requestRobotJson(`/api/robots/${encodeURIComponent(robotId)}`, {
    method: "DELETE",
  });
}

export async function fetchRosComparison(): Promise<RosComparisonPayload> {
  return requestRobotJson<RosComparisonPayload>("/api/robots/ros-comparison", undefined, 2);
}

export async function fetchRobotNetwork(robotId: string): Promise<RobotNetworkTelemetry> {
  const data = await requestRobotJson<RobotNetworkTelemetry>(
    `/api/robots/${encodeURIComponent(robotId)}/network`,
    undefined,
    2
  );
  return {
    ...data,
    wifi: data.wifi ?? null,
    ethernet: Array.isArray(data.ethernet) ? data.ethernet : [],
    interfaces: Array.isArray(data.interfaces) ? data.interfaces : [],
  };
}

export async function setRobotActiveIp(
  robotId: string,
  ipAddress: string
): Promise<{ robot?: RobotRecord; ip_address?: string; [key: string]: unknown }> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/active-ip`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip_address: ipAddress }),
    },
    1
  );
}

export async function runRobotUpdateCheck(robotId: string): Promise<UpdateCheckReport> {
  return requestRobotJson<UpdateCheckReport>(
    `/api/robots/${encodeURIComponent(robotId)}/update-check`,
    { method: "POST" },
    1
  );
}

export async function runRobotUpdateDryRun(
  robotId: string,
  payload: { track: "host_apt" | "ros_pip"; packages?: string[] }
): Promise<UpdateActionResponse> {
  return requestRobotJson<UpdateActionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/dry-run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function runRobotUpdateDownload(
  robotId: string,
  payload: { track: "host_apt" | "ros_pip"; packages?: string[] }
): Promise<UpdateActionResponse> {
  return requestRobotJson<UpdateActionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/download`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function runRobotUpdateApply(
  robotId: string,
  payload: {
    track: "host_apt" | "ros_pip";
    packages?: string[];
    allow_abi_sensitive?: boolean;
    run_tests?: boolean;
  }
): Promise<UpdateActionResponse> {
  return requestRobotJson<UpdateActionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function runRobotUpdateTests(
  robotId: string,
  packages?: string[]
): Promise<UpdateActionResponse> {
  return requestRobotJson<UpdateActionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/test`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(packages && packages.length > 0 ? { packages } : {}),
    },
    1
  );
}

export async function runRobotUpdateRollback(
  robotId: string,
  payload: { rollback_tag: string; container?: string }
): Promise<UpdateActionResponse> {
  return requestRobotJson<UpdateActionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/rollback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function fetchRobotUpdateHistory(robotId: string): Promise<UpdateHistoryResponse> {
  const data = await requestRobotJson<UpdateHistoryResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/updates/history`,
    undefined,
    2
  );
  return {
    robot_id: data.robot_id ?? robotId,
    jobs: Array.isArray(data.jobs) ? data.jobs : [],
    snapshots: Array.isArray(data.snapshots) ? data.snapshots : [],
  };
}

export async function fetchPi5HardwareDiagnostics(
  robotId: string
): Promise<Pi5HardwareDiagnostics> {
  const data = await requestRobotJson<Pi5HardwareDiagnostics>(
    `/api/robots/${encodeURIComponent(robotId)}/hardware-diagnostics`,
    undefined,
    2
  );
  return {
    ...data,
    load_avg: Array.isArray(data.load_avg) ? data.load_avg : [],
    throttled_flags: Array.isArray(data.throttled_flags) ? data.throttled_flags : [],
    pmic_rails: Array.isArray(data.pmic_rails) ? data.pmic_rails : [],
    usb_ports: Array.isArray(data.usb_ports) ? data.usb_ports : [],
    components: Array.isArray(data.components) ? data.components : [],
  };
}

export async function triggerRobotEstop(robotId: string): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/estop`,
    { method: "POST" },
    2
  );
}

export async function setRobotVisionMode(
  robotId: string,
  mode: string
): Promise<{ ok: boolean; mode: string; topic: string; heartbeat_active: boolean }> {
  return requestRobotJson<{ ok: boolean; mode: string; topic: string; heartbeat_active: boolean }>(
    `/api/robots/${encodeURIComponent(robotId)}/control/vision-mode`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    },
    1
  );
}

export async function sendRobotVelocity(
  robotId: string,
  payload: { x: number; y: number; yaw_rate: number; use_autogait?: boolean }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/velocity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function sendRobotGoHome(robotId: string): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/go-home`,
    { method: "POST" },
    1
  );
}

export async function sendRobotMarkTime(
  robotId: string,
  enabled: boolean
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/mark-time`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
    1
  );
}

export async function sendRobotPose(
  robotId: string,
  payload: {
    roll?: number;
    pitch?: number;
    yaw?: number;
    height?: number;
    x_shift?: number;
    stance_x?: number;
    stance_y?: number;
    run_time?: number;
    preset?: string;
  }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/pose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function sendRobotGait(
  robotId: string,
  payload: {
    overlap_time?: number;
    swing_time?: number;
    clearance_time?: number;
    z_clearance?: number;
    preset?: string;
  }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/gait`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function runRobotAction(
  robotId: string,
  name: string,
  wait = false
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/action`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, wait }),
    },
    1
  );
}

export async function sendRobotServo(
  robotId: string,
  payload: { id: number; pulse: number; time: number }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/servo`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function sendRobotBuzzer(
  robotId: string,
  payload: { freq?: number; on_time?: number; off_time?: number; repeat?: number }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/buzzer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function sendRobotRgb(
  robotId: string,
  data: { id: number; r: number; g: number; b: number }[] | Record<string, unknown>
): Promise<Record<string, unknown>> {
  const body = Array.isArray(data) ? { data } : data;
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/rgb`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    1
  );
}

export async function sendRobotOled(
  robotId: string,
  payload: { index: number; text: string }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/control/oled`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function updateRobotWifi(
  robotId: string,
  payload: {
    mode: number;
    ssid: string;
    password?: string;
    country_code?: string;
    restart_service?: boolean;
  }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/config/wifi`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function updateRobotPassword(
  robotId: string,
  payload: { target_user: string; new_password: string }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/config/password`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function updateRobotMechanics(
  robotId: string,
  payload: {
    with_arm?: number | boolean;
    x_shift?: number;
    servo_deviations?: Record<string, number>;
  }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/config/mechanics`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function updateRobotRos(
  robotId: string,
  payload: {
    target_ros?: string;
    asr_language?: string;
    ros_domain_id?: number;
    rmw_implementation?: string;
  }
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/config/ros`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function sendRobotPower(
  robotId: string,
  action: "restart_ros" | "reboot" | "shutdown" | string
): Promise<Record<string, unknown>> {
  return requestRobotJson(
    `/api/robots/${encodeURIComponent(robotId)}/config/power`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    },
    1
  );
}

export function getRobotVideoStreamUrl(robotId: string, topic = "/usb_cam/image_raw"): string {
  return `${API_URL}/api/robots/${encodeURIComponent(robotId)}/video/stream?topic=${encodeURIComponent(
    topic
  )}`;
}

export function getRobotVideoSnapshotUrl(robotId: string, topic = "/usb_cam/image_raw"): string {
  return `${API_URL}/api/robots/${encodeURIComponent(robotId)}/video/snapshot?topic=${encodeURIComponent(
    topic
  )}`;
}

export function getRobotRosbridgeWsUrl(robotId: string): string {
  return `${WS_URL}/api/robots/${encodeURIComponent(robotId)}/rosbridge`;
}

export function getRobotCycloneDxUrl(robotId: string): string {
  return `${API_URL}/api/robots/${encodeURIComponent(robotId)}/export/cyclonedx`;
}

export async function snapRobotCameraToVision(
  robotId: string,
  params: SnapToVisionParams = {}
): Promise<SnapToVisionResponse> {
  const payload = {
    topic: params.topic ?? "/usb_cam/image_raw",
    model: params.model,
    consensus: params.consensus ?? false,
    context_hint: params.context_hint ?? params.contextHint ?? "",
    camera_yaw_deg: params.camera_yaw_deg ?? params.cameraYawDeg ?? 0,
  };
  return requestRobotJson<SnapToVisionResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/video/snap-to-vision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

// --- Semantic Spatial Memory Pro ---

export type SpatialSightingKind = "face" | "animal" | "object" | "scene" | string;
export type SpatialMemoryStatusFilter = "active" | "archived" | "all";

export interface SpatialSighting {
  id: string;
  robot_id: string;
  space_id?: string | null;
  label: string;
  kind: SpatialSightingKind;
  x_m: number;
  y_m: number;
  confidence: number;
  snapshot_file_id?: string | null;
  snapshot_url?: string | null;
  notes?: string;
  seen_at: string;
  archived: boolean;
  archived_at?: string | null;
  camera_source: string;
  tags: string[];
}

export interface SpatialMemoryCounts {
  active: number;
  archived: number;
  total: number;
}

function normalizeSpatialSighting(raw: Partial<SpatialSighting>): SpatialSighting {
  return {
    id: String(raw.id ?? ""),
    robot_id: String(raw.robot_id ?? ""),
    space_id: raw.space_id ?? null,
    label: String(raw.label ?? "Unknown"),
    kind: String(raw.kind ?? "object"),
    x_m: Number(raw.x_m ?? 0),
    y_m: Number(raw.y_m ?? 0),
    confidence: Number(raw.confidence ?? 0),
    snapshot_file_id: raw.snapshot_file_id ?? null,
    snapshot_url: raw.snapshot_url ?? null,
    notes: raw.notes ?? "",
    seen_at: String(raw.seen_at ?? ""),
    archived: Boolean(raw.archived),
    archived_at: raw.archived_at ?? null,
    camera_source: String(raw.camera_source || "puppypi_fpv"),
    tags: Array.isArray(raw.tags) ? raw.tags.map((t) => String(t)) : [],
  };
}

export async function listSpatialMemory(params: {
  query?: string;
  status?: SpatialMemoryStatusFilter;
  kind?: string;
  space_id?: string;
  limit?: number;
} = {}): Promise<{ sightings: SpatialSighting[]; counts: SpatialMemoryCounts }> {
  const sp = new URLSearchParams();
  if (params.query?.trim()) sp.set("query", params.query.trim());
  sp.set("status", params.status ?? "active");
  if (params.kind && params.kind !== "all") sp.set("kind", params.kind);
  if (params.space_id) sp.set("space_id", params.space_id);
  sp.set("limit", String(params.limit ?? 200));
  const data = await requestRobotJson<
    { sightings?: Partial<SpatialSighting>[]; counts?: Partial<SpatialMemoryCounts> } | Partial<SpatialSighting>[]
  >(`/api/spatial-memory?${sp.toString()}`, undefined, 2);
  const rawList = Array.isArray(data) ? data : Array.isArray(data.sightings) ? data.sightings : [];
  const sightings = rawList.map(normalizeSpatialSighting);
  const rawCounts = Array.isArray(data) ? undefined : data.counts;
  const active = Number(
    rawCounts?.active ?? sightings.filter((s) => !s.archived).length
  );
  const archived = Number(
    rawCounts?.archived ?? sightings.filter((s) => s.archived).length
  );
  const total = Number(rawCounts?.total ?? active + archived);
  return {
    sightings,
    counts: { active, archived, total },
  };
}

export async function updateSpatialSighting(
  sightingId: string,
  payload: {
    label?: string;
    kind?: string;
    notes?: string;
    tags?: string[];
    archived?: boolean;
    space_id?: string | null;
  }
): Promise<{ ok: boolean; sighting: SpatialSighting }> {
  const data = await requestRobotJson<{ ok?: boolean; sighting: Partial<SpatialSighting> }>(
    `/api/spatial-memory/${encodeURIComponent(sightingId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  return {
    ok: Boolean(data.ok ?? true),
    sighting: normalizeSpatialSighting(data.sighting ?? {}),
  };
}

export async function bulkSpatialSightings(payload: {
  action: "archive" | "retrieve" | "delete";
  ids: string[];
}): Promise<{ ok: boolean; affected: number }> {
  return requestRobotJson<{ ok: boolean; affected: number }>(
    "/api/spatial-memory/bulk",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function deleteSpatialSightingPro(
  sightingId: string
): Promise<{ deleted: boolean }> {
  return requestRobotJson<{ deleted: boolean }>(
    `/api/spatial-memory/${encodeURIComponent(sightingId)}`,
    { method: "DELETE" },
    1
  );
}

export async function captureSpatialMemoryPro(
  robotId: string
): Promise<{ ok: boolean; recorded_count: number; sightings: SpatialSighting[] }> {
  const data = await requestRobotJson<{
    ok: boolean;
    recorded_count: number;
    sightings?: Partial<SpatialSighting>[];
  }>(
    `/api/spatial-memory/capture/${encodeURIComponent(robotId)}`,
    { method: "POST" },
    1
  );
  return {
    ok: Boolean(data.ok),
    recorded_count: Number(data.recorded_count ?? 0),
    sightings: Array.isArray(data.sightings) ? data.sightings.map(normalizeSpatialSighting) : [],
  };
}

// --- Stage 3: Autonomous Frontier Explorer, Multi-Angle Mapper & Low-Battery RTH ---

export type ExplorerCaptureMode = "quick_3" | "level_360" | "multi_pitch";

export interface ExplorerStartPayload {
  space_id?: string | null;
  max_iterations?: number;
  target_coverage_pct?: number;
  capture_mode?: ExplorerCaptureMode;
  quality_preset?: "fast" | "balanced" | "studio_ultra";
  rth_battery_v?: number;
  max_speed_cms?: number;
  obstacle_clearance_m?: number;
  apriltag_home_id?: number;
  announce_voice?: boolean;
  require_lidar?: boolean;
}

export interface ExplorerStatus {
  robot_id: string;
  space_id: string | null;
  active: boolean;
  state:
    | "idle"
    | "exploring_transit"
    | "capturing_multi_angle"
    | "returning_home"
    | "parked_home"
    | "stopped"
    | "blocked_no_lidar";
  iteration: number;
  max_iterations: number;
  coverage_pct: number;
  target_coverage_pct: number;
  dark_zones_remaining: number;
  panels_captured: number;
  objects_identified: number;
  battery_v: number | null;
  battery_pct: number | null;
  rth_battery_v: number;
  capture_mode: ExplorerCaptureMode;
  quality_preset: string;
  current_pitch_deg: number;
  current_yaw_deg: number;
  home_xy: [number, number];
  current_xy: [number, number];
  target_xy: [number, number] | null;
  path_xy: [number, number][];
  apriltag_home_seen: boolean;
  lidar_live: boolean;
  started_at: string | null;
  error: string | null;
  event_log: { ts: string; level: "info" | "warn" | "ok"; message: string }[];
}

export async function startRobotExplorer(
  robotId: string,
  payload: ExplorerStartPayload = {}
): Promise<ExplorerStatus> {
  return requestRobotJson<ExplorerStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/explore/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function triggerRobotRth(robotId: string): Promise<ExplorerStatus> {
  return requestRobotJson<ExplorerStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/explore/rth`,
    { method: "POST" },
    1
  );
}

export async function stopRobotExplorer(robotId: string): Promise<ExplorerStatus> {
  return requestRobotJson<ExplorerStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/explore/stop`,
    { method: "POST" },
    1
  );
}

export async function getRobotExplorerStatus(robotId: string): Promise<ExplorerStatus> {
  const data = await requestRobotJson<ExplorerStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/explore/status`,
    undefined,
    2
  );
  return {
    ...data,
    path_xy: Array.isArray(data.path_xy) ? data.path_xy : [],
    event_log: Array.isArray(data.event_log) ? data.event_log : [],
  };
}

// --- Pi 5 Stale ROS Log Maintenance ---

export interface CleanLogsResult {
  ok: boolean;
  files_removed: number;
  reclaimed_mb: number;
  disk_use_pct: string;
  detail?: string;
}

export async function cleanRobotStaleLogs(robotId: string): Promise<CleanLogsResult> {
  return requestRobotJson<CleanLogsResult>(
    `/api/robots/${encodeURIComponent(robotId)}/maintenance/clean-logs`,
    { method: "POST" },
    1
  );
}
