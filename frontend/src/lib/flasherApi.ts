import { API_URL } from "./api";

export interface FlashPlatform {
  id: string;
  name: string;
  family: string;
  flash_method: string;
  min_storage_gb: number;
  recommended_storage_gb: string;
  supports_headless_provision: boolean;
  description: string;
}

export interface OsCatalogImage {
  id: string;
  name: string;
  description: string;
  url: string;
  download_mb: number | null;
  extract_mb: number | null;
  recommended?: boolean;
}

export interface RemovableDevice {
  device_id: string;
  device_path: string;
  kind: string;
  label: string;
  mount_point?: string;
  size_gb: number;
  is_removable: boolean;
}

export interface FlashJob {
  job_id: string;
  board_id: string;
  image_name: string;
  status: string;
  progress_pct: number;
  message: string;
  target: { device_id: string; device_path: string; size_gb: number; label: string };
}

async function fetchFlasherJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function listFlashPlatforms(): Promise<FlashPlatform[]> {
  const data = await fetchFlasherJson<{ platforms: FlashPlatform[] }>("/api/flasher/platforms");
  return data.platforms ?? [];
}

export async function getBoardOsCatalog(boardId: string): Promise<{ source: string; images: OsCatalogImage[] }> {
  return fetchFlasherJson(`/api/flasher/os-catalog?board=${encodeURIComponent(boardId)}`);
}

export async function listRemovableDevices(): Promise<{
  host_bridge_online: boolean;
  host: { os: string; tools: Record<string, boolean> } | null;
  devices: RemovableDevice[];
}> {
  return fetchFlasherJson("/api/flasher/devices");
}

export async function previewHeadlessProvision(payload: {
  hostname: string;
  username: string;
  wifi_ssid?: string;
  wifi_password?: string;
  country_code?: string;
  twinscan_url?: string;
  role?: string;
}): Promise<{ firstrun_sh: string }> {
  return fetchFlasherJson("/api/flasher/provision-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function createFlashJob(payload: {
  board_id: string;
  image_url: string;
  image_name: string;
  device_id: string;
  confirmation_token: string;
  provision?: {
    hostname: string;
    username: string;
    wifi_ssid?: string;
    wifi_password?: string;
    country_code?: string;
    twinscan_url?: string;
    role?: string;
  };
}): Promise<FlashJob> {
  return fetchFlasherJson<FlashJob>("/api/flasher/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
