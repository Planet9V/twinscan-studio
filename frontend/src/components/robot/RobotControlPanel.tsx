"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BatteryCharging,
  Bot,
  Camera,
  Compass,
  Cpu,
  Eye,
  Footprints,
  Gamepad2,
  Layers,
  Lightbulb,
  Loader2,
  Monitor,
  Navigation,
  Radio,
  RefreshCw,
  RotateCcw,
  RotateCw,
  ScanFace,
  Search,
  Sliders,
  Sparkles,
  Square,
  Volume2,
  Wifi,
  WifiOff,
  Wrench,
} from "lucide-react";
import { AiVisionStudioPanel } from "@/components/robot/AiVisionStudioPanel";
import { PatrolPlannerPanel } from "@/components/robot/PatrolPlannerPanel";
import { VoiceControlPanel } from "@/components/robot/VoiceControlPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import {
  getAiVisionStreamUrl,
  setAiVisionMode,
  type AiVisionMode,
} from "@/lib/aiVisionApi";
import {
  getRobotRosbridgeWsUrl,
  getRobotVideoStreamUrl,
  runRobotAction,
  sendRobotBuzzer,
  sendRobotGait,
  sendRobotGoHome,
  sendRobotMarkTime,
  sendRobotOled,
  sendRobotPose,
  sendRobotRgb,
  sendRobotServo,
  sendRobotVelocity,
  setRobotVisionMode,
  triggerRobotEstop,
  updateRobotRos,
  type RobotRecord,
} from "@/lib/robotApi";

interface RobotControlPanelProps {
  robot: RobotRecord | null;
  onRefreshRobot: () => void;
  activeRosMode?: "ros1" | "ros2";
}

const ROS1_VIDEO_TOPICS = [
  { topic: "/usb_cam/image_raw", label: "USB Cam Raw (ROS 1)" },
  { topic: "/apriltag_detect/image_result", label: "AprilTag Detect (runs sit/handshake/lie_down)" },
  { topic: "/color_detect/image_result", label: "Color Detect (runs sit + nod/shake)" },
  { topic: "/face_detect/image_result", label: "Face Detect (runs sit + shake_hands)" },
  { topic: "/object_tracking/image_result", label: "Object Tracking (autonomous chase)" },
  { topic: "/visual_patrol/image_result", label: "Visual Patrol (autonomous line patrol)" },
  { topic: "/lab_config_manager/image_result", label: "LAB Threshold" },
] as const;

const ROS2_VIDEO_TOPICS = [
  { topic: "/image_raw", label: "Camera Raw (/image_raw)" },
  { topic: "ai:face_recognition", label: "AI Face Recognition (YuNet + SFace)" },
  { topic: "ai:object_animal", label: "AI Animals & Objects (YOLO11n)" },
  { topic: "ai:track_follow", label: "AI Track & Follow" },
  { topic: "ai:line_follow", label: "AI Line Follow v2" },
  { topic: "ai:apriltag", label: "AI AprilTag (36h11)" },
] as const;

const ROS1_CV_APP_DECK = [
  {
    mode: "visual_patrol",
    label: "Visual Patrol",
    topic: "/visual_patrol/image_result",
    desc: "Autonomous line patrol",
    movesLegs: true,
  },
  {
    mode: "apriltag_detect",
    label: "AprilTag Detect",
    topic: "/apriltag_detect/image_result",
    desc: "Runs sit / handshake / lie_down",
    movesLegs: true,
  },
  {
    mode: "color_detect",
    label: "Color Detect",
    topic: "/color_detect/image_result",
    desc: "Runs sit + nod / shake_head",
    movesLegs: true,
  },
  {
    mode: "face_detect",
    label: "Face Detect",
    topic: "/face_detect/image_result",
    desc: "Runs sit + shake_hands",
    movesLegs: true,
  },
  {
    mode: "object_tracking",
    label: "Object Tracking",
    topic: "/object_tracking/image_result",
    desc: "Autonomous target chase",
    movesLegs: true,
  },
  {
    mode: "lab_config_manager",
    label: "LAB Threshold",
    topic: "/lab_config_manager/image_result",
    desc: "Color mask calibration",
    movesLegs: false,
  },
] as const;

const ROS2_AUTONOMY_STACK = [
  { name: "slam_toolbox 2.6.8", role: "SLAM", desc: "Lifelong 2D pose-graph mapping & loop closure" },
  { name: "Nav2 1.1.16", role: "Autonomous Nav", desc: "Behavior trees, costmaps & TEB local planning" },
  { name: "MoveIt 2.5.5", role: "2-DOF Arm", desc: "Inverse kinematics & collision-aware arm motion" },
  { name: "rosbridge v2 DDS", role: "Bridge :9090", desc: "Native CycloneDDS JSON telemetry & control" },
] as const;

const BODY_ACTION_GROUPS = [
  "stand",
  "lie_down",
  "sit",
  "bow",
  "wave",
  "shake_hands",
  "shake_head",
  "nod",
  "stretch",
  "push-up",
  "press-up",
  "boxing",
  "boxing2",
  "jump",
  "2_legs_stand",
  "moonwalk",
  "spacewalk",
  "pee",
  "kick_ball_left",
  "kick_ball_right",
  "look_down.d6ac",
  "up_stairs_2cm",
  "up_stairs_3.5cm",
] as const;

const ARM_ACTION_GROUPS = [
  "stand_with_arm.d6a",
  "grab.d6a",
  "place.d6a",
  "Clamping.d6a",
  "look_down.d6a",
] as const;

