"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Cable,
  CheckCircle2,
  Code2,
  Cpu,
  GripVertical,
  HelpCircle,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  Trash2,
  Volume2,
  VolumeX,
  Wand2,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Microbit3DCanvas,
  type Microbit3DHandle,
} from "@/components/microbit/Microbit3DCanvas";
import {
  chatWithMicrobitCopilot,
  createMicrobitProject,
  deployMicrobitCode,
  generateMicrobitCode,
  getMicrobitCatalog,
  getMicrobitHardwareStatus,
  listMicrobitProjects,
  readMicrobitSensors,
  runMicrobitSelfTest,
  updateMicrobitProject,
  type BoardId,
  type MicrobitAccessorySpec,
  type MicrobitAttachment,
  type MicrobitCatalog,
  type MicrobitHardwareStatus,
  type MicrobitLiveSensors,
  type MicrobitProject,
  type MicrobitTrigger,
} from "@/lib/microbitApi";
import { cn } from "@/lib/utils";

function playBrowserSoundEffect(effect: string): void {
  if (typeof window === "undefined" || !effect || effect === "none") return;
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    const now = ctx.currentTime;
    gain.gain.setValueAtTime(0.18, now);

    if (effect === "slide") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(340, now);
      osc.frequency.exponentialRampToValueAtTime(1180, now + 0.32);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.36);
      osc.start(now);
      osc.stop(now + 0.38);
    } else if (effect === "chime") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(523.25, now);
      osc.frequency.setValueAtTime(659.25, now + 0.11);
      osc.frequency.setValueAtTime(783.99, now + 0.22);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
      osc.start(now);
      osc.stop(now + 0.46);
    } else if (effect === "giggle") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(620, now);
      osc.frequency.setValueAtTime(840, now + 0.08);
      osc.frequency.setValueAtTime(660, now + 0.16);
      osc.frequency.setValueAtTime(920, now + 0.24);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
      osc.start(now);
      osc.stop(now + 0.4);
    } else if (effect === "spring") {
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(220, now);
      osc.frequency.linearRampToValueAtTime(740, now + 0.28);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
      osc.start(now);
      osc.stop(now + 0.34);
    } else if (effect === "sad") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.exponentialRampToValueAtTime(210, now + 0.35);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.42);
    }
  } catch {
    // AudioContext blocked until user gesture
  }
}

