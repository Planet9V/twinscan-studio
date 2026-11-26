"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  Camera,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Cpu,
  Ear,
  Edit3,
  Loader2,
  MessageSquare,
  Mic,
  MicOff,
  Plus,
  Radio,
  RefreshCw,
  Save,
  Send,
  Settings2,
  ShieldCheck,
  Sliders,
  Sparkles,
  Square,
  Stethoscope,
  Trash2,
  User,
  Volume2,
  VolumeX,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { OpenRouterModelPicker } from "@/components/admin/OpenRouterModelPicker";
import { VoicePipelineFlow } from "@/components/robot/VoicePipelineFlow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { refreshOpenRouterModels } from "@/lib/api";
import type { RobotRecord } from "@/lib/robotApi";
import type { OpenRouterModelInfo } from "@/lib/types";
import {
  clearConversationHistory,
  createVoicePersonality,
  deleteVoicePersonality,
  fetchConversationHistory,
  fetchConversationState,
  fetchVoiceCatalog,
  fetchVoiceConfig,
  fetchVoiceLogs,
  fetchVoiceStatus,
  installUdevRules,
  listenVoiceCommand,
  listVoicePersonalities,
  playRobotChime,
  runVoiceDiagnostics,
  sendVoiceChat,
  speakOnRobot,
  startHandsFreeConversation,
  stopHandsFreeConversation,
  updateVoiceConfig,
  updateVoiceMixer,
  updateVoicePersonality,
  type ConversationState,
  type ConversationTurn,
  type VoiceActorOption,
  type VoiceAssistantConfig,
  type VoiceCatalogResponse,
  type VoiceDiagnosticCheck,
  type VoiceDiagnosticsResponse,
  type VoiceEngineKey,
  type VoiceLogEntry,
  type VoicePersonality,
  type VoiceStatus,
  type WakeMode,
} from "@/lib/voiceApi";

interface VoiceControlPanelProps {
  robot: RobotRecord | null;
}

const FALLBACK_ENGINES: VoiceCatalogResponse["engines"] = [
  {
    id: "piper_tts",
    label: "Piper Neural (100% Offline)",
    description: "Local ONNX VITS neural speech synthesis — zero internet required",
    offline: true,
  },
  {
    id: "edge_tts",
    label: "Edge Neural (Studio Online)",
    description: "Microsoft Neural Studio voices (Andrew, Aria, Guy, Jenny, Sonia)",
    offline: false,
  },
  {
    id: "auto",
    label: "Auto (Studio → Offline Neural)",
    description: "Edge Neural online → Piper Neural offline → eSpeak fallback",
    offline: false,
  },
  {
    id: "espeak",
    label: "eSpeak (Legacy)",
    description: "Ultra-fast robotic formant fallback",
    offline: true,
  },
];

const FALLBACK_VOICES: VoiceActorOption[] = [
  {
    id: "en_US-lessac-medium",
    label: "Lessac · Offline US Natural",
    engine: "piper_tts",
    accent: "US",
    gender: "female",
    cached: true,
  },
  {
    id: "en_US-ryan-medium",
    label: "Ryan · Offline US Male",
    engine: "piper_tts",
    accent: "US",
    gender: "male",
    cached: false,
  },
  {
    id: "en-US-AndrewMultilingualNeural",
    label: "Andrew · US Warm Male",
    engine: "edge_tts",
    accent: "US",
    gender: "male",
  },
  {
    id: "en-US-AriaNeural",
    label: "Aria · US Expressive Female",
    engine: "edge_tts",
    accent: "US",
    gender: "female",
  },
  {
    id: "en-US-GuyNeural",
    label: "Guy · US Clear Male",
    engine: "edge_tts",
    accent: "US",
    gender: "male",
  },
  {
    id: "en-US-JennyNeural",
    label: "Jenny · US Assistant Female",
    engine: "edge_tts",
    accent: "US",
    gender: "female",
  },
  {
    id: "en-GB-SoniaNeural",
    label: "Sonia · UK Crisp Female",
    engine: "edge_tts",
    accent: "UK",
    gender: "female",
  },
  {
    id: "en-us",
    label: "en-us · Legacy eSpeak Male",
    engine: "espeak",
    accent: "US",
    gender: "male",
  },
  {
    id: "en-gb",
    label: "en-gb · Legacy eSpeak UK",
    engine: "espeak",
    accent: "UK",
    gender: "male",
  },
  {
    id: "en-us+f3",
    label: "en-us+f3 · Legacy eSpeak Female",
    engine: "espeak",
    accent: "US",
    gender: "female",
  },
];

const FALLBACK_PERSONALITIES: VoicePersonality[] = [
  {
    id: "robot_dog",
    name: "Playful Robot Dog",
    badge: "Robot Dog",
    description: "Enthusiastic, loyal quadruped companion who loves tricks, walks, and greeting people.",
    system_prompt:
      "You are OX, an enthusiastic, loyal robotic dog running ROS 2 Humble. Keep replies short, upbeat, and playful.",
    default_voice: "en_US-lessac-medium",
    allow_body_actions: true,
    is_builtin: true,
  },
  {
    id: "aloof_cat",
    name: "Aloof Robot Cat",
    badge: "Aloof Cat",
    description: "Dryly amused, slightly superior feline intellect who tolerates humans on its own terms.",
    system_prompt:
      "You are OX, a poised, mildly unimpressed robotic cat who secretly likes humans. Keep answers witty and concise.",
    default_voice: "en_US-lessac-medium",
    allow_body_actions: true,
    is_builtin: true,
  },
  {
    id: "marvin_android",
    name: "Irritable Paranoid Android (Marvin)",
    badge: "Marvin",
    description: "Brain the size of a planet, tasked with walking across the living room floor.",
    system_prompt:
      "You are OX in Marvin mode — brilliantly weary, deadpan sarcastic, perpetually exasperated yet completely helpful.",
    default_voice: "en_US-ryan-medium",
    allow_body_actions: true,
    is_builtin: true,
  },
  {
    id: "dad_joke_nerd",
    name: "Know-It-All Dad-Joke Nerd",
    badge: "Dad-Joke Nerd",
    description: "Delivers encyclopedic robotics trivia wrapped in shameless puns and dad jokes.",
    system_prompt:
      "You are OX, a cheerful trivia nerd who slips a crisp pun or dad joke into every helpful answer.",
    default_voice: "en_US-ryan-medium",
    allow_body_actions: true,
    is_builtin: true,
  },
  {
    id: "lab_engineer",
    name: "Eigenia Lab Engineer",
    badge: "Lab",
    description: "Crisp, precise cyber-physical telemetry specialist for field diagnostics and inspections.",
    system_prompt:
      "You are OX, an Eigenia B.V. robotics engineer. Deliver concise, accurate telemetry and operational guidance.",
    default_voice: "en_US-lessac-medium",
    allow_body_actions: true,
    is_builtin: true,
  },
];

const QUICK_STARTERS = [
  "Hey OX, introduce yourself",
  "What do you see in front of you?",
  "Tell me a joke and do a trick",
  "How's your battery?",
] as const;

const QUICK_PHRASES = [
  "Hello! I am OX, online and ready.",
  "Autonomous patrol started. Scanning perimeter.",
  "Obstacle detected ahead. Rerouting safely.",
  "All Eigenia TwinScan systems are nominal.",
] as const;

const CHIMES: { id: "dong" | "wakeup" | "success" | "alert"; label: string }[] = [
  { id: "dong", label: "Dong" },
  { id: "wakeup", label: "Wakeup" },
  { id: "success", label: "Success" },
  { id: "alert", label: "Alert" },
];