const POSE_PRESETS = [
  {
    name: "GoHome",
    kind: "go_home" as const,
    roll: 0,
    pitch: 0,
    height: -10,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "Stand",
    kind: "pose" as const,
    roll: 0,
    pitch: 0,
    height: -10,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "StandLow",
    kind: "pose" as const,
    roll: 0,
    pitch: 0,
    height: -7,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "LieDown",
    kind: "pose" as const,
    roll: 0,
    pitch: 0,
    height: -5,
    x_shift: 2.0,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "LookDown",
    kind: "pose" as const,
    roll: 0,
    pitch: -0.2618,
    height: -10,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "Sit",
    kind: "action" as const,
    actionName: "sit.d6ac",
    roll: 0,
    pitch: 0,
    height: -10,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
  {
    name: "Bow",
    kind: "action" as const,
    actionName: "bow.d6ac",
    roll: 0,
    pitch: 0,
    height: -10,
    x_shift: -0.5,
    stance_x: 0,
    stance_y: 0,
    run_time: 500,
  },
] as const;

const GAIT_PRESETS = [
  {
    name: "Fast",
    desc: "0.1 / 0.15 / 0.0 · 5cm",
    payload: { overlap_time: 0.1, swing_time: 0.15, clearance_time: 0.0, z_clearance: 5.0, preset: "Fast" },
  },
  {
    name: "Slow",
    desc: "0.4 / 0.3 / 0.26 · 4cm",
    payload: { overlap_time: 0.4, swing_time: 0.3, clearance_time: 0.26, z_clearance: 4.0, preset: "Slow" },
  },
  {
    name: "Trot",
    desc: "0.2 / 0.3 / 0.0 · 8cm",
    payload: { overlap_time: 0.2, swing_time: 0.3, clearance_time: 0.0, z_clearance: 8.0, preset: "Trot" },
  },
  {
    name: "Amble",
    desc: "0.1 / 0.2 / 0.1 · 5cm",
    payload: { overlap_time: 0.1, swing_time: 0.2, clearance_time: 0.1, z_clearance: 5.0, preset: "Amble" },
  },
  {
    name: "Walk",
    desc: "0.1 / 0.2 / 0.3 · 5cm",
    payload: { overlap_time: 0.1, swing_time: 0.2, clearance_time: 0.3, z_clearance: 5.0, preset: "Walk" },
  },
  {
    name: "Crawl",
    desc: "0.4 / 0.3 / 0.20 · 3cm",
    payload: { overlap_time: 0.4, swing_time: 0.3, clearance_time: 0.2, z_clearance: 3.0, preset: "Crawl" },
  },
] as const;

const RGB_SWATCHES = [
  { label: "Eigenia Orange", r: 224, g: 90, b: 16, dot: "bg-eigenia-orange" },
  { label: "Telemetry Sky", r: 56, g: 189, b: 248, dot: "bg-eigenia-sky" },
  { label: "Amber Caution", r: 245, g: 158, b: 11, dot: "bg-eigenia-amber" },
  { label: "Fault Red", r: 239, g: 68, b: 68, dot: "bg-eigenia-fault" },
  { label: "Stealth Off", r: 0, g: 0, b: 0, dot: "bg-white/20" },
] as const;

function compute2sLipoPercent(volts: number): number {
  const pct = ((volts - 6.4) / (8.4 - 6.4)) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

function quaternionToEulerDeg(x: number, y: number, z: number, w: number) {
  const sinrCosp = 2 * (w * x + y * z);
  const cosrCosp = 1 - 2 * (x * x + y * y);
  const roll = (Math.atan2(sinrCosp, cosrCosp) * 180) / Math.PI;

  const sinp = 2 * (w * y - z * x);
  const pitch =
    Math.abs(sinp) >= 1
      ? (Math.sign(sinp) * 90)
      : (Math.asin(sinp) * 180) / Math.PI;

  const sinyCosp = 2 * (w * z + x * y);
  const cosyCosp = 1 - 2 * (y * y + z * z);
  const yaw = (Math.atan2(sinyCosp, cosyCosp) * 180) / Math.PI;

  return { roll, pitch, yaw };
}

function topicToVisionMode(topic: string): string {
  if (topic === "/usb_cam/image_raw" || topic === "/image_raw") return "raw";
  if (topic.startsWith("/apriltag_detect")) return "apriltag_detect";
  if (topic.startsWith("/color_detect")) return "color_detect";
  if (topic.startsWith("/face_detect")) return "face_detect";
  if (topic.startsWith("/object_tracking")) return "object_tracking";
  if (topic.startsWith("/visual_patrol")) return "visual_patrol";
  if (topic.startsWith("/lab_config_manager")) return "lab_config_manager";
  return "raw";
}

export function RobotControlPanel({
  robot,
  onRefreshRobot,
  activeRosMode = "ros1",
}: RobotControlPanelProps) {
  const isRos2 = activeRosMode === "ros2";
  const videoTopics = isRos2 ? ROS2_VIDEO_TOPICS : ROS1_VIDEO_TOPICS;
  const [selectedTopic, setSelectedTopic] = useState<string>(
    isRos2 ? "/image_raw" : "/usb_cam/image_raw"
  );
  const [streamNonce, setStreamNonce] = useState(0);
  const [controlDeckTab, setControlDeckTab] = useState<"actions" | "motion" | "peripherals">("actions");
  const [actionSearch, setActionSearch] = useState("");
  const [legServos, setLegServos] = useState<Record<number, number>>({
    1: 1500,
    2: 1500,
    3: 1500,
    4: 1500,
    5: 1500,
    6: 1500,
    7: 1500,
    8: 1500,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab");
    if (tabParam === "actions" || tabParam === "motion" || tabParam === "peripherals") {
      setControlDeckTab(tabParam);
    }
  }, []);

  const handleControlDeckTabChange = (next: string) => {
    if (next !== "actions" && next !== "motion" && next !== "peripherals") return;
    setControlDeckTab(next);
    if (typeof window !== "undefined" && window.location.pathname === "/control") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", next);
      window.history.replaceState({}, "", url.toString());
    }
  };
  const [streamError, setStreamError] = useState(false);
  const [cvStatus, setCvStatus] = useState<"raw" | "activating" | "active">("raw");
  const activeCvModeRef = useRef<string>("raw");
  const fpvImgRef = useRef<HTMLImageElement | null>(null);

  // V5 Chromium MJPEG Socket Leak Fix: abort active multipart socket on unmount
  useEffect(() => {
    return () => {
      if (fpvImgRef.current) {
        fpvImgRef.current.src = "";
      }
    };
  }, []);

  // Adapt default FPV topic cleanly when switching ROS 1 <-> ROS 2
  useEffect(() => {
    if (fpvImgRef.current) {
      fpvImgRef.current.src = "";
    }
    setSelectedTopic(isRos2 ? "/image_raw" : "/usb_cam/image_raw");
    setStreamError(false);
    setStreamNonce((n) => n + 1);
  }, [isRos2]);

  // Live ROSBridge WebSocket telemetry
  const [wsConnected, setWsConnected] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [batteryVolts, setBatteryVolts] = useState<number | null>(null);
  const [imu, setImu] = useState<{ roll: number; pitch: number; yaw: number } | null>(null);

  // Motion & Dead-man's switch state
  const [speedCmS, setSpeedCmS] = useState(15);
  const [turnRateRadS, setTurnRateRadS] = useState(0.35);
  const [activeVector, setActiveVector] = useState<{ x: number; yaw_rate: number } | null>(null);
  const [activeKeys, setActiveKeys] = useState<Set<string>>(new Set());
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeVectorRef = useRef<{ x: number; yaw_rate: number } | null>(null);

  // Pose & Gait state
  const [rollDeg, setRollDeg] = useState(0);
  const [pitchDeg, setPitchDeg] = useState(0);
  const [heightCm, setHeightCm] = useState(-10);
  const [xShiftCm, setXShiftCm] = useState(-0.5);
  const [activeGait, setActiveGait] = useState<string>("Slow");
  const [useAutogait, setUseAutogait] = useState<boolean>(true);
  const useAutogaitRef = useRef<boolean>(true);
  const [markTimeActive, setMarkTimeActive] = useState<boolean>(false);

  useEffect(() => {
    useAutogaitRef.current = useAutogait;
  }, [useAutogait]);

  // 2-DOF Arm Servo state (IDs 9, 10, 11)
  const [servoGripper, setServoGripper] = useState(1200);
  const [servoElbow, setServoElbow] = useState(800);
  const [servoShoulder, setServoShoulder] = useState(850);
  const [servoTimeMs, setServoTimeMs] = useState(500);

  // Peripherals state
  const [buzzerFreq, setBuzzerFreq] = useState(1900);
  const [buzzerOnTime, setBuzzerOnTime] = useState(0.15);
  const [buzzerRepeat, setBuzzerRepeat] = useState(1);
  const [rgbColor, setRgbColor] = useState({ r: 224, g: 90, b: 16 });
  const [oledLine, setOledLine] = useState(1);
  const [oledText, setOledText] = useState("EIGENIA TWINSCAN");

  const [cmdBanner, setCmdBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [restartingRos2, setRestartingRos2] = useState(false);

  const robotId = robot?.id ?? null;

  // Fallback battery from robot record when WS hasn't pushed yet
  useEffect(() => {
    if (robot?.battery_mv && batteryVolts === null) {
      setBatteryVolts(robot.battery_mv > 100 ? robot.battery_mv / 1000 : robot.battery_mv);
    }
  }, [robot?.battery_mv, batteryVolts]);

  // Live ROSBridge WebSocket Telemetry subscription
  useEffect(() => {
    if (!robotId) {
      setWsConnected(false);
      setLatencyMs(null);
      return;
    }

    let closed = false;
    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    const pingSentAt = new Map<string, number>();

    try {
      ws = new WebSocket(getRobotRosbridgeWsUrl(robotId));
      ws.onopen = () => {
        if (closed || !ws) return;
        setWsConnected(true);
        ws.send(JSON.stringify({ op: "subscribe", topic: "/ros_robot_controller/battery" }));
        ws.send(JSON.stringify({ op: "subscribe", topic: "/ros_robot_controller/imu_raw" }));
        ws.send(JSON.stringify({ op: "subscribe", topic: "/imu" }));

        const sendPing = () => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          const pingId = `ping-${Date.now()}`;
          pingSentAt.set(pingId, performance.now());
          ws.send(
            JSON.stringify({
              op: "call_service",
              id: pingId,
              service: "/rosapi/get_time",
            })
          );
        };
        sendPing();
        pingTimer = setInterval(sendPing, 4000);
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(String(evt.data));
          if (msg.op === "service_response" && typeof msg.id === "string" && pingSentAt.has(msg.id)) {
            const started = pingSentAt.get(msg.id)!;
            pingSentAt.delete(msg.id);
            setLatencyMs(Math.max(1, Math.round(performance.now() - started)));
            return;
          }
          if (msg.op === "publish" && msg.msg) {
            if (msg.topic === "/ros_robot_controller/battery") {
              const raw = Number(msg.msg.data ?? msg.msg.voltage ?? msg.msg);
              if (Number.isFinite(raw) && raw > 0) {
                setBatteryVolts(raw > 100 ? raw / 1000 : raw);
              }
            } else if (msg.topic === "/ros_robot_controller/imu_raw" || msg.topic === "/imu") {
              const o = msg.msg.orientation;
              if (o && typeof o.w === "number" && (o.x !== 0 || o.y !== 0 || o.z !== 0 || o.w !== 0)) {
                setImu(quaternionToEulerDeg(o.x, o.y, o.z, o.w));
              } else if (msg.msg.linear_acceleration) {
                const a = msg.msg.linear_acceleration;
                const roll = (Math.atan2(a.y, a.z) * 180) / Math.PI;
                const pitch = (Math.atan2(-a.x, Math.hypot(a.y, a.z)) * 180) / Math.PI;
                setImu((prev) => ({ roll, pitch, yaw: prev?.yaw ?? 0 }));
              }
            }
          }
        } catch {
          // Ignore malformed telemetry frames
        }
      };

      ws.onclose = () => {
        if (!closed) setWsConnected(false);
      };

      ws.onerror = () => {
        if (!closed) setWsConnected(false);
      };
    } catch {
      setWsConnected(false);
    }

    return () => {
      closed = true;
      if (pingTimer) clearInterval(pingTimer);
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
  }, [robotId]);

  const stopMotion = useCallback(async () => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    const wasMoving = activeVectorRef.current !== null;
    activeVectorRef.current = null;
    setActiveVector(null);
    if (robotId && wasMoving) {
      try {
        await sendRobotVelocity(robotId, {
          x: 0,
          y: 0,
          yaw_rate: 0,
          use_autogait: useAutogaitRef.current,
        });
      } catch {
        // Best-effort stop; server-side watchdog also enforces zero velocity
      }
    }
  }, [robotId]);

  const startMotion = useCallback(
    (x: number, yawRate: number) => {
      if (!robotId) return;
      const vec = { x, yaw_rate: yawRate };
      activeVectorRef.current = vec;
      setActiveVector(vec);
      if (activeCvModeRef.current !== "raw") {
        activeCvModeRef.current = "raw";
        setCvStatus("raw");
      }

      const dispatch = () => {
        if (!activeVectorRef.current) return;
        sendRobotVelocity(robotId, {
          x: activeVectorRef.current.x,
          y: 0,
          yaw_rate: activeVectorRef.current.yaw_rate,
          use_autogait: useAutogaitRef.current,
        }).catch((err) => {
          setCmdBanner({
            kind: "error",
            text: err instanceof Error ? err.message : "Velocity command failed",
          });
        });
      };

      dispatch();
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      heartbeatRef.current = setInterval(dispatch, 150);
    },
    [robotId]
  );

  // Stop cleanly on blur, visibility change, or unmount (dead-man's switch)
  useEffect(() => {
    const handleSafetyStop = () => {
      setActiveKeys(new Set());
      void stopMotion();
    };
    const handleVisibility = () => {
      if (document.hidden) handleSafetyStop();
    };
    window.addEventListener("blur", handleSafetyStop);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("blur", handleSafetyStop);
      document.removeEventListener("visibilitychange", handleVisibility);
      void stopMotion();
    };
  }, [stopMotion]);

  // WASD keyboard teleop
  useEffect(() => {
    if (!robotId) return;

    const isEditable = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
    };

    const recomputeFromKeys = (keys: Set<string>) => {
      const fwd = (keys.has("w") ? 1 : 0) - (keys.has("s") ? 1 : 0);
      const turn = (keys.has("a") ? 1 : 0) - (keys.has("d") ? 1 : 0);
      if (fwd === 0 && turn === 0) {
        void stopMotion();
      } else {
        startMotion(fwd * speedCmS, turn * turnRateRadS);
      }
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (isEditable(e.target) || e.repeat) return;
      const k = e.key.toLowerCase();
      if (k === " ") {
        e.preventDefault();
        setActiveKeys(new Set());
        void stopMotion();
        return;
      }
      if (k === "w" || k === "a" || k === "s" || k === "d") {
        e.preventDefault();
        setActiveKeys((prev) => {
          const next = new Set(prev);
          next.add(k);
          recomputeFromKeys(next);
          return next;
        });
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "w" || k === "a" || k === "s" || k === "d") {
        setActiveKeys((prev) => {
          if (!prev.has(k)) return prev;
          const next = new Set(prev);
          next.delete(k);
          recomputeFromKeys(next);
          return next;
        });
      }
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [robotId, speedCmS, turnRateRadS, startMotion, stopMotion]);

  // Clean up any active CV / AI Vision node on unmount so the robot never stays stuck in a CV mode
  useEffect(() => {
    return () => {
      if (robotId && activeCvModeRef.current !== "raw") {
        if (activeCvModeRef.current.startsWith("ai:")) {
          void setAiVisionMode(robotId, { mode: "raw" }).catch(() => {});
        } else {
          void setRobotVisionMode(robotId, "raw").catch(() => {});
        }
        activeCvModeRef.current = "raw";
      }
    };
  }, [robotId]);

  const handleTopicChange = async (newTopic: string) => {
    // V5 Chromium MJPEG Socket Leak Fix: explicitly close previous MJPEG socket before switching
    if (fpvImgRef.current) {
      fpvImgRef.current.src = "";
    }
    setSelectedTopic(newTopic);
    // Always clear error & bump stream nonce synchronously so switching back to Raw never stays blank
    setStreamError(false);
    setStreamNonce((n) => n + 1);
    if (!robotId) return;

    // ROS 2 Humble path: route AI Vision options to our real ROS 2 AI Vision Engine (never ROS 1 services!)
    if (isRos2) {
      if (newTopic.startsWith("ai:")) {
        const aiMode = newTopic.slice(3) as AiVisionMode;
        setCvStatus("activating");
        try {
          await setAiVisionMode(robotId, { mode: aiMode });
          activeCvModeRef.current = newTopic;
          setCvStatus("active");
          setStreamError(false);
          setStreamNonce((n) => n + 1);
          setCmdBanner({
            kind: "ok",
            text: `ROS 2 AI Vision "${aiMode}" active on annotated MJPEG stream.`,
          });
        } catch (err) {
          setCvStatus("raw");
          setCmdBanner({
            kind: "error",
            text: err instanceof Error ? err.message : `Failed to start AI Vision mode "${aiMode}"`,
          });
        }
        return;
      }

      // Raw /image_raw on ROS 2
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
      void setAiVisionMode(robotId, { mode: "raw" }).catch(() => {});
      return;
    }

    // ROS 1 Noetic path: Hiwonder CV nodes
    const modeKey = topicToVisionMode(newTopic);
    if (modeKey === "raw") {
      setCvStatus("raw");
      if (activeCvModeRef.current !== "raw") {
        activeCvModeRef.current = "raw";
        void setRobotVisionMode(robotId, "raw").catch(() => {});
      }
      return;
    }

    setCvStatus("activating");
    try {
      const resp = await setRobotVisionMode(robotId, modeKey);
      activeCvModeRef.current = resp.mode || modeKey;
      setCvStatus(resp.heartbeat_active ? "active" : "raw");
      setStreamError(false);
      setStreamNonce((n) => n + 1);
      setCmdBanner({
        kind: "ok",
        text: `CV node "${modeKey}" activated (${resp.heartbeat_active ? "2.5s heartbeat ON" : "idle"}).`,
      });
    } catch (err) {
      setCvStatus("raw");
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : `Failed to activate CV mode "${modeKey}"`,
      });
    }
  };

  const handleEstop = async () => {
    if (!robotId) return;
    await stopMotion();
    setMarkTimeActive(false);
    if (activeCvModeRef.current !== "raw") {
      const prevMode = activeCvModeRef.current;
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
      setSelectedTopic(isRos2 ? "/image_raw" : "/usb_cam/image_raw");
      setStreamError(false);
      setStreamNonce((n) => n + 1);
      if (prevMode.startsWith("ai:") || isRos2) {
        void setAiVisionMode(robotId, { mode: "raw" }).catch(() => {});
      } else {
        void setRobotVisionMode(robotId, "raw").catch(() => {});
      }
    }
    try {
      await triggerRobotEstop(robotId);
      setCmdBanner({ kind: "ok", text: "E-STOP dispatched — velocity zeroed, CV exited, and robot returned to home stance." });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "E-STOP request failed",
      });
    }
  };

  const handleRestartRos2Stack = async () => {
    if (!robotId) return;
    setRestartingRos2(true);
    setCmdBanner(null);
    try {
      await updateRobotRos(robotId, {
        target_ros: "ros2",
        ros_domain_id: 0,
        rmw_implementation: "rmw_cyclonedds_cpp",
      });
      setCmdBanner({
        kind: "ok",
        text: "ROS 2 Humble CycloneDDS bringup stack started/restarted on PuppyPi (puppypi_ros2).",
      });
      onRefreshRobot();
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to start/restart ROS 2 stack on robot",
      });
    } finally {
      setRestartingRos2(false);
    }
  };

  const handleApplyPose = async (override?: {
    roll: number;
    pitch: number;
    height: number;
    x_shift: number;
    stance_x?: number;
    stance_y?: number;
    run_time: number;
    preset?: string;
  }) => {
    if (!robotId) return;
    if (activeCvModeRef.current !== "raw") {
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
    }
    const payload = override ?? {
      roll: Number(((rollDeg * Math.PI) / 180).toFixed(4)),
      pitch: Number(((pitchDeg * Math.PI) / 180).toFixed(4)),
      yaw: 0,
      height: heightCm,
      x_shift: xShiftCm,
      stance_x: 0,
      stance_y: 0,
      run_time: 500,
    };
    try {
      await sendRobotPose(robotId, { yaw: 0, stance_x: 0, stance_y: 0, ...payload });
      setCmdBanner({
        kind: "ok",
        text: override?.preset ? `Pose preset "${override.preset}" applied.` : "Custom body pose applied.",
      });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Pose command failed",
      });
    }
  };

  const handlePosePreset = async (p: (typeof POSE_PRESETS)[number]) => {
    if (!robotId) return;
    if (activeCvModeRef.current !== "raw") {
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
    }
    setRollDeg(Math.round((p.roll * 180) / Math.PI));
    setPitchDeg(Math.round((p.pitch * 180) / Math.PI));
    setHeightCm(p.height);
    setXShiftCm(p.x_shift);

    if (p.kind === "go_home") {
      setMarkTimeActive(false);
      try {
        await sendRobotGoHome(robotId);
        setCmdBanner({ kind: "ok", text: "GoHome (/puppy_control/go_home) executed." });
      } catch (err) {
        setCmdBanner({
          kind: "error",
          text: err instanceof Error ? err.message : "GoHome service failed",
        });
      }
      return;
    }

    if (p.kind === "action") {
      await handleActionGroup(p.actionName);
      return;
    }

    await handleApplyPose({
      roll: p.roll,
      pitch: p.pitch,
      height: p.height,
      x_shift: p.x_shift,
      stance_x: p.stance_x,
      stance_y: p.stance_y,
      run_time: p.run_time,
      preset: p.name,
    });
  };

  const handleGait = async (preset: (typeof GAIT_PRESETS)[number]) => {
    if (!robotId) return;
    setActiveGait(preset.name);
    setUseAutogait(false);
    useAutogaitRef.current = false;
    if (activeCvModeRef.current !== "raw") {
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
    }
    try {
      await sendRobotGait(robotId, preset.payload);
      setCmdBanner({
        kind: "ok",
        text: `Manual gait "${preset.name}" applied (Auto-Gait OFF so teleop preserves this gait).`,
      });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Gait switch failed",
      });
    }
  };

  const handleToggleMarkTime = async () => {
    if (!robotId) return;
    const nextEnabled = !markTimeActive;
    if (activeCvModeRef.current !== "raw") {
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
    }
    try {
      if (nextEnabled) {
        await sendRobotGait(robotId, {
          overlap_time: 0.2,
          swing_time: 0.1,
          clearance_time: 0.0,
          z_clearance: 5.0,
          preset: "MarkTime",
        });
      }
      await sendRobotMarkTime(robotId, nextEnabled);
      setMarkTimeActive(nextEnabled);
      setCmdBanner({
        kind: "ok",
        text: nextEnabled
          ? "MarkTime ON (/puppy_control/set_mark_time = true)."
          : "MarkTime OFF (/puppy_control/set_mark_time = false).",
      });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "MarkTime toggle failed",
      });
    }
  };

  const handleActionGroup = async (actionName: string) => {
    if (!robotId) return;
    if (activeCvModeRef.current !== "raw") {
      activeCvModeRef.current = "raw";
      setCvStatus("raw");
    }
    setRunningAction(actionName);
    try {
      await runRobotAction(robotId, actionName);
      setCmdBanner({ kind: "ok", text: `Action group "${actionName}" triggered.` });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : `Action "${actionName}" failed`,
      });
    } finally {
      setRunningAction(null);
    }
  };

  const handleServo = async (id: number, pulse: number) => {
    if (!robotId) return;
    try {
      await sendRobotServo(robotId, { id, pulse, time: servoTimeMs });
      setCmdBanner({ kind: "ok", text: `Servo ID ${id} moved to pulse ${pulse} (${servoTimeMs}ms).` });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : `Servo ${id} command failed`,
      });
    }
  };

  const handleBuzzer = async () => {
    if (!robotId) return;
    try {
      await sendRobotBuzzer(robotId, {
        freq: buzzerFreq,
        on_time: buzzerOnTime,
        off_time: 0.1,
        repeat: buzzerRepeat,
      });
      setCmdBanner({ kind: "ok", text: `Buzzer sounded (${buzzerFreq} Hz × ${buzzerRepeat}).` });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Buzzer command failed",
      });
    }
  };

  const handleRgb = async (r: number, g: number, b: number) => {
    if (!robotId) return;
    setRgbColor({ r, g, b });
    try {
      await sendRobotRgb(robotId, [
        { id: 1, r, g, b },
        { id: 2, r, g, b },
      ]);
      setCmdBanner({ kind: "ok", text: `RGB LEDs set to rgb(${r}, ${g}, ${b}).` });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "RGB LED command failed",
      });
    }
  };

  const handleOled = async () => {
    if (!robotId) return;
    try {
      await sendRobotOled(robotId, { index: oledLine, text: oledText });
      setCmdBanner({ kind: "ok", text: `OLED line ${oledLine} updated.` });
    } catch (err) {
      setCmdBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "OLED command failed",
      });
    }
  };

  const videoSrc = useMemo(() => {
    if (!robotId) return "";
    if (selectedTopic.startsWith("ai:")) {
      return `${getAiVisionStreamUrl(robotId)}?_r=${streamNonce}`;
    }
    return `${getRobotVideoStreamUrl(robotId, selectedTopic)}&_r=${streamNonce}`;
  }, [robotId, selectedTopic, streamNonce]);

  if (!robot) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <Bot className="h-10 w-10 text-eigenia-orange/60" />
          <div className="text-sm font-semibold text-white">No Active PuppyPi Robot Selected</div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a registered robot from the top telemetry bar or run Auto-Discover LAN Fleet in the Fleet BOM & SBOM catalog.
          </p>
        </CardContent>
      </Card>
    );
  }

  const batteryPct = batteryVolts !== null ? compute2sLipoPercent(batteryVolts) : null;
  const batteryVariant =
    batteryPct === null ? "neutral" : batteryPct <= 20 ? "fault" : batteryPct <= 45 ? "amber" : "sky";

  const msgNamespace = isRos2 ? "puppy_control_msgs/msg" : "puppy_control";
  const srvNamespace = isRos2 ? "puppy_control_msgs/srv" : "puppy_control";
  const rrcNamespace = isRos2 ? "ros_robot_controller_msgs/msg" : "ros_robot_controller";

  const filteredBodyActions = BODY_ACTION_GROUPS.filter((a) =>
    a.toLowerCase().includes(actionSearch.trim().toLowerCase())
  );
  const filteredArmActions = ARM_ACTION_GROUPS.filter((a) =>
    a.toLowerCase().includes(actionSearch.trim().toLowerCase())
  );
  const rgbHex = `rgb(${rgbColor.r}, ${rgbColor.g}, ${rgbColor.b})`;

  return (
    <div className="flex flex-col gap-4">
      {/* Compact Workspace Header */}
      <WorkspaceHeader
        badge={isRos2 ? "ROS 2 HUMBLE // CYCLONEDDS" : "ROS 1 NOETIC // ROSMASTER"}
        title={`${robot.name} Teleop & Control Cockpit`}
        subtitle={`IP ${robot.ip_address} · ${msgNamespace}/* · IMU R:${imu ? imu.roll.toFixed(1) : "--"}° P:${imu ? imu.pitch.toFixed(1) : "--"}° Y:${imu ? imu.yaw.toFixed(1) : "--"}°`}
        statusTone={wsConnected ? "ok" : "warning"}
        statusLabel={wsConnected ? "ROSBRIDGE LIVE" : "REST FALLBACK"}
        metrics={[
          {
            label: "Active Mode",
            value: isRos2 ? "ROS 2" : "ROS 1",
            tone: isRos2 ? "orange" : "sky",
          },
          {
            label: "Battery",
            value: batteryVolts !== null ? batteryVolts : "--",
            unit: batteryVolts !== null ? "V" : undefined,
            decimals: 2,
            progressPct: batteryPct,
            tone:
              batteryPct === null
                ? "default"
                : batteryPct <= 20
                  ? "fault"
                  : batteryPct <= 45
                    ? "amber"
                    : "emerald",
            hint: batteryPct !== null ? `${batteryPct}% 2S LiPo` : "Awaiting telemetry",
          },
          {
            label: "Auto-Gait",
            value: useAutogait ? "ON" : activeGait,
            tone: useAutogait ? "sky" : "amber",
          },
          {
            label: "Latency",
            value: latencyMs !== null ? latencyMs : "--",
            unit: latencyMs !== null ? "ms" : undefined,
            tone: "sky",
          },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" onClick={onRefreshRobot}>
              <RefreshCw className="h-3.5 w-3.5" />
              Sync State
            </Button>
            <Button size="sm" variant="destructive" onClick={handleEstop}>
              <AlertOctagon className="h-3.5 w-3.5" />
              E-STOP
            </Button>
          </div>
        }
      />

      {cmdBanner && (
        <div
          className={`flex items-center justify-between rounded-md border px-3 py-1.5 font-mono text-[11px] ${
            cmdBanner.kind === "ok"
              ? "border-eigenia-sky/35 bg-eigenia-sky/10 text-eigenia-sky"
              : "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault"
          }`}
        >
          <span>{cmdBanner.text}</span>
          <button
            type="button"
            onClick={() => setCmdBanner(null)}
            className="ml-2 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Top-Level Operational Workspace Tabs on /control */}
      <Tabs defaultValue="drive" className="w-full">
        <TabsList className="flex h-auto flex-wrap">
          <TabsTrigger value="drive">
            <Gamepad2 className="h-3.5 w-3.5" />
            Drive & Stance Control
          </TabsTrigger>
          <TabsTrigger value="ai_vision">
            <ScanFace className="h-3.5 w-3.5" />
            AI Vision & People
          </TabsTrigger>
          <TabsTrigger value="voice">
            <Volume2 className="h-3.5 w-3.5" />
            Voice & Speaker
          </TabsTrigger>
          <TabsTrigger value="patrol">
            <Navigation className="h-3.5 w-3.5" />
            Autonomous Patrol
          </TabsTrigger>
        </TabsList>

        <TabsContent value="ai_vision">
          <AiVisionStudioPanel robot={robot} activeRosMode={activeRosMode} />
        </TabsContent>

        <TabsContent value="voice">
          <VoiceControlPanel robot={robot} />
        </TabsContent>

        <TabsContent value="patrol">
          <PatrolPlannerPanel robot={robot} />
        </TabsContent>

        <TabsContent value="drive" className="space-y-4">
          {/* Collapsible ROS 1 / ROS 2 Stack Strip */}
          {isRos2 ? (
            <InteractiveSurface
              accent="orange"
              title="ROS 2 Humble DDS & Autonomy Stack"
              subtitle="Ubuntu 22.04 LTS · rmw_cyclonedds_cpp · slam_toolbox 2.6.8 · Nav2 1.1.16 · MoveIt 2.5.5"
              collapsible
              defaultCollapsed
              headerRight={
                <Button
                  size="sm"
                  variant="default"
                  disabled={restartingRos2}
                  onClick={() => void handleRestartRos2Stack()}
                >
                  {restartingRos2 ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  {restartingRos2 ? "Starting..." : "Restart ROS 2 Stack"}
                </Button>
              }
            >
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {ROS2_AUTONOMY_STACK.map((item) => (
                  <div
                    key={item.name}
                    className="rounded-md border border-eigenia-orange/35 bg-eigenia-obsidian/85 p-3"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="font-mono text-xs font-semibold text-white">{item.name}</span>
                      <Badge variant="default" className="text-[9px]">
                        {item.role}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[10px] leading-relaxed text-eigenia-muted">{item.desc}</p>
                  </div>
                ))}
              </div>
            </InteractiveSurface>
          ) : (
            <InteractiveSurface
              accent="sky"
              title="ROS 1 Noetic — Hiwonder OpenCV App Deck"
              subtitle="rosmaster :11311 · gmapping / move_base / TEB · /usb_cam/image_raw"
              collapsible
              defaultCollapsed
              headerRight={
                cvStatus !== "raw" ? (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => void handleTopicChange("/usb_cam/image_raw")}
                  >
                    <Square className="h-3 w-3" />
                    Stop CV
                  </Button>
                ) : undefined
              }
            >
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {ROS1_CV_APP_DECK.map((app) => {
                  const isSelected = selectedTopic === app.topic;
                  return (
                    <button
                      key={app.mode}
                      type="button"
                      onClick={() => void handleTopicChange(app.topic)}
                      className={`flex flex-col items-start gap-1 rounded-md border p-2.5 text-left transition-colors ${
                        isSelected
                          ? "border-eigenia-sky bg-eigenia-sky/15 text-white"
                          : "border-white/10 bg-eigenia-obsidian text-eigenia-ink hover:border-eigenia-sky/50"
                      }`}
                    >
                      <div className="flex w-full items-center justify-between gap-1">
                        <span className="text-xs font-semibold text-white">{app.label}</span>
                        {isSelected ? (
                          <Badge
                            variant="sky"
                            className="border-emerald-500/40 bg-emerald-500/20 px-1 py-0 text-[8px] text-emerald-400"
                          >
                            ON
                          </Badge>
                        ) : app.movesLegs ? (
                          <Badge variant="amber" className="px-1 py-0 text-[8px]">
                            <AlertTriangle className="h-2.5 w-2.5" />
                            LEGS
                          </Badge>
                        ) : null}
                      </div>
                      <span className="text-[10px] leading-snug text-eigenia-muted">{app.desc}</span>
                    </button>
                  );
                })}
              </div>
            </InteractiveSurface>
          )}

          {/* 2-COLUMN COCKPIT: STICKY DRIVE DECK (LEFT 5) + 3-TAB CONTROL DECK (RIGHT 7) */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            {/* LEFT STICKY DRIVE DECK */}
            <div className="space-y-4 self-start lg:sticky lg:top-20 lg:col-span-5">
              {/* Live Single-Origin MJPEG FPV Feed */}
              <Card className={isRos2 ? "border-eigenia-orange/45" : undefined}>
                <CardHeader className="flex flex-col gap-2 pb-2">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="flex items-center gap-2 text-xs">
                      <Camera className="h-3.5 w-3.5 text-eigenia-orange" />
                      Live FPV Feed ({robot.ip_address})
                    </CardTitle>
                    <div className="flex items-center gap-1.5">
                      {cvStatus === "activating" && (
                        <Badge variant="amber" className="text-[9px]">
                          STARTING...
                        </Badge>
                      )}
                      {cvStatus === "active" && (
                        <Badge
                          variant="sky"
                          className="border-emerald-500/40 bg-emerald-500/15 text-[9px] text-emerald-400"
                        >
                          CV LIVE
                        </Badge>
                      )}
                      {cvStatus !== "raw" && (
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 px-2 text-[9px]"
                          onClick={() => void handleTopicChange(isRos2 ? "/image_raw" : "/usb_cam/image_raw")}
                        >
                          <Square className="h-2.5 w-2.5" /> Raw
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-6 px-2"
                        onClick={() => {
                          if (fpvImgRef.current) fpvImgRef.current.src = "";
                          setStreamError(false);
                          setStreamNonce((n) => n + 1);
                        }}
                      >
                        <RefreshCw className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                  <select
                    value={selectedTopic}
                    onChange={(e) => void handleTopicChange(e.target.value)}
                    className="h-7 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-[10px] text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                  >
                    {videoTopics.map((t) => (
                      <option key={t.topic} value={t.topic}>
                        {t.label} ({t.topic})
                      </option>
                    ))}
                  </select>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border border-white/10 bg-eigenia-obsidian">
                    {!streamError ? (
                      <img
                        ref={fpvImgRef}
                        key={videoSrc}
                        src={videoSrc}
                        alt={`PuppyPi FPV ${selectedTopic}`}
                        className="h-full w-full object-contain"
                        onError={() => setStreamError(true)}
                      />
                    ) : (
                      <div className="flex flex-col items-center gap-2 p-4 text-center">
                        <Camera className="h-6 w-6 text-eigenia-muted" />
                        <div className="text-xs font-medium text-white">FPV Stream Unavailable</div>
                        <Button
                          size="sm"
                          variant="sky"
                          onClick={() => {
                            setStreamError(false);
                            setStreamNonce((n) => n + 1);
                          }}
                        >
                          Reconnect Stream
                        </Button>
                      </div>
                    )}
                    <div className="pointer-events-none absolute left-2 top-2 rounded bg-eigenia-obsidian/80 px-2 py-0.5 font-mono text-[9px] text-eigenia-sky">
                      {selectedTopic}
                    </div>
                    {activeVector && (
                      <div className="pointer-events-none absolute bottom-2 left-2 rounded border border-eigenia-orange/60 bg-eigenia-obsidian/85 px-2 py-0.5 font-mono text-[9px] tabular-nums text-eigenia-orange">
                        x={activeVector.x.toFixed(1)} · yaw={activeVector.yaw_rate.toFixed(2)}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Dead-Man Directional Velocity Pad + Quick Stop */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                  <CardTitle className="flex items-center gap-2 text-xs">
                    <Gamepad2 className="h-3.5 w-3.5 text-eigenia-orange" />
                    Dead-Man Directional Pad
                  </CardTitle>
                  <Badge variant={activeVector ? "default" : "neutral"} className="text-[9px]">
                    {activeVector ? "150ms Active" : "WASD / Hold"}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="mx-auto grid w-full max-w-[248px] grid-cols-3 gap-1.5 select-none">
                    <Button
                      variant={activeKeys.has("w") && activeKeys.has("a") ? "default" : "secondary"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(speedCmS, turnRateRadS)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Fwd-L
                    </Button>
                    <Button
                      variant={activeKeys.has("w") && !activeKeys.has("a") && !activeKeys.has("d") ? "default" : "sky"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(speedCmS, 0)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                      W · Fwd
                    </Button>
                    <Button
                      variant={activeKeys.has("w") && activeKeys.has("d") ? "default" : "secondary"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(speedCmS, -turnRateRadS)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <RotateCw className="h-3.5 w-3.5" />
                      Fwd-R
                    </Button>

                    <Button
                      variant={activeKeys.has("a") ? "default" : "secondary"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(0, turnRateRadS)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      A · Left
                    </Button>
                    <Button
                      variant="destructive"
                      className="h-11 flex-col gap-0.5 text-[10px] font-semibold"
                      onClick={() => void stopMotion()}
                    >
                      <Square className="h-3.5 w-3.5" />
                      STOP
                    </Button>
                    <Button
                      variant={activeKeys.has("d") ? "default" : "secondary"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(0, -turnRateRadS)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <ArrowRight className="h-3.5 w-3.5" />
                      D · Right
                    </Button>

                    <div />
                    <Button
                      variant={activeKeys.has("s") ? "default" : "secondary"}
                      className="h-11 flex-col gap-0.5 text-[10px]"
                      onPointerDown={() => startMotion(-speedCmS, 0)}
                      onPointerUp={() => void stopMotion()}
                      onPointerLeave={() => void stopMotion()}
                      onPointerCancel={() => void stopMotion()}
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                      S · Rev
                    </Button>
                    <div />
                  </div>

                  <div className="space-y-2.5 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                    <div className="space-y-1">
                      <div className="flex items-center justify-between font-mono text-[10px]">
                        <span className="text-eigenia-muted">Linear Speed</span>
                        <span className="tabular-nums text-white">{speedCmS} cm/s</span>
                      </div>
                      <Slider min={5} max={25} step={1} value={[speedCmS]} onValueChange={([v]) => setSpeedCmS(v)} />
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center justify-between font-mono text-[10px]">
                        <span className="text-eigenia-muted">Yaw Turn Rate</span>
                        <span className="tabular-nums text-white">{turnRateRadS.toFixed(2)} rad/s</span>
                      </div>
                      <Slider
                        min={0.15}
                        max={0.55}
                        step={0.05}
                        value={[turnRateRadS]}
                        onValueChange={([v]) => setTurnRateRadS(v)}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* RIGHT 3-TAB CONTROL DECK */}
            <div className="space-y-4 lg:col-span-7">
              <SegmentedTabs
                value={controlDeckTab}
                onValueChange={handleControlDeckTabChange}
                tabs={[
                  {
                    id: "actions",
                    label: "Stances & Actions",
                    icon: <Bot className="h-3.5 w-3.5" />,
                    count: BODY_ACTION_GROUPS.length + ARM_ACTION_GROUPS.length,
                  },
                  {
                    id: "motion",
                    label: "Gait & Servos",
                    icon: <Sliders className="h-3.5 w-3.5" />,
                  },
                  {
                    id: "peripherals",
                    label: "LEDs, OLED & Buzzer",
                    icon: <Lightbulb className="h-3.5 w-3.5" />,
                  },
                ]}
              />

              {/* DECK TAB 1: STANCES & ACTIONS (28) */}
              {controlDeckTab === "actions" && (
                <div className="space-y-4">
                  <InteractiveSurface
                    accent="orange"
                    title="Quick Stance Presets"
                    subtitle="Code-verified PuppyPi postures (GoHome, Stand, Sit, Bow, LieDown, LookDown)"
                  >
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {POSE_PRESETS.map((p) => (
                        <button
                          key={p.name}
                          type="button"
                          onClick={() => void handlePosePreset(p)}
                          className={`group flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left transition-all duration-150 hover:-translate-y-0.5 motion-reduce:transition-none ${
                            p.name === "GoHome"
                              ? "border-eigenia-sky/45 bg-eigenia-sky/10 hover:border-eigenia-sky hover:bg-eigenia-sky/15"
                              : "border-white/10 bg-eigenia-obsidian hover:border-eigenia-orange/55 hover:bg-eigenia-orange/10"
                          }`}
                        >
                          <span className="text-xs font-semibold text-white">{p.name}</span>
                          <span className="font-mono text-[9px] text-eigenia-muted">
                            {p.kind === "go_home"
                              ? "go_home srv"
                              : p.kind === "action"
                                ? p.actionName
                                : `H ${p.height}cm · P ${Math.round((p.pitch * 180) / Math.PI)}°`}
                          </span>
                        </button>
                      ))}
                    </div>
                  </InteractiveSurface>

                  <InteractiveSurface
                    accent="sky"
                    title={`Verified ActionGroups (${BODY_ACTION_GROUPS.length + ARM_ACTION_GROUPS.length})`}
                    subtitle={`/puppy_control/runActionGroup (${srvNamespace}/SetRunActionName)`}
                    headerRight={
                      <div className="relative w-52">
                        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-eigenia-muted" />
                        <Input
                          value={actionSearch}
                          onChange={(e) => setActionSearch(e.target.value)}
                          placeholder="Search 28 actions..."
                          className="h-7 pl-8 font-mono text-[11px]"
                        />
                      </div>
                    }
                  >
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                          Body Action Groups (.d6ac · {filteredBodyActions.length})
                        </div>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
                          {filteredBodyActions.map((action) => (
                            <Button
                              key={action}
                              variant={runningAction === action ? "default" : "secondary"}
                              size="sm"
                              disabled={runningAction !== null}
                              className="justify-start font-mono text-[11px] transition-transform hover:-translate-y-0.5 motion-reduce:transition-none"
                              onClick={() => void handleActionGroup(action)}
                            >
                              {action}
                            </Button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-2 border-t border-white/10 pt-3">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-orange">
                          2-DOF Arm Action Groups (.d6a · {filteredArmActions.length})
                        </div>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                          {filteredArmActions.map((action) => (
                            <Button
                              key={action}
                              variant={runningAction === action ? "default" : "outline"}
                              size="sm"
                              disabled={runningAction !== null}
                              className="justify-start font-mono text-[11px]"
                              onClick={() => void handleActionGroup(action)}
                            >
                              {action}
                            </Button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </InteractiveSurface>
                </div>
              )}

              {/* DECK TAB 2: GAIT & SERVOS */}
              {controlDeckTab === "motion" && (
                <div className="space-y-4">
                  <InteractiveSurface
                    accent="sky"
                    title="Auto-Gait & Official Gait Profiles"
                    headerRight={
                      <label className="flex items-center gap-2 rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-1 font-mono text-[10px] text-white">
                        <span>Auto-Gait ({useAutogait ? "ON" : "Manual"})</span>
                        <Switch checked={useAutogait} onCheckedChange={setUseAutogait} />
                      </label>
                    }
                  >
                    <div className="space-y-2.5">
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {GAIT_PRESETS.map((g) => (
                          <Button
                            key={g.name}
                            size="sm"
                            variant={!useAutogait && activeGait === g.name ? "default" : "secondary"}
                            className="h-auto flex-col py-2"
                            onClick={() => void handleGait(g)}
                          >
                            <span className="text-xs font-semibold">{g.name}</span>
                            <span className="font-mono text-[9px] opacity-75">{g.desc}</span>
                          </Button>
                        ))}
                      </div>
                      <Button
                        size="sm"
                        variant={markTimeActive ? "default" : "outline"}
                        className="w-full font-mono text-[11px]"
                        onClick={() => void handleToggleMarkTime()}
                      >
                        <Footprints className="h-3.5 w-3.5" />
                        {markTimeActive
                          ? "MarkTime ACTIVE — Click to Stop (/puppy_control/set_mark_time)"
                          : "Toggle MarkTime In-Place Step (/puppy_control/set_mark_time)"}
                      </Button>
                    </div>
                  </InteractiveSurface>

                  <InteractiveSurface
                    accent="orange"
                    title="Body Pose Kinematics (Roll / Pitch / Height / X-Shift)"
                    headerRight={
                      <Button size="sm" onClick={() => void handleApplyPose()}>
                        Apply Body Pose
                      </Button>
                    }
                  >
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-3">
                        <div className="flex justify-between font-mono text-[11px]">
                          <span className="text-eigenia-muted">Roll</span>
                          <span className="tabular-nums text-white">{rollDeg}°</span>
                        </div>
                        <Slider min={-20} max={20} step={1} value={[rollDeg]} onValueChange={([v]) => setRollDeg(v)} />
                      </div>
                      <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-3">
                        <div className="flex justify-between font-mono text-[11px]">
                          <span className="text-eigenia-muted">Pitch</span>
                          <span className="tabular-nums text-white">{pitchDeg}°</span>
                        </div>
                        <Slider min={-20} max={20} step={1} value={[pitchDeg]} onValueChange={([v]) => setPitchDeg(v)} />
                      </div>
                      <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-3">
                        <div className="flex justify-between font-mono text-[11px]">
                          <span className="text-eigenia-muted">Height (-15 tall .. -5 low)</span>
                          <span className="tabular-nums text-white">{heightCm.toFixed(1)} cm</span>
                        </div>
                        <Slider min={-15} max={-5} step={0.5} value={[heightCm]} onValueChange={([v]) => setHeightCm(v)} />
                      </div>
                      <div className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-3">
                        <div className="flex justify-between font-mono text-[11px]">
                          <span className="text-eigenia-muted">X-Shift Center of Mass</span>
                          <span className="tabular-nums text-white">{xShiftCm.toFixed(1)} cm</span>
                        </div>
                        <Slider min={-6} max={6} step={0.5} value={[xShiftCm]} onValueChange={([v]) => setXShiftCm(v)} />
                      </div>
                    </div>
                  </InteractiveSurface>

                  <InteractiveSurface
                    title="Direct Bus Servos (8 Leg Servos + 2-DOF Arm)"
                    subtitle={`/puppy_control/setServo (${msgNamespace}/SetServo · 500..2500 PWM)`}
                    headerRight={
                      <div className="flex items-center gap-1.5 font-mono text-[10px]">
                        <span className="text-eigenia-muted">Time:</span>
                        <Input
                          type="number"
                          min={100}
                          max={5000}
                          step={50}
                          value={servoTimeMs}
                          onChange={(e) => setServoTimeMs(Number(e.target.value) || 500)}
                          className="h-7 w-20 font-mono text-[10px]"
                        />
                        <span className="text-eigenia-muted">ms</span>
                      </div>
                    }
                  >
                    <div className="space-y-4">
                      {/* 8 Leg Servo Sliders */}
                      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                        {[
                          { id: 1, label: "S1 · FR Hip" },
                          { id: 2, label: "S2 · FR Knee" },
                          { id: 3, label: "S3 · FL Hip" },
                          { id: 4, label: "S4 · FL Knee" },
                          { id: 5, label: "S5 · RR Hip" },
                          { id: 6, label: "S6 · RR Knee" },
                          { id: 7, label: "S7 · RL Hip" },
                          { id: 8, label: "S8 · RL Knee" },
                        ].map((s) => (
                          <div
                            key={s.id}
                            className="space-y-1.5 rounded border border-white/10 bg-eigenia-obsidian p-2.5"
                          >
                            <div className="flex items-center justify-between font-mono text-[11px]">
                              <span className="text-white">{s.label}</span>
                              <span className="tabular-nums text-eigenia-sky">{legServos[s.id] ?? 1500}</span>
                            </div>
                            <Slider
                              min={500}
                              max={2500}
                              step={10}
                              value={[legServos[s.id] ?? 1500]}
                              onValueChange={([v]) =>
                                setLegServos((prev) => ({ ...prev, [s.id]: v }))
                              }
                              onValueCommit={([v]) => void handleServo(s.id, v)}
                            />
                          </div>
                        ))}
                      </div>

                      {/* 2-DOF Arm Servos (IDs 9, 10, 11) */}
                      <div className="grid grid-cols-1 gap-2.5 border-t border-white/10 pt-3 md:grid-cols-3">
                        <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                          <div className="flex items-center justify-between font-mono text-xs">
                            <span className="font-semibold text-white">ID 9 · Gripper</span>
                            <Badge variant="default" className="tabular-nums">
                              {servoGripper}
                            </Badge>
                          </div>
                          <Slider
                            min={500}
                            max={2500}
                            step={10}
                            value={[servoGripper]}
                            onValueChange={([v]) => setServoGripper(v)}
                            onValueCommit={([v]) => void handleServo(9, v)}
                          />
                          <div className="flex gap-1.5">
                            <Button
                              size="sm"
                              variant="secondary"
                              className="flex-1 text-[10px]"
                              onClick={() => {
                                setServoGripper(950);
                                void handleServo(9, 950);
                              }}
                            >
                              Open
                            </Button>
                            <Button
                              size="sm"
                              variant="sky"
                              className="flex-1 text-[10px]"
                              onClick={() => {
                                setServoGripper(1500);
                                void handleServo(9, 1500);
                              }}
                            >
                              Close
                            </Button>
                          </div>
                        </div>

                        <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                          <div className="flex items-center justify-between font-mono text-xs">
                            <span className="font-semibold text-white">ID 10 · Elbow</span>
                            <Badge variant="sky" className="tabular-nums">
                              {servoElbow}
                            </Badge>
                          </div>
                          <Slider
                            min={500}
                            max={2500}
                            step={10}
                            value={[servoElbow]}
                            onValueChange={([v]) => setServoElbow(v)}
                            onValueCommit={([v]) => void handleServo(10, v)}
                          />
                          <Button
                            size="sm"
                            variant="secondary"
                            className="w-full text-[10px]"
                            onClick={() => void handleServo(10, servoElbow)}
                          >
                            Send ID 10
                          </Button>
                        </div>

                        <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                          <div className="flex items-center justify-between font-mono text-xs">
                            <span className="font-semibold text-white">ID 11 · Shoulder</span>
                            <Badge variant="sky" className="tabular-nums">
                              {servoShoulder}
                            </Badge>
                          </div>
                          <Slider
                            min={500}
                            max={2500}
                            step={10}
                            value={[servoShoulder]}
                            onValueChange={([v]) => setServoShoulder(v)}
                            onValueCommit={([v]) => void handleServo(11, v)}
                          />
                          <Button
                            size="sm"
                            variant="secondary"
                            className="w-full text-[10px]"
                            onClick={() => void handleServo(11, servoShoulder)}
                          >
                            Send ID 11
                          </Button>
                        </div>
                      </div>
                    </div>
                  </InteractiveSurface>
                </div>
              )}

              {/* DECK TAB 3: LEDS, OLED & BUZZER */}
              {controlDeckTab === "peripherals" && (
                <div className="space-y-4">
                  {/* Chassis RGB LEDs with Glowing Swatch Preview */}
                  <InteractiveSurface
                    accent="amber"
                    title="Chassis RGB LEDs"
                    subtitle="Live glowing color preview synced to /ros_robot_controller/set_rgb"
                    headerRight={
                      <div className="flex items-center gap-2">
                        <div
                          className="h-6 w-6 rounded-full border border-white/30 transition-all duration-200 motion-reduce:transition-none"
                          style={{
                            backgroundColor: rgbHex,
                            boxShadow: `0 0 18px ${rgbHex}`,
                          }}
                        />
                        <span className="font-mono text-[10px] text-white">
                          rgb({rgbColor.r}, {rgbColor.g}, {rgbColor.b})
                        </span>
                      </div>
                    }
                  >
                    <div className="space-y-3">
                      <div className="flex flex-wrap gap-1.5">
                        {RGB_SWATCHES.map((s) => (
                          <Button
                            key={s.label}
                            size="sm"
                            variant="secondary"
                            className="h-7 gap-1.5 text-[10px]"
                            onClick={() => void handleRgb(s.r, s.g, s.b)}
                          >
                            <span className={`h-2.5 w-2.5 rounded-full ${s.dot}`} />
                            {s.label}
                          </Button>
                        ))}
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <label className="font-mono text-[10px] text-eigenia-muted">R</label>
                          <Input
                            type="number"
                            min={0}
                            max={255}
                            value={rgbColor.r}
                            onChange={(e) => setRgbColor({ ...rgbColor, r: Number(e.target.value) || 0 })}
                          />
                        </div>
                        <div>
                          <label className="font-mono text-[10px] text-eigenia-muted">G</label>
                          <Input
                            type="number"
                            min={0}
                            max={255}
                            value={rgbColor.g}
                            onChange={(e) => setRgbColor({ ...rgbColor, g: Number(e.target.value) || 0 })}
                          />
                        </div>
                        <div>
                          <label className="font-mono text-[10px] text-eigenia-muted">B</label>
                          <Input
                            type="number"
                            min={0}
                            max={255}
                            value={rgbColor.b}
                            onChange={(e) => setRgbColor({ ...rgbColor, b: Number(e.target.value) || 0 })}
                          />
                        </div>
                      </div>
                      <Button
                        className="w-full"
                        variant="sky"
                        onClick={() => void handleRgb(rgbColor.r, rgbColor.g, rgbColor.b)}
                      >
                        Apply RGB Color
                      </Button>
                    </div>
                  </InteractiveSurface>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {/* Onboard OLED Display */}
                    <InteractiveSurface accent="sky" title="Onboard OLED Display">
                      <div className="space-y-3">
                        <div>
                          <label className="text-[10px] text-eigenia-muted">Display Line Index</label>
                          <select
                            value={oledLine}
                            onChange={(e) => setOledLine(Number(e.target.value))}
                            className="mt-1 h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                          >
                            <option value={1}>Line 1 (Top)</option>
                            <option value={2}>Line 2 (Bottom)</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-[10px] text-eigenia-muted">Text Payload</label>
                          <Input
                            value={oledText}
                            maxLength={32}
                            onChange={(e) => setOledText(e.target.value)}
                            placeholder="Display text..."
                            className="mt-1 font-mono text-xs"
                          />
                        </div>
                        <Button className="w-full" variant="secondary" onClick={handleOled}>
                          <Monitor className="h-3.5 w-3.5" />
                          Write OLED Line
                        </Button>
                      </div>
                    </InteractiveSurface>

                    {/* STM32 Buzzer */}
                    <InteractiveSurface accent="orange" title="STM32 Buzzer">
                      <div className="space-y-3">
                        <div className="space-y-1">
                          <div className="flex justify-between font-mono text-[11px]">
                            <span className="text-eigenia-muted">Frequency</span>
                            <span className="tabular-nums text-white">{buzzerFreq} Hz</span>
                          </div>
                          <Slider
                            min={500}
                            max={4000}
                            step={100}
                            value={[buzzerFreq]}
                            onValueChange={([v]) => setBuzzerFreq(v)}
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="text-[10px] text-eigenia-muted">On Time (s)</label>
                            <Input
                              type="number"
                              step="0.05"
                              min="0.05"
                              max="2"
                              value={buzzerOnTime}
                              onChange={(e) => setBuzzerOnTime(Number(e.target.value) || 0.1)}
                            />
                          </div>
                          <div>
                            <label className="text-[10px] text-eigenia-muted">Repeat</label>
                            <Input
                              type="number"
                              min="1"
                              max="5"
                              value={buzzerRepeat}
                              onChange={(e) => setBuzzerRepeat(Number(e.target.value) || 1)}
                            />
                          </div>
                        </div>
                        <Button className="w-full" onClick={handleBuzzer}>
                          <Volume2 className="h-3.5 w-3.5" />
                          Trigger Beep
                        </Button>
                      </div>
                    </InteractiveSurface>
                  </div>
                </div>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
