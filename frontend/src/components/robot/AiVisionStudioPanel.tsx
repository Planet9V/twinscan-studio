"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Brain,
  Camera,
  CheckCircle2,
  Crosshair,
  Edit3,
  Eye,
  Gauge,
  Loader2,
  PawPrint,
  Pipette,
  RefreshCw,
  Save,
  ScanFace,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Upload,
  UserPlus,
  Users,
  Volume2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { OverwatchHudCard } from "@/components/vision/OverwatchHudCard";
import { SpatialMemoryGallery } from "@/components/vision/SpatialMemoryGallery";
import { useStudio } from "@/context/StudioContext";
import { getFileUrl } from "@/lib/api";
import {
  armRobotSentry,
  clearSentryEvents,
  deepIdentifyFrame,
  deleteKnownPerson,
  disarmRobotSentry,
  enrollPersonFromCamera,
  enrollPersonFromUpload,
  fetchAiVisionState,
  fetchSentryEvents,
  fetchSentryStatus,
  getAiVisionStreamUrl,
  listKnownPeople,
  pickLineColor,
  selectAiVisionTarget,
  setAiVisionMode,
  updateKnownPerson,
  updateSentryConfig,
  type AiDetection,
  type AiVisionMode,
  type AiVisionState,
  type KnownPerson,
  type LineColorPreset,
  type SentryEvent,
  type SentryStatus,
} from "@/lib/aiVisionApi";
import {
  listSpatialMemory,
  type RobotRecord,
  type SpatialMemoryCounts,
} from "@/lib/robotApi";

interface AiVisionStudioPanelProps {
  robot: RobotRecord | null;
  activeRosMode: "ros1" | "ros2";
}

const VISION_MODES: { id: AiVisionMode; label: string; hint: string }[] = [
  { id: "raw", label: "Raw FPV", hint: "Annotated passthrough" },
  { id: "face_recognition", label: "Face Recognition", hint: "YuNet + SFace 128-D" },
  { id: "object_animal", label: "Animals & Objects", hint: "YOLO11n 80-class COCO" },
  { id: "track_follow", label: "Click-to-Track & Follow", hint: "Click video to lock" },
  { id: "line_follow", label: "Line Follow v2", hint: "Click line to pick color" },
  { id: "apriltag", label: "AprilTag", hint: "Fiducial tag overlay" },
];

const LINE_COLOR_PRESETS: { id: LineColorPreset; label: string; dot: string }[] = [
  { id: "black", label: "Black", dot: "bg-zinc-900 border border-white/40" },
  { id: "red", label: "Red", dot: "bg-red-500" },
  { id: "blue", label: "Blue", dot: "bg-sky-500" },
  { id: "green", label: "Green", dot: "bg-emerald-500" },
  { id: "yellow", label: "Yellow", dot: "bg-amber-400" },
  { id: "custom", label: "Custom", dot: "bg-eigenia-orange" },
];

const GREET_ACTIONS = [
  { value: "none", label: "None (Safe · No Leg Motion)" },
  { value: "wave.d6ac", label: "Wave (wave.d6ac)" },
  { value: "nod.d6ac", label: "Nod (nod.d6ac)" },
  { value: "shake_hands.d6ac", label: "Shake Hands (shake_hands.d6ac)" },
];

function resolveSnapshotSrc(
  snapshotUrl?: string | null,
  snapshotFileId?: string | null
): string | null {
  if (snapshotUrl) return getFileUrl(snapshotUrl);
  if (snapshotFileId) return getFileUrl(`/api/files/${encodeURIComponent(snapshotFileId)}`);
  return null;
}

function getSeverityBadgeVariant(severity: string): "fault" | "amber" | "sky" | "neutral" {
  const s = (severity || "").toLowerCase();
  if (s === "critical" || s === "high") return "fault";
  if (s === "medium" || s === "warn" || s === "warning") return "amber";
  if (s === "low" || s === "info") return "sky";
  return "neutral";
}

