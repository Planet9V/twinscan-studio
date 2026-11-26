import { API_URL } from "./api";

export type VoiceEngineKey = "auto" | "edge_tts" | "piper_tts" | "espeak";

export type WakeMode = "custom_software" | "hardware_wonderecho" | "both";

export interface VoiceAssistantConfig {
  robot_id: string;
  assistant_name: string;
  wake_word: string;
  wake_aliases: string[];
  wake_mode: WakeMode;
  default_engine: VoiceEngineKey;
  default_voice: string;
  default_speed: number;
  anti_clip: boolean;
  followup_window_sec: number;
  personality_id: string;
  llm_model: string;
  attach_camera_on_visual: boolean;
  allow_body_actions: boolean;
  updated_at?: string | null;
}

export interface VoicePersonality {
  id: string;
  name: string;
  badge: string;
  description: string;
  system_prompt: string;
  default_voice: string;
  allow_body_actions: boolean;
  is_builtin: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface VoiceToolCall {
  tool: string;
  arguments?: Record<string, unknown>;
  ok: boolean;
  summary: string;
  data?: Record<string, unknown>;
  duration_ms?: number;
}

export interface AgentToolSchema {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
}

export interface AgentToolsResponse {
  count: number;
  openrouter_tools: Record<string, unknown>[];
  mcp_tools: AgentToolSchema[];
}

export interface AgentExecuteResult {
  ok: boolean;
  tool: string;
  robot_id: string | null;
  summary: string;
  data: Record<string, unknown>;
  duration_ms: number;
}

export interface OpenClawBundle {
  api_url: string;
  robot_id: string | null;
  robot_name: string | null;
  tool_count: number;
  skill_path: string;
  mcp_config: Record<string, unknown>;
  install_commands: string[];
}

export interface ConversationTurn {
  id: string;
  robot_id: string;
  role: "user" | "assistant";
  content: string;
  personality_id?: string | null;
  action_taken?: string | null;
  rgb_applied?: number[] | null;
  camera_attached?: boolean;
  engine_used?: string | null;
  latency_ms?: number | null;
  tool_calls?: VoiceToolCall[];
  created_at: string;
}

export interface ConversationState {
  robot_id: string;
  active: boolean;
  state:
    | "idle"
    | "listening_wake"
    | "in_conversation"
    | "thinking"
    | "speaking"
    | "followup_window"
    | string;
  wake_word: string;
  personality_id: string;
  personality_name?: string;
  followup_remaining_sec?: number;
  mic_rms?: number;
  noise_floor?: number;
  last_heard?: string | null;
  last_reply?: string | null;
  error?: string | null;
}

export interface VoiceChatResponse {
  ok: boolean;
  user_turn: ConversationTurn;
  assistant_turn: ConversationTurn;
  reply: string;
  action_taken?: string | null;
  rgb_applied?: number[] | null;
  camera_attached: boolean;
  spoken: boolean;
  engine_used?: string | null;
  voice_used?: string | null;
  latency_ms: number;
  source: string;
  tool_calls?: VoiceToolCall[];
}

export interface VoiceDiagnosticCheck {
  id: string;
  name: string;
  status: "pass" | "warn" | "fail" | "skipped";
  detail: string;
  latency_ms?: number;
}

export interface VoiceLiveMicTestResult {
  recorded: boolean;
  duration_sec: number;
  audio_bytes: number;
  mic_rms: number;
  mic_peak: number;
  live_transcript: string;
  wake_matched: boolean;
  remainder: string;
  suggested_alias?: string | null;
  error?: string | null;
}

export interface VoiceDiagnosticsResponse {
  ok: boolean;
  robot_id: string;
  passed_count: number;
  total_count: number;
  card_index?: number | null;
  wake_word: string;
  checks: VoiceDiagnosticCheck[];
  live_mic_test?: VoiceLiveMicTestResult | null;
  dmesg_usb_warnings: string[];
  usb_devices: string[];
}

export interface VoiceActorOption {
  id: string;
  label: string;
  engine: "edge_tts" | "piper_tts" | "espeak";
  accent?: string;
  gender?: string;
  description?: string;
  cached?: boolean;
}

export interface VoiceCatalogResponse {
  default_engine: VoiceEngineKey;
  engines: Array<{
    id: VoiceEngineKey;
    label: string;
    description: string;
    offline: boolean;
  }>;
  voices: VoiceActorOption[];
  cached_piper_voices: string[];
}

export interface VoiceStatus {
  robot_id: string;
  audio_card_detected: boolean;
  card_index: number | null;
  device_name: string | null;
  speaker_volume_pct: number;
  speaker_muted: boolean;
  mic_gain_pct: number;
  mic_muted: boolean;
  serial_symlink_present: boolean;
  serial_device: string | null;
  asr_language: string;
  wake_listener_active: boolean;
  last_wake_event: Record<string, unknown> | string | null;
  error?: string | null;
}

export interface VoiceLogEntry {
  id: string;
  robot_id: string;
  direction: string;
  transcript: string;
  action_taken: string;
  reply_text: string;
  created_at: string;
}

export interface VoiceListenResponse {
  ok: boolean;
  transcript: string;
  intent: Record<string, unknown> | string | null;
  action_taken: string;
  reply_text: string;
  spoken: boolean;
  audio_bytes: number;
}

async function requestVoiceJson<T>(path: string, init?: RequestInit, maxRetries = 3): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(`${API_URL}${path}`, init);
      if (!res.ok) {
        const text = await res.text();
        const err = new Error(`Voice API ${path} failed (${res.status}): ${text}`);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[voiceApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`Voice API ${path} failed`);
}

export async function fetchVoiceStatus(robotId: string): Promise<VoiceStatus> {
  return requestVoiceJson<VoiceStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/status`,
    undefined,
    2
  );
}

export async function updateVoiceMixer(
  robotId: string,
  payload: {
    speaker_volume_pct?: number;
    mic_gain_pct?: number;
    speaker_mute?: boolean;
    mic_mute?: boolean;
  }
): Promise<VoiceStatus> {
  return requestVoiceJson<VoiceStatus>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/mixer`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function fetchVoiceCatalog(robotId: string): Promise<VoiceCatalogResponse> {
  return requestVoiceJson<VoiceCatalogResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/voices`,
    undefined,
    2
  );
}

export async function speakOnRobot(
  robotId: string,
  payload: {
    text: string;
    engine?: VoiceEngineKey;
    voice?: string;
    speed?: number;
    anti_clip?: boolean;
  }
): Promise<{
  ok: boolean;
  text: string;
  bytes_sent: number;
  engine: string;
  voice?: string;
  anti_clip?: boolean;
}> {
  return requestVoiceJson(
    `/api/robots/${encodeURIComponent(robotId)}/voice/speak`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function playRobotChime(
  robotId: string,
  chime: "dong" | "wakeup" | "success" | "alert"
): Promise<{ ok: boolean; chime: string }> {
  return requestVoiceJson(
    `/api/robots/${encodeURIComponent(robotId)}/voice/chime`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chime }),
    },
    1
  );
}

export async function listenVoiceCommand(
  robotId: string,
  payload: {
    duration_sec?: number;
    execute_commands?: boolean;
    speak_reply?: boolean;
    simulated_transcript?: string;
  } = {}
): Promise<VoiceListenResponse> {
  return requestVoiceJson<VoiceListenResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/listen`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function toggleWakeListener(
  robotId: string,
  enabled: boolean
): Promise<{ ok: boolean; wake_listener_active: boolean }> {
  return requestVoiceJson(
    `/api/robots/${encodeURIComponent(robotId)}/voice/wake-listener`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
    1
  );
}

export async function fetchVoiceLogs(
  robotId: string,
  limit?: number
): Promise<{ entries: VoiceLogEntry[] }> {
  const qs = limit != null ? `?limit=${encodeURIComponent(String(limit))}` : "";
  const data = await requestVoiceJson<{ entries?: VoiceLogEntry[] } | VoiceLogEntry[]>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/logs${qs}`,
    undefined,
    2
  );
  if (Array.isArray(data)) {
    return { entries: data };
  }
  return { entries: Array.isArray(data.entries) ? data.entries : [] };
}

export async function installUdevRules(
  robotId: string
): Promise<{ ok: boolean; wonderecho_present: boolean; ldlidar_present: boolean; detail: string }> {
  return requestVoiceJson(
    `/api/robots/${encodeURIComponent(robotId)}/hardware/udev-rules`,
    { method: "POST" },
    1
  );
}

// --- Conversational Voice Assistant ("Hey OX", Personalities & Hands-Free Loop) ---

export async function fetchVoiceConfig(robotId: string): Promise<VoiceAssistantConfig> {
  return requestVoiceJson<VoiceAssistantConfig>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/config`,
    undefined,
    2
  );
}

export async function updateVoiceConfig(
  robotId: string,
  payload: Partial<VoiceAssistantConfig>
): Promise<VoiceAssistantConfig> {
  return requestVoiceJson<VoiceAssistantConfig>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/config`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function listVoicePersonalities(): Promise<{ personalities: VoicePersonality[] }> {
  const data = await requestVoiceJson<
    { personalities?: VoicePersonality[] } | VoicePersonality[]
  >("/api/voice/personalities", undefined, 2);
  if (Array.isArray(data)) {
    return { personalities: data };
  }
  return { personalities: Array.isArray(data.personalities) ? data.personalities : [] };
}

export async function createVoicePersonality(payload: {
  name: string;
  badge?: string;
  description?: string;
  system_prompt: string;
  default_voice?: string;
  allow_body_actions?: boolean;
}): Promise<{ personality: VoicePersonality }> {
  const data = await requestVoiceJson<
    { personality: VoicePersonality } | VoicePersonality
  >(
    "/api/voice/personalities",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("personality" in data && data.personality) {
    return data;
  }
  return { personality: data as VoicePersonality };
}

export async function updateVoicePersonality(
  personalityId: string,
  payload: Partial<VoicePersonality>
): Promise<{ personality: VoicePersonality }> {
  const data = await requestVoiceJson<
    { personality: VoicePersonality } | VoicePersonality
  >(
    `/api/voice/personalities/${encodeURIComponent(personalityId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  if ("personality" in data && data.personality) {
    return data;
  }
  return { personality: data as VoicePersonality };
}

export async function deleteVoicePersonality(
  personalityId: string
): Promise<{ deleted: boolean }> {
  return requestVoiceJson(
    `/api/voice/personalities/${encodeURIComponent(personalityId)}`,
    { method: "DELETE" },
    1
  );
}

export async function sendVoiceChat(
  robotId: string,
  payload: {
    message: string;
    speak_reply?: boolean;
    attach_camera?: "auto" | "always" | "never";
    execute_actions?: boolean;
  }
): Promise<VoiceChatResponse> {
  return requestVoiceJson<VoiceChatResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}

export async function startHandsFreeConversation(
  robotId: string
): Promise<ConversationState> {
  return requestVoiceJson<ConversationState>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/conversation/start`,
    { method: "POST" },
    1
  );
}

export async function stopHandsFreeConversation(
  robotId: string
): Promise<ConversationState> {
  return requestVoiceJson<ConversationState>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/conversation/stop`,
    { method: "POST" },
    1
  );
}

export async function fetchConversationState(
  robotId: string
): Promise<ConversationState> {
  return requestVoiceJson<ConversationState>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/conversation/state`,
    undefined,
    2
  );
}

export async function fetchConversationHistory(
  robotId: string,
  limit?: number
): Promise<{ turns: ConversationTurn[] }> {
  const qs = limit != null ? `?limit=${encodeURIComponent(String(limit))}` : "";
  const data = await requestVoiceJson<
    { turns?: ConversationTurn[] } | ConversationTurn[]
  >(
    `/api/robots/${encodeURIComponent(robotId)}/voice/conversation/history${qs}`,
    undefined,
    2
  );
  if (Array.isArray(data)) {
    return { turns: data };
  }
  return { turns: Array.isArray(data.turns) ? data.turns : [] };
}

export async function clearConversationHistory(
  robotId: string
): Promise<{ cleared: number }> {
  return requestVoiceJson<{ cleared: number }>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/conversation/history`,
    { method: "DELETE" },
    1
  );
}

export async function runVoiceDiagnostics(
  robotId: string,
  payload: { record_live_sec?: number; test_speaker?: boolean } = {}
): Promise<VoiceDiagnosticsResponse> {
  const data = await requestVoiceJson<VoiceDiagnosticsResponse>(
    `/api/robots/${encodeURIComponent(robotId)}/voice/diagnostics`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
  return {
    ...data,
    checks: Array.isArray(data.checks) ? data.checks : [],
    dmesg_usb_warnings: Array.isArray(data.dmesg_usb_warnings) ? data.dmesg_usb_warnings : [],
    usb_devices: Array.isArray(data.usb_devices) ? data.usb_devices : [],
  };
}

// --- OpenClaw & MCP Unified Robot Agent Tool Bridge ---

export async function getAgentTools(): Promise<AgentToolsResponse> {
  const data = await requestVoiceJson<Partial<AgentToolsResponse>>(
    "/api/agent/tools",
    undefined,
    3
  );
  const mcpTools = Array.isArray(data.mcp_tools) ? data.mcp_tools : [];
  const openrouterTools = Array.isArray(data.openrouter_tools) ? data.openrouter_tools : [];
  return {
    count: typeof data.count === "number" ? data.count : mcpTools.length,
    openrouter_tools: openrouterTools,
    mcp_tools: mcpTools,
  };
}

export async function executeAgentTool(
  tool: string,
  args: Record<string, unknown> = {},
  robotId?: string | null
): Promise<AgentExecuteResult> {
  return requestVoiceJson<AgentExecuteResult>(
    "/api/agent/execute",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool,
        arguments: args,
        ...(robotId ? { robot_id: robotId } : {}),
      }),
    },
    1
  );
}

export async function getOpenClawBundle(robotId?: string | null): Promise<OpenClawBundle> {
  const qs = robotId ? `?robot_id=${encodeURIComponent(robotId)}` : "";
  const data = await requestVoiceJson<Partial<OpenClawBundle>>(
    `/api/agent/openclaw-bundle${qs}`,
    undefined,
    3
  );
  return {
    api_url: data.api_url ?? API_URL,
    robot_id: data.robot_id ?? robotId ?? null,
    robot_name: data.robot_name ?? null,
    tool_count: typeof data.tool_count === "number" ? data.tool_count : 10,
    skill_path: data.skill_path ?? "openclaw/skills/puppypi-twinscan/SKILL.md",
    mcp_config:
      data.mcp_config && typeof data.mcp_config === "object"
        ? data.mcp_config
        : {
            mcpServers: {
              "puppypi-twinscan": {
                command: ".venv/bin/python",
                args: ["-m", "src.agent.mcp_bridge"],
                env: { TWINSCAN_API_URL: API_URL || "http://localhost:8000" },
              },
            },
          },
    install_commands: Array.isArray(data.install_commands) ? data.install_commands : [],
  };
}
