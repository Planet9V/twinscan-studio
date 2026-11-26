"use client";

import React, { useMemo, useState } from "react";
import { Activity, Cpu, Info, Mic, Radio, Sparkles, Volume2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import {
  TopologyFlowCanvas,
  type TopologyEdgeSpec,
  type TopologyNodeSpec,
  type TopologyNodeStatus,
} from "@/components/ui/TopologyFlowCanvas";
import type {
  ConversationState,
  VoiceAssistantConfig,
  VoiceDiagnosticCheck,
  VoiceDiagnosticsResponse,
  VoiceStatus,
} from "@/lib/voiceApi";

export interface VoicePipelineFlowProps {
  status: VoiceStatus | null;
  convState: ConversationState | null;
  diagResult: VoiceDiagnosticsResponse | null;
  config: VoiceAssistantConfig | null;
  activeEngine?: string;
  activeVoice?: string;
  activeLlmModel?: string;
  antiClip?: boolean;
  speakerVol?: number;
  speakerMuted?: boolean;
  micGain?: number;
  micMuted?: boolean;
}

interface StageMetadata {
  id: string;
  title: string;
  role: string;
  status: TopologyNodeStatus;
  summary: string;
  metrics: Record<string, string | number | boolean>;
  troubleshooting?: string;
}

function checkToStatus(chk?: VoiceDiagnosticCheck | null): TopologyNodeStatus | null {
  if (!chk) return null;
  if (chk.status === "pass") return "ok";
  if (chk.status === "warn") return "warning";
  if (chk.status === "fail") return "fault";
  return "idle";
}

function shortModel(model?: string | null): string {
  if (!model) return "gemini-2.5-flash";
  const parts = model.split("/");
  return parts[parts.length - 1] || model;
}

export function VoicePipelineFlow({
  status,
  convState,
  diagResult,
  config,
  activeEngine = "piper_tts",
  activeVoice = "en_US-lessac-medium",
  activeLlmModel = "google/gemini-2.5-flash",
  antiClip = true,
  speakerVol = 80,
  speakerMuted = false,
  micGain = 75,
  micMuted = false,
}: VoicePipelineFlowProps) {
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);

  const checksById = useMemo(() => {
    const map = new Map<string, VoiceDiagnosticCheck>();
    for (const c of diagResult?.checks ?? []) {
      map.set(c.id, c);
    }
    return map;
  }, [diagResult]);

  const { nodes, edges, stageMap } = useMemo(() => {
    const audioPresent = status ? Boolean(status.audio_card_detected) : diagResult ? diagResult.card_index != null : null;
    const cardIdx = diagResult?.card_index ?? status?.card_index ?? null;
    const micRms = typeof convState?.mic_rms === "number" ? Math.round(convState.mic_rms) : null;
    const wakeWord = config?.wake_word || diagResult?.wake_word || "Hey OX";
    const hasConvErr = Boolean(convState?.error);

    const usbChk = checksById.get("usb_audio") ?? checksById.get("usb_enumeration") ?? null;
    const mixerChk = checksById.get("alsa_mixer") ?? null;
    const sshChk = checksById.get("ssh") ?? checksById.get("ssh_connectivity") ?? null;
    const sttChk = checksById.get("stt_loopback") ?? checksById.get("whisper_loopback") ?? null;
    const liveMicChk = checksById.get("live_mic") ?? checksById.get("live_mic_test") ?? null;
    const speakerChk = checksById.get("speaker") ?? checksById.get("speaker_chime") ?? null;

    const micStatus: TopologyNodeStatus =
      audioPresent === false
        ? "fault"
        : micMuted
          ? "warning"
          : checkToStatus(usbChk) ?? (audioPresent ? "ok" : "idle");

    const alsaStatus: TopologyNodeStatus =
      audioPresent === false
        ? "fault"
        : checkToStatus(mixerChk) ?? checkToStatus(usbChk) ?? (cardIdx != null ? "ok" : "idle");

    const sshStatus: TopologyNodeStatus = hasConvErr
      ? "fault"
      : checkToStatus(sshChk) ?? (convState?.active ? "ok" : audioPresent ? "ok" : "idle");

    const sttStatus: TopologyNodeStatus =
      checkToStatus(liveMicChk) ??
      checkToStatus(sttChk) ??
      (hasConvErr ? "fault" : convState?.active ? "ok" : "idle");

    const llmStatus: TopologyNodeStatus = hasConvErr
      ? "warning"
      : convState?.state === "thinking"
        ? "ok"
        : activeLlmModel
          ? "ok"
          : "idle";

    const ttsStatus: TopologyNodeStatus =
      checkToStatus(sttChk) ?? (convState?.state === "speaking" ? "ok" : "ok");

    const speakerStatus: TopologyNodeStatus =
      audioPresent === false
        ? "fault"
        : speakerMuted
          ? "warning"
          : checkToStatus(speakerChk) ?? (audioPresent ? "ok" : "idle");

    const builtNodes: TopologyNodeSpec[] = [
      {
        id: "usb_mic",
        label: "WonderEcho USB Mic",
        subtitle: status?.serial_symlink_present ? "/dev/wonderecho · 16kHz" : "USB PnP Audio Capture",
        metric: micMuted ? "MUTED" : `Gain ${micGain}%`,
        category: "STAGE 1 · CAPTURE",
        status: micStatus,
        x: 20,
        y: 30,
      },
      {
        id: "alsa_card",
        label: "ALSA Audio Card",
        subtitle: cardIdx != null ? `plughw:${cardIdx},0` : "USB Audio Enum",
        metric: cardIdx != null ? `Card ${cardIdx}` : "Missing",
        category: "STAGE 2 · KERNEL",
        status: alsaStatus,
        x: 260,
        y: 30,
      },
      {
        id: "ssh_pcm",
        label: "SSH PCM Stream",
        subtitle: "Zero-gap arecord pipe",
        metric: micRms !== null ? `RMS ${micRms}` : convState?.active ? "Streaming" : "Standby",
        category: "STAGE 3 · TRANSPORT",
        status: sshStatus,
        x: 500,
        y: 30,
      },
      {
        id: "whisper_stt",
        label: "Faster-Whisper STT",
        subtitle: `Wake "${wakeWord}"`,
        metric:
          typeof sttChk?.latency_ms === "number"
            ? `${Math.round(sttChk.latency_ms)} ms`
            : "Local CPU",
        category: "STAGE 4 · ASR",
        status: sttStatus,
        x: 740,
        y: 30,
      },
      {
        id: "openrouter_llm",
        label: "OpenRouter LLM",
        subtitle: shortModel(activeLlmModel),
        metric: config?.personality_id || "dog",
        category: "STAGE 5 · REASONING",
        status: llmStatus,
        x: 620,
        y: 215,
      },
      {
        id: "neural_tts",
        label: "Piper / Edge Neural TTS",
        subtitle: activeVoice.split("-").slice(0, 2).join("-"),
        metric: activeEngine === "piper_tts" ? "Offline ONNX" : activeEngine,
        category: "STAGE 6 · SYNTHESIS",
        status: ttsStatus,
        x: 340,
        y: 215,
      },
      {
        id: "ffmpeg_speaker",
        label: "FFmpeg EQ & Speaker",
        subtitle: antiClip ? "180Hz HPF + Limiter" : "Direct PCM Out",
        metric: speakerMuted ? "MUTED" : `Vol ${speakerVol}%`,
        category: "STAGE 7 · PLAYBACK",
        status: speakerStatus,
        x: 60,
        y: 215,
      },
    ];

    const edgeStatus = (a: TopologyNodeStatus, b: TopologyNodeStatus): TopologyNodeStatus => {
      if (a === "fault" || b === "fault") return "fault";
      if (a === "warning" || b === "warning") return "warning";
      if (a === "ok" && b === "ok") return "ok";
      return "idle";
    };

    const builtEdges: TopologyEdgeSpec[] = [
      {
        id: "e-mic-alsa",
        source: "usb_mic",
        target: "alsa_card",
        label: "USB 2.0",
        status: edgeStatus(micStatus, alsaStatus),
        animated: micStatus === "ok" && alsaStatus === "ok",
      },
      {
        id: "e-alsa-ssh",
        source: "alsa_card",
        target: "ssh_pcm",
        label: "16kHz PCM",
        status: edgeStatus(alsaStatus, sshStatus),
        animated: Boolean(convState?.active) && sshStatus === "ok",
      },
      {
        id: "e-ssh-stt",
        source: "ssh_pcm",
        target: "whisper_stt",
        label: "VAD Chunks",
        status: edgeStatus(sshStatus, sttStatus),
        animated: Boolean(convState?.active) && sttStatus === "ok",
      },
      {
        id: "e-stt-llm",
        source: "whisper_stt",
        target: "openrouter_llm",
        label: "Transcript",
        status: edgeStatus(sttStatus, llmStatus),
        animated: convState?.state === "thinking" || (sttStatus === "ok" && llmStatus === "ok"),
      },
      {
        id: "e-llm-tts",
        source: "openrouter_llm",
        target: "neural_tts",
        label: "Reply + Action",
        status: edgeStatus(llmStatus, ttsStatus),
        animated: convState?.state === "speaking" || (llmStatus === "ok" && ttsStatus === "ok"),
      },
      {
        id: "e-tts-spk",
        source: "neural_tts",
        target: "ffmpeg_speaker",
        label: "Zlib WAV",
        status: edgeStatus(ttsStatus, speakerStatus),
        animated: convState?.state === "speaking" || (ttsStatus === "ok" && speakerStatus === "ok"),
      },
    ];

    const stages: Record<string, StageMetadata> = {
      usb_mic: {
        id: "usb_mic",
        title: "WonderEcho Pro USB Microphone",
        role: "Stage 1 · Acoustic Capture",
        status: micStatus,
        summary:
          usbChk?.detail ||
          (audioPresent === false
            ? "No USB audio capture device enumerated on PuppyPi."
            : "USB PnP Sound Device ready for continuous 16kHz mono capture."),
        metrics: {
          "Audio Detected": Boolean(audioPresent),
          "Mic Gain": `${micGain}%`,
          "Mic Muted": micMuted,
          "Serial Symlink": status?.serial_symlink_present ? "/dev/wonderecho" : "Absent",
        },
        troubleshooting:
          micStatus === "fault"
            ? "Re-seat WonderEcho Pro into a black USB 2.0 port (e.g. port 1-2) on the Raspberry Pi 5 and re-run diagnostics."
            : micMuted
              ? "Unmute the microphone in Voice & Personalities -> ALSA Audio Mixer."
              : undefined,
      },
      alsa_card: {
        id: "alsa_card",
        title: "Linux ALSA Kernel Driver & Mixer",
        role: "Stage 2 · Dynamic USB Card Auto-Detection",
        status: alsaStatus,
        summary:
          mixerChk?.detail ||
          (cardIdx != null
            ? `Auto-detected USB Audio Card ${cardIdx} (plughw:${cardIdx},0) with capture & playback controls.`
            : "Run diagnostics to probe active ALSA USB card index."),
        metrics: {
          "Card Index": cardIdx != null ? cardIdx : "None",
          "Device Name": status?.device_name || "USB PnP Sound Device",
          "Speaker Vol": `${speakerVol}%`,
          "Mic Gain": `${micGain}%`,
        },
      },
      ssh_pcm: {
        id: "ssh_pcm",
        title: "Persistent SSH PCM Stream",
        role: "Stage 3 · Zero-Gap Audio Transport",
        status: sshStatus,
        summary:
          convState?.error ||
          sshChk?.detail ||
          (convState?.active
            ? `Live hands-free stream active (${convState.state}).`
            : "Streams raw 16kHz S16_LE PCM frames from PuppyPi to the TwinScan backend when Hands-Free is started."),
        metrics: {
          "Hands-Free Active": Boolean(convState?.active),
          "Pipeline State": convState?.state || "idle",
          "Live Mic RMS": micRms ?? "--",
          "Noise Floor": typeof convState?.noise_floor === "number" ? Math.round(convState.noise_floor) : "--",
        },
        troubleshooting: hasConvErr
          ? "Check WonderEcho USB connection and click Re-Check USB or Restart Hands-Free."
          : undefined,
      },
      whisper_stt: {
        id: "whisper_stt",
        title: "Faster-Whisper Offline STT & Wake Matcher",
        role: "Stage 4 · Speech-to-Text + Wake-Word Gate",
        status: sttStatus,
        summary:
          liveMicChk?.detail ||
          sttChk?.detail ||
          `Offline faster-whisper transcription with wake word "${wakeWord}" and phonetic alias matching.`,
        metrics: {
          "Wake Word": wakeWord,
          "Wake Mode": config?.wake_mode || "custom_software",
          "Last Heard": convState?.last_heard || "(none)",
          "Follow-Up Window": `${config?.followup_window_sec ?? 12}s`,
        },
      },
      openrouter_llm: {
        id: "openrouter_llm",
        title: "OpenRouter Conversational Brain",
        role: "Stage 5 · Personality, Memory & Embodied Actions",
        status: llmStatus,
        summary:
          "Generates personality-styled replies, optional ROS 2 body actions (wave, sit, nod, RGB), and camera-aware visual descriptions.",
        metrics: {
          Model: activeLlmModel,
          Personality: config?.personality_id || "dog",
          "Camera Context": config?.attach_camera_on_visual ? "Auto on Visual" : "Disabled",
          "Body Actions": config?.allow_body_actions ? "Enabled" : "Disabled",
        },
      },
      neural_tts: {
        id: "neural_tts",
        title: "Piper Offline / Edge Studio Neural TTS",
        role: "Stage 6 · Neural Speech Synthesis",
        status: ttsStatus,
        summary:
          "Synthesizes natural speech via local offline Piper ONNX VITS (default) or Microsoft Edge Neural Studio voices.",
        metrics: {
          Engine: activeEngine,
          "Voice Actor": activeVoice,
          "Speech Speed": `${config?.default_speed ?? 155} WPM`,
        },
      },
      ffmpeg_speaker: {
        id: "ffmpeg_speaker",
        title: "FFmpeg Anti-Clipping EQ & WonderEcho Speaker",
        role: "Stage 7 · 2W Speaker Conditioning & Playback",
        status: speakerStatus,
        summary:
          speakerChk?.detail ||
          "Applies 180Hz high-pass filter, dynamic compressor, and peak limiter before zlib-chunked playback to WonderEcho Pro.",
        metrics: {
          "Anti-Clip EQ": antiClip ? "Active (180Hz HPF + Limiter)" : "Bypassed",
          "Speaker Volume": `${speakerVol}%`,
          "Speaker Muted": speakerMuted,
          "Target Card": cardIdx != null ? `plughw:${cardIdx},0` : "Auto",
        },
        troubleshooting: speakerMuted
          ? "Unmute the speaker or click 'Ideal 80% (No Clip)' in Voice & Personalities."
          : undefined,
      },
    };

    return { nodes: builtNodes, edges: builtEdges, stageMap: stages };
  }, [
    status,
    convState,
    diagResult,
    config,
    checksById,
    activeEngine,
    activeVoice,
    activeLlmModel,
    antiClip,
    speakerVol,
    speakerMuted,
    micGain,
    micMuted,
  ]);

  const selectedStage = selectedStageId ? stageMap[selectedStageId] ?? null : null;

  return (
    <div className="space-y-2">
      <TopologyFlowCanvas
        nodes={nodes}
        edges={edges}
        selectedNodeId={selectedStageId}
        onSelectNode={(id) => setSelectedStageId(id)}
        heightClassName="h-[390px]"
        title="Live 7-Stage Voice & Audio Pipeline (Click any stage to inspect)"
        legend
      />

      <SlideOverDrawer
        open={Boolean(selectedStage)}
        onClose={() => setSelectedStageId(null)}
        title={selectedStage?.title || "Pipeline Stage"}
        subtitle={selectedStage?.role}
        badge={selectedStage ? selectedStage.status.toUpperCase() : undefined}
        badgeVariant={
          selectedStage?.status === "fault"
            ? "fault"
            : selectedStage?.status === "warning"
              ? "amber"
              : selectedStage?.status === "ok"
                ? "sky"
                : "neutral"
        }
      >
        {selectedStage && (
          <div className="space-y-4">
            <div className="rounded-lg border border-white/10 bg-eigenia-obsidian p-3.5 text-xs leading-relaxed text-eigenia-ink">
              <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-sky">
                <Info className="h-3.5 w-3.5" />
                Live Stage Telemetry
              </div>
              {selectedStage.summary}
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              {Object.entries(selectedStage.metrics).map(([k, v]) => (
                <div
                  key={k}
                  className="rounded-md border border-white/10 bg-eigenia-surface p-2.5"
                >
                  <div className="font-mono text-[9px] uppercase tracking-wider text-eigenia-muted">
                    {k}
                  </div>
                  <div className="mt-1 truncate font-mono text-xs font-semibold text-white">
                    {typeof v === "boolean" ? (v ? "YES" : "NO") : String(v)}
                  </div>
                </div>
              ))}
            </div>

            {selectedStage.troubleshooting && (
              <div className="rounded-lg border border-eigenia-amber/40 bg-eigenia-amber/10 p-3 text-xs text-eigenia-ink">
                <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase text-eigenia-amber">
                  <Activity className="h-3.5 w-3.5" />
                  Recommended Action
                </div>
                {selectedStage.troubleshooting}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-1.5 border-t border-white/10 pt-3">
              <Badge variant="neutral" className="font-mono text-[9px]">
                <Mic className="h-3 w-3" /> WonderEcho Pro
              </Badge>
              <Badge variant="sky" className="font-mono text-[9px]">
                <Cpu className="h-3 w-3" /> Faster-Whisper + Piper
              </Badge>
              <Badge variant="default" className="font-mono text-[9px]">
                <Sparkles className="h-3 w-3" /> OpenRouter
              </Badge>
              <Badge variant="neutral" className="font-mono text-[9px]">
                <Volume2 className="h-3 w-3" /> FFmpeg EQ
              </Badge>
              <Badge variant="neutral" className="font-mono text-[9px]">
                <Radio className="h-3 w-3" /> Stage ID: {selectedStage.id}
              </Badge>
            </div>
          </div>
        )}
      </SlideOverDrawer>
    </div>
  );
}
