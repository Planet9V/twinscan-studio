import { API_URL } from "./api";

export interface MicrobitPinSpec {
  id: string;
  label: string;
  pad_type: "ring" | "edge" | string;
  x_mm: number;
  capabilities: string[];
  voltage: string;
  max_ma: number;
  notes: string;
}

export interface MicrobitAccessoryWire {
  from: string;
  to_role: "signal" | "secondary" | "3V" | "GND" | string;
  color: string;
}

export type BoardId = "microbit_v2" | "rpi5_16gb" | "puppypi_pro";

export interface BoardProfile {
  id: BoardId;
  name: string;
  mcu: string;
  logic_v: number;
  has_5v_rail: boolean;
  language: string;
  pins: MicrobitPinSpec[];
  sensors: string[];
  wireless: string[];
}

export interface MicrobitAccessorySpec {
  id: string;
  name: string;
  vendor?: string;
  category: string;
  color_hex: string;
  ic?: string;
  protocol?: string;
  i2c_address?: string | null;
  voltage_min_v?: number;
  voltage_max_v?: number;
  requires_5v?: boolean;
  allowed_signal_pins: string[];
  default_pin: string;
  secondary_pin: string | null;
  default_pins_by_board?: Record<string, { pin: string; secondary_pin?: string | null }>;
  needs_power: boolean;
  power_note: string;
  how_it_works?: string;
  wires: MicrobitAccessoryWire[];
  summary: string;
}

export interface MicrobitAttachment {
  id: string;
  accessory_id: string;
  label: string;
  pin: string;
  secondary_pin?: string | null;
}

export interface MicrobitWiringStep {
  step: string;
  accessory: string;
  from_pin: string;
  to_pin: string;
  color: string;
  instruction: string;
}

export interface MicrobitWiringValidation {
  ok: boolean;
  conflicts: string[];
  warnings: string[];
  used_pins: string[];
  wiring_steps: MicrobitWiringStep[];
}

export type MicrobitTrigger =
  | "lift"
  | "tilt_left"
  | "tilt_right"
  | "shake"
  | "button_a"
  | "button_b"
  | "logo_touch"
  | "pir_motion"
  | "touch_pad"
  | "ultrasonic_near"
  | "temp_high";

export interface MicrobitSimRule {
  trigger: MicrobitTrigger;
  led_icon: string;
  speak_text: string;
  sound_effect: string;
  servo_angle: number | null;
  neopixel_hex: string | null;
}

export interface MicrobitChatMessage {
  role: "user" | "assistant";
  text: string;
}

export interface MicrobitProject {
  id: string;
  name: string;
  board_id?: BoardId;
  description: string;
  attachments: MicrobitAttachment[];
  sim_rules?: MicrobitSimRule[];
  chat_history?: MicrobitChatMessage[];
  code: string;
  wiring: MicrobitWiringValidation;
  created_at: number;
  updated_at: number;
}

export interface MicrobitCatalog {
  ok: boolean;
  board: BoardProfile;
  boards?: Record<BoardId, BoardProfile>;
  pins: MicrobitPinSpec[];
  accessories: MicrobitAccessorySpec[];
  templates: Array<{ id: string; name: string; code: string }>;
}

export interface MicrobitHardwareStatus {
  ok: boolean;
  connected: boolean;
  usb_detected?: boolean;
  serial_port?: string | null;
  flash_drive?: boolean;
  host_ip?: string;
  host_name?: string;
  error?: string;
}

export interface MicrobitLiveSensors {
  ax: number;
  ay: number;
  az: number;
  temp_c: number;
  light: number;
  sound: number;
  btn_a: boolean;
  btn_b: boolean;
  logo: boolean;
}

async function mbReq<T>(path: string, init?: RequestInit): Promise<T> {
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

export async function getMicrobitCatalog(): Promise<MicrobitCatalog> {
  return mbReq<MicrobitCatalog>("/api/microbit/catalog");
}

export async function listMicrobitProjects(): Promise<{ projects: MicrobitProject[] }> {
  return mbReq("/api/microbit/projects");
}

export async function createMicrobitProject(payload: {
  name: string;
  description?: string;
  board_id?: BoardId;
}): Promise<{ project: MicrobitProject }> {
  return mbReq("/api/microbit/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateMicrobitProject(
  projectId: string,
  payload: Partial<{
    name: string;
    board_id: BoardId;
    description: string;
    attachments: MicrobitAttachment[];
    code: string;
  }>
): Promise<{ project: MicrobitProject }> {
  return mbReq(`/api/microbit/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteMicrobitProject(projectId: string): Promise<{ ok: boolean }> {
  return mbReq(`/api/microbit/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

export async function generateMicrobitCode(
  projectId: string
): Promise<{ ok: boolean; code: string; project: MicrobitProject }> {
  return mbReq(`/api/microbit/projects/${encodeURIComponent(projectId)}/generate-code`, {
    method: "POST",
  });
}

export async function getMicrobitHardwareStatus(): Promise<MicrobitHardwareStatus> {
  return mbReq<MicrobitHardwareStatus>("/api/microbit/hardware/status");
}

export async function deployMicrobitCode(
  code: string
): Promise<{ ok: boolean; host_name?: string; upload?: string; boot?: string }> {
  return mbReq("/api/microbit/hardware/deploy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

export async function readMicrobitSensors(): Promise<{ ok: boolean; sensors: MicrobitLiveSensors }> {
  return mbReq("/api/microbit/hardware/sensors");
}

export async function runMicrobitSelfTest(): Promise<{ ok: boolean; sensors: MicrobitLiveSensors }> {
  return mbReq("/api/microbit/hardware/self-test", { method: "POST" });
}

export async function chatWithMicrobitCopilot(
  projectId: string,
  message: string
): Promise<{ ok: boolean; assistant_reply: string; provider?: string; project: MicrobitProject }> {
  return mbReq(`/api/microbit/projects/${encodeURIComponent(projectId)}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