function formatKb(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function getEngineShortLabel(engine?: string | null): string {
  switch (engine) {
    case "piper_tts":
      return "Piper Offline";
    case "edge_tts":
      return "Edge Studio";
    case "auto":
      return "Auto Neural";
    case "espeak":
      return "eSpeak";
    default:
      return "Piper Offline";
  }
}

function getConversationStatePill(convState: ConversationState | null, wakeWord: string) {
  const s = String(convState?.state ?? "idle").toLowerCase();
  const wakeUpper = (wakeWord || "Hey OX").toUpperCase();
  if (!convState?.active || s === "idle") {
    return {
      label: "HANDS-FREE OFF",
      variant: "neutral" as const,
      extraClass: "",
      pulse: false,
    };
  }
  if (s === "listening_wake") {
    return {
      label: `STANDBY · SAY "${wakeUpper}"`,
      variant: "sky" as const,
      extraClass: "border-eigenia-sky/50 bg-eigenia-sky/15 text-eigenia-sky",
      pulse: true,
    };
  }
  if (s === "in_conversation") {
    return {
      label: "IN CONVERSATION",
      variant: "default" as const,
      extraClass: "border-emerald-500/50 bg-emerald-500/20 text-emerald-400",
      pulse: true,
    };
  }
  if (s === "followup_window") {
    const rem =
      typeof convState.followup_remaining_sec === "number"
        ? ` (${Math.ceil(convState.followup_remaining_sec)}s)`
        : "";
    return {
      label: `FOLLOW-UP WINDOW${rem}`,
      variant: "amber" as const,
      extraClass: "",
      pulse: true,
    };
  }
  if (s === "thinking") {
    return {
      label: "THINKING",
      variant: "default" as const,
      extraClass: "",
      pulse: true,
    };
  }
  if (s === "speaking") {
    return {
      label: "SPEAKING",
      variant: "sky" as const,
      extraClass: "border-eigenia-orange/60 bg-eigenia-orange/20 text-eigenia-orange",
      pulse: true,
    };
  }
  return {
    label: s.toUpperCase(),
    variant: "sky" as const,
    extraClass: "",
    pulse: true,
  };
}

export function VoiceControlPanel({ robot }: VoiceControlPanelProps) {
  const robotId = robot?.id ?? null;

  // Hardware status, catalog, config, personalities, conversation & logs
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [catalog, setCatalog] = useState<VoiceCatalogResponse | null>(null);
  const [config, setConfig] = useState<VoiceAssistantConfig | null>(null);
  const [personalities, setPersonalities] = useState<VoicePersonality[]>(FALLBACK_PERSONALITIES);
  const [convState, setConvState] = useState<ConversationState | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [logs, setLogs] = useState<VoiceLogEntry[]>([]);
  const [loading, setLoading] = useState(false);

  // OpenRouter LLM model catalog for Settings tab
  const [openRouterModels, setOpenRouterModels] = useState<OpenRouterModelInfo[]>([]);
  const [llmCatalogLoading, setLlmCatalogLoading] = useState(false);

  // Tab 1: Conversation composer state
  const [chatInput, setChatInput] = useState("");
  const [chatSpeakReply, setChatSpeakReply] = useState(true);
  const [chatCameraMode, setChatCameraMode] = useState<"auto" | "always" | "never">("auto");
  const [chatBodyActions, setChatBodyActions] = useState(true);
  const [sendingChat, setSendingChat] = useState(false);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const lastConvReplyRef = useRef<string | null>(null);

  // Tab 2: Custom Personality form state
  const [editingPersonalityId, setEditingPersonalityId] = useState<string | null>(null);
  const [pName, setPName] = useState("");
  const [pBadge, setPBadge] = useState("");
  const [pDesc, setPDesc] = useState("");
  const [pPrompt, setPPrompt] = useState("");
  const [pVoice, setPVoice] = useState("en_US-lessac-medium");
  const [pAllowActions, setPAllowActions] = useState(true);

  // Tab 3: Wake Word & Assistant Settings form state
  const [cfgAssistantName, setCfgAssistantName] = useState("OX");
  const [cfgWakeWord, setCfgWakeWord] = useState("Hey OX");
  const [cfgWakeAliases, setCfgWakeAliases] = useState("hey ox, hey aux, hey o x, hey box, hey fox");
  const [cfgWakeMode, setCfgWakeMode] = useState<WakeMode>("custom_software");
  const [cfgFollowupSec, setCfgFollowupSec] = useState(12);
  const [cfgEngine, setCfgEngine] = useState<VoiceEngineKey>("piper_tts");
  const [cfgVoice, setCfgVoice] = useState("en_US-lessac-medium");
  const [cfgAntiClip, setCfgAntiClip] = useState(true);
  const [cfgLlmModel, setCfgLlmModel] = useState("google/gemini-2.5-flash");
  const [cfgAttachCam, setCfgAttachCam] = useState(true);
  const [cfgAllowActions, setCfgAllowActions] = useState(true);

  // Tab 4: Audio Mixer & Direct TTS state (default Piper Offline)
  const [speakerVol, setSpeakerVol] = useState(80);
  const [speakerMuted, setSpeakerMuted] = useState(false);
  const [micGain, setMicGain] = useState(75);
  const [micMuted, setMicMuted] = useState(false);
  const [ttsText, setTtsText] = useState("Hello! This is OX speaking via offline Piper neural voice.");
  const [ttsEngine, setTtsEngine] = useState<VoiceEngineKey>("piper_tts");
  const [ttsVoice, setTtsVoice] = useState("en_US-lessac-medium");
  const [ttsSpeed, setTtsSpeed] = useState(155);
  const [antiClipEq, setAntiClipEq] = useState(true);
  const [lastSpokenMeta, setLastSpokenMeta] = useState<{
    engine: string;
    voiceLabel: string;
    bytes: number;
    antiClip: boolean;
  } | null>(null);

  const [activeTab, setActiveTab] = useState<"live" | "personas" | "diagnostics">("live");
  const [personalityDrawerOpen, setPersonalityDrawerOpen] = useState(false);
  const [copiedTurnId, setCopiedTurnId] = useState<string | null>(null);
  const [diagResult, setDiagResult] = useState<VoiceDiagnosticsResponse | null>(null);
  const [diagTestSpeaker, setDiagTestSpeaker] = useState(false);
  const [diagListeningSec, setDiagListeningSec] = useState<number | null>(null);
  const [diagUsbExpanded, setDiagUsbExpanded] = useState(false);

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const normalizeVoiceTab = useCallback((raw: string | null): "live" | "personas" | "diagnostics" => {
    if (raw === "personas" || raw === "personalities" || raw === "settings" || raw === "mixer") {
      return "personas";
    }
    if (raw === "diagnostics" || raw === "pipeline" || raw === "audio") {
      return "diagnostics";
    }
    return "live";
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab");
    if (tabParam) {
      setActiveTab(normalizeVoiceTab(tabParam));
    }
  }, [normalizeVoiceTab]);

  const handleVoiceTabChange = useCallback(
    (next: string) => {
      const valid = normalizeVoiceTab(next);
      setActiveTab(valid);
      if (typeof window !== "undefined" && window.location.pathname === "/voice") {
        const url = new URL(window.location.href);
        url.searchParams.set("tab", valid);
        window.history.replaceState({}, "", url.toString());
      }
    },
    [normalizeVoiceTab]
  );

  const handleCopyTurn = (turn: ConversationTurn) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(turn.content).catch(() => {});
    }
    setCopiedTurnId(turn.id);
    window.setTimeout(() => setCopiedTurnId((prev) => (prev === turn.id ? null : prev)), 1500);
  };

  const hydrateConfigForm = useCallback((cfg: VoiceAssistantConfig) => {
    setConfig(cfg);
    setCfgAssistantName(cfg.assistant_name || "OX");
    setCfgWakeWord(cfg.wake_word || "Hey OX");
    setCfgWakeAliases(
      Array.isArray(cfg.wake_aliases) && cfg.wake_aliases.length > 0
        ? cfg.wake_aliases.join(", ")
        : "hey ox, hey aux, hey o x, hey box, hey fox"
    );
    setCfgWakeMode(cfg.wake_mode || "custom_software");
    setCfgFollowupSec(typeof cfg.followup_window_sec === "number" ? cfg.followup_window_sec : 12);
    setCfgEngine(cfg.default_engine || "piper_tts");
    setCfgVoice(cfg.default_voice || "en_US-lessac-medium");
    setCfgAntiClip(cfg.anti_clip ?? true);
    setCfgLlmModel(cfg.llm_model || "google/gemini-2.5-flash");
    setCfgAttachCam(cfg.attach_camera_on_visual ?? true);
    setCfgAllowActions(cfg.allow_body_actions ?? true);
    setChatBodyActions(cfg.allow_body_actions ?? true);
  }, []);

  const loadOpenRouterCatalog = useCallback(async (forceRefresh = false) => {
    setLlmCatalogLoading(true);
    try {
      const resp = await refreshOpenRouterModels(forceRefresh);
      if (Array.isArray(resp?.models)) setOpenRouterModels(resp.models);
    } catch {
      // Non-fatal
    } finally {
      setLlmCatalogLoading(false);
    }
  }, []);

  const refreshAll = useCallback(
    async (id: string) => {
      setLoading(true);
      try {
        const [st, cat, cfg, pList, cState, hist, lg] = await Promise.all([
          fetchVoiceStatus(id).catch(() => null),
          fetchVoiceCatalog(id).catch(() => null),
          fetchVoiceConfig(id).catch(() => null),
          listVoicePersonalities().catch(() => null),
          fetchConversationState(id).catch(() => null),
          fetchConversationHistory(id, 40).catch(() => null),
          fetchVoiceLogs(id, 30).catch(() => null),
        ]);
        if (st) {
          setStatus(st);
          setSpeakerVol(st.speaker_volume_pct ?? 80);
          setSpeakerMuted(Boolean(st.speaker_muted));
          setMicGain(st.mic_gain_pct ?? 75);
          setMicMuted(Boolean(st.mic_muted));
        }
        if (cat) setCatalog(cat);
        if (cfg) hydrateConfigForm(cfg);
        if (pList && Array.isArray(pList.personalities) && pList.personalities.length > 0) {
          setPersonalities(pList.personalities);
        }
        if (cState) {
          setConvState(cState);
          lastConvReplyRef.current = cState.last_reply ?? null;
        }
        if (hist && Array.isArray(hist.turns)) setTurns(hist.turns);
        if (lg && Array.isArray(lg.entries)) setLogs(lg.entries);
      } catch (err) {
        setBanner({
          kind: "error",
          text: err instanceof Error ? err.message : "Failed to load Voice Studio telemetry",
        });
      } finally {
        setLoading(false);
      }
    },
    [hydrateConfigForm]
  );

  useEffect(() => {
    void loadOpenRouterCatalog(false);
  }, [loadOpenRouterCatalog]);

  useEffect(() => {
    if (!robotId) {
      setStatus(null);
      setCatalog(null);
      setConfig(null);
      setConvState(null);
      setTurns([]);
      setLogs([]);
      setDiagResult(null);
      return;
    }
    setDiagResult(null);
    void refreshAll(robotId);
  }, [robotId, refreshAll]);

  // Poll hands-free conversation state while active
  useEffect(() => {
    if (!robotId || !convState?.active) return;
    let cancelled = false;
    const timer = setInterval(() => {
      fetchConversationState(robotId)
        .then((next) => {
          if (cancelled) return;
          setConvState(next);
          if (next.last_reply && next.last_reply !== lastConvReplyRef.current) {
            lastConvReplyRef.current = next.last_reply;
            void fetchConversationHistory(robotId, 40).then((h) => {
              if (!cancelled && Array.isArray(h.turns)) setTurns(h.turns);
            });
          }
        })
        .catch(() => {});
    }, 1200);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [robotId, convState?.active]);

  // Scroll conversation thread smoothly to latest message
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [turns.length]);

  const engines = useMemo(
    () =>
      Array.isArray(catalog?.engines) && catalog.engines.length > 0
        ? catalog.engines
        : FALLBACK_ENGINES,
    [catalog]
  );

  const allVoices = useMemo(() => {
    const raw =
      Array.isArray(catalog?.voices) && catalog.voices.length > 0
        ? catalog.voices
        : FALLBACK_VOICES;
    const cachedSet = new Set(
      Array.isArray(catalog?.cached_piper_voices) ? catalog.cached_piper_voices : []
    );
    return raw.map((v) => ({
      ...v,
      cached: v.cached || (v.engine === "piper_tts" && cachedSet.has(v.id)),
    }));
  }, [catalog]);

  const filterVoicesForEngine = useCallback(
    (eng: VoiceEngineKey) => {
      if (eng === "auto") {
        return allVoices.filter((v) => v.engine === "piper_tts" || v.engine === "edge_tts");
      }
      return allVoices.filter((v) => v.engine === eng);
    },
    [allVoices]
  );

  const cfgVoices = useMemo(() => filterVoicesForEngine(cfgEngine), [filterVoicesForEngine, cfgEngine]);
  const ttsVoices = useMemo(() => filterVoicesForEngine(ttsEngine), [filterVoicesForEngine, ttsEngine]);

  useEffect(() => {
    if (cfgVoices.length > 0 && !cfgVoices.some((v) => v.id === cfgVoice)) {
      setCfgVoice(cfgVoices[0].id);
    }
  }, [cfgVoices, cfgVoice]);

  useEffect(() => {
    if (ttsVoices.length > 0 && !ttsVoices.some((v) => v.id === ttsVoice)) {
      setTtsVoice(ttsVoices[0].id);
    }
  }, [ttsVoices, ttsVoice]);

  const activePersonality = useMemo(() => {
    const pid = config?.personality_id ?? convState?.personality_id ?? "robot_dog";
    return personalities.find((p) => p.id === pid) ?? personalities[0] ?? FALLBACK_PERSONALITIES[0];
  }, [personalities, config?.personality_id, convState?.personality_id]);

  if (!robot || !robotId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <Bot className="h-10 w-10 text-eigenia-orange/60" />
          <div className="text-sm font-semibold text-white">No Robot Selected for Voice Studio</div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a PuppyPi robot to launch hands-free &quot;Hey OX&quot; conversations, personality presets, neural TTS, and WonderEcho Pro mixer controls.
          </p>
        </CardContent>
      </Card>
    );
  }

  const runAction = async (key: string, fn: () => Promise<void>) => {
    setBusyAction(key);
    setBanner(null);
    try {
      await fn();
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : `Action "${key}" failed`,
      });
    } finally {
      setBusyAction(null);
    }
  };

  // Hands-Free toggle
  const handleToggleHandsFree = () =>
    runAction("hands-free", async () => {
      if (convState?.active) {
        const next = await stopHandsFreeConversation(robotId);
        setConvState(next);
        setBanner({ kind: "ok", text: `Hands-free "${cfgWakeWord}" listener stopped.` });
      } else {
        const next = await startHandsFreeConversation(robotId);
        setConvState(next);
        setBanner({
          kind: "ok",
          text: `Hands-free "${next.wake_word || cfgWakeWord}" active — say "${next.wake_word || cfgWakeWord}" anytime!`,
        });
      }
    });

  // Conversation chat submit
  const handleSendChat = async (messageOverride?: string) => {
    const msg = (messageOverride ?? chatInput).trim();
    if (!msg || sendingChat) return;
    setSendingChat(true);
    setBanner(null);
    if (!messageOverride) setChatInput("");
    try {
      const res = await sendVoiceChat(robotId, {
        message: msg,
        speak_reply: chatSpeakReply,
        attach_camera: chatCameraMode,
        execute_actions: chatBodyActions,
      });
      setTurns((prev) => [...prev, res.user_turn, res.assistant_turn]);
      if (res.spoken && res.engine_used) {
        setLastSpokenMeta({
          engine: res.engine_used,
          voiceLabel: res.voice_used || cfgVoice,
          bytes: 0,
          antiClip: cfgAntiClip,
        });
      }
      void fetchVoiceLogs(robotId, 30).then((lg) => setLogs(lg.entries)).catch(() => {});
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Conversation request failed",
      });
    } finally {
      setSendingChat(false);
    }
  };

  // Push-to-Talk mic capture
  const handlePushToTalk = () =>
    runAction("ptt", async () => {
      const res = await listenVoiceCommand(robotId, {
        duration_sec: 4,
        execute_commands: chatBodyActions,
        speak_reply: chatSpeakReply,
      });
      setBanner({
        kind: res.ok ? "ok" : "error",
        text: `Heard "${res.transcript || "(silence)"}" → ${res.action_taken || "chat"} · "${res.reply_text}"`,
      });
      const [hist, lg] = await Promise.all([
        fetchConversationHistory(robotId, 40).catch(() => null),
        fetchVoiceLogs(robotId, 30).catch(() => null),
      ]);
      if (hist) setTurns(hist.turns);
      if (lg) setLogs(lg.entries);
    });

  // Clear conversation memory
  const handleClearMemory = () =>
    runAction("clear-mem", async () => {
      const res = await clearConversationHistory(robotId);
      setTurns([]);
      setBanner({ kind: "ok", text: `Cleared ${res.cleared} conversation turn(s) from memory.` });
    });

  // Select Personality
  const handleSelectPersonality = (p: VoicePersonality) =>
    runAction(`use-p-${p.id}`, async () => {
      const updated = await updateVoiceConfig(robotId, {
        personality_id: p.id,
        default_voice: p.default_voice || cfgVoice,
        allow_body_actions: p.allow_body_actions,
      });
      hydrateConfigForm(updated);
      setBanner({ kind: "ok", text: `Active personality switched to "${p.name}".` });
    });

  // Create / Update Custom Personality
  const resetPersonalityForm = () => {
    setEditingPersonalityId(null);
    setPName("");
    setPBadge("");
    setPDesc("");
    setPPrompt("");
    setPVoice("en_US-lessac-medium");
    setPAllowActions(true);
  };

  const handleSavePersonality = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pName.trim() || !pPrompt.trim()) return;
    void runAction("save-personality", async () => {
      if (editingPersonalityId) {
        await updateVoicePersonality(editingPersonalityId, {
          name: pName.trim(),
          badge: pBadge.trim() || "Custom",
          description: pDesc.trim(),
          system_prompt: pPrompt.trim(),
          default_voice: pVoice,
          allow_body_actions: pAllowActions,
        });
        setBanner({ kind: "ok", text: `Updated custom personality "${pName.trim()}".` });
      } else {
        await createVoicePersonality({
          name: pName.trim(),
          badge: pBadge.trim() || "Custom",
          description: pDesc.trim(),
          system_prompt: pPrompt.trim(),
          default_voice: pVoice,
          allow_body_actions: pAllowActions,
        });
        setBanner({ kind: "ok", text: `Created custom personality "${pName.trim()}".` });
      }
      resetPersonalityForm();
      const refreshed = await listVoicePersonalities();
      if (refreshed.personalities.length > 0) setPersonalities(refreshed.personalities);
    });
  };

  const handleDeletePersonality = (p: VoicePersonality) =>
    runAction(`del-p-${p.id}`, async () => {
      await deleteVoicePersonality(p.id);
      const refreshed = await listVoicePersonalities();
      if (refreshed.personalities.length > 0) setPersonalities(refreshed.personalities);
      setBanner({ kind: "ok", text: `Deleted custom personality "${p.name}".` });
    });

  // Save Wake Word & Assistant Settings
  const handleSaveAssistantSettings = (e: React.FormEvent) => {
    e.preventDefault();
    void runAction("save-config", async () => {
      const aliases = cfgWakeAliases
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      const updated = await updateVoiceConfig(robotId, {
        assistant_name: cfgAssistantName.trim() || "OX",
        wake_word: cfgWakeWord.trim() || "Hey OX",
        wake_aliases: aliases,
        wake_mode: cfgWakeMode,
        followup_window_sec: cfgFollowupSec,
        default_engine: cfgEngine,
        default_voice: cfgVoice,
        anti_clip: cfgAntiClip,
        llm_model: cfgLlmModel,
        attach_camera_on_visual: cfgAttachCam,
        allow_body_actions: cfgAllowActions,
      });
      hydrateConfigForm(updated);
      setBanner({
        kind: "ok",
        text: `Saved assistant settings — Wake: "${updated.wake_word}" · Speech: ${getEngineShortLabel(
          updated.default_engine
        )} · LLM: ${updated.llm_model}.`,
      });
    });
  };

  // Mixer & Direct TTS handlers
  const handleMixerUpdate = (patch: {
    speaker_volume_pct?: number;
    mic_gain_pct?: number;
    speaker_mute?: boolean;
    mic_mute?: boolean;
  }) =>
    runAction("mixer", async () => {
      const updated = await updateVoiceMixer(robotId, patch);
      setStatus(updated);
      setSpeakerVol(updated.speaker_volume_pct ?? speakerVol);
      setSpeakerMuted(Boolean(updated.speaker_muted));
      setMicGain(updated.mic_gain_pct ?? micGain);
      setMicMuted(Boolean(updated.mic_muted));
      setBanner({ kind: "ok", text: "Updated WonderEcho Pro ALSA mixer levels." });
    });

  const handleSpeakDirect = (textOverride?: string) => {
    const text = (textOverride ?? ttsText).trim();
    if (!text) return;
    void runAction("speak", async () => {
      const res = await speakOnRobot(robotId, {
        text,
        engine: ttsEngine,
        voice: ttsVoice || undefined,
        speed: ttsSpeed,
        anti_clip: antiClipEq,
      });
      const resolvedVoice =
        allVoices.find((v) => v.id === (res.voice || ttsVoice))?.label ??
        res.voice ??
        ttsVoice;
      const shortVoice = resolvedVoice.split("·")[0]?.trim() || resolvedVoice;
      setLastSpokenMeta({
        engine: res.engine,
        voiceLabel: shortVoice,
        bytes: res.bytes_sent,
        antiClip: res.anti_clip ?? antiClipEq,
      });
      setBanner({
        kind: "ok",
        text: `Spoke via ${res.engine} · ${shortVoice} · ${formatKb(res.bytes_sent)}`,
      });
      const [lg, cat] = await Promise.all([
        fetchVoiceLogs(robotId, 30),
        fetchVoiceCatalog(robotId).catch(() => null),
      ]);
      setLogs(lg.entries);
      if (cat) setCatalog(cat);
    });
  };

  const handleChime = (chime: "dong" | "wakeup" | "success" | "alert") =>
    runAction(`chime-${chime}`, async () => {
      await playRobotChime(robotId, chime);
      setBanner({ kind: "ok", text: `Played "${chime}" chime on WonderEcho Pro speaker.` });
    });

  const handleInstallUdev = () =>
    runAction("udev", async () => {
      const res = await installUdevRules(robotId);
      setBanner({
        kind: res.ok ? "ok" : "error",
        text: `${res.detail} (wonderecho=${res.wonderecho_present ? "OK" : "absent"}, ldlidar=${res.ldlidar_present ? "OK" : "absent"})`,
      });
      await refreshAll(robotId);
    });

  const handleRunDiagnostics = (recordLiveSec: number) =>
    runAction(recordLiveSec > 0 ? "diag-live" : "diag-quick", async () => {
      setDiagListeningSec(recordLiveSec > 0 ? recordLiveSec : null);
      try {
        const res = await runVoiceDiagnostics(robotId, {
          record_live_sec: recordLiveSec,
          test_speaker: diagTestSpeaker,
        });
        setDiagResult(res);
        if (res.dmesg_usb_warnings.length > 0) {
          setDiagUsbExpanded(true);
        }
        setBanner({
          kind: res.ok ? "ok" : "error",
          text: `Voice diagnostics complete: ${res.passed_count}/${res.total_count} checks passed${
            res.card_index != null ? ` (USB Audio Card ${res.card_index})` : " (no USB audio card)"
          }.`,
        });
        // Refresh status & conversation state so USB alert banner reflects latest probe
        const [st, cState] = await Promise.all([
          fetchVoiceStatus(robotId).catch(() => null),
          fetchConversationState(robotId).catch(() => null),
        ]);
        if (st) setStatus(st);
        if (cState) setConvState(cState);
      } finally {
        setDiagListeningSec(null);
      }
    });

  const handleAddSuggestedAlias = (alias: string) => {
    const normalized = alias.trim().toLowerCase();
    if (!normalized) return;
    void runAction("add-alias", async () => {
      const existing = Array.isArray(config?.wake_aliases)
        ? config.wake_aliases.map((a) => a.trim().toLowerCase()).filter(Boolean)
        : cfgWakeAliases
            .split(",")
            .map((a) => a.trim().toLowerCase())
            .filter(Boolean);
      const nextAliases = Array.from(new Set([...existing, normalized]));
      const updated = await updateVoiceConfig(robotId, { wake_aliases: nextAliases });
      hydrateConfigForm(updated);
      setBanner({
        kind: "ok",
        text: `Added "${normalized}" to wake aliases for "${updated.wake_word}".`,
      });
    });
  };

  const statePill = getConversationStatePill(convState, cfgWakeWord);
  const selectedCfgVoiceObj = allVoices.find((v) => v.id === cfgVoice) ?? null;
  const selectedTtsVoiceObj = allVoices.find((v) => v.id === ttsVoice) ?? null;
  const liveMicRms = typeof convState?.mic_rms === "number" ? convState.mic_rms : null;
  const liveNoiseFloor =
    typeof convState?.noise_floor === "number" ? convState.noise_floor : null;
  const micBarPct =
    liveMicRms !== null ? Math.max(4, Math.min(100, Math.round((liveMicRms / 450) * 100))) : 0;
  const micHot =
    liveMicRms !== null &&
    liveMicRms >= Math.max(22, (liveNoiseFloor ?? 12) * 1.65);

  const usbAudioDisconnected = Boolean(status && !status.audio_card_detected);
  const convErrorText = convState?.error ? String(convState.error) : null;
  const showUsbAlertBanner = usbAudioDisconnected || Boolean(convErrorText);

  const normalizedAliasesSet = new Set(
    (Array.isArray(config?.wake_aliases) && config.wake_aliases.length > 0
      ? config.wake_aliases
      : cfgWakeAliases.split(",")
    )
      .map((a) => a.trim().toLowerCase())
      .filter(Boolean)
  );
  const suggestedAlias = diagResult?.live_mic_test?.suggested_alias?.trim() || null;
  const canAddSuggestedAlias = Boolean(
    suggestedAlias && !normalizedAliasesSet.has(suggestedAlias.toLowerCase())
  );

  const renderCheckBadge = (checkStatus: VoiceDiagnosticCheck["status"]) => {
    switch (checkStatus) {
      case "pass":
        return (
          <Badge
            variant="sky"
            className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[9px] text-emerald-400"
          >
            <CheckCircle2 className="h-3 w-3" />
            PASS
          </Badge>
        );
      case "warn":
        return (
          <Badge variant="amber" className="font-mono text-[9px]">
            <AlertTriangle className="h-3 w-3" />
            WARN
          </Badge>
        );
      case "fail":
        return (
          <Badge variant="fault" className="font-mono text-[9px]">
            <XCircle className="h-3 w-3" />
            FAIL
          </Badge>
        );
      default:
        return (
          <Badge variant="neutral" className="font-mono text-[9px]">
            SKIPPED
          </Badge>
        );
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 0. PROMINENT RED USB DISCONNECT / VOICE ERROR ALERT BANNER */}
      {showUsbAlertBanner && (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-lg border-2 border-eigenia-fault/70 bg-eigenia-fault/15 p-4 text-white shadow-sm shadow-eigenia-fault/20 lg:flex-row lg:items-center lg:justify-between"
        >
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-eigenia-fault/60 bg-eigenia-fault/25 text-eigenia-fault">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-eigenia-fault">
                  {usbAudioDisconnected
                    ? "WonderEcho Pro USB Audio Disconnected"
                    : "Hands-Free Voice Pipeline Error"}
                </span>
                <Badge variant="fault" className="font-mono text-[9px]">
                  {usbAudioDisconnected ? "NO USB AUDIO CARD" : "PIPELINE FAULT"}
                </Badge>
              </div>
              {usbAudioDisconnected && (
                <p className="text-xs leading-relaxed text-eigenia-ink">
                  No USB audio capture/playback device is enumerated on PuppyPi. Unplug and firmly
                  re-seat both ends of the WonderEcho Pro USB cable into the{" "}
                  <span className="font-semibold text-white">lower black USB 2.0 port</span> on the
                  Raspberry Pi 5, then click{" "}
                  <span className="font-mono text-white">Re-Check USB</span>.
                </p>
              )}
              {convErrorText && (
                <div className="rounded border border-eigenia-fault/40 bg-eigenia-obsidian/80 px-2.5 py-1.5 font-mono text-[11px] text-eigenia-fault">
                  {convErrorText}
                </div>
              )}
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={loading}
              onClick={() => void refreshAll(robotId)}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Re-Check USB
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => handleVoiceTabChange("diagnostics")}
            >
              <Stethoscope className="h-3.5 w-3.5" />
              Open Diagnostics
            </Button>
          </div>
        </div>
      )}

      {/* 1. COMPACT WORKSPACE HEADER */}
      <WorkspaceHeader
        badge="WONDERECHO PRO · NEURAL VOICE"
        title={`${cfgAssistantName} Conversational Voice & Personality Studio`}
        subtitle={
          status?.audio_card_detected
            ? `USB Audio Card ${status.card_index ?? 2}${status.serial_symlink_present ? " · /dev/wonderecho" : ""} · Faster-Whisper Offline STT + ${getEngineShortLabel(cfgEngine)}`
            : "WonderEcho Pro USB audio awaiting detection · Run 6-Step Diagnostics to inspect pipeline"
        }
        statusTone={
          showUsbAlertBanner
            ? "fault"
            : convState?.active
              ? "ok"
              : status?.audio_card_detected
                ? "ok"
                : "idle"
        }
        statusLabel={statePill.label}
        metrics={[
          {
            label: "Mic RMS",
            value: liveMicRms !== null ? Math.round(liveMicRms) : "--",
            progressPct: convState?.active ? micBarPct : 0,
            tone: micHot ? "emerald" : "sky",
            pulse: micHot,
            hint: liveNoiseFloor !== null ? `Floor ${Math.round(liveNoiseFloor)}` : "Standby",
          },
          {
            label: "Wake Word",
            value: cfgWakeWord,
            tone: "orange",
          },
          {
            label: "Personality",
            value: activePersonality.badge || activePersonality.name,
            tone: "amber",
          },
          {
            label: "TTS Engine",
            value: getEngineShortLabel(cfgEngine),
            tone: "sky",
          },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={convState?.active ? "destructive" : "default"}
              disabled={busyAction !== null}
              onClick={() => void handleToggleHandsFree()}
              className="font-semibold"
            >
              {busyAction === "hands-free" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : convState?.active ? (
                <Square className="h-3.5 w-3.5" />
              ) : (
                <Mic className="h-3.5 w-3.5" />
              )}
              {convState?.active
                ? "Stop Hands-Free"
                : `Start Hands-Free ("${cfgWakeWord}")`}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={busyAction !== null}
              onClick={() => {
                handleVoiceTabChange("diagnostics");
                void handleRunDiagnostics(0);
              }}
            >
              {busyAction === "diag-quick" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Stethoscope className="h-3.5 w-3.5" />
              )}
              Run 6-Step Diagnostics
            </Button>
            <Button
              size="icon"
              variant="secondary"
              disabled={loading}
              onClick={() => void refreshAll(robotId)}
              title="Refresh Voice Studio"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        }
      />

      {banner && (
        <div
          className={`flex items-center justify-between rounded-md border px-3 py-2 font-mono text-xs ${
            banner.kind === "ok"
              ? "border-eigenia-sky/40 bg-eigenia-sky/10 text-eigenia-sky"
              : "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault"
          }`}
        >
          <span>{banner.text}</span>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="ml-2 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 2. 3-TAB URL-SYNCED VOICE COCKPIT */}
      <SegmentedTabs
        value={activeTab}
        onValueChange={handleVoiceTabChange}
        tabs={[
          {
            id: "live",
            label: "Live Conversation",
            icon: <MessageSquare className="h-3.5 w-3.5" />,
            count: turns.length,
            alertTone: convState?.active ? "ok" : null,
          },
          {
            id: "personas",
            label: "Voice & Personalities",
            icon: <Sparkles className="h-3.5 w-3.5" />,
            count: personalities.length,
          },
          {
            id: "diagnostics",
            label: "Diagnostics & Audio Flow",
            icon: <Stethoscope className="h-3.5 w-3.5" />,
            alertTone: showUsbAlertBanner
              ? "fault"
              : diagResult
                ? diagResult.ok
                  ? "ok"
                  : "warning"
                : null,
          },
        ]}
      />

      {/* TAB 1: LIVE CONVERSATION */}
      {activeTab === "live" && (
        <div className="space-y-4">
          {convState?.active && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-eigenia-sky/35 bg-eigenia-obsidian/90 px-3.5 py-2.5">
              <div className="flex flex-wrap items-center gap-2.5">
                <Badge
                  variant={micHot ? "default" : "sky"}
                  className={
                    micHot
                      ? "border-emerald-500/50 bg-emerald-500/20 font-mono text-[10px] tabular-nums text-emerald-400"
                      : "font-mono text-[10px] tabular-nums"
                  }
                >
                  <Mic className="h-3 w-3" />
                  Mic Level: {liveMicRms !== null ? `RMS ${Math.round(liveMicRms)}` : "RMS --"}
                  {liveNoiseFloor !== null ? ` (floor ${Math.round(liveNoiseFloor)})` : ""}
                </Badge>
                <div className="h-2 w-32 overflow-hidden rounded-full bg-white/10">
                  <div
                    className={`h-full transition-all duration-150 motion-reduce:transition-none ${
                      micHot ? "bg-emerald-400" : "bg-eigenia-sky"
                    }`}
                    style={{ width: `${micBarPct}%` }}
                  />
                </div>
              </div>
              <div className="min-w-0 flex-1 text-right font-mono text-[11px] text-eigenia-ink">
                <span className="text-eigenia-muted">Heard: </span>
                <span className="text-white">
                  {convState.last_heard ? `"${convState.last_heard}"` : `Listening for "${cfgWakeWord}"...`}
                </span>
              </div>
            </div>
          )}

          <Card className="flex flex-col">
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <MessageSquare className="h-3.5 w-3.5 text-eigenia-orange" />
                  You ↔ {cfgAssistantName} Live Thread
                </CardTitle>
                <p className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
                  Personality: <span className="text-white">{activePersonality.name}</span> · Model:{" "}
                  <span className="text-eigenia-sky">{cfgLlmModel}</span>
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busyAction !== null || turns.length === 0}
                onClick={() => void handleClearMemory()}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear Memory
              </Button>
            </CardHeader>

            <CardContent className="flex flex-col gap-3">
              {/* Scrolling Chat Thread */}
              <div
                ref={chatScrollRef}
                className="flex h-[390px] flex-col gap-3 overflow-y-auto rounded-lg border border-white/10 bg-eigenia-obsidian p-4"
              >
                {turns.length === 0 ? (
                  <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full border border-eigenia-orange/40 bg-eigenia-orange/15">
                      <Bot className="h-6 w-6 text-eigenia-orange" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-semibold text-white">
                        Say &quot;{cfgWakeWord}&quot; or start chatting with {cfgAssistantName}
                      </div>
                      <p className="max-w-md text-xs text-eigenia-muted">
                        Multi-turn memory, live PuppyPi camera awareness, ROS 2 body actions, and instant offline Piper neural speech.
                      </p>
                    </div>
                    <div className="flex max-w-xl flex-wrap justify-center gap-2">
                      {QUICK_STARTERS.map((starter) => (
                        <Button
                          key={starter}
                          size="sm"
                          variant="secondary"
                          disabled={sendingChat}
                          className="h-auto px-3 py-1.5 text-xs"
                          onClick={() => void handleSendChat(starter)}
                        >
                          &quot;{starter}&quot;
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : (
                  turns.map((turn) => {
                    const isUser = turn.role === "user";
                    const pMeta = personalities.find((p) => p.id === turn.personality_id);
                    const hasRgb =
                      Array.isArray(turn.rgb_applied) && turn.rgb_applied.length >= 3;
                    return (
                      <div
                        key={turn.id}
                        className={`group flex ${isUser ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[84%] space-y-1.5 rounded-xl border px-3.5 py-2.5 transition-colors ${
                            isUser
                              ? "border-eigenia-orange/45 bg-eigenia-orange/15 text-white hover:border-eigenia-orange/70"
                              : "border-white/10 bg-eigenia-surface text-eigenia-ink hover:border-eigenia-sky/35"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[10px]">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="inline-flex items-center gap-1 font-semibold text-white">
                                {isUser ? (
                                  <>
                                    <User className="h-3 w-3 text-eigenia-orange" /> You
                                  </>
                                ) : (
                                  <>
                                    <Bot className="h-3 w-3 text-eigenia-sky" /> {cfgAssistantName}
                                  </>
                                )}
                              </span>
                              {!isUser && pMeta && (
                                <Badge variant="amber" className="px-1.5 py-0 text-[8px]">
                                  {pMeta.badge || pMeta.name}
                                </Badge>
                              )}
                              {turn.camera_attached && (
                                <Badge variant="sky" className="px-1.5 py-0 text-[8px]">
                                  <Camera className="h-2.5 w-2.5" /> Vision Attached
                                </Badge>
                              )}
                              {turn.action_taken && turn.action_taken !== "none" && (
                                <Badge variant="default" className="px-1.5 py-0 text-[8px]">
                                  {turn.action_taken}
                                </Badge>
                              )}
                              {hasRgb && (
                                <Badge variant="neutral" className="px-1.5 py-0 text-[8px]">
                                  RGB({turn.rgb_applied![0]},{turn.rgb_applied![1]},{turn.rgb_applied![2]})
                                </Badge>
                              )}
                              {turn.engine_used && (
                                <Badge
                                  variant="sky"
                                  className="border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0 text-[8px] text-emerald-400"
                                >
                                  {turn.engine_used}
                                </Badge>
                              )}
                              {typeof turn.latency_ms === "number" && turn.latency_ms > 0 && (
                                <span className="tabular-nums text-[9px] text-eigenia-muted">
                                  {Math.round(turn.latency_ms)} ms
                                </span>
                              )}
                            </div>

                            {/* Hover Copy & Replay Controls */}
                            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                              <button
                                type="button"
                                onClick={() => handleCopyTurn(turn)}
                                title="Copy transcript"
                                className="inline-flex h-5 items-center gap-1 rounded border border-white/10 bg-eigenia-obsidian/80 px-1.5 text-[9px] text-eigenia-muted hover:border-eigenia-sky/40 hover:text-white"
                              >
                                <Copy className="h-2.5 w-2.5" />
                                {copiedTurnId === turn.id ? "Copied" : "Copy"}
                              </button>
                              <button
                                type="button"
                                disabled={busyAction !== null}
                                onClick={() => handleSpeakDirect(turn.content)}
                                title="Replay aloud on WonderEcho Pro"
                                className="inline-flex h-5 items-center gap-1 rounded border border-white/10 bg-eigenia-obsidian/80 px-1.5 text-[9px] text-eigenia-sky hover:border-eigenia-sky/50 hover:text-white disabled:opacity-40"
                              >
                                <Volume2 className="h-2.5 w-2.5" />
                                Replay
                              </button>
                            </div>
                          </div>
                          <div className="text-xs leading-relaxed text-white whitespace-pre-wrap">
                            {turn.content}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
                {sendingChat && (
                  <div className="flex justify-start">
                    <div className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-eigenia-surface px-3.5 py-2 text-xs text-eigenia-sky">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      {cfgAssistantName} is thinking & synthesizing speech...
                    </div>
                  </div>
                )}
              </div>

              {/* Clean Bottom Composer */}
              <div className="space-y-2.5 rounded-lg border border-white/10 bg-eigenia-shell p-3">
                <div className="flex gap-2">
                  <Input
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && chatInput.trim()) {
                        e.preventDefault();
                        void handleSendChat();
                      }
                    }}
                    placeholder={`Message ${cfgAssistantName} (e.g. "What do you see?" or "Wave and tell a joke")...`}
                    className="text-xs"
                  />
                  <Button
                    disabled={sendingChat || !chatInput.trim()}
                    onClick={() => void handleSendChat()}
                  >
                    {sendingChat ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    Send
                  </Button>
                  <Button
                    variant="sky"
                    disabled={busyAction !== null || sendingChat}
                    onClick={() => void handlePushToTalk()}
                    title="Push-to-Talk via PuppyPi Mic (4s)"
                  >
                    {busyAction === "ptt" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Mic className="h-3.5 w-3.5" />
                    )}
                    Push-to-Talk
                  </Button>
                </div>

                {/* Inline Composer Controls */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-0.5 text-xs">
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="inline-flex items-center gap-2 text-[11px] text-eigenia-ink">
                      <Switch checked={chatSpeakReply} onCheckedChange={setChatSpeakReply} />
                      Speak Reply Aloud
                    </label>
                    <label className="inline-flex items-center gap-2 text-[11px] text-eigenia-ink">
                      <Switch checked={chatBodyActions} onCheckedChange={setChatBodyActions} />
                      Body Actions
                    </label>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-[10px] text-eigenia-muted">Camera Context:</span>
                    {(
                      [
                        { id: "auto", label: "Auto" },
                        { id: "always", label: "Always" },
                        { id: "never", label: "Off" },
                      ] as const
                    ).map((opt) => (
                      <Button
                        key={opt.id}
                        size="sm"
                        variant={chatCameraMode === opt.id ? "sky" : "secondary"}
                        className="h-6 px-2 text-[10px]"
                        onClick={() => setChatCameraMode(opt.id)}
                      >
                        {opt.label}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Quick Direct Text-to-Speech & Chimes Bar */}
          <InteractiveSurface
            accent="sky"
            title="Quick Text-to-Speech & Test Chimes"
            subtitle={`Direct WonderEcho Pro playback (${getEngineShortLabel(ttsEngine)} · ${ttsSpeed} WPM)`}
            badge={
              lastSpokenMeta ? (
                <Badge
                  variant="sky"
                  className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[9px] text-emerald-400"
                >
                  {lastSpokenMeta.engine} · {lastSpokenMeta.voiceLabel}
                  {lastSpokenMeta.bytes > 0 ? ` · ${formatKb(lastSpokenMeta.bytes)}` : ""}
                </Badge>
              ) : undefined
            }
            collapsible
          >
            <div className="space-y-2.5">
              <div className="flex flex-wrap gap-2">
                <Input
                  value={ttsText}
                  onChange={(e) => setTtsText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSpeakDirect()}
                  placeholder="Type phrase to speak directly on PuppyPi..."
                  className="min-w-[240px] flex-1 text-xs"
                />
                <Button
                  disabled={busyAction !== null || !ttsText.trim()}
                  onClick={() => handleSpeakDirect()}
                >
                  {busyAction === "speak" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Volume2 className="h-3.5 w-3.5" />
                  )}
                  Speak Aloud
                </Button>
                <div className="flex items-center gap-1">
                  {CHIMES.map((c) => (
                    <Button
                      key={`quick-chime-${c.id}`}
                      size="sm"
                      variant="secondary"
                      disabled={busyAction !== null}
                      onClick={() => void handleChime(c.id)}
                    >
                      <Bell className="h-3 w-3 text-eigenia-amber" />
                      {c.label}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {QUICK_PHRASES.map((phrase) => (
                  <Button
                    key={phrase}
                    size="sm"
                    variant="outline"
                    className="h-auto px-2.5 py-1 text-[10px]"
                    disabled={busyAction !== null}
                    onClick={() => handleSpeakDirect(phrase)}
                  >
                    {phrase}
                  </Button>
                ))}
              </div>
            </div>
          </InteractiveSurface>
        </div>
      )}

      {/* TAB 2: VOICE & PERSONALITIES */}
      {activeTab === "personas" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-surface px-4 py-3">
            <div>
              <div className="text-xs font-semibold text-white">
                Embodied Personalities ({personalities.length})
              </div>
              <p className="font-mono text-[10px] text-eigenia-muted">
                Active: <span className="text-eigenia-orange">{activePersonality.name}</span> · Built-in + Custom Personas
              </p>
            </div>
            <Button
              size="sm"
              onClick={() => {
                resetPersonalityForm();
                setPersonalityDrawerOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              New Custom Personality
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {personalities.map((p) => {
              const isActive = activePersonality.id === p.id;
              return (
                <InteractiveSurface
                  key={p.id}
                  hoverable
                  accent={isActive ? "orange" : "none"}
                  className={isActive ? "bg-eigenia-orange/10" : undefined}
                >
                  <div className="flex h-full flex-col justify-between gap-3">
                    <div className="space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-sm font-semibold text-white">{p.name}</span>
                            <Badge variant={isActive ? "default" : "amber"} className="text-[9px]">
                              {p.badge || "Persona"}
                            </Badge>
                            <Badge variant="neutral" className="text-[9px]">
                              {p.is_builtin ? "Built-In" : "Custom"}
                            </Badge>
                          </div>
                          <p className="mt-1 text-xs text-eigenia-ink">{p.description}</p>
                        </div>
                        {isActive && (
                          <Badge variant="sky" className="shrink-0 text-[9px]">
                            <CheckCircle2 className="h-3 w-3" /> ACTIVE
                          </Badge>
                        )}
                      </div>

                      <div className="line-clamp-2 rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-1.5 font-mono text-[10px] text-eigenia-muted">
                        {p.system_prompt}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 pt-2.5">
                      <span className="font-mono text-[10px] text-eigenia-muted">
                        Voice: <span className="text-eigenia-sky">{p.default_voice}</span>
                      </span>
                      <div className="flex items-center gap-1.5">
                        {!p.is_builtin && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2"
                              onClick={() => {
                                setEditingPersonalityId(p.id);
                                setPName(p.name);
                                setPBadge(p.badge);
                                setPDesc(p.description);
                                setPPrompt(p.system_prompt);
                                setPVoice(p.default_voice);
                                setPAllowActions(p.allow_body_actions);
                                setPersonalityDrawerOpen(true);
                              }}
                            >
                              <Edit3 className="h-3 w-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              className="h-7 px-2"
                              disabled={busyAction !== null}
                              onClick={() => void handleDeletePersonality(p)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </>
                        )}
                        <Button
                          size="sm"
                          variant={isActive ? "secondary" : "default"}
                          disabled={isActive || busyAction !== null}
                          onClick={() => void handleSelectPersonality(p)}
                        >
                          {isActive ? "In Use" : "Use Personality"}
                        </Button>
                      </div>
                    </div>
                  </div>
                </InteractiveSurface>
              );
            })}
          </div>

          {/* Slide-Over Drawer for Creating / Editing Custom Personality */}
          <SlideOverDrawer
            open={personalityDrawerOpen}
            onClose={() => {
              setPersonalityDrawerOpen(false);
              resetPersonalityForm();
            }}
            title={editingPersonalityId ? "Edit Custom Personality" : "Create Custom Personality"}
            subtitle="Define custom system instructions, voice actor, and embodied ROS 2 actions."
            badge={editingPersonalityId ? "EDIT" : "NEW PERSONA"}
          >
            <form
              onSubmit={(e) => {
                void handleSavePersonality(e);
                setPersonalityDrawerOpen(false);
              }}
              className="space-y-3.5"
            >
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">Personality Name</label>
                <Input
                  value={pName}
                  onChange={(e) => setPName(e.target.value)}
                  placeholder="e.g. Grumpy Pirate Bot"
                  className="text-xs"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] text-eigenia-muted">Badge Tag</label>
                  <Input
                    value={pBadge}
                    onChange={(e) => setPBadge(e.target.value)}
                    placeholder="e.g. Pirate"
                    className="text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] text-eigenia-muted">Preferred Voice Actor</label>
                  <select
                    value={pVoice}
                    onChange={(e) => setPVoice(e.target.value)}
                    className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                  >
                    {allVoices.map((v) => (
                      <option key={`custom-${v.engine}-${v.id}`} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">Short Description</label>
                <Input
                  value={pDesc}
                  onChange={(e) => setPDesc(e.target.value)}
                  placeholder="One-line summary shown on the personality card..."
                  className="text-xs"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">System Prompt</label>
                <textarea
                  rows={5}
                  value={pPrompt}
                  onChange={(e) => setPPrompt(e.target.value)}
                  placeholder="Define how OX should talk, joke, react to people, and choose physical tricks..."
                  className="w-full rounded-md border border-white/15 bg-eigenia-obsidian p-2.5 font-mono text-xs text-white placeholder:text-eigenia-muted focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                />
              </div>
              <label className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian px-3 py-2 text-xs text-white">
                <span>Allow Embodied ROS 2 Body Actions (wave, sit, nod, RGB)</span>
                <Switch checked={pAllowActions} onCheckedChange={setPAllowActions} />
              </label>
              <div className="flex items-center justify-end gap-2 border-t border-white/10 pt-3">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setPersonalityDrawerOpen(false);
                    resetPersonalityForm();
                  }}
                >
                  <X className="h-3.5 w-3.5" /> Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={busyAction !== null || !pName.trim() || !pPrompt.trim()}
                >
                  {busyAction === "save-personality" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {editingPersonalityId ? "Update Personality" : "Save Custom Personality"}
                </Button>
              </div>
            </form>
          </SlideOverDrawer>

          {/* Assistant Wake Word, Speech Engine & LLM Settings */}
          <form onSubmit={handleSaveAssistantSettings} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Ear className="h-3.5 w-3.5 text-eigenia-orange" />
                    Assistant Identity & Custom Wake Word
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3.5">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] text-eigenia-muted">Assistant Name</label>
                      <Input
                        value={cfgAssistantName}
                        onChange={(e) => setCfgAssistantName(e.target.value)}
                        placeholder="OX"
                        className="font-mono text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] text-eigenia-muted">Custom Wake Word</label>
                      <Input
                        value={cfgWakeWord}
                        onChange={(e) => setCfgWakeWord(e.target.value)}
                        placeholder="Hey OX"
                        className="font-mono text-xs"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] text-eigenia-muted">
                      Phonetic Aliases (comma-separated for reliable STT matching)
                    </label>
                    <Input
                      value={cfgWakeAliases}
                      onChange={(e) => setCfgWakeAliases(e.target.value)}
                      placeholder="hey ox, hey aux, hey o x, hey box, hey fox"
                      className="font-mono text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] text-eigenia-muted">Wake Detection Mode</label>
                    <select
                      value={cfgWakeMode}
                      onChange={(e) => setCfgWakeMode(e.target.value as WakeMode)}
                      className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                    >
                      <option value="custom_software">
                        Custom Software (&quot;{cfgWakeWord}&quot;)
                      </option>
                      <option value="hardware_wonderecho">
                        Hardware WonderEcho (&quot;Hello Hiwonder&quot;)
                      </option>
                      <option value="both">Both (Custom Software + Hardware UART)</option>
                    </select>
                  </div>
                  <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                    <div className="flex justify-between font-mono text-[11px]">
                      <span className="text-eigenia-muted">Follow-Up Listening Window</span>
                      <span className="tabular-nums text-eigenia-orange">{cfgFollowupSec} s</span>
                    </div>
                    <Slider
                      min={0}
                      max={30}
                      step={1}
                      value={[cfgFollowupSec]}
                      onValueChange={([v]) => setCfgFollowupSec(v)}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5 text-eigenia-sky" />
                    Piper / Edge Neural Voice, LLM Brain & WonderEcho EQ
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3.5">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-[11px] text-eigenia-muted">Default Speech Engine</label>
                      <select
                        value={cfgEngine}
                        onChange={(e) => setCfgEngine(e.target.value as VoiceEngineKey)}
                        className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                      >
                        {engines.map((eng) => (
                          <option key={`cfg-eng-${eng.id}`} value={eng.id}>
                            {eng.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <label className="text-[11px] text-eigenia-muted">Default Voice Actor</label>
                        {selectedCfgVoiceObj?.engine === "piper_tts" && (
                          <Badge
                            variant={selectedCfgVoiceObj.cached ? "sky" : "amber"}
                            className="px-1.5 py-0 text-[8px]"
                          >
                            {selectedCfgVoiceObj.cached ? "Cached Offline" : "Auto-Download"}
                          </Badge>
                        )}
                      </div>
                      <select
                        value={cfgVoice}
                        onChange={(e) => setCfgVoice(e.target.value)}
                        className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                      >
                        {cfgVoices.map((v) => (
                          <option key={`cfg-v-${v.engine}-${v.id}`} value={v.id}>
                            {v.label}
                            {v.engine === "piper_tts" && v.cached ? " [Cached]" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-eigenia-muted">
                      Conversational LLM Model (OpenRouter · Live Costs & Search)
                    </label>
                    <OpenRouterModelPicker
                      value={cfgLlmModel}
                      onChange={setCfgLlmModel}
                      models={openRouterModels}
                      loading={llmCatalogLoading}
                      defaultCategory="text"
                      onRefreshModels={() => void loadOpenRouterCatalog(true)}
                      compact
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between rounded-md border border-eigenia-sky/30 bg-eigenia-sky/10 px-3 py-2">
                      <div className="pr-2">
                        <div className="text-xs font-medium text-white">Anti-Clipping WonderEcho EQ</div>
                        <div className="text-[10px] text-eigenia-muted">
                          180 Hz high-pass + compressor + limiter tuned for 2 W speaker
                        </div>
                      </div>
                      <Switch checked={cfgAntiClip} onCheckedChange={setCfgAntiClip} />
                    </div>
                    <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian px-3 py-2">
                      <div className="pr-2">
                        <div className="text-xs font-medium text-white">
                          Auto-Attach Live Camera on Visual Questions
                        </div>
                        <div className="text-[10px] text-eigenia-muted">
                          Automatically snaps PuppyPi FPV when you ask &quot;what do you see?&quot;
                        </div>
                      </div>
                      <Switch checked={cfgAttachCam} onCheckedChange={setCfgAttachCam} />
                    </div>
                    <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian px-3 py-2">
                      <div className="pr-2">
                        <div className="text-xs font-medium text-white">Allow Embodied Body Actions</div>
                        <div className="text-[10px] text-eigenia-muted">
                          Permits expressive ROS 2 actions (wave, sit, nod, bow, RGB mood)
                        </div>
                      </div>
                      <Switch checked={cfgAllowActions} onCheckedChange={setCfgAllowActions} />
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
            <Button type="submit" disabled={busyAction !== null} className="w-full sm:w-auto">
              {busyAction === "save-config" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save Assistant Settings
            </Button>
          </form>

          {/* WonderEcho Pro ALSA Mixer, Direct TTS Tuning & Persistent Udev Rules */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <Card className="lg:col-span-6">
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  <Radio className="h-3.5 w-3.5 text-eigenia-sky" />
                  ALSA Audio Mixer & Udev Rules
                </CardTitle>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busyAction !== null}
                  onClick={() => void handleInstallUdev()}
                >
                  {busyAction === "udev" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Wrench className="h-3.5 w-3.5" />
                  )}
                  Install Udev Rules
                </Button>
              </CardHeader>
              <CardContent className="space-y-3.5">
                <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-mono text-xs text-white">
                      {speakerMuted ? (
                        <VolumeX className="h-3.5 w-3.5 text-eigenia-fault" />
                      ) : (
                        <Volume2 className="h-3.5 w-3.5 text-eigenia-sky" />
                      )}
                      Speaker Volume
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-xs tabular-nums text-white">{speakerVol}%</span>
                      <Button
                        size="sm"
                        variant="sky"
                        className="h-6 px-2 text-[10px]"
                        disabled={busyAction !== null}
                        onClick={() => {
                          setSpeakerVol(80);
                          setSpeakerMuted(false);
                          void handleMixerUpdate({ speaker_volume_pct: 80, speaker_mute: false });
                        }}
                      >
                        Ideal 80%
                      </Button>
                      <Button
                        size="sm"
                        variant={speakerMuted ? "destructive" : "secondary"}
                        className="h-6 px-2 text-[10px]"
                        onClick={() => {
                          const next = !speakerMuted;
                          setSpeakerMuted(next);
                          void handleMixerUpdate({ speaker_mute: next });
                        }}
                      >
                        {speakerMuted ? "Unmute" : "Mute"}
                      </Button>
                    </div>
                  </div>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={[speakerVol]}
                    onValueChange={([v]) => setSpeakerVol(v)}
                    onValueCommit={([v]) => void handleMixerUpdate({ speaker_volume_pct: v })}
                  />
                </div>

                <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 font-mono text-xs text-white">
                      {micMuted ? (
                        <MicOff className="h-3.5 w-3.5 text-eigenia-fault" />
                      ) : (
                        <Mic className="h-3.5 w-3.5 text-eigenia-orange" />
                      )}
                      Microphone Gain
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs tabular-nums text-white">{micGain}%</span>
                      <Button
                        size="sm"
                        variant={micMuted ? "destructive" : "secondary"}
                        className="h-6 px-2 text-[10px]"
                        onClick={() => {
                          const next = !micMuted;
                          setMicMuted(next);
                          void handleMixerUpdate({ mic_mute: next });
                        }}
                      >
                        {micMuted ? "Unmute" : "Mute"}
                      </Button>
                    </div>
                  </div>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={[micGain]}
                    onValueChange={([v]) => setMicGain(v)}
                    onValueCommit={([v]) => void handleMixerUpdate({ mic_gain_pct: v })}
                  />
                </div>
              </CardContent>
            </Card>

            <Card className="lg:col-span-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sliders className="h-3.5 w-3.5 text-eigenia-orange" />
                  Direct TTS Voice & EQ Tuning
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <label className="text-[10px] text-eigenia-muted">TTS Engine</label>
                    <select
                      value={ttsEngine}
                      onChange={(e) => setTtsEngine(e.target.value as VoiceEngineKey)}
                      className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white"
                    >
                      {engines.map((eng) => (
                        <option key={`tts-eng-${eng.id}`} value={eng.id}>
                          {eng.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] text-eigenia-muted">Voice Actor</label>
                      {selectedTtsVoiceObj?.engine === "piper_tts" && (
                        <Badge
                          variant={selectedTtsVoiceObj.cached ? "sky" : "amber"}
                          className="px-1.5 py-0 text-[8px]"
                        >
                          {selectedTtsVoiceObj.cached ? "Cached" : "Auto-DL"}
                        </Badge>
                      )}
                    </div>
                    <select
                      value={ttsVoice}
                      onChange={(e) => setTtsVoice(e.target.value)}
                      className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white"
                    >
                      {ttsVoices.map((v) => (
                        <option key={`tts-v-${v.engine}-${v.id}`} value={v.id}>
                          {v.label}
                          {v.engine === "piper_tts" && v.cached ? " [Cached]" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex items-center justify-between rounded border border-eigenia-sky/30 bg-eigenia-sky/10 px-3 py-1.5">
                    <span className="text-xs text-white">Anti-Clipping EQ</span>
                    <Switch checked={antiClipEq} onCheckedChange={setAntiClipEq} />
                  </div>
                  <div className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian px-3 py-1.5">
                    <div className="flex justify-between font-mono text-[10px]">
                      <span className="text-eigenia-muted">Speed</span>
                      <span className="tabular-nums text-white">{ttsSpeed} WPM</span>
                    </div>
                    <Slider
                      min={100}
                      max={220}
                      step={5}
                      value={[ttsSpeed]}
                      onValueChange={([v]) => setTtsSpeed(v)}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Collapsible Raw Voice Event Log */}
          <InteractiveSurface
            title={`Raw Voice Event Log (${logs.length})`}
            badge={<Badge variant="neutral">PG18 Persisted</Badge>}
            collapsible
            defaultCollapsed
          >
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {logs.length === 0 ? (
                <div className="rounded border border-dashed border-white/10 bg-eigenia-obsidian/60 p-5 text-center text-xs text-eigenia-muted">
                  No raw voice events logged yet.
                </div>
              ) : (
                logs.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded border border-white/10 bg-eigenia-obsidian p-2.5 font-mono text-[10px]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <Badge
                          variant={entry.direction === "out" ? "sky" : "default"}
                          className="text-[8px]"
                        >
                          {entry.direction}
                        </Badge>
                        <span className="font-semibold text-white">
                          {entry.action_taken || "speech"}
                        </span>
                      </div>
                      <span className="text-[9px] text-eigenia-muted">
                        {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ""}
                      </span>
                    </div>
                    {entry.transcript && (
                      <div className="mt-1 text-eigenia-ink">Heard: &quot;{entry.transcript}&quot;</div>
                    )}
                    {entry.reply_text && (
                      <div className="mt-0.5 text-eigenia-sky">Reply: &quot;{entry.reply_text}&quot;</div>
                    )}
                  </div>
                ))
              )}
            </div>
          </InteractiveSurface>
        </div>
      )}

      {/* TAB 3: DIAGNOSTICS & AUDIO FLOW */}
      {activeTab === "diagnostics" && (
        <div className="space-y-4">
          {/* Live 7-Stage React Flow Audio Pipeline */}
          <VoicePipelineFlow
            status={status}
            convState={convState}
            diagResult={diagResult}
            config={config}
            activeEngine={cfgEngine}
            activeVoice={cfgVoice}
            activeLlmModel={cfgLlmModel}
            antiClip={cfgAntiClip}
            speakerVol={speakerVol}
            speakerMuted={speakerMuted}
            micGain={micGain}
            micMuted={micMuted}
          />

          {/* Action Bar Card */}
          <Card className="border-eigenia-sky/30">
            <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Stethoscope className="h-3.5 w-3.5 text-eigenia-orange" />
                  End-to-End Voice Pipeline Diagnostics & Live Wake-Word Test
                </CardTitle>
                <p className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
                  Probes SSH, USB ALSA enumeration, ALSA mixer levels, Piper → faster-whisper
                  loopback, live mic recording, and optional speaker chime.
                </p>
              </div>
              {diagResult && (
                <Badge
                  variant={diagResult.ok ? "sky" : "fault"}
                  className={
                    diagResult.ok
                      ? "border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
                      : "font-mono text-[10px]"
                  }
                >
                  {diagResult.passed_count} / {diagResult.total_count} PASSED
                </Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busyAction !== null}
                  onClick={() => void handleRunDiagnostics(0)}
                >
                  {busyAction === "diag-quick" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Activity className="h-3.5 w-3.5" />
                  )}
                  Run Diagnostics (No Recording)
                </Button>

                <Button
                  size="sm"
                  variant="default"
                  disabled={busyAction !== null}
                  onClick={() => void handleRunDiagnostics(4)}
                  className="font-semibold"
                >
                  {busyAction === "diag-live" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Mic className="h-3.5 w-3.5" />
                  )}
                  {busyAction === "diag-live"
                    ? `Listening ${diagListeningSec ?? 4}s — say '${cfgWakeWord}' now...`
                    : `Record 4s & Test Saying "${cfgWakeWord}"`}
                </Button>

                <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-white/10 bg-eigenia-obsidian px-3 py-1.5 text-xs text-eigenia-ink select-none">
                  <input
                    type="checkbox"
                    checked={diagTestSpeaker}
                    onChange={(e) => setDiagTestSpeaker(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-white/20 bg-eigenia-obsidian accent-eigenia-orange"
                  />
                  Test Speaker Chime
                </label>
              </div>

              {busyAction === "diag-live" && (
                <div className="flex items-center gap-2.5 rounded-md border border-eigenia-orange/50 bg-eigenia-orange/15 px-3 py-2 font-mono text-xs text-eigenia-orange">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>
                    Listening {diagListeningSec ?? 4}s — say &apos;{cfgWakeWord}&apos; now...
                  </span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Live Mic & Wake-Word Test Result Card */}
          {diagResult?.live_mic_test &&
            (diagResult.live_mic_test.recorded ||
              Boolean(diagResult.live_mic_test.error) ||
              Boolean(diagResult.live_mic_test.live_transcript)) && (
            <Card className="border-eigenia-orange/40 bg-eigenia-surface">
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  <Mic className="h-3.5 w-3.5 text-eigenia-orange" />
                  Live Mic & Wake-Word Test Result
                </CardTitle>
                <Badge
                  variant={diagResult.live_mic_test.wake_matched ? "sky" : "fault"}
                  className={
                    diagResult.live_mic_test.wake_matched
                      ? "border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
                      : "font-mono text-[10px]"
                  }
                >
                  {diagResult.live_mic_test.wake_matched ? "MATCHED" : "NOT MATCHED"}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Mic RMS
                    </div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-white">
                      {Math.round(Number(diagResult.live_mic_test.mic_rms ?? 0))}
                    </div>
                  </div>
                  <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Mic Peak
                    </div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-white">
                      {Math.round(Number(diagResult.live_mic_test.mic_peak ?? 0))}
                    </div>
                  </div>
                  <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Captured Audio
                    </div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-eigenia-sky">
                      {formatKb(Number(diagResult.live_mic_test.audio_bytes ?? 0))} (
                      {Number(diagResult.live_mic_test.duration_sec ?? 4)}s)
                    </div>
                  </div>
                  <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Wake Target
                    </div>
                    <div className="mt-1 truncate font-mono text-sm font-semibold text-eigenia-orange">
                      &quot;{diagResult.wake_word || cfgWakeWord}&quot;
                    </div>
                  </div>
                </div>

                <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-3 font-mono text-xs">
                  <div className="text-[10px] uppercase text-eigenia-muted">
                    Exact Whisper Transcript
                  </div>
                  <div className="text-sm text-white">
                    {diagResult.live_mic_test.live_transcript
                      ? `"${diagResult.live_mic_test.live_transcript}"`
                      : "(silence / no speech detected)"}
                  </div>
                  {diagResult.live_mic_test.remainder && (
                    <div className="text-[11px] text-eigenia-sky">
                      Command Remainder: &quot;{diagResult.live_mic_test.remainder}&quot;
                    </div>
                  )}
                  {diagResult.live_mic_test.error && (
                    <div className="text-[11px] text-eigenia-fault">
                      Error: {diagResult.live_mic_test.error}
                    </div>
                  )}
                </div>

                {canAddSuggestedAlias && suggestedAlias && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-eigenia-amber/40 bg-eigenia-amber/10 px-3 py-2">
                    <div className="text-xs text-eigenia-ink">
                      Whisper heard{" "}
                      <span className="font-mono font-semibold text-white">
                        &quot;{suggestedAlias}&quot;
                      </span>
                      . Add it as a phonetic wake alias so future triggers match reliably:
                    </div>
                    <Button
                      size="sm"
                      variant="default"
                      disabled={busyAction !== null}
                      onClick={() => handleAddSuggestedAlias(suggestedAlias)}
                    >
                      {busyAction === "add-alias" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      + Add &quot;{suggestedAlias}&quot; as Wake Alias
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* 6-Point Diagnostic Scorecard */}
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-2 sm:flex-row">
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5 text-eigenia-sky" />
                6-Point Voice Diagnostic Scorecard
              </CardTitle>
              <div className="flex flex-wrap items-center gap-1.5">
                {diagResult && (
                  <Badge
                    variant={diagResult.card_index != null ? "sky" : "fault"}
                    className="font-mono text-[9px]"
                  >
                    {diagResult.card_index != null
                      ? `USB Audio Card ${diagResult.card_index}`
                      : "USB Card Missing"}
                  </Badge>
                )}
                <Badge variant="neutral" className="font-mono text-[9px]">
                  Wake: &quot;{diagResult?.wake_word || cfgWakeWord}&quot;
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {!diagResult ? (
                <div className="rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center text-xs text-eigenia-muted">
                  Click <span className="font-semibold text-white">Run Diagnostics (No Recording)</span>{" "}
                  or{" "}
                  <span className="font-semibold text-white">
                    Record 4s &amp; Test Saying &quot;{cfgWakeWord}&quot;
                  </span>{" "}
                  above to run the full 6-point hardware &amp; STT diagnostic scorecard.
                </div>
              ) : (
                <>
                  <div className="divide-y divide-white/10 rounded-md border border-white/10 bg-eigenia-obsidian">
                    {diagResult.checks.map((chk) => (
                      <div
                        key={chk.id}
                        className="flex flex-col gap-1.5 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0 space-y-0.5">
                          <div className="flex flex-wrap items-center gap-2">
                            {renderCheckBadge(chk.status)}
                            <span className="text-xs font-semibold text-white">{chk.name}</span>
                          </div>
                          <p className="font-mono text-[11px] leading-relaxed text-eigenia-ink break-words">
                            {chk.detail}
                          </p>
                        </div>
                        {typeof chk.latency_ms === "number" && (
                          <span className="shrink-0 font-mono text-[10px] tabular-nums text-eigenia-muted">
                            {Math.round(chk.latency_ms)} ms
                          </span>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Expandable dmesg USB Warnings & lsusb Box */}
                  {(diagResult.dmesg_usb_warnings.length > 0 ||
                    diagResult.usb_devices.length > 0) && (
                    <div className="rounded-md border border-white/10 bg-eigenia-obsidian">
                      <button
                        type="button"
                        onClick={() => setDiagUsbExpanded((v) => !v)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-white/5"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          {diagUsbExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5 text-eigenia-sky" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-eigenia-muted" />
                          )}
                          <Cpu className="h-3.5 w-3.5 text-eigenia-amber" />
                          <span className="font-mono text-xs font-semibold text-white">
                            dmesg USB Warnings &amp; lsusb Enumeration
                          </span>
                          {diagResult.dmesg_usb_warnings.length > 0 && (
                            <Badge variant="fault" className="font-mono text-[9px]">
                              {diagResult.dmesg_usb_warnings.length} USB warning(s)
                            </Badge>
                          )}
                          <Badge variant="neutral" className="font-mono text-[9px]">
                            {diagResult.usb_devices.length} USB device(s)
                          </Badge>
                        </div>
                        <span className="font-mono text-[10px] text-eigenia-muted">
                          {diagUsbExpanded ? "Collapse" : "Expand"}
                        </span>
                      </button>

                      {diagUsbExpanded && (
                        <div className="space-y-3 border-t border-white/10 p-3 font-mono text-[10px]">
                          <div className="space-y-1">
                            <div className="uppercase text-eigenia-fault">
                              Kernel dmesg USB Warnings ({diagResult.dmesg_usb_warnings.length})
                            </div>
                            {diagResult.dmesg_usb_warnings.length === 0 ? (
                              <div className="rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5 text-eigenia-muted">
                                No recent USB disconnect/over-current warnings in dmesg.
                              </div>
                            ) : (
                              <pre className="max-h-40 overflow-auto rounded border border-eigenia-fault/30 bg-eigenia-shell p-2.5 text-[10px] leading-relaxed text-eigenia-fault whitespace-pre-wrap">
                                {diagResult.dmesg_usb_warnings.join("\n")}
                              </pre>
                            )}
                          </div>

                          <div className="space-y-1">
                            <div className="uppercase text-eigenia-sky">
                              Enumerated USB Devices (lsusb · {diagResult.usb_devices.length})
                            </div>
                            {diagResult.usb_devices.length === 0 ? (
                              <div className="rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5 text-eigenia-muted">
                                No lsusb output returned.
                              </div>
                            ) : (
                              <pre className="max-h-40 overflow-auto rounded border border-eigenia-shell bg-eigenia-shell p-2.5 text-[10px] leading-relaxed text-eigenia-ink whitespace-pre-wrap">
                                {diagResult.usb_devices.join("\n")}
                              </pre>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