function speakBrowserText(text: string): void {
  if (typeof window === "undefined" || !text.trim() || !("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.05;
    u.pitch = 1.25;
    window.speechSynthesis.speak(u);
  } catch {
    // ignore speech synth errors
  }
}

const QUICK_PROMPTS = [
  "On lift say 'Weeee!' with a surprised face and slide sound",
  "On left button play a chime and sweep the servo to 180 degrees",
  "Attach NeoPixels on P1 and glow purple on right button",
  "Add an external speaker on P0 and on touch logo say 'That tickles!'",
];

export function MicrobitLabStudio(): React.JSX.Element {
  const canvasRef = useRef<Microbit3DHandle | null>(null);

  const [catalog, setCatalog] = useState<MicrobitCatalog | null>(null);
  const [projects, setProjects] = useState<MicrobitProject[]>([]);
  const [project, setProject] = useState<MicrobitProject | null>(null);
  const [hwStatus, setHwStatus] = useState<MicrobitHardwareStatus | null>(null);
  const [selectedPinId, setSelectedPinId] = useState<string>("P0");
  const [codeDraft, setCodeDraft] = useState<string>("");

  // Virtual 3D Twin Simulator live state
  const [simLedIcon, setSimLedIcon] = useState<string>("HAPPY");
  const [simServoAngle, setSimServoAngle] = useState<number>(90);
  const [simNeopixelHex, setSimNeopixelHex] = useState<string>("#22d3ee");
  const [simAudioOn, setSimAudioOn] = useState<boolean>(true);
  const [simLastEvent, setSimLastEvent] = useState<string>(
    "Click Button A, Button B, Gold Logo on the 3D board, or any trigger below!"
  );

  // Right panel mode: AI Co-Pilot Chat vs MicroPython Code
  const [rightTab, setRightTab] = useState<"chat" | "code">("chat");
  const [chatInput, setChatInput] = useState<string>("");
  const [chatBusy, setChatBusy] = useState<boolean>(false);

  const [liveSensors, setLiveSensors] = useState<MicrobitLiveSensors | null>(null);
  const [liveTilt, setLiveTilt] = useState(false);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [consoleLog, setConsoleLog] = useState<string>(
    "Ready. Chat with the AI Co-Pilot, test in the 3D Twin, then Deploy & Run on your real micro:bit!"
  );

  const [newProjOpen, setNewProjOpen] = useState(false);
  const [newProjName, setNewProjName] = useState("Smart Desk Prototype");
  const [dragOverCanvas, setDragOverCanvas] = useState(false);
  const [infoAccId, setInfoAccId] = useState<string | null>(null);

  const hydrate = useCallback(async (selectId?: string) => {
    try {
      const [cat, projRes, hw] = await Promise.all([
        getMicrobitCatalog(),
        listMicrobitProjects(),
        getMicrobitHardwareStatus(),
      ]);
      setCatalog(cat);
      setProjects(projRes.projects || []);
      setHwStatus(hw);
      const chosen =
        (selectId ? projRes.projects.find((p) => p.id === selectId) : null) ||
        projRes.projects[0] ||
        null;
      if (chosen) {
        setProject(chosen);
        setCodeDraft(chosen.code);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initialize micro:bit Lab.");
    }
  }, []);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!liveTilt) return;
    let active = true;
    const poll = async () => {
      try {
        const res = await readMicrobitSensors();
        if (active && res.ok) setLiveSensors(res.sensors);
      } catch {
        // ignore transient poll hiccup
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1800);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [liveTilt]);

  // Execute a trigger live in the 3D Digital Twin Canvas!
  const handleVirtualTrigger = useCallback(
    (trigger: MicrobitTrigger) => {
      if (trigger === "lift" || trigger === "shake" || trigger === "tilt_left" || trigger === "tilt_right") {
        canvasRef.current?.playMotionPulse(trigger);
      }
      const rule = (project?.sim_rules || []).find((r) => r.trigger === trigger);
      if (!rule) {
        setSimLastEvent(`Triggered '${trigger}' (no rule set yet — ask the AI Co-Pilot to add one!)`);
        return;
      }
      if (rule.led_icon) setSimLedIcon(rule.led_icon);
      if (typeof rule.servo_angle === "number") setSimServoAngle(rule.servo_angle);
      if (rule.neopixel_hex) setSimNeopixelHex(rule.neopixel_hex);
      if (simAudioOn) {
        if (rule.sound_effect && rule.sound_effect !== "none") {
          playBrowserSoundEffect(rule.sound_effect);
        }
        if (rule.speak_text) {
          speakBrowserText(rule.speak_text);
        }
      }
      const parts = [
        `[${trigger.toUpperCase()}]`,
        `LED: ${rule.led_icon}`,
        rule.speak_text ? `Say: "${rule.speak_text}"` : null,
        rule.sound_effect && rule.sound_effect !== "none" ? `Sound: ${rule.sound_effect}` : null,
        typeof rule.servo_angle === "number" ? `Servo: ${rule.servo_angle}°` : null,
        rule.neopixel_hex ? `NeoPixel: ${rule.neopixel_hex}` : null,
      ].filter(Boolean);
      setSimLastEvent(parts.join(" · "));
    },
    [project?.sim_rules, simAudioOn]
  );

  const handleSendChat = async (textOverride?: string) => {
    const msg = (textOverride ?? chatInput).trim();
    if (!msg || !project || chatBusy) return;
    setChatInput("");
    setChatBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await chatWithMicrobitCopilot(project.id, msg);
      setProject(res.project);
      setCodeDraft(res.project.code);
      setNotice("AI Co-Pilot updated your 3D Twin, jumper wiring, simulator rules & MicroPython!");
      // Auto-preview the newest rule in 3D if present
      const latestRule = res.project.sim_rules?.[res.project.sim_rules.length - 1];
      if (latestRule?.led_icon) setSimLedIcon(latestRule.led_icon);
      if (typeof latestRule?.servo_angle === "number") setSimServoAngle(latestRule.servo_angle);
      if (latestRule?.neopixel_hex) setSimNeopixelHex(latestRule.neopixel_hex);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI Co-Pilot chat failed.");
    } finally {
      setChatBusy(false);
    }
  };

  const handleAttachAccessory = async (acc: MicrobitAccessorySpec) => {
    if (!project) return;
    const activeBoardId: BoardId = project.board_id || "microbit_v2";
    const boardDef = acc.default_pins_by_board?.[activeBoardId];
    const used = new Set(project.wiring.used_pins);
    const freePin =
      boardDef?.pin || acc.allowed_signal_pins.find((p) => !used.has(p)) || acc.default_pin;
    const secPin = boardDef?.secondary_pin !== undefined ? boardDef.secondary_pin : acc.secondary_pin;
    const next: MicrobitAttachment[] = [
      ...project.attachments,
      {
        id: `att_${Date.now().toString(36)}`,
        accessory_id: acc.id,
        label: acc.name,
        pin: freePin,
        secondary_pin: secPin,
      },
    ];
    try {
      const res = await updateMicrobitProject(project.id, { attachments: next });
      setProject(res.project);
      setSelectedPinId(freePin);
      setNotice(`Attached ${acc.name} on ${freePin} — check 3D jumper wires & safety notes!`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed attaching part.");
    }
  };

  const handleSwitchBoard = async (nextBoard: BoardId) => {
    if (!project || project.board_id === nextBoard) return;
    try {
      const res = await updateMicrobitProject(project.id, { board_id: nextBoard });
      setProject(res.project);
      const firstPin = catalog?.boards?.[nextBoard]?.pins?.[0]?.id || "P0";
      setSelectedPinId(firstPin);
      setNotice(`Switched 3D Prototyping Board to ${catalog?.boards?.[nextBoard]?.name || nextBoard}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed switching board.");
    }
  };

  const handleChangePin = async (attId: string, newPin: string) => {
    if (!project) return;
    const next = project.attachments.map((a) => (a.id === attId ? { ...a, pin: newPin } : a));
    const res = await updateMicrobitProject(project.id, { attachments: next });
    setProject(res.project);
    setSelectedPinId(newPin);
  };

  const handleRemoveAttachment = async (attId: string) => {
    if (!project) return;
    const next = project.attachments.filter((a) => a.id !== attId);
    const res = await updateMicrobitProject(project.id, { attachments: next });
    setProject(res.project);
  };

  const handleGenerateCode = async () => {
    if (!project) return;
    setBusy("Generating MicroPython for attached parts...");
    setError(null);
    try {
      const res = await generateMicrobitCode(project.id);
      setProject(res.project);
      setCodeDraft(res.code);
      setNotice("Generated MicroPython tailored to your attached 3D accessories!");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Code generation failed.");
    } finally {
      setBusy(null);
    }
  };

  const handleDeploy = async () => {
    if (!project) return;
    setBusy("Deploying main.py to live micro:bit v2.2 via Pi 5 (/dev/ttyACM0)...");
    setError(null);
    setNotice(null);
    try {
      await updateMicrobitProject(project.id, { code: codeDraft });
      const res = await deployMicrobitCode(codeDraft);
      setConsoleLog(
        `[DEPLOY OK on ${res.host_name || "Pi 5"}]\n${res.upload || ""}\n${res.boot || ""}`.trim()
      );
      setNotice("Deployed & running live on your real BBC micro:bit v2.2!");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Deploy failed.";
      setError(msg);
      setConsoleLog(`[DEPLOY ERROR] ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSelfTest = async () => {
    setBusy("Running live hardware self-test (LED + chime + sensors)...");
    setError(null);
    try {
      const res = await runMicrobitSelfTest();
      setLiveSensors(res.sensors);
      setConsoleLog(
        `[SELF-TEST PASSED]\nAccel: (${res.sensors.ax}, ${res.sensors.ay}, ${res.sensors.az}) mg\nTemp: ${res.sensors.temp_c}°C (${Math.round((res.sensors.temp_c * 9) / 5 + 32)}°F)\nLight: ${res.sensors.light}/255 | Sound: ${res.sensors.sound}/255`
      );
      setNotice("Hardware self-test passed!");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Self-test failed.");
    } finally {
      setBusy(null);
    }
  };

  if (!catalog || !project) {
    return (
      <div className="flex h-96 items-center justify-center text-sm text-slate-300">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-cyan-400" />
        Loading micro:bit v2.2 AI Prototyping Lab...
      </div>
    );
  }

  const activeBoardId: BoardId = project.board_id || "microbit_v2";
  const activeBoardProfile = catalog.boards?.[activeBoardId] || catalog.board;
  const activePins = activeBoardProfile.pins || catalog.pins;
  const selectedPin = activePins.find((p) => p.id === selectedPinId) || activePins[0];

  return (
    <div className="space-y-4">
      {/* Top Project & Hardware Command Bar */}
      <Card className="border-white/10 bg-slate-950/90">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <Cpu className="h-5 w-5 text-amber-400" />
            <div>
              <h1 className="text-sm font-semibold text-white">Universal 3D Hardware Lab &amp; AI Co-Pilot</h1>
              <p className="text-[11px] text-slate-400">
                {activeBoardProfile.name} · {activeBoardProfile.language}
              </p>
            </div>

            {/* Multi-Board Switcher */}
            <div className="flex items-center rounded-md border border-white/10 bg-slate-900 p-0.5">
              {(
                [
                  { id: "microbit_v2", label: "micro:bit v2.2" },
                  { id: "rpi5_16gb", label: "Raspberry Pi 5" },
                  { id: "puppypi_pro", label: "PuppyPi + LiDAR" },
                ] as Array<{ id: BoardId; label: string }>
              ).map((b) => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => void handleSwitchBoard(b.id)}
                  className={cn(
                    "rounded px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer",
                    activeBoardId === b.id
                      ? "bg-cyan-600 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  )}
                >
                  {b.label}
                </button>
              ))}
            </div>

            <select
              aria-label="Select micro:bit project"
              value={project.id}
              onChange={(e) => {
                const found = projects.find((p) => p.id === e.target.value);
                if (found) {
                  setProject(found);
                  setCodeDraft(found.code);
                }
              }}
              className="h-8 rounded-md border border-white/15 bg-slate-900 px-2 text-xs font-medium text-slate-100"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>

            <Button size="sm" variant="outline" onClick={() => setNewProjOpen(true)} className="h-8 gap-1 text-xs cursor-pointer">
              <Plus className="h-3.5 w-3.5" /> New
            </Button>

            <Badge variant={hwStatus?.connected ? "sky" : "neutral"} className="text-[10px]">
              {hwStatus?.connected
                ? `LIVE on ${hwStatus.host_name || "Pi 5"} (${hwStatus.serial_port})`
                : "USB Standby"}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={liveTilt ? "default" : "outline"}
              onClick={() => setLiveTilt((v) => !v)}
              className={cn("h-8 gap-1.5 text-xs cursor-pointer", liveTilt && "bg-cyan-600 text-white")}
            >
              <Activity className="h-3.5 w-3.5" />
              {liveTilt ? "Live Tilt: ON" : "Live Tilt"}
            </Button>

            <Button
              size="sm"
              variant="outline"
              disabled={Boolean(busy)}
              onClick={() => void handleSelfTest()}
              className="h-8 gap-1.5 text-xs cursor-pointer"
            >
              <Zap className="h-3.5 w-3.5 text-amber-400" />
              Self-Test
            </Button>

            <Button
              size="sm"
              disabled={Boolean(busy)}
              onClick={() => void handleDeploy()}
              className="h-8 gap-1.5 bg-emerald-600 text-xs text-white hover:bg-emerald-500 cursor-pointer"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Deploy to Real micro:bit
            </Button>
          </div>
        </CardContent>
      </Card>

      {(busy || error || notice) && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
            error
              ? "border-red-500/40 bg-red-950/50 text-red-200"
              : busy
                ? "border-cyan-500/40 bg-cyan-950/40 text-cyan-200"
                : "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
          )}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : !error ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
          <span>{busy || error || notice}</span>
        </div>
      )}

      {/* 3-Column Workbench */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* LEFT: Parts Library & Wiring Checklist */}
        <div className="space-y-4 xl:col-span-3">
          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-1.5 text-xs font-semibold text-amber-300">
                <Cable className="h-3.5 w-3.5" /> Attached Parts &amp; Wiring ({project.attachments.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {project.wiring.conflicts.map((c, idx) => (
                <div key={`conf_${idx}`} className="flex items-start gap-1.5 rounded-md border border-red-500/40 bg-red-950/50 p-2 text-[11px] text-red-200">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                  <span>{c}</span>
                </div>
              ))}
              {project.wiring.warnings.map((w, idx) => (
                <div key={`warn_${idx}`} className="flex items-start gap-1.5 rounded-md border border-amber-500/40 bg-amber-950/40 p-2 text-[11px] text-amber-200">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <span>{w}</span>
                </div>
              ))}
              {project.attachments.map((att) => {
                const spec = catalog.accessories.find((a) => a.id === att.accessory_id);
                return (
                  <div key={att.id} className="flex items-center justify-between gap-1.5 rounded-lg border border-white/10 bg-slate-900/70 px-2.5 py-1.5 text-xs">
                    <span className="truncate font-medium text-slate-100">{att.label}</span>
                    <div className="flex items-center gap-1">
                      <select
                        value={att.pin}
                        onChange={(e) => void handleChangePin(att.id, e.target.value)}
                        className="h-6 rounded border border-white/15 bg-slate-950 px-1 font-mono text-[10px] text-cyan-300"
                      >
                        {(spec?.allowed_signal_pins || ["P0", "P1", "P2"]).map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => void handleRemoveAttachment(att.id)}
                        className="text-slate-500 hover:text-red-400 cursor-pointer"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}

              {project.wiring.wiring_steps.length > 0 && (
                <div className="max-h-36 space-y-1 overflow-y-auto border-t border-white/10 pt-2">
                  {project.wiring.wiring_steps.map((s) => (
                    <div key={`ws_${s.step}`} className="flex items-center gap-2 text-[10px] text-slate-300">
                      <span
                        style={{ backgroundColor: s.color }}
                        className="h-2 w-2 shrink-0 rounded-full border border-white/30"
                      />
                      <span>{s.instruction}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-xs font-semibold text-cyan-300">
                <span className="flex items-center gap-1.5">
                  <Plus className="h-3.5 w-3.5" /> Hiwonder &amp; Parts Library
                </span>
                <span className="text-[10px] font-normal text-slate-400">Drag onto 3D</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="max-h-[420px] space-y-1.5 overflow-y-auto">
              {catalog.accessories.map((acc) => {
                const expanded = infoAccId === acc.id;
                return (
                  <div
                    key={acc.id}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", acc.id);
                      e.dataTransfer.effectAllowed = "copy";
                    }}
                    className="rounded-lg border border-white/10 bg-slate-900/60 px-2.5 py-1.5 transition-colors hover:border-cyan-500/40 cursor-grab active:cursor-grabbing"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <GripVertical className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-[11px] font-medium text-slate-100">{acc.name}</span>
                            {acc.requires_5v && (
                              <span className="rounded bg-amber-500/20 px-1 font-mono text-[9px] text-amber-300">
                                5V
                              </span>
                            )}
                          </div>
                          <div className="truncate text-[10px] text-slate-400">{acc.summary}</div>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setInfoAccId(expanded ? null : acc.id)}
                          title="Specs & How It Works"
                          className="rounded p-1 text-slate-400 hover:bg-white/10 hover:text-cyan-300 cursor-pointer"
                        >
                          <HelpCircle className="h-3.5 w-3.5" />
                        </button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void handleAttachAccessory(acc)}
                          className="h-6 px-2 text-[10px] cursor-pointer"
                        >
                          + Add
                        </Button>
                      </div>
                    </div>
                    {expanded && (
                      <div className="mt-2 space-y-1 border-t border-white/10 pt-2 text-[10px] text-slate-300">
                        {acc.ic && (
                          <div>
                            <strong className="text-cyan-300">IC / Bus:</strong> {acc.ic} ({acc.protocol})
                          </div>
                        )}
                        {acc.how_it_works && <div>{acc.how_it_works}</div>}
                        <div className="text-amber-200/90">
                          <strong>Wiring Note:</strong> {acc.power_note}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </div>

        {/* CENTER: Interactive 3D Virtual Twin Simulator + Trigger Test Bar + Pinout */}
        <div className="space-y-4 xl:col-span-5">
          <Card className="overflow-hidden border-white/10 bg-slate-950/90">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3.5 py-2">
              <div className="flex items-center gap-2">
                <CardTitle className="text-xs font-semibold text-white">
                  Live Interactive 3D Twin Simulator
                </CardTitle>
                <Badge variant="sky" className="text-[9px]">
                  Click 3D Buttons / Logo / Pins
                </Badge>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setSimAudioOn((v) => !v)}
                  title={simAudioOn ? "Mute virtual speaker" : "Unmute virtual speaker"}
                  className="h-6 px-2 text-cyan-300 cursor-pointer"
                >
                  {simAudioOn ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5 text-slate-500" />}
                </Button>
                {(["front", "back", "iso", "top"] as const).map((v) => (
                  <Button
                    key={v}
                    size="sm"
                    variant="ghost"
                    onClick={() => canvasRef.current?.setView(v)}
                    className="h-6 px-1.5 text-[10px] uppercase text-slate-300 hover:text-white cursor-pointer"
                  >
                    {v}
                  </Button>
                ))}
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverCanvas(true);
                }}
                onDragLeave={() => setDragOverCanvas(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOverCanvas(false);
                  const accId = e.dataTransfer.getData("text/plain");
                  const found = catalog.accessories.find((a) => a.id === accId);
                  if (found) void handleAttachAccessory(found);
                }}
                className={cn(
                  "relative h-[390px] w-full bg-[#050914] transition-all",
                  dragOverCanvas && "ring-2 ring-inset ring-cyan-400"
                )}
              >
                <Microbit3DCanvas
                  ref={canvasRef}
                  boardId={activeBoardId}
                  pins={activePins}
                  accessories={catalog.accessories}
                  attachments={project.attachments}
                  selectedPinId={selectedPinId}
                  liveSensors={liveSensors}
                  liveTiltEnabled={liveTilt}
                  ledIcon={simLedIcon}
                  simServoAngle={simServoAngle}
                  simNeopixelHex={simNeopixelHex}
                  onSelectPin={(pid) => setSelectedPinId(pid)}
                  onVirtualTrigger={handleVirtualTrigger}
                />
                {dragOverCanvas && (
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-cyan-950/40 backdrop-blur-[1px]">
                    <span className="rounded-full border border-cyan-400 bg-slate-950/90 px-4 py-1.5 text-xs font-semibold text-cyan-200 shadow-lg">
                      Drop to Attach Component &amp; Auto-Wire 3D Jumpers
                    </span>
                  </div>
                )}
              </div>

              {/* Virtual Event Simulator Test Bar */}
              <div className="space-y-2 border-t border-white/10 bg-slate-900/70 p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Test in 3D:
                  </span>
                  {(
                    [
                      { id: "button_a", label: "Btn A (Left)" },
                      { id: "button_b", label: "Btn B (Right)" },
                      { id: "logo_touch", label: "Logo" },
                      { id: "lift", label: "Lift Up" },
                      { id: "shake", label: "Shake" },
                      { id: "touch_pad", label: "Hiwonder Touch" },
                      { id: "ultrasonic_near", label: "Ultrasonic <20cm" },
                      { id: "temp_high", label: "Temp High" },
                    ] as Array<{ id: MicrobitTrigger; label: string }>
                  ).map((t) => {
                    const hasRule = (project.sim_rules || []).some((r) => r.trigger === t.id);
                    return (
                      <Button
                        key={t.id}
                        size="sm"
                        variant={hasRule ? "default" : "outline"}
                        onClick={() => handleVirtualTrigger(t.id)}
                        className={cn(
                          "h-6 px-2 text-[10px] cursor-pointer",
                          hasRule && "bg-cyan-600/80 text-white hover:bg-cyan-500"
                        )}
                      >
                        {t.label}
                      </Button>
                    );
                  })}
                </div>
                <div className="rounded-md border border-cyan-500/25 bg-slate-950/80 px-2.5 py-1.5 font-mono text-[11px] text-cyan-200">
                  {simLastEvent}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Pinout Schematic Inspector */}
          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-xs font-semibold text-amber-300">
                  Pin Schematic — {selectedPin.label}
                </CardTitle>
                <div className="flex flex-wrap gap-1">
                  {activePins.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setSelectedPinId(p.id)}
                      className={cn(
                        "rounded border px-1.5 py-0.5 font-mono text-[10px] cursor-pointer",
                        p.id === selectedPinId
                          ? "border-cyan-400 bg-cyan-950/70 text-cyan-200"
                          : "border-white/10 bg-slate-900 text-slate-400 hover:text-slate-200"
                      )}
                    >
                      {p.id}
                    </button>
                  ))}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="sky" className="font-mono text-[10px]">
                  {selectedPin.voltage} · Max {selectedPin.max_ma}mA
                </Badge>
                {selectedPin.capabilities.map((cap) => (
                  <Badge key={cap} variant="neutral" className="text-[10px]">
                    {cap}
                  </Badge>
                ))}
              </div>
              <p className="text-[11px] text-slate-300">{selectedPin.notes}</p>
            </CardContent>
          </Card>
        </div>

        {/* RIGHT: Built-In AI Hardware Co-Pilot Chat | MicroPython Code Studio */}
        <div className="xl:col-span-4">
          <Card className="flex h-full min-h-[600px] flex-col border-white/10 bg-slate-950/90">
            <CardHeader className="flex flex-row items-center justify-between border-b border-white/10 px-3.5 py-2.5">
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant={rightTab === "chat" ? "default" : "ghost"}
                  onClick={() => setRightTab("chat")}
                  className={cn("h-7 gap-1.5 text-xs cursor-pointer", rightTab === "chat" && "bg-cyan-600 text-white")}
                >
                  <Bot className="h-3.5 w-3.5" /> AI Co-Pilot Chat
                </Button>
                <Button
                  size="sm"
                  variant={rightTab === "code" ? "default" : "ghost"}
                  onClick={() => setRightTab("code")}
                  className={cn("h-7 gap-1.5 text-xs cursor-pointer", rightTab === "code" && "bg-cyan-600 text-white")}
                >
                  <Code2 className="h-3.5 w-3.5" /> MicroPython (`main.py`)
                </Button>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void hydrate(project.id)}
                className="h-7 px-2 text-slate-400 hover:text-white cursor-pointer"
                title="Refresh USB status"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </CardHeader>

            {rightTab === "chat" ? (
              <CardContent className="flex flex-1 flex-col justify-between gap-3 p-3">
                {/* Chat History */}
                <div className="flex-1 space-y-2.5 overflow-y-auto pr-1">
                  {(project.chat_history || []).length === 0 ? (
                    <div className="space-y-2.5 rounded-xl border border-cyan-500/20 bg-cyan-950/15 p-3 text-xs text-slate-300">
                      <div className="font-semibold text-cyan-300">
                        Tell me what you want your micro:bit to do!
                      </div>
                      <p className="text-[11px] text-slate-400">
                        I will attach 3D parts, wire the jumper cables, program the virtual 3D twin so you can test it immediately, and keep the real MicroPython ready to flash.
                      </p>
                      <div className="space-y-1.5 pt-1">
                        {QUICK_PROMPTS.map((qp) => (
                          <button
                            key={qp}
                            type="button"
                            onClick={() => void handleSendChat(qp)}
                            className="block w-full rounded-lg border border-white/10 bg-slate-900/80 px-2.5 py-1.5 text-left text-[11px] text-slate-200 hover:border-cyan-400/50 hover:text-cyan-200 cursor-pointer"
                          >
                            &ldquo;{qp}&rdquo;
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    (project.chat_history || []).map((m, idx) => (
                      <div
                        key={`msg_${idx}`}
                        className={cn(
                          "rounded-xl px-3 py-2 text-xs leading-relaxed",
                          m.role === "user"
                            ? "ml-6 border border-cyan-500/30 bg-cyan-950/50 text-cyan-100"
                            : "mr-4 border border-white/10 bg-slate-900/90 text-slate-200"
                        )}
                      >
                        <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          {m.role === "user" ? "You" : "micro:bit AI Co-Pilot"}
                        </div>
                        {m.text}
                      </div>
                    ))
                  )}
                  {chatBusy && (
                    <div className="flex items-center gap-2 rounded-xl border border-cyan-500/30 bg-slate-900 px-3 py-2 text-xs text-cyan-300">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Wiring 3D twin &amp; writing MicroPython...
                    </div>
                  )}
                </div>

                {/* Chat Composer */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleSendChat();
                  }}
                  className="flex gap-2 border-t border-white/10 pt-2.5"
                >
                  <Input
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="e.g. On lift say 'Weeee!', on left button play a chime..."
                    className="h-9 bg-slate-900 text-xs"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={chatBusy || !chatInput.trim()}
                    className="h-9 bg-cyan-600 px-3 text-white hover:bg-cyan-500 cursor-pointer"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </Button>
                </form>
              </CardContent>
            ) : (
              <CardContent className="flex flex-1 flex-col gap-2.5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void handleGenerateCode()}
                    className="h-7 gap-1 border-cyan-500/40 text-[11px] text-cyan-200 cursor-pointer"
                  >
                    <Wand2 className="h-3 w-3" /> Generate from Parts
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      const res = await updateMicrobitProject(project.id, { code: codeDraft });
                      setProject(res.project);
                      setNotice("Saved MicroPython code.");
                    }}
                    className="h-7 gap-1 text-[11px] cursor-pointer"
                  >
                    <Save className="h-3 w-3" /> Save
                  </Button>
                </div>

                <textarea
                  value={codeDraft}
                  onChange={(e) => setCodeDraft(e.target.value)}
                  spellCheck={false}
                  rows={16}
                  className="flex-1 rounded-xl border border-white/15 bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-emerald-200 focus:border-cyan-400 focus:outline-none"
                />

                <div className="rounded-xl border border-white/10 bg-black/80 p-2.5">
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Hardware Console (/dev/ttyACM0)
                  </div>
                  <pre className="max-h-24 overflow-y-auto whitespace-pre-wrap font-mono text-[10px] text-slate-300">
                    {consoleLog}
                  </pre>
                </div>
              </CardContent>
            )}
          </Card>
        </div>
      </div>

      {/* New Project Modal */}
      {newProjOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-4 rounded-2xl border border-white/15 bg-slate-950 p-5 text-slate-100 shadow-2xl">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-amber-400" /> New micro:bit v2.2 Prototype Project
            </h3>
            <Input
              value={newProjName}
              onChange={(e) => setNewProjName(e.target.value)}
              placeholder="Project name"
              className="h-9 bg-slate-900 text-xs"
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setNewProjOpen(false)} className="cursor-pointer">
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={async () => {
                  const res = await createMicrobitProject({ name: newProjName });
                  setNewProjOpen(false);
                  await hydrate(res.project.id);
                }}
                className="bg-cyan-600 text-white hover:bg-cyan-500 cursor-pointer"
              >
                Create Project
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
