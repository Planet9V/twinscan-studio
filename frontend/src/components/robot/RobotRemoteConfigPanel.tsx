"use client";

import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Cable,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Volume2,
  Wifi,
  WifiOff,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { RosComparisonCard } from "@/components/robot/RosComparisonCard";
import { VoiceControlPanel } from "@/components/robot/VoiceControlPanel";
import {
  fetchRobotNetwork,
  sendRobotPower,
  setRobotActiveIp,
  updateRobotMechanics,
  updateRobotPassword,
  updateRobotRos,
  updateRobotWifi,
  type NetworkInterfaceInfo,
  type RobotNetworkTelemetry,
  type RobotRecord,
} from "@/lib/robotApi";

interface RobotRemoteConfigPanelProps {
  robot: RobotRecord | null;
  onUpdated: () => void;
  activeRosMode?: "ros1" | "ros2";
  robotNetwork?: RobotNetworkTelemetry | null;
  onRefreshNetwork?: () => Promise<void>;
  onSwitchActiveIp?: (ip: string) => Promise<void>;
  previewMode?: "ros1" | "ros2" | null;
  onTogglePreview?: (mode: "ros1" | "ros2" | null) => void;
}

const SERVO_LABELS: Record<string, string> = {
  "1": "S1 · FR Hip",
  "2": "S2 · FR Knee",
  "3": "S3 · FL Hip",
  "4": "S4 · FL Knee",
  "5": "S5 · RR Hip",
  "6": "S6 · RR Knee",
  "7": "S7 · RL Hip",
  "8": "S8 · RL Knee",
  "9": "S9 · Arm Gripper",
  "10": "S10 · Arm Elbow",
  "11": "S11 · Arm Shoulder",
};

function buildDefaultServoTrims(): Record<string, number> {
  const trims: Record<string, number> = {};
  for (let i = 1; i <= 11; i++) {
    trims[String(i)] = 0;
  }
  return trims;
}

function formatBand(freqMhz?: number | null): string {
  if (!freqMhz) return "";
  return freqMhz >= 5000 ? `${(freqMhz / 1000).toFixed(2)} GHz (5GHz)` : `${freqMhz} MHz (2.4GHz)`;
}