export function AiVisionStudioPanel({ robot, activeRosMode }: AiVisionStudioPanelProps) {
  const { spaces, activeSpaceId } = useStudio();
  const isRos2 = activeRosMode === "ros2";
  const robotId = robot?.id ?? null;

  const [activeTab, setActiveTab] = useState("live");
  const [visionState, setVisionState] = useState<AiVisionState | null>(null);
  const [streamNonce, setStreamNonce] = useState(0);
  const [streamError, setStreamError] = useState(false);
  const [clickPing, setClickPing] = useState<{ xPct: number; yPct: number } | null>(null);
  const [busyMode, setBusyMode] = useState(false);

  // Local safety & tuning control state synced with backend AiVisionState
  const [followEnabled, setFollowEnabled] = useState(false);
  const [lineFollowEnabled, setLineFollowEnabled] = useState(false);
  const [autoGreetEnabled, setAutoGreetEnabled] = useState(true);
  const [lidarStopM, setLidarStopM] = useState(0.35);
  const [targetFps, setTargetFps] = useState(10);
  const [confThreshold, setConfThreshold] = useState(0.4);
  const draggingSliderRef = useRef(false);

  // OpenRouter Deep Identify state
  const [speakVlm, setSpeakVlm] = useState(true);
  const [identifying, setIdentifying] = useState(false);
  const [vlmResult, setVlmResult] = useState<{
    description: string;
    objects: string[];
    animals: string[];
    spoken: boolean;
    model_used?: string;
  } | null>(null);

  // People Registry state
  const [people, setPeople] = useState<KnownPerson[]>([]);
  const [enrollName, setEnrollName] = useState("");
  const [enrollRole, setEnrollRole] = useState("Operator");
  const [enrollGreeting, setEnrollGreeting] = useState("");
  const [enrollAction, setEnrollAction] = useState("none");
  const [enrollAutoSpeak, setEnrollAutoSpeak] = useState(true);
  const [enrolling, setEnrolling] = useState(false);
  const [editingPersonId, setEditingPersonId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<{
    name: string;
    role: string;
    greeting_phrase: string;
    greet_action: string;
    auto_speak: boolean;
  }>({ name: "", role: "", greeting_phrase: "", greet_action: "none", auto_speak: true });

  // Add-On B: Semantic Spatial Memory Pro counts (managed inside SpatialMemoryGallery)
  const [memoryCounts, setMemoryCounts] = useState<SpatialMemoryCounts>({
    active: 0,
    archived: 0,
    total: 0,
  });

  // Add-On C: Sentry Guard Mode state
  const [sentryStatus, setSentryStatus] = useState<SentryStatus | null>(null);
  const [sentryEvents, setSentryEvents] = useState<SentryEvent[]>([]);
  const [watchMotion, setWatchMotion] = useState(true);
  const [watchUnknownFaces, setWatchUnknownFaces] = useState(true);
  const [watchAnimals, setWatchAnimals] = useState(false);
  const [speakChallenge, setSpeakChallenge] = useState(true);
  const [flashRgb, setFlashRgb] = useState(true);
  const [cooldownSec, setCooldownSec] = useState(20);
  const [customChallenge, setCustomChallenge] = useState("");
  const [sentryBusy, setSentryBusy] = useState<string | null>(null);

  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  // V5 MJPEG Socket Leak Fix: abort open MJPEG connection on unmount or when leaving live tab
  const abortStreamSocket = useCallback(() => {
    if (imgRef.current) {
      imgRef.current.src = "";
    }
  }, []);

  useEffect(() => {
    return () => {
      abortStreamSocket();
    };
  }, [abortStreamSocket]);

  const loadPeople = useCallback(async () => {
    try {
      const resp = await listKnownPeople();
      setPeople(Array.isArray(resp.people) ? resp.people : []);
    } catch {
      // Non-fatal on initial load
    }
  }, []);

  const loadMemoryCounts = useCallback(async () => {
    try {
      const resp = await listSpatialMemory({ status: "active", limit: 1 });
      setMemoryCounts(resp.counts);
    } catch {
      // Non-fatal
    }
  }, []);

  const hydrateSentryForm = useCallback((st: SentryStatus) => {
    setSentryStatus(st);
    setWatchMotion(Boolean(st.watch_motion));
    setWatchUnknownFaces(Boolean(st.watch_unknown_faces));
    setWatchAnimals(Boolean(st.watch_animals));
    setSpeakChallenge(Boolean(st.speak_challenge));
    setFlashRgb(Boolean(st.flash_rgb));
    if (typeof st.cooldown_sec === "number" && Number.isFinite(st.cooldown_sec)) {
      setCooldownSec(st.cooldown_sec);
    }
    setCustomChallenge(st.custom_challenge ?? "");
  }, []);

  const loadSentryAll = useCallback(
    async (id: string, hydrateForm = true) => {
      try {
        const [st, ev] = await Promise.all([
          fetchSentryStatus(id).catch(() => null),
          fetchSentryEvents(id, 40).catch(() => null),
        ]);
        if (st) {
          if (hydrateForm) {
            hydrateSentryForm(st);
          } else {
            setSentryStatus(st);
          }
        }
        if (ev && Array.isArray(ev.events)) {
          setSentryEvents(ev.events);
        }
      } catch {
        // Non-fatal
      }
    },
    [hydrateSentryForm]
  );

  const syncFromState = useCallback((st: AiVisionState) => {
    setVisionState(st);
    setFollowEnabled(Boolean(st.follow_enabled));
    setLineFollowEnabled(Boolean(st.line_follow_enabled));
    setAutoGreetEnabled(Boolean(st.auto_greet_enabled));
    if (!draggingSliderRef.current) {
      if (typeof st.lidar_stop_m === "number" && Number.isFinite(st.lidar_stop_m)) {
        setLidarStopM(st.lidar_stop_m);
      }
      if (typeof st.target_fps === "number" && Number.isFinite(st.target_fps)) {
        setTargetFps(st.target_fps);
      }
      if (typeof st.conf_threshold === "number" && Number.isFinite(st.conf_threshold)) {
        setConfThreshold(st.conf_threshold);
      }
    }
  }, []);

  useEffect(() => {
    void loadPeople();
    void loadMemoryCounts();
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      const tabParam = sp.get("tab");
      if (tabParam === "live" || tabParam === "memory" || tabParam === "sentry") {
        setActiveTab(tabParam);
      }
    }
  }, [loadPeople, loadMemoryCounts]);

  useEffect(() => {
    if (!robotId) {
      setVisionState(null);
      setSentryStatus(null);
      setSentryEvents([]);
      return;
    }
    let cancelled = false;
    void loadSentryAll(robotId, true);

    const poll = () => {
      fetchAiVisionState(robotId)
        .then((st) => {
          if (!cancelled && st) syncFromState(st);
        })
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 1400);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [robotId, syncFromState, loadSentryAll]);

  // Poll Sentry events & armed state while Sentry tab is open or armed
  useEffect(() => {
    if (!robotId) return;
    if (activeTab !== "sentry" && !sentryStatus?.armed) return;
    const timer = setInterval(() => {
      void loadSentryAll(robotId, false);
    }, 3000);
    return () => clearInterval(timer);
  }, [robotId, activeTab, sentryStatus?.armed, loadSentryAll]);

  if (!robot || !robotId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <Bot className="h-10 w-10 text-eigenia-orange/60" />
          <div className="text-sm font-semibold text-white">No Robot Selected for AI Vision Studio</div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a PuppyPi robot to launch Face Recognition, Animal & Object Detection, Click-to-Track,
            Spatial Memory, and Autonomous Sentry Guard Mode.
          </p>
        </CardContent>
      </Card>
    );
  }

  const currentMode: AiVisionMode = visionState?.mode ?? "raw";
  const detections: AiDetection[] = Array.isArray(visionState?.detections)
    ? visionState!.detections
    : [];
  const cameraConnected = visionState?.camera_connected;
  const lostFrames = Number(visionState?.lost_frames ?? 0);
  const isLostTarget = Boolean(visionState?.tracked_target) && lostFrames >= 5;

  const handleReconnectStream = () => {
    abortStreamSocket();
    setStreamError(false);
    setStreamNonce((n) => n + 1);
  };

  const handleTabChange = (nextTab: string) => {
    if (activeTab === "live" && nextTab !== "live") {
      abortStreamSocket();
    }
    setActiveTab(nextTab);
    if (nextTab === "sentry") {
      void loadSentryAll(robotId, false);
    } else if (nextTab === "live") {
      setStreamError(false);
      setStreamNonce((n) => n + 1);
    }
  };

  const applyVisionSettings = async (
    overrides: Partial<{
      mode: AiVisionMode;
      follow_enabled: boolean;
      line_follow_enabled: boolean;
      auto_greet_enabled: boolean;
      lidar_stop_m: number;
      line_color: LineColorPreset;
      target_fps: number;
      conf_threshold: number;
    }>
  ) => {
    setBusyMode(true);
    setBanner(null);
    try {
      const next = await setAiVisionMode(robotId, {
        mode: overrides.mode ?? currentMode,
        follow_enabled: overrides.follow_enabled ?? followEnabled,
        line_follow_enabled: overrides.line_follow_enabled ?? lineFollowEnabled,
        auto_greet_enabled: overrides.auto_greet_enabled ?? autoGreetEnabled,
        lidar_stop_m: overrides.lidar_stop_m ?? lidarStopM,
        line_color: overrides.line_color ?? visionState?.line_color ?? "black",
        target_fps: overrides.target_fps ?? targetFps,
        conf_threshold: overrides.conf_threshold ?? confThreshold,
      });
      syncFromState(next);
      setStreamError(false);
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to update AI Vision mode",
      });
    } finally {
      setBusyMode(false);
    }
  };

  const handleStopTrackFollow = async () => {
    setBusyMode(true);
    setBanner(null);
    try {
      await selectAiVisionTarget(robotId, { norm_x: 0.5, norm_y: 0.5, clear: true });
      const next = await setAiVisionMode(robotId, {
        mode: currentMode,
        follow_enabled: false,
        line_follow_enabled: false,
        auto_greet_enabled: autoGreetEnabled,
        lidar_stop_m: lidarStopM,
        line_color: visionState?.line_color ?? "black",
        target_fps: targetFps,
        conf_threshold: confThreshold,
      });
      syncFromState(next);
      setBanner({ kind: "ok", text: "Stopped autonomous tracking & line following cleanly." });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to stop tracking",
      });
    } finally {
      setBusyMode(false);
    }
  };

  const handleVideoClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = (imgRef.current ?? e.currentTarget).getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const normX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const normY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    setClickPing({ xPct: normX * 100, yPct: normY * 100 });
    setTimeout(() => setClickPing(null), 900);

    if (currentMode === "line_follow") {
      try {
        const next = await pickLineColor(robotId, { norm_x: normX, norm_y: normY });
        syncFromState(next);
        setBanner({
          kind: "ok",
          text: `Picked custom line color at (${(normX * 100).toFixed(0)}%, ${(normY * 100).toFixed(0)}%)!`,
        });
      } catch (err) {
        setBanner({
          kind: "error",
          text: err instanceof Error ? err.message : "Color eyedropper failed",
        });
      }
      return;
    }

    if (currentMode === "track_follow" || currentMode === "object_animal") {
      try {
        const next = await selectAiVisionTarget(robotId, { norm_x: normX, norm_y: normY });
        syncFromState(next);
        setBanner({
          kind: "ok",
          text: `Locked target at (${(normX * 100).toFixed(0)}%, ${(normY * 100).toFixed(0)}%) — ${
            next.tracked_target?.label || "Target Acquired"
          }.`,
        });
      } catch (err) {
        setBanner({
          kind: "error",
          text: err instanceof Error ? err.message : "Target selection failed",
        });
      }
    }
  };

  const handleTrackDetection = async (det: AiDetection) => {
    const [x1, y1, x2, y2] =
      Array.isArray(det.bbox_norm) && det.bbox_norm.length >= 4
        ? det.bbox_norm
        : [0.4, 0.4, 0.6, 0.6];
    const cx = Math.max(0, Math.min(1, (x1 + x2) / 2));
    const cy = Math.max(0, Math.min(1, (y1 + y2) / 2));
    try {
      await setAiVisionMode(robotId, {
        mode: "track_follow",
        follow_enabled: followEnabled,
        line_follow_enabled: false,
        auto_greet_enabled: autoGreetEnabled,
        lidar_stop_m: lidarStopM,
        target_fps: targetFps,
        conf_threshold: confThreshold,
      });
      const next = await selectAiVisionTarget(robotId, { norm_x: cx, norm_y: cy });
      syncFromState(next);
      setBanner({
        kind: "ok",
        text: `Tracking "${det.label}" (${Math.round(det.confidence * 100)}%).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to track detection",
      });
    }
  };

  const handleDeepIdentify = async () => {
    setIdentifying(true);
    setBanner(null);
    try {
      const res = await deepIdentifyFrame(robotId, { speak_result: speakVlm });
      setVlmResult(res);
      setBanner({
        kind: "ok",
        text: `OpenRouter VLM identified scene${res.spoken ? " and spoke answer on PuppyPi speaker" : ""}.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "OpenRouter Deep Identify failed",
      });
    } finally {
      setIdentifying(false);
    }
  };

  const handleEnrollCamera = async () => {
    if (!enrollName.trim()) {
      setBanner({ kind: "error", text: "Enter a person's name before enrolling." });
      return;
    }
    setEnrolling(true);
    setBanner(null);
    try {
      const res = await enrollPersonFromCamera(robotId, {
        name: enrollName.trim(),
        role: enrollRole.trim() || "Guest",
        greeting_phrase: enrollGreeting.trim() || `Hello ${enrollName.trim()}!`,
        greet_action: enrollAction,
        auto_speak: enrollAutoSpeak,
      });
      setEnrollName("");
      setEnrollGreeting("");
      await loadPeople();
      setBanner({
        kind: "ok",
        text: `Enrolled "${res.person.name}" from live PuppyPi FPV (${
          res.face_detected ? "128-D face embedding saved" : "saved — snap again closer for face vector"
        }).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Camera face enrollment failed",
      });
    } finally {
      setEnrolling(false);
    }
  };

  const handleEnrollUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!enrollName.trim()) {
      setBanner({ kind: "error", text: "Enter a person's name before uploading a face photo." });
      e.target.value = "";
      return;
    }
    setEnrolling(true);
    setBanner(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", enrollName.trim());
      fd.append("role", enrollRole.trim() || "Guest");
      fd.append("greeting_phrase", enrollGreeting.trim() || `Hello ${enrollName.trim()}!`);
      fd.append("greet_action", enrollAction);
      fd.append("auto_speak", String(enrollAutoSpeak));
      const res = await enrollPersonFromUpload(fd);
      setEnrollName("");
      setEnrollGreeting("");
      await loadPeople();
      setBanner({
        kind: "ok",
        text: `Enrolled "${res.person.name}" from uploaded photo (${
          res.face_detected ? "face embedding extracted" : "no face detected in photo"
        }).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Photo enrollment failed",
      });
    } finally {
      setEnrolling(false);
      e.target.value = "";
    }
  };

  const handleSaveEditPerson = async (personId: string) => {
    try {
      await updateKnownPerson(personId, editDraft);
      setEditingPersonId(null);
      await loadPeople();
      setBanner({ kind: "ok", text: "Updated person profile in PostgreSQL 18." });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to update person",
      });
    }
  };

  const handleDeletePerson = async (person: KnownPerson) => {
    try {
      await deleteKnownPerson(person.id);
      await loadPeople();
      setBanner({ kind: "ok", text: `Deleted "${person.name}" and face embeddings.` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete person",
      });
    }
  };

  // Add-On C: Sentry Guard Mode handlers
  const handleToggleSentryArm = async () => {
    setSentryBusy("arm");
    setBanner(null);
    try {
      const next = sentryStatus?.armed
        ? await disarmRobotSentry(robotId)
        : await armRobotSentry(robotId);
      hydrateSentryForm(next);
      await loadSentryAll(robotId, false);
      setBanner({
        kind: "ok",
        text: next.armed
          ? "Sentry Guard Mode ARMED — monitoring LiDAR motion, unknown faces & animals."
          : "Sentry Guard Mode DISARMED.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to toggle Sentry Guard arm state",
      });
    } finally {
      setSentryBusy(null);
    }
  };

  const handleSaveSentryRules = async () => {
    setSentryBusy("save");
    setBanner(null);
    try {
      const next = await updateSentryConfig(robotId, {
        watch_motion: watchMotion,
        watch_unknown_faces: watchUnknownFaces,
        watch_animals: watchAnimals,
        speak_challenge: speakChallenge,
        flash_rgb: flashRgb,
        cooldown_sec: cooldownSec,
        custom_challenge: customChallenge.trim(),
      });
      hydrateSentryForm(next);
      setBanner({ kind: "ok", text: "Saved Sentry Guard rules to PostgreSQL 18." });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to save Sentry Guard rules",
      });
    } finally {
      setSentryBusy(null);
    }
  };

  const handleClearSentryEvents = async () => {
    setSentryBusy("clear");
    setBanner(null);
    try {
      const res = await clearSentryEvents(robotId);
      setSentryEvents([]);
      await loadSentryAll(robotId, false);
      setBanner({ kind: "ok", text: `Cleared ${res.cleared} Sentry security alert(s).` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to clear Sentry alerts",
      });
    } finally {
      setSentryBusy(null);
    }
  };

  const streamUrl = `${getAiVisionStreamUrl(robotId)}?_n=${streamNonce}`;
  const isClickableMode =
    currentMode === "track_follow" ||
    currentMode === "object_animal" ||
    currentMode === "line_follow";

  return (
    <div className="flex flex-col gap-4">
      <WorkspaceHeader
        badge="AI VISION"
        title="VISION, SPATIAL MEMORY & SENTRY"
        subtitle={`${robot.name} (${robot.ip_address}) · ${isRos2 ? "ROS 2 Humble" : "ROS 1 Noetic"} · Mode: ${currentMode.replace("_", " ")}`}
        statusTone={
          cameraConnected === false
            ? "fault"
            : cameraConnected === true
              ? "ok"
              : "idle"
        }
        statusLabel={
          cameraConnected === false
            ? "CAMERA OFFLINE"
            : cameraConnected === true
              ? `CAMERA LIVE · ${visionState ? `${visionState.fps.toFixed(1)} FPS` : "--"}`
              : "CAMERA PROBING"
        }
        metrics={[
          {
            label: "Enrolled People",
            value: people.length,
            tone: "sky",
            compact: true,
          },
          {
            label: "Spatial Sightings",
            value: memoryCounts.active,
            tone: "orange",
            compact: true,
          },
          {
            label: "Live Detections",
            value: detections.length,
            tone: detections.length > 0 ? "emerald" : "default",
            compact: true,
          },
          {
            label: "Sentry Guard",
            value: sentryStatus?.armed ? "ARMED" : "STANDBY",
            tone: sentryStatus?.armed ? "fault" : "default",
            pulse: Boolean(sentryStatus?.armed),
            compact: true,
          },
        ]}
        actions={
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              void loadPeople();
              void loadMemoryCounts();
              void loadSentryAll(robotId, false);
              if (activeTab === "live") handleReconnectStream();
            }}
            title="Refresh AI Vision telemetry, People & Spatial Memory"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
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

      {/* Camera / Vision Engine Error Alert */}
      {(cameraConnected === false || Boolean(visionState?.last_error)) && (
        <div
          role="alert"
          className="flex flex-col gap-2 rounded-lg border border-eigenia-fault/60 bg-eigenia-fault/15 px-3.5 py-2.5 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-eigenia-fault" />
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-eigenia-fault">
                {cameraConnected === false
                  ? "PuppyPi Camera Stream Offline"
                  : "AI Vision Engine Warning"}
              </div>
              <div className="font-mono text-[11px] text-eigenia-ink">
                {visionState?.last_error ||
                  "Camera feed is not delivering frames from web_video_server (:8080). Verify ROS 2 camera node is running."}
              </div>
            </div>
          </div>
          <Button
            size="sm"
            variant="destructive"
            className="shrink-0"
            onClick={handleReconnectStream}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Reconnect Camera
          </Button>
        </div>
      )}

      {/* 3-Subtab Organization */}
      <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
        <TabsList className="flex h-auto flex-wrap">
          <TabsTrigger value="live">
            <ScanFace className="h-3.5 w-3.5" />
            Live AI Vision &amp; People
          </TabsTrigger>
          <TabsTrigger value="memory">
            <Brain className="h-3.5 w-3.5" />
            Spatial Memory ({memoryCounts.active})
          </TabsTrigger>
          <TabsTrigger value="sentry">
            {sentryStatus?.armed ? (
              <ShieldAlert className="h-3.5 w-3.5 text-eigenia-fault" />
            ) : (
              <Shield className="h-3.5 w-3.5" />
            )}
            Sentry Guard Mode
            {sentryStatus?.armed && (
              <span className="ml-1 inline-block h-2 w-2 animate-pulse rounded-full bg-eigenia-fault" />
            )}
          </TabsTrigger>
        </TabsList>

        {/* TAB 1: LIVE AI VISION & PEOPLE */}
        <TabsContent value="live" className="space-y-4">
          {/* Mode Selector Bar */}
          <Card className={isRos2 ? "border-eigenia-orange/55" : undefined}>
            <CardHeader className="gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  <ScanFace className="h-4 w-4 text-eigenia-orange" />
                  AI Vision Studio — Faces, Animals, Click-to-Track &amp; Line Follow v2
                </CardTitle>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={isRos2 ? "default" : "sky"}>
                    {isRos2 ? "ROS 2 HUMBLE AI" : "ROS 1 NOETIC AI"}
                  </Badge>
                  <Badge
                    variant={cameraConnected === false ? "fault" : "sky"}
                    className={
                      cameraConnected === true
                        ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
                        : undefined
                    }
                  >
                    {cameraConnected === false ? (
                      <>
                        <WifiOff className="h-3 w-3" /> Camera: OFFLINE
                      </>
                    ) : (
                      <>
                        <Wifi className="h-3 w-3" /> Camera:{" "}
                        {cameraConnected === true ? "LIVE" : "PROBING"}
                      </>
                    )}
                  </Badge>
                  <Badge variant="neutral" className="tabular-nums">
                    {visionState ? `${visionState.fps.toFixed(1)} FPS` : "-- FPS"}
                  </Badge>
                  {isLostTarget && (
                    <Badge variant="amber" className="animate-pulse font-mono text-[9px]">
                      <AlertTriangle className="h-3 w-3" />
                      LOST TARGET ({lostFrames}f)
                    </Badge>
                  )}
                  {visionState?.models_ready &&
                    Object.entries(visionState.models_ready).map(([k, ready]) => (
                      <Badge
                        key={k}
                        variant={ready ? "sky" : "amber"}
                        className="text-[9px]"
                      >
                        {k}: {ready ? "ONNX" : "Fallback"}
                      </Badge>
                    ))}
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {VISION_MODES.map((m) => (
                  <Button
                    key={m.id}
                    size="sm"
                    variant={currentMode === m.id ? "default" : "secondary"}
                    disabled={busyMode}
                    className="h-auto flex-col items-start px-3 py-1.5 text-left"
                    onClick={() => void applyVisionSettings({ mode: m.id })}
                  >
                    <span className="text-xs font-semibold">{m.label}</span>
                    <span className="font-mono text-[9px] opacity-75">{m.hint}</span>
                  </Button>
                ))}
              </div>
            </CardHeader>
          </Card>

          {/* Collapsible HD Overwatch Room Cam (4K/1080p) */}
          <OverwatchHudCard compact defaultVisible={false} />

          {/* Main Split: Interactive Annotated MJPEG Video + Safety & VLM Controls */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            {/* Annotated MJPEG Video + Click-to-Track / Color Picker */}
            <Card className={`flex flex-col xl:col-span-7 ${isRos2 ? "border-eigenia-orange/50" : ""}`}>
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  <Eye className="h-3.5 w-3.5 text-eigenia-sky" />
                  Live AI Annotated Stream
                  {isClickableMode && (
                    <Badge variant="default" className="text-[9px]">
                      {currentMode === "line_follow" ? (
                        <>
                          <Pipette className="h-2.5 w-2.5" /> Click Line to Pick Color
                        </>
                      ) : (
                        <>
                          <Crosshair className="h-2.5 w-2.5" /> Click Video to Track Target
                        </>
                      )}
                    </Badge>
                  )}
                </CardTitle>
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-7 px-2"
                  onClick={handleReconnectStream}
                  title="Reconnect AI Vision MJPEG Stream"
                >
                  <RefreshCw className="h-3 w-3" />
                </Button>
              </CardHeader>

              <CardContent className="space-y-3">
                <div
                  onClick={isClickableMode ? (e) => void handleVideoClick(e) : undefined}
                  className={`relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian ${
                    isClickableMode ? "cursor-crosshair" : ""
                  }`}
                >
                  {!streamError ? (
                    <img
                      ref={imgRef}
                      key={streamUrl}
                      src={streamUrl}
                      alt="PuppyPi AI Vision Annotated Stream"
                      className="h-full w-full object-contain select-none"
                      onError={() => setStreamError(true)}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-2 p-6 text-center">
                      <Camera className="h-7 w-7 text-eigenia-muted" />
                      <div className="text-xs font-medium text-white">AI Vision Stream Disconnected</div>
                      <Button size="sm" variant="sky" onClick={handleReconnectStream}>
                        Reconnect AI Stream
                      </Button>
                    </div>
                  )}

                  {clickPing && (
                    <div
                      className="pointer-events-none absolute h-8 w-8 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-eigenia-orange bg-eigenia-orange/20 animate-ping"
                      style={{ left: `${clickPing.xPct}%`, top: `${clickPing.yPct}%` }}
                    />
                  )}

                  {isLostTarget && (
                    <div className="pointer-events-none absolute left-2.5 top-2.5 rounded border border-eigenia-amber/70 bg-eigenia-obsidian/90 px-2 py-1 font-mono text-[10px] font-semibold text-eigenia-amber">
                      LOST TARGET · {lostFrames} frames
                    </div>
                  )}

                  {visionState?.tracked_target && (
                    <div className="pointer-events-none absolute bottom-2.5 left-2.5 rounded border border-eigenia-orange/60 bg-eigenia-obsidian/85 px-2 py-1 font-mono text-[10px] text-eigenia-orange">
                      LOCKED: {visionState.tracked_target.label}
                    </div>
                  )}
                  {visionState?.last_greeting && (
                    <div className="pointer-events-none absolute bottom-2.5 right-2.5 rounded border border-emerald-500/50 bg-eigenia-obsidian/85 px-2 py-1 font-mono text-[10px] text-emerald-400">
                      {visionState.last_greeting}
                    </div>
                  )}
                </div>

                {/* Line Follow v2 Color Preset Pills */}
                {currentMode === "line_follow" && (
                  <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <span className="mr-1 font-mono text-[10px] uppercase text-eigenia-muted">
                      Line Color:
                    </span>
                    {LINE_COLOR_PRESETS.map((c) => (
                      <Button
                        key={c.id}
                        size="sm"
                        variant={visionState?.line_color === c.id ? "default" : "secondary"}
                        className="h-6 gap-1.5 px-2 text-[10px]"
                        onClick={() =>
                          void applyVisionSettings({ mode: "line_follow", line_color: c.id })
                        }
                      >
                        <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} />
                        {c.label}
                      </Button>
                    ))}
                  </div>
                )}

                {/* Live Detections Strip */}
                <div className="space-y-1.5">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                    Live Detections ({detections.length})
                  </div>
                  {detections.length === 0 ? (
                    <div className="rounded border border-dashed border-white/10 bg-eigenia-obsidian/60 px-3 py-2 font-mono text-[10px] text-eigenia-muted">
                      No active detections in current frame — switch mode or point PuppyPi camera at a
                      face, pet, or object.
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {detections.map((det) => {
                        const isAnimal = Boolean(det.is_animal || det.kind === "animal");
                        const isFace = det.kind === "face";
                        return (
                          <div
                            key={det.id}
                            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[10px] ${
                              det.tracked
                                ? "border-eigenia-orange bg-eigenia-orange/20 text-white"
                                : isAnimal
                                  ? "border-eigenia-amber/50 bg-eigenia-amber/15 text-eigenia-amber"
                                  : isFace
                                    ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
                                    : "border-eigenia-sky/35 bg-eigenia-sky/10 text-eigenia-sky"
                            }`}
                          >
                            {isAnimal && <PawPrint className="h-3 w-3" />}
                            {isFace && <ScanFace className="h-3 w-3" />}
                            <span className="font-semibold">{det.label}</span>
                            <span className="tabular-nums opacity-80">
                              {Math.round(det.confidence * 100)}%
                            </span>
                            <button
                              type="button"
                              onClick={() => void handleTrackDetection(det)}
                              className="ml-1 rounded bg-white/10 px-1.5 py-0.5 text-[9px] text-white hover:bg-eigenia-orange"
                            >
                              Track
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Right Column: Live FPS/Confidence Tuning + Safety & Autonomy + Deep Identify */}
            <div className="flex flex-col gap-4 xl:col-span-5">
              {/* Live Vision Performance Tuning */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Gauge className="h-3.5 w-3.5 text-eigenia-sky" />
                    Real-Time Vision Tuning (FPS &amp; Confidence)
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-eigenia-muted">Target Vision FPS</span>
                      <span className="tabular-nums font-semibold text-eigenia-sky">
                        {targetFps} FPS
                      </span>
                    </div>
                    <Slider
                      min={2}
                      max={20}
                      step={1}
                      value={[targetFps]}
                      onValueChange={([v]) => {
                        draggingSliderRef.current = true;
                        setTargetFps(v);
                      }}
                      onValueCommit={([v]) => {
                        draggingSliderRef.current = false;
                        void applyVisionSettings({ target_fps: v });
                      }}
                    />
                  </div>

                  <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-eigenia-muted">Detection Confidence</span>
                      <span className="tabular-nums font-semibold text-eigenia-orange">
                        {confThreshold.toFixed(2)} ({Math.round(confThreshold * 100)}%)
                      </span>
                    </div>
                    <Slider
                      min={0.2}
                      max={0.8}
                      step={0.05}
                      value={[confThreshold]}
                      onValueChange={([v]) => {
                        draggingSliderRef.current = true;
                        setConfThreshold(v);
                      }}
                      onValueCommit={([v]) => {
                        draggingSliderRef.current = false;
                        void applyVisionSettings({ conf_threshold: Number(v.toFixed(2)) });
                      }}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Safety & Autonomy Toggles */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 text-eigenia-amber" />
                    Autonomy &amp; LiDAR Safety Controls
                  </CardTitle>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busyMode}
                    onClick={() => void handleStopTrackFollow()}
                  >
                    <Square className="h-3 w-3" />
                    STOP TRACK/FOLLOW
                  </Button>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div>
                      <div className="text-xs font-medium text-white">Follow Target (Auto-Move)</div>
                      <div className="text-[10px] text-eigenia-muted">
                        PD yaw + forward/reverse pursuit toward clicked target
                      </div>
                    </div>
                    <Switch
                      checked={followEnabled}
                      onCheckedChange={(v) => {
                        setFollowEnabled(v);
                        void applyVisionSettings({ follow_enabled: v });
                      }}
                    />
                  </div>

                  <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div>
                      <div className="text-xs font-medium text-white">Line Follow (Auto-Drive)</div>
                      <div className="text-[10px] text-eigenia-muted">
                        Autonomous steering along picked line color contour
                      </div>
                    </div>
                    <Switch
                      checked={lineFollowEnabled}
                      onCheckedChange={(v) => {
                        setLineFollowEnabled(v);
                        void applyVisionSettings({ line_follow_enabled: v });
                      }}
                    />
                  </div>

                  <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div>
                      <div className="text-xs font-medium text-white">Auto-Greet via Speaker</div>
                      <div className="text-[10px] text-eigenia-muted">
                        Speaks saved greeting on WonderEcho Pro (30s cooldown)
                      </div>
                    </div>
                    <Switch
                      checked={autoGreetEnabled}
                      onCheckedChange={(v) => {
                        setAutoGreetEnabled(v);
                        void applyVisionSettings({ auto_greet_enabled: v });
                      }}
                    />
                  </div>

                  <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-eigenia-muted">LD19 LiDAR Stop Distance</span>
                      <span className="tabular-nums font-semibold text-eigenia-orange">
                        {lidarStopM.toFixed(2)} m
                      </span>
                    </div>
                    <Slider
                      min={0.2}
                      max={1.0}
                      step={0.05}
                      value={[lidarStopM]}
                      onValueChange={([v]) => {
                        draggingSliderRef.current = true;
                        setLidarStopM(v);
                      }}
                      onValueCommit={([v]) => {
                        draggingSliderRef.current = false;
                        void applyVisionSettings({ lidar_stop_m: v });
                      }}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Deep Identify with OpenRouter VLM */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5 text-eigenia-orange" />
                    Deep Identify with OpenRouter VLM
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-eigenia-ink">
                      <input
                        type="checkbox"
                        checked={speakVlm}
                        onChange={(e) => setSpeakVlm(e.target.checked)}
                        className="h-3.5 w-3.5 accent-eigenia-orange"
                      />
                      <Volume2 className="h-3.5 w-3.5 text-eigenia-sky" />
                      Speak answer aloud on PuppyPi
                    </label>
                    <Button
                      size="sm"
                      variant="default"
                      disabled={identifying}
                      onClick={() => void handleDeepIdentify()}
                    >
                      {identifying ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      {identifying ? "Identifying..." : "Deep Identify Frame"}
                    </Button>
                  </div>

                  {vlmResult && (
                    <div className="space-y-2 rounded-md border border-eigenia-sky/35 bg-eigenia-obsidian p-3 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-1">
                        <span className="font-mono text-[10px] text-eigenia-sky">
                          {vlmResult.model_used || "OpenRouter VLM"}
                        </span>
                        {vlmResult.spoken && (
                          <Badge variant="sky" className="text-[9px]">
                            Spoken Aloud
                          </Badge>
                        )}
                      </div>
                      <p className="leading-relaxed text-white">{vlmResult.description}</p>
                      <div className="flex flex-wrap gap-1">
                        {vlmResult.animals.map((a) => (
                          <Badge key={`a-${a}`} variant="default" className="text-[9px]">
                            <PawPrint className="h-2.5 w-2.5" /> {a}
                          </Badge>
                        ))}
                        {vlmResult.objects.map((o) => (
                          <Badge key={`o-${o}`} variant="neutral" className="text-[9px]">
                            {o}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          {/* People Registry Card (Face Recognition + PG18 pgvector 128-D) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <Users className="h-4 w-4 text-eigenia-sky" />
                Known People Registry — SFace 128-D Recognition ({people.length})
              </CardTitle>
              <Button size="sm" variant="ghost" onClick={() => void loadPeople()}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              {/* Enroll Form */}
              <div className="space-y-3 rounded-md border border-white/10 bg-eigenia-obsidian p-3.5 lg:col-span-5">
                <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase text-eigenia-orange">
                  <UserPlus className="h-3.5 w-3.5" />
                  Enroll New Person
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    placeholder="Name (e.g. Jim)"
                    value={enrollName}
                    onChange={(e) => setEnrollName(e.target.value)}
                    className="text-xs"
                  />
                  <Input
                    placeholder="Role (e.g. Owner)"
                    value={enrollRole}
                    onChange={(e) => setEnrollRole(e.target.value)}
                    className="text-xs"
                  />
                </div>
                <Input
                  placeholder='Custom Greeting Phrase (e.g. "Hello Jim!")'
                  value={enrollGreeting}
                  onChange={(e) => setEnrollGreeting(e.target.value)}
                  className="text-xs"
                />
                <div className="space-y-1">
                  <label className="text-[10px] text-eigenia-muted">Opt-In Greet Action</label>
                  <select
                    value={enrollAction}
                    onChange={(e) => setEnrollAction(e.target.value)}
                    className="h-8 w-full rounded-md border border-white/15 bg-eigenia-shell px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                  >
                    {GREET_ACTIONS.map((ga) => (
                      <option key={ga.value} value={ga.value}>
                        {ga.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center justify-between rounded border border-white/10 bg-eigenia-shell px-2.5 py-1.5">
                  <span className="text-xs text-white">Auto-Speak Greeting</span>
                  <Switch checked={enrollAutoSpeak} onCheckedChange={setEnrollAutoSpeak} />
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button
                    size="sm"
                    className="flex-1"
                    disabled={enrolling || !enrollName.trim()}
                    onClick={() => void handleEnrollCamera()}
                  >
                    {enrolling ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Camera className="h-3.5 w-3.5" />
                    )}
                    Snap from Live Camera
                  </Button>
                  <label className="inline-flex h-7 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-md border border-eigenia-sky/40 bg-eigenia-sky/15 px-2.5 text-[11px] font-medium text-eigenia-sky hover:bg-eigenia-sky/25">
                    <Upload className="h-3.5 w-3.5" />
                    Upload Photo
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => void handleEnrollUpload(e)}
                    />
                  </label>
                </div>
              </div>

              {/* Saved People List */}
              <div className="space-y-2 lg:col-span-7">
                {people.length === 0 ? (
                  <div className="flex h-full min-h-[180px] flex-col items-center justify-center rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center text-xs text-eigenia-muted">
                    No people enrolled yet. Enter a name and snap from PuppyPi FPV or upload a portrait
                    photo.
                  </div>
                ) : (
                  people.map((p) => {
                    const isEditing = editingPersonId === p.id;
                    return (
                      <div
                        key={p.id}
                        className="rounded-md border border-white/10 bg-eigenia-obsidian p-3"
                      >
                        {isEditing ? (
                          <div className="space-y-2">
                            <div className="grid grid-cols-2 gap-2">
                              <Input
                                value={editDraft.name}
                                onChange={(e) =>
                                  setEditDraft({ ...editDraft, name: e.target.value })
                                }
                                placeholder="Name"
                                className="h-7 text-xs"
                              />
                              <Input
                                value={editDraft.role}
                                onChange={(e) =>
                                  setEditDraft({ ...editDraft, role: e.target.value })
                                }
                                placeholder="Role"
                                className="h-7 text-xs"
                              />
                            </div>
                            <Input
                              value={editDraft.greeting_phrase}
                              onChange={(e) =>
                                setEditDraft({ ...editDraft, greeting_phrase: e.target.value })
                              }
                              placeholder="Greeting Phrase"
                              className="h-7 text-xs"
                            />
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <select
                                value={editDraft.greet_action}
                                onChange={(e) =>
                                  setEditDraft({ ...editDraft, greet_action: e.target.value })
                                }
                                className="h-7 rounded border border-white/15 bg-eigenia-shell px-2 font-mono text-[11px] text-white"
                              >
                                {GREET_ACTIONS.map((ga) => (
                                  <option key={ga.value} value={ga.value}>
                                    {ga.label}
                                  </option>
                                ))}
                              </select>
                              <div className="flex items-center gap-1.5">
                                <Button
                                  size="sm"
                                  className="h-7 px-2 text-[10px]"
                                  onClick={() => void handleSaveEditPerson(p.id)}
                                >
                                  <Save className="h-3 w-3" /> Save
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2 text-[10px]"
                                  onClick={() => setEditingPersonId(null)}
                                >
                                  <X className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start gap-2.5">
                              {p.avatar_url ? (
                                <img
                                  src={getFileUrl(p.avatar_url)}
                                  alt={p.name}
                                  className="h-10 w-10 rounded-md border border-white/15 object-cover"
                                />
                              ) : (
                                <div className="flex h-10 w-10 items-center justify-center rounded-md border border-white/15 bg-eigenia-shell font-mono text-xs font-semibold text-eigenia-orange">
                                  {p.name.slice(0, 2).toUpperCase()}
                                </div>
                              )}
                              <div>
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span className="text-xs font-semibold text-white">{p.name}</span>
                                  <Badge variant="neutral" className="text-[9px]">
                                    {p.role || "Member"}
                                  </Badge>
                                  <Badge variant="sky" className="tabular-nums text-[9px]">
                                    {p.embedding_count}{" "}
                                    {p.embedding_count === 1 ? "sample" : "samples"}
                                  </Badge>
                                  {p.auto_speak && (
                                    <Badge variant="default" className="text-[9px]">
                                      <CheckCircle2 className="h-2.5 w-2.5" /> Auto-Speak
                                    </Badge>
                                  )}
                                </div>
                                <div className="mt-1 font-mono text-[10px] text-eigenia-ink">
                                  &quot;{p.greeting_phrase || `Hello ${p.name}!`}&quot; · Action:{" "}
                                  <span className="text-eigenia-sky">
                                    {p.greet_action || "none"}
                                  </span>
                                </div>
                                <div className="mt-0.5 font-mono text-[9px] text-eigenia-muted">
                                  Last seen:{" "}
                                  {p.last_seen_at
                                    ? new Date(p.last_seen_at).toLocaleString()
                                    : "Never"}
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                onClick={() => {
                                  setEditingPersonId(p.id);
                                  setEditDraft({
                                    name: p.name,
                                    role: p.role,
                                    greeting_phrase: p.greeting_phrase,
                                    greet_action: p.greet_action || "none",
                                    auto_speak: p.auto_speak,
                                  });
                                }}
                              >
                                <Edit3 className="h-3 w-3" />
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                className="h-7 px-2"
                                onClick={() => void handleDeletePerson(p)}
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: SPATIAL MEMORY PRO (ADD-ON B) */}
        <TabsContent value="memory" className="space-y-4">
          <SpatialMemoryGallery
            robotId={robotId}
            activeSpaceId={activeSpaceId}
            spaces={spaces}
            onBanner={setBanner}
            onCountChange={setMemoryCounts}
          />
        </TabsContent>

        {/* TAB 3: SENTRY GUARD MODE (ADD-ON C) */}
        <TabsContent value="sentry" className="space-y-4">
          {/* Armed / Disarmed Command Banner */}
          <Card
            className={
              sentryStatus?.armed
                ? "border-2 border-eigenia-fault/75 bg-gradient-to-r from-eigenia-fault/20 via-eigenia-surface to-eigenia-orange/15 shadow-md shadow-eigenia-fault/15"
                : "border-white/15 bg-eigenia-surface"
            }
          >
            <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${
                    sentryStatus?.armed
                      ? "animate-pulse border-eigenia-fault/70 bg-eigenia-fault/25 text-eigenia-fault"
                      : "border-white/15 bg-eigenia-obsidian text-eigenia-sky"
                  }`}
                >
                  {sentryStatus?.armed ? (
                    <ShieldAlert className="h-5 w-5" />
                  ) : (
                    <ShieldCheck className="h-5 w-5" />
                  )}
                </div>
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-white">
                      Autonomous Sentry Guard Mode
                    </span>
                    <Badge
                      variant={sentryStatus?.armed ? "fault" : "neutral"}
                      className={sentryStatus?.armed ? "animate-pulse font-mono text-[10px]" : "font-mono text-[10px]"}
                    >
                      {sentryStatus?.armed ? "ARMED · ACTIVE WATCH" : "DISARMED · STANDBY"}
                    </Badge>
                    <Badge variant="sky" className="font-mono text-[10px] tabular-nums">
                      {sentryStatus?.event_count ?? sentryEvents.length} Alert(s)
                    </Badge>
                  </div>
                  <p className="font-mono text-[11px] text-eigenia-muted">
                    {sentryStatus?.armed
                      ? `Actively fusing LiDAR motion tracks + AI vision detections · Last trigger: ${
                          sentryStatus.last_trigger || "None yet"
                        }`
                      : "Configure watch triggers below and arm PuppyPi to guard the room with photo evidence, RGB flash & spoken personality challenges."}
                  </p>
                </div>
              </div>

              <Button
                size="sm"
                variant={sentryStatus?.armed ? "destructive" : "default"}
                disabled={sentryBusy !== null}
                onClick={() => void handleToggleSentryArm()}
                className="shrink-0 font-semibold"
              >
                {sentryBusy === "arm" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : sentryStatus?.armed ? (
                  <Square className="h-4 w-4" />
                ) : (
                  <ShieldAlert className="h-4 w-4" />
                )}
                {sentryStatus?.armed ? "DISARM SENTRY" : "ARM SENTRY GUARD"}
              </Button>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            {/* Left: Sentry Guard Trigger Rules */}
            <Card className="xl:col-span-5">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Shield className="h-3.5 w-3.5 text-eigenia-orange" />
                  Guard Triggers &amp; Deterrence Rules
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div>
                    <div className="text-xs font-medium text-white">LiDAR Moving Objects</div>
                    <div className="text-[10px] text-eigenia-muted">
                      Trigger when 2D LiDAR detects velocity-tracked movement
                    </div>
                  </div>
                  <Switch checked={watchMotion} onCheckedChange={setWatchMotion} />
                </div>

                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div>
                    <div className="text-xs font-medium text-white">Unknown Faces</div>
                    <div className="text-[10px] text-eigenia-muted">
                      Trigger on faces not enrolled in Known People Registry
                    </div>
                  </div>
                  <Switch checked={watchUnknownFaces} onCheckedChange={setWatchUnknownFaces} />
                </div>

                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div>
                    <div className="text-xs font-medium text-white">Animals</div>
                    <div className="text-[10px] text-eigenia-muted">
                      Trigger when pets or wildlife enter the camera view
                    </div>
                  </div>
                  <Switch checked={watchAnimals} onCheckedChange={setWatchAnimals} />
                </div>

                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div>
                    <div className="text-xs font-medium text-white">
                      Spoken Personality Challenge
                    </div>
                    <div className="text-[10px] text-eigenia-muted">
                      Speak challenge aloud via WonderEcho Pro using OX&apos;s voice
                    </div>
                  </div>
                  <Switch checked={speakChallenge} onCheckedChange={setSpeakChallenge} />
                </div>

                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div>
                    <div className="text-xs font-medium text-white">RGB Alert Flash</div>
                    <div className="text-[10px] text-eigenia-muted">
                      Flash PuppyPi RGB LEDs red/orange on intrusion trigger
                    </div>
                  </div>
                  <Switch checked={flashRgb} onCheckedChange={setFlashRgb} />
                </div>

                <div className="space-y-1.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                  <div className="flex items-center justify-between font-mono text-[11px]">
                    <span className="text-eigenia-muted">Alert Cooldown</span>
                    <span className="tabular-nums font-semibold text-eigenia-orange">
                      {cooldownSec} s
                    </span>
                  </div>
                  <Slider
                    min={5}
                    max={120}
                    step={5}
                    value={[cooldownSec]}
                    onValueChange={([v]) => setCooldownSec(v)}
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] text-eigenia-muted">
                    Custom Spoken Challenge (optional)
                  </label>
                  <Input
                    value={customChallenge}
                    onChange={(e) => setCustomChallenge(e.target.value)}
                    placeholder='e.g. "Halt! Identify yourself to Eigenia Security."'
                    className="text-xs"
                  />
                </div>

                <Button
                  size="sm"
                  variant="sky"
                  disabled={sentryBusy !== null}
                  onClick={() => void handleSaveSentryRules()}
                  className="w-full"
                >
                  {sentryBusy === "save" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Save Rules
                </Button>
              </CardContent>
            </Card>

            {/* Right: Live Security Alert Feed */}
            <Card className="xl:col-span-7">
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  <ShieldAlert className="h-3.5 w-3.5 text-eigenia-fault" />
                  Live Security Alert Feed ({sentryEvents.length})
                </CardTitle>
                <div className="flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void loadSentryAll(robotId, false)}
                    title="Refresh Alerts"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={sentryBusy !== null || sentryEvents.length === 0}
                    onClick={() => void handleClearSentryEvents()}
                  >
                    {sentryBusy === "clear" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    Clear Events
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="max-h-[560px] space-y-2.5 overflow-y-auto">
                {sentryEvents.length === 0 ? (
                  <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center">
                    <ShieldCheck className="h-8 w-8 text-emerald-400/70" />
                    <div className="text-xs font-semibold text-white">Perimeter Clear</div>
                    <p className="max-w-sm text-[11px] text-eigenia-muted">
                      No Sentry Guard security alerts logged. Arm Sentry Guard Mode to monitor for
                      LiDAR movement, unknown faces, and animals.
                    </p>
                  </div>
                ) : (
                  sentryEvents.map((ev) => {
                    const snapSrc = resolveSnapshotSrc(ev.snapshot_url, ev.snapshot_file_id);
                    return (
                      <div
                        key={ev.id}
                        className="flex flex-col gap-3 rounded-md border border-white/10 bg-eigenia-obsidian p-3 sm:flex-row"
                      >
                        {snapSrc && (
                          <img
                            src={snapSrc}
                            alt={ev.label}
                            className="h-24 w-36 shrink-0 rounded border border-white/15 object-cover"
                          />
                        )}
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="flex flex-wrap items-center justify-between gap-1.5">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge
                                variant={getSeverityBadgeVariant(ev.severity)}
                                className="font-mono text-[9px] uppercase"
                              >
                                {ev.severity || "alert"}
                              </Badge>
                              <Badge variant="neutral" className="font-mono text-[9px] uppercase">
                                {ev.trigger_type}
                              </Badge>
                              <span className="text-xs font-semibold text-white">{ev.label}</span>
                            </div>
                            <span className="font-mono text-[10px] text-eigenia-muted">
                              {ev.created_at ? new Date(ev.created_at).toLocaleString() : ""}
                            </span>
                          </div>

                          {ev.detail && (
                            <p className="font-mono text-[11px] text-eigenia-ink">{ev.detail}</p>
                          )}

                          {ev.spoken_alert && (
                            <div className="flex items-start gap-1.5 rounded border border-eigenia-orange/30 bg-eigenia-orange/10 px-2 py-1 font-mono text-[10px] text-eigenia-orange">
                              <Volume2 className="mt-0.5 h-3 w-3 shrink-0" />
                              <span>Spoken: &quot;{ev.spoken_alert}&quot;</span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