export function RobotRemoteConfigPanel({
  robot,
  onUpdated,
  activeRosMode,
  robotNetwork,
  onRefreshNetwork,
  onSwitchActiveIp,
  previewMode = null,
  onTogglePreview,
}: RobotRemoteConfigPanelProps) {
  // Wi-Fi state
  const [wifiMode, setWifiMode] = useState<number>(2);
  const [wifiSsid, setWifiSsid] = useState("Wildcat");
  const [wifiPassword, setWifiPassword] = useState("");
  const [showWifiPass, setShowWifiPass] = useState(false);
  const [wifiCountry, setWifiCountry] = useState("US");
  const [restartWifiService, setRestartWifiService] = useState(true);

  // Local network fallback when prop isn't passed
  const [localNetwork, setLocalNetwork] = useState<RobotNetworkTelemetry | null>(null);
  const [refreshingNet, setRefreshingNet] = useState(false);

  // Password state
  const [targetUser, setTargetUser] = useState<"pi" | "root">("pi");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPass, setShowNewPass] = useState(false);

  // Mechanics & Servos state
  const [withArm, setWithArm] = useState(false);
  const [xShift, setXShift] = useState(-0.5);
  const [servoDeviations, setServoDeviations] = useState<Record<string, number>>(buildDefaultServoTrims);

  // ROS & AI state
  const [targetRos, setTargetRos] = useState<"ros1" | "ros2">("ros1");
  const [asrLanguage, setAsrLanguage] = useState<"English" | "Chinese">("English");
  const [rosDomainId, setRosDomainId] = useState<number>(0);
  const [rmwImplementation, setRmwImplementation] = useState<string>("rmw_cyclonedds_cpp");
  const [confirmReboot, setConfirmReboot] = useState(false);

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [remoteTab, setRemoteTab] = useState<"wifi" | "ros" | "mechanics" | "voice" | "passwords">("wifi");

  const rawDistro = String(robot?.active_ros_distro ?? "").trim();
  const rawDistroLower = rawDistro.toLowerCase();
  const detectedRosLabel =
    rawDistroLower.includes("ros2") || rawDistroLower.includes("humble")
      ? "ROS 2 Humble"
      : rawDistroLower.includes("ros1") || rawDistroLower.includes("noetic")
        ? "ROS 1 Noetic"
        : null;

  const effectiveRosMode: "ros1" | "ros2" =
    activeRosMode ?? (detectedRosLabel === "ROS 2 Humble" ? "ros2" : "ros1");
  const isRos2 = effectiveRosMode === "ros2";

  const networkData = robotNetwork ?? localNetwork;

  // Hydrate initial values from robot capabilities (live_config nested or top-level)
  useEffect(() => {
    if (!robot) return;
    const caps = (robot.capabilities && typeof robot.capabilities === "object"
      ? robot.capabilities
      : {}) as Record<string, unknown>;
    const liveCfg = (caps.live_config && typeof caps.live_config === "object"
      ? caps.live_config
      : caps) as Record<string, unknown>;

    const wifiCfg =
      liveCfg.wifi && typeof liveCfg.wifi === "object"
        ? (liveCfg.wifi as Record<string, unknown>)
        : null;
    if (wifiCfg) {
      if (wifiCfg.mode === 1 || wifiCfg.mode === 2) setWifiMode(wifiCfg.mode);
      const preferredSsid =
        wifiCfg.mode === 1
          ? wifiCfg.ap_ssid ?? wifiCfg.sta_ssid
          : wifiCfg.sta_ssid ?? wifiCfg.ap_ssid;
      if (typeof preferredSsid === "string" && preferredSsid.trim()) {
        setWifiSsid(preferredSsid);
      }
    }

    const rawWithArm = liveCfg.with_arm ?? caps.with_arm;
    if (typeof rawWithArm === "boolean") setWithArm(rawWithArm);
    else if (typeof rawWithArm === "number") setWithArm(rawWithArm === 1);

    const rawXShift = liveCfg.x_shift ?? caps.x_shift;
    if (typeof rawXShift === "number" && Number.isFinite(rawXShift)) setXShift(rawXShift);

    const rawDeviations = liveCfg.servo_deviations ?? caps.servo_deviations;
    if (rawDeviations && typeof rawDeviations === "object") {
      const next = buildDefaultServoTrims();
      for (const [k, v] of Object.entries(rawDeviations as Record<string, unknown>)) {
        if (k in next && typeof v === "number" && Number.isFinite(v)) next[k] = v;
      }
      setServoDeviations(next);
    }

    const distro = String(robot.active_ros_distro ?? "").toLowerCase();
    if (distro.includes("ros2") || distro.includes("humble")) setTargetRos("ros2");
    else setTargetRos("ros1");

    const rawAsr = liveCfg.asr_language ?? caps.asr_language;
    if (rawAsr === "Chinese" || rawAsr === "English") {
      setAsrLanguage(rawAsr);
    }
  }, [robot]);

  // Fetch local network telemetry if parent didn't pass robotNetwork
  useEffect(() => {
    if (!robot?.id || robotNetwork) return;
    let cancelled = false;
    fetchRobotNetwork(robot.id)
      .then((data) => {
        if (!cancelled) setLocalNetwork(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [robot?.id, robotNetwork]);

  if (!robot) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <Bot className="h-10 w-10 text-eigenia-orange/60" />
          <div className="text-sm font-semibold text-white">No Robot Selected for Remote Administration</div>
          <p className="max-w-md text-xs text-eigenia-muted">
            Select a PuppyPi robot from the top Telemetry Bar to configure Wi-Fi, credentials, servo trims, and ROS1/ROS2 runtime over SSH.
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
        text: err instanceof Error ? err.message : `SSH operation "${key}" failed`,
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleRefreshNetwork = async () => {
    setRefreshingNet(true);
    try {
      if (onRefreshNetwork) {
        await onRefreshNetwork();
      } else {
        const data = await fetchRobotNetwork(robot.id);
        setLocalNetwork(data);
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to refresh live network telemetry",
      });
    } finally {
      setRefreshingNet(false);
    }
  };

  const handleUseIp = (ip: string) =>
    runAction(`switch-ip-${ip}`, async () => {
      if (onSwitchActiveIp) {
        await onSwitchActiveIp(ip);
      } else {
        await setRobotActiveIp(robot.id, ip);
        onUpdated();
      }
      setBanner({
        kind: "ok",
        text: `Active control IP switched to ${ip} — ROSBridge, FPV video, and SSH now target ${ip}.`,
      });
    });

  const handleSaveWifi = (e: React.FormEvent) => {
    e.preventDefault();
    void runAction("wifi", async () => {
      if (!wifiSsid.trim()) throw new Error("Wi-Fi SSID cannot be empty.");
      await updateRobotWifi(robot.id, {
        mode: wifiMode,
        ssid: wifiSsid.trim(),
        password: wifiPassword || undefined,
        country_code: wifiCountry.trim().toUpperCase() || "US",
        restart_service: restartWifiService,
      });
      setBanner({
        kind: "ok",
        text: `Updated PuppyPi Wi-Fi to ${wifiMode === 2 ? "STA" : "AP"} mode (SSID: ${wifiSsid.trim()}, Country: ${wifiCountry.toUpperCase()}).`,
      });
      onUpdated();
      void handleRefreshNetwork();
    });
  };

  const handleSavePassword = (e: React.FormEvent) => {
    e.preventDefault();
    void runAction("password", async () => {
      if (!newPassword) throw new Error("Enter a new password.");
      if (newPassword !== confirmPassword) throw new Error("Passwords do not match.");
      if (/[\r\n:]/.test(newPassword)) {
        throw new Error("Password cannot contain newlines or colons.");
      }
      await updateRobotPassword(robot.id, {
        target_user: targetUser,
        new_password: newPassword,
      });
      setNewPassword("");
      setConfirmPassword("");
      setBanner({
        kind: "ok",
        text: `Password rotated for Linux user "${targetUser}"${
          targetUser === "pi" ? " and synced to PostgreSQL 18 Fernet vault" : ""
        }.`,
      });
      onUpdated();
    });
  };

  const handleSaveMechanics = () =>
    runAction("mechanics", async () => {
      await updateRobotMechanics(robot.id, {
        with_arm: withArm ? 1 : 0,
        x_shift: xShift,
        servo_deviations: servoDeviations,
      });
      setBanner({
        kind: "ok",
        text: `Updated ${isRos2 ? "ROS 2" : "ROS 1"} puppy.py (with_arm=${withArm ? 1 : 0}, x_shift=${xShift.toFixed(
          1
        )}) and 11-servo deviation trims.`,
      });
      onUpdated();
    });

  const handleSaveRos = (overrideTarget?: "ros1" | "ros2") =>
    runAction("ros", async () => {
      const nextTarget = overrideTarget ?? targetRos;
      setTargetRos(nextTarget);
      await updateRobotRos(robot.id, {
        target_ros: nextTarget,
        asr_language: asrLanguage,
        ...(nextTarget === "ros2"
          ? { ros_domain_id: rosDomainId, rmw_implementation: rmwImplementation }
          : {}),
      });
      if (onTogglePreview) onTogglePreview(null);
      setBanner({
        kind: "ok",
        text: `Switched PuppyPi to ${
          nextTarget === "ros2"
            ? `ROS 2 Humble (CycloneDDS, DOMAIN_ID=${rosDomainId})`
            : "ROS 1 Noetic (rosmaster :11311)"
        } with ASR_LANGUAGE=${asrLanguage}.`,
      });
      onUpdated();
    });

  const handlePower = (action: "restart_ros" | "reboot") =>
    runAction(`power-${action}`, async () => {
      await sendRobotPower(robot.id, action);
      setConfirmReboot(false);
      setBanner({
        kind: "ok",
        text:
          action === "restart_ros"
            ? "Dispatched start_node.service restart on PuppyPi."
            : "Reboot command sent to PuppyPi — allow ~45 seconds for reconnect.",
      });
      onUpdated();
    });

  const wifiIface: NetworkInterfaceInfo | null = networkData?.wifi ?? null;
  const ethIfaces: NetworkInterfaceInfo[] = Array.isArray(networkData?.ethernet)
    ? networkData.ethernet
    : [];

  const activePuppyPyPath = isRos2
    ? "puppypi_ros2:/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py"
    : "puppypi:/home/ubuntu/puppypi/src/puppy_control/scripts/puppy.py";

  return (
    <div className="flex flex-col gap-4">
      {/* Robot Identity Banner */}
      <InteractiveSurface
        accent={isRos2 ? "orange" : "sky"}
        title={`${robot.name} · Remote SSH Administration`}
        subtitle={`SSH Target: ${robot.ssh_user}@${robot.ip_address} · Atomic py_compile + stdin chpasswd safety enforced`}
        badge={
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="sky" className="font-mono">
              {robot.ip_address}
            </Badge>
            <Badge variant={detectedRosLabel === "ROS 2 Humble" ? "default" : detectedRosLabel ? "sky" : "amber"}>
              Live Robot: {detectedRosLabel ?? "Detecting..."}
            </Badge>
            {isRos2 && detectedRosLabel !== "ROS 2 Humble" && (
              <Badge variant="default">UI Theme: ROS 2 Preview</Badge>
            )}
          </div>
        }
        headerRight={
          <div className="flex items-center gap-2">
            {!detectedRosLabel && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 px-2 text-[10px]"
                disabled={refreshingNet}
                onClick={() => void handleRefreshNetwork()}
              >
                {refreshingNet ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                Re-Detect ROS
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={onUpdated}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh Robot
            </Button>
          </div>
        }
      >
        <SegmentedTabs
          value={remoteTab}
          onValueChange={(next) =>
            setRemoteTab(next as "wifi" | "ros" | "mechanics" | "voice" | "passwords")
          }
          tabs={[
            { id: "wifi", label: "Wi-Fi & Network", icon: <Wifi className="h-3.5 w-3.5" /> },
            {
              id: "ros",
              label: "ROS 1 ↔ ROS 2 & Power",
              icon: <Cpu className="h-3.5 w-3.5" />,
              alertTone: isRos2 ? "ok" : null,
            },
            { id: "mechanics", label: "Mechanics & 11-Servo Trims", icon: <Wrench className="h-3.5 w-3.5" /> },
            { id: "voice", label: "Voice & Audio", icon: <Volume2 className="h-3.5 w-3.5" /> },
            { id: "passwords", label: "Passwords (pi / root)", icon: <KeyRound className="h-3.5 w-3.5" /> },
          ]}
        />
      </InteractiveSurface>

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
            className="ml-3 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      <Tabs value={remoteTab} onValueChange={(v) => setRemoteTab(v as "wifi" | "ros" | "mechanics" | "voice" | "passwords")} className="w-full">

        {/* TAB 1: WI-FI & NETWORK + LIVE INTERFACE CARDS */}
        <TabsContent value="wifi" className="space-y-4">
          {/* Live Network Interface Cards (Wi-Fi + Ethernet) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2">
                <Wifi className="h-3.5 w-3.5 text-eigenia-sky" />
                Live PuppyPi Network Interfaces (Wi-Fi & Ethernet)
              </CardTitle>
              <Button
                size="sm"
                variant="secondary"
                disabled={refreshingNet}
                onClick={() => void handleRefreshNetwork()}
              >
                {refreshingNet ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Refresh IPs
              </Button>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {/* Wi-Fi Card (wlan0) */}
              <div
                className={`flex flex-col justify-between gap-2.5 rounded-md border p-3 ${
                  wifiIface?.enabled
                    ? "border-emerald-500/40 bg-emerald-500/10"
                    : "border-white/10 bg-eigenia-obsidian"
                }`}
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-mono text-xs font-semibold text-white">
                      {wifiIface?.enabled ? (
                        <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <WifiOff className="h-3.5 w-3.5 text-eigenia-muted" />
                      )}
                      Wi-Fi ({wifiIface?.ifname || "wlan0"})
                    </span>
                    <Badge
                      variant={wifiIface?.enabled ? "sky" : "neutral"}
                      className={
                        wifiIface?.enabled
                          ? "border-emerald-500/40 bg-emerald-500/20 text-emerald-400"
                          : undefined
                      }
                    >
                      {wifiIface?.enabled ? "ENABLED" : "DISABLED"}
                    </Badge>
                  </div>
                  <div className="font-mono text-sm font-semibold tabular-nums text-white">
                    {wifiIface?.ipv4 || "No IPv4"}
                  </div>
                  <div className="space-y-0.5 font-mono text-[10px] text-eigenia-muted">
                    <div>
                      SSID: <span className="text-white">{wifiIface?.ssid || "—"}</span>
                      {wifiIface?.mode ? ` (${wifiIface.mode})` : ""}
                    </div>
                    {wifiIface?.freq_mhz && (
                      <div>
                        Band: <span className="text-eigenia-sky">{formatBand(wifiIface.freq_mhz)}</span>
                        {typeof wifiIface.signal_pct === "number" ? ` · ${wifiIface.signal_pct}%` : ""}
                      </div>
                    )}
                    <div>MAC: {wifiIface?.mac || "—"}</div>
                  </div>
                </div>
                {wifiIface?.ipv4 && (
                  <Button
                    size="sm"
                    variant={wifiIface.ipv4 === robot.ip_address ? "secondary" : "default"}
                    disabled={wifiIface.ipv4 === robot.ip_address || busyAction !== null}
                    className="w-full text-[11px]"
                    onClick={() => void handleUseIp(wifiIface.ipv4!)}
                  >
                    <CheckCircle2 className="h-3 w-3" />
                    {wifiIface.ipv4 === robot.ip_address
                      ? "Active Control IP"
                      : "Set as Active Control IP"}
                  </Button>
                )}
              </div>

              {/* Ethernet Cards (eth0, eth1, eth2) */}
              {(ethIfaces.length > 0
                ? ethIfaces
                : [
                    { ifname: "eth0", enabled: false, state: "down", ipv4: null, mac: null },
                    { ifname: "eth1", enabled: false, state: "down", ipv4: null, mac: null },
                  ]
              ).map((eth) => {
                const isActiveIp = Boolean(eth.ipv4 && eth.ipv4 === robot.ip_address);
                return (
                  <div
                    key={eth.ifname}
                    className={`flex flex-col justify-between gap-2.5 rounded-md border p-3 ${
                      eth.enabled
                        ? "border-eigenia-sky/40 bg-eigenia-sky/10"
                        : "border-white/10 bg-eigenia-obsidian"
                    }`}
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 font-mono text-xs font-semibold text-white">
                          <Cable className="h-3.5 w-3.5 text-eigenia-sky" />
                          Ethernet ({eth.ifname})
                        </span>
                        <Badge variant={eth.enabled ? "sky" : "neutral"}>
                          {eth.enabled ? "ENABLED" : "DISABLED"}
                        </Badge>
                      </div>
                      <div className="font-mono text-sm font-semibold tabular-nums text-white">
                        {eth.ipv4 || "No IPv4"}
                      </div>
                      <div className="space-y-0.5 font-mono text-[10px] text-eigenia-muted">
                        <div>
                          State: <span className="text-white">{eth.state || "down"}</span>
                          {eth.kind ? ` · ${eth.kind}` : ""}
                        </div>
                        <div>MAC: {eth.mac || "—"}</div>
                      </div>
                    </div>
                    {eth.ipv4 && (
                      <Button
                        size="sm"
                        variant={isActiveIp ? "secondary" : "sky"}
                        disabled={isActiveIp || busyAction !== null}
                        className="w-full text-[11px]"
                        onClick={() => void handleUseIp(eth.ipv4!)}
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        {isActiveIp ? "Active Control IP" : "Set as Active Control IP"}
                      </Button>
                    )}
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>PuppyPi Wi-Fi Controller (`/etc/wifi/wifi_conf.py` + NetworkManager)</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSaveWifi} className="max-w-xl space-y-4">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    type="button"
                    variant={wifiMode === 2 ? "default" : "secondary"}
                    onClick={() => setWifiMode(2)}
                  >
                    STA Client Mode (`2`)
                  </Button>
                  <Button
                    type="button"
                    variant={wifiMode === 1 ? "default" : "secondary"}
                    onClick={() => setWifiMode(1)}
                  >
                    AP Hotspot Mode (`1`)
                  </Button>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="space-y-1 sm:col-span-2">
                    <label className="text-[11px] text-eigenia-muted">Wi-Fi SSID</label>
                    <Input
                      value={wifiSsid}
                      onChange={(e) => setWifiSsid(e.target.value)}
                      placeholder="Wildcat"
                      className="font-mono text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] text-eigenia-muted">Country Code</label>
                    <Input
                      value={wifiCountry}
                      maxLength={2}
                      onChange={(e) => setWifiCountry(e.target.value.toUpperCase())}
                      placeholder="US"
                      className="font-mono text-xs uppercase"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-[11px] text-eigenia-muted">Wi-Fi Passphrase</label>
                  <div className="flex gap-1.5">
                    <Input
                      type={showWifiPass ? "text" : "password"}
                      value={wifiPassword}
                      onChange={(e) => setWifiPassword(e.target.value)}
                      placeholder="Enter WPA2/WPA3 password"
                      className="font-mono text-xs"
                    />
                    <Button
                      type="button"
                      size="icon"
                      variant="secondary"
                      onClick={() => setShowWifiPass((v) => !v)}
                    >
                      {showWifiPass ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </div>

                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div>
                    <div className="text-xs font-medium text-white">Apply NetworkManager Connection Immediately</div>
                    <div className="text-[10px] text-eigenia-muted">
                      Creates a persistent STA profile (`autoconnect=yes`) while keeping Ethernet online.
                    </div>
                  </div>
                  <Switch checked={restartWifiService} onCheckedChange={setRestartWifiService} />
                </div>

                <Button type="submit" disabled={busyAction !== null}>
                  {busyAction === "wifi" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Apply Wi-Fi Configuration via SSH
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: ROS 1 <-> ROS 2 COMPARISON, SETTINGS & POWER */}
        <TabsContent
          value="ros"
          className={`space-y-4 ${
            isRos2
              ? "rounded-lg border border-eigenia-orange/60 bg-gradient-to-br from-eigenia-orange/15 via-eigenia-obsidian/60 to-eigenia-orange/10 p-3 shadow-md shadow-eigenia-orange/10"
              : ""
          }`}
        >
          <RosComparisonCard
            activeRosMode={effectiveRosMode}
            robot={robot}
            onSwitchRos={async (target) => {
              await handleSaveRos(target);
            }}
            switching={busyAction === "ros"}
            previewMode={previewMode}
            onTogglePreview={onTogglePreview ?? (() => {})}
          />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card
              className={
                targetRos === "ros2" || isRos2
                  ? "border-eigenia-orange/65 bg-eigenia-surface shadow-sm shadow-eigenia-orange/15"
                  : "border-eigenia-sky/35"
              }
            >
              <CardHeader>
                <CardTitle>ROS Container Runtime & Voice AI Settings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[11px] text-eigenia-muted">Target ROS Stack</label>
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      type="button"
                      variant={targetRos === "ros1" ? "sky" : "secondary"}
                      onClick={() => setTargetRos("ros1")}
                    >
                      ROS 1 Noetic (`puppypi`)
                    </Button>
                    <Button
                      type="button"
                      variant={targetRos === "ros2" ? "default" : "secondary"}
                      onClick={() => setTargetRos("ros2")}
                    >
                      ROS 2 Humble (`puppypi_ros2`)
                    </Button>
                  </div>
                </div>

                {/* Mode-Specific Environment Settings */}
                {targetRos === "ros2" ? (
                  <div className="space-y-3 rounded-md border border-eigenia-orange/55 bg-eigenia-orange/15 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-1">
                      <span className="font-mono text-[10px] font-semibold uppercase text-eigenia-orange">
                        ROS 2 Humble DDS Settings & Auto-Bringup
                      </span>
                      <Badge variant="default" className="font-mono text-[9px]">
                        /home/ubuntu/ros2_ws/.typerc
                      </Badge>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="space-y-1">
                        <label className="font-mono text-[10px] text-eigenia-muted">ROS_DOMAIN_ID</label>
                        <Input
                          type="number"
                          min={0}
                          max={232}
                          value={rosDomainId}
                          onChange={(e) => setRosDomainId(Math.max(0, Math.min(232, Number(e.target.value) || 0)))}
                          className="font-mono text-xs tabular-nums"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="font-mono text-[10px] text-eigenia-muted">RMW_IMPLEMENTATION</label>
                        <select
                          value={rmwImplementation}
                          onChange={(e) => setRmwImplementation(e.target.value)}
                          className="h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                        >
                          <option value="rmw_cyclonedds_cpp">rmw_cyclonedds_cpp</option>
                          <option value="rmw_fastrtps_cpp">rmw_fastrtps_cpp</option>
                        </select>
                      </div>
                    </div>
                    <div className="space-y-0.5 rounded bg-eigenia-obsidian/75 px-2.5 py-1.5 font-mono text-[10px] text-eigenia-muted">
                      <div>
                        Kinematics: <span className="text-white">ros2_ws/src/driver/puppy_control/puppy_control/puppy.py</span>
                      </div>
                      <div>
                        Auto-Bringup: <span className="text-eigenia-orange">ros_robot_controller · puppy_control · usb_cam · web_video_server · rosbridge_websocket</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5 rounded-md border border-eigenia-sky/35 bg-eigenia-sky/10 p-3 font-mono text-[10px]">
                    <div className="flex flex-wrap items-center justify-between gap-1">
                      <span className="font-semibold uppercase text-eigenia-sky">ROS 1 Noetic Master Settings</span>
                      <Badge variant="sky" className="text-[9px]">
                        /home/ubuntu/puppypi/.robotrc
                      </Badge>
                    </div>
                    <div className="text-eigenia-muted">
                      ROS_MASTER_URI: <span className="text-white">http://{robot.ip_address}:11311</span> · Container: <span className="text-white">puppypi</span>
                    </div>
                    <div className="text-eigenia-muted">
                      Kinematics: <span className="text-white">puppypi/src/puppy_control/scripts/puppy.py</span>
                    </div>
                  </div>
                )}

                <div className="space-y-1.5">
                  <label className="text-[11px] text-eigenia-muted">Onboard Voice `ASR_LANGUAGE`</label>
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      type="button"
                      variant={asrLanguage === "English" ? "sky" : "secondary"}
                      onClick={() => setAsrLanguage("English")}
                    >
                      English
                    </Button>
                    <Button
                      type="button"
                      variant={asrLanguage === "Chinese" ? "sky" : "secondary"}
                      onClick={() => setAsrLanguage("Chinese")}
                    >
                      Chinese
                    </Button>
                  </div>
                </div>

                <Button className="w-full" disabled={busyAction !== null} onClick={() => void handleSaveRos()}>
                  {busyAction === "ros" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Apply {targetRos === "ros2" ? "ROS 2 Humble" : "ROS 1 Noetic"} & ASR Configuration
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Power className="h-3.5 w-3.5 text-eigenia-fault" />
                  Power & Service Lifecycle Controls
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div className="text-xs font-semibold text-white">Restart ROS Stack (`start_node.service`)</div>
                  <p className="mt-1 text-[11px] text-eigenia-muted">
                    Reloads `puppy_control`, `rosbridge_websocket:9090`, and `web_video_server:8080` after kinematics or ASR edits.
                  </p>
                  <Button
                    className="mt-3 w-full"
                    variant="sky"
                    disabled={busyAction !== null}
                    onClick={() => void handlePower("restart_ros")}
                  >
                    {busyAction === "power-restart_ros" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    Restart ROS Stack
                  </Button>
                </div>

                <div className="rounded-md border border-eigenia-fault/40 bg-eigenia-fault/10 p-3">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-eigenia-fault">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Reboot PuppyPi Raspberry Pi 5
                  </div>
                  <p className="mt-1 text-[11px] text-eigenia-muted">
                    Temporarily interrupts SSH, ROSBridge, and FPV video for ~45 seconds while Debian Bookworm restarts.
                  </p>
                  {!confirmReboot ? (
                    <Button
                      className="mt-3 w-full"
                      variant="destructive"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmReboot(true)}
                    >
                      <Power className="h-3.5 w-3.5" />
                      Reboot PuppyPi
                    </Button>
                  ) : (
                    <div className="mt-3 flex gap-2">
                      <Button
                        className="flex-1"
                        variant="destructive"
                        disabled={busyAction !== null}
                        onClick={() => void handlePower("reboot")}
                      >
                        {busyAction === "power-reboot" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Power className="h-3.5 w-3.5" />
                        )}
                        Confirm Reboot Now
                      </Button>
                      <Button variant="secondary" onClick={() => setConfirmReboot(false)}>
                        Cancel
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* TAB 3: MECHANICS & 11-SERVO TRIMS */}
        <TabsContent value="mechanics">
          <Card>
            <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle>Kinematics (`puppy.py`) & 11-Servo Deviation Trims</CardTitle>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
                  <Badge variant={isRos2 ? "default" : "sky"} className="text-[9px]">
                    {isRos2 ? "ROS 2 Target" : "ROS 1 Target"}
                  </Badge>
                  <span className="text-eigenia-muted">{activePuppyPyPath}</span>
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setServoDeviations(buildDefaultServoTrims())}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Zero All Trims
              </Button>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="flex items-center justify-between rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div>
                    <div className="text-xs font-semibold text-white">
                      2-DOF Robotic Arm Installed (`with_arm = {withArm ? 1 : 0}`)
                    </div>
                    <div className="text-[10px] text-eigenia-muted">
                      Adjusts PuppyPi center-of-mass kinematics & activates arm action groups.
                    </div>
                  </div>
                  <Switch checked={withArm} onCheckedChange={setWithArm} />
                </div>

                <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3">
                  <div className="flex justify-between font-mono text-xs">
                    <span className="text-eigenia-muted">Default `x_shift` Offset</span>
                    <span className="tabular-nums text-white">{xShift.toFixed(1)} cm</span>
                  </div>
                  <Slider
                    min={-6}
                    max={6}
                    step={0.1}
                    value={[xShift]}
                    onValueChange={([v]) => setXShift(Number(v.toFixed(1)))}
                  />
                </div>
              </div>

              <div>
                <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  Servo Deviation Offsets (`servo_deviation.json`, range -125 .. +125)
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                  {Object.entries(SERVO_LABELS).map(([id, label]) => (
                    <div
                      key={id}
                      className="space-y-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5"
                    >
                      <label className="block font-mono text-[10px] text-eigenia-muted">{label}</label>
                      <Input
                        type="number"
                        min={-125}
                        max={125}
                        value={servoDeviations[id] ?? 0}
                        onChange={(e) => {
                          const val = Math.max(-125, Math.min(125, Number(e.target.value) || 0));
                          setServoDeviations((prev) => ({ ...prev, [id]: val }));
                        }}
                        className="h-7 font-mono text-xs tabular-nums"
                      />
                    </div>
                  ))}
                </div>
              </div>

              <Button disabled={busyAction !== null} onClick={handleSaveMechanics}>
                {busyAction === "mechanics" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save Kinematics & Servo Trims via SSH
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 4: VOICE & AUDIO */}
        <TabsContent value="voice">
          <VoiceControlPanel robot={robot} />
        </TabsContent>

        {/* TAB 5: PASSWORDS */}
        <TabsContent value="passwords">
          <Card>
            <CardHeader>
              <CardTitle>Linux Account Password Rotation (`chpasswd` over SSH stdin)</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSavePassword} className="max-w-xl space-y-4">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    type="button"
                    variant={targetUser === "pi" ? "default" : "secondary"}
                    onClick={() => setTargetUser("pi")}
                  >
                    User: `pi`
                  </Button>
                  <Button
                    type="button"
                    variant={targetUser === "root" ? "default" : "secondary"}
                    onClick={() => setTargetUser("root")}
                  >
                    User: `root`
                  </Button>
                </div>

                {targetUser === "pi" && (
                  <div className="flex items-start gap-2 rounded-md border border-eigenia-sky/35 bg-eigenia-sky/10 p-3 text-xs text-eigenia-sky">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      Rotating the <strong className="font-mono">pi</strong> password automatically updates the Fernet-encrypted SSH credential stored in PostgreSQL 18 so TwinScan never loses SSH access.
                    </span>
                  </div>
                )}

                <div className="space-y-1">
                  <label className="text-[11px] text-eigenia-muted">New Password for `{targetUser}`</label>
                  <div className="flex gap-1.5">
                    <Input
                      type={showNewPass ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="New password"
                      className="font-mono text-xs"
                    />
                    <Button
                      type="button"
                      size="icon"
                      variant="secondary"
                      onClick={() => setShowNewPass((v) => !v)}
                    >
                      {showNewPass ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-[11px] text-eigenia-muted">Confirm New Password</label>
                  <Input
                    type={showNewPass ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter new password"
                    className="font-mono text-xs"
                  />
                </div>

                <Button
                  type="submit"
                  disabled={busyAction !== null || !newPassword || newPassword !== confirmPassword}
                >
                  {busyAction === "password" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <KeyRound className="h-3.5 w-3.5" />
                  )}
                  Update `{targetUser}` Password
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
