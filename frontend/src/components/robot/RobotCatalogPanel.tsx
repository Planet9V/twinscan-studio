"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Box,
  Cable,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Download,
  GitBranch,
  HardDrive,
  LayoutGrid,
  Loader2,
  Package,
  PlusCircle,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Usb,
  Wifi,
  WifiOff,
  Wrench,
} from "lucide-react";
import { AnimatedMetric } from "@/components/ui/AnimatedMetric";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs, type SegmentedTabItem } from "@/components/ui/SegmentedTabs";
import { SlideOverDrawer } from "@/components/ui/SlideOverDrawer";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { Pi5TopologyFlow } from "@/components/robot/Pi5TopologyFlow";
import { UpdateAndFeatureCheckPanel } from "@/components/robot/UpdateAndFeatureCheckPanel";
import {
  catalogueRobot,
  cleanRobotStaleLogs,
  deleteRobot,
  discoverRobots,
  fetchPi5HardwareDiagnostics,
  fetchRobotNetwork,
  getRobotCycloneDxUrl,
  getRobotDetail,
  registerRobot,
  setRobotActiveIp,
  type Pi5ComponentStatus,
  type Pi5HardwareComponentState,
  type Pi5HardwareDiagnostics,
  type Pi5PmicRail,
  type RobotDevice,
  type RobotNetworkTelemetry,
  type RobotRecord,
  type RobotSbomPackage,
} from "@/lib/robotApi";

const Pi5HardwareTwin3D = dynamic(() => import("@/components/robot/Pi5HardwareTwin3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[520px] items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian font-mono text-xs text-eigenia-muted">
      Initializing Interactive 3D Raspberry Pi 5 BOM Twin...
    </div>
  ),
});

interface RobotCatalogPanelProps {
  robots: RobotRecord[];
  activeRobotId: string | null;
  onSelectRobot: (id: string) => void;
  onRobotsChanged: () => void;
  robotNetwork?: RobotNetworkTelemetry | null;
  onRefreshNetwork?: () => Promise<void>;
  onSwitchActiveIp?: (ip: string) => Promise<void>;
}

type CatalogTabId = "hardware" | "bom" | "sbom" | "updates" | "fleet";
type HardwareViewMode = "3d" | "flow" | "split";

const VALID_TABS: CatalogTabId[] = ["hardware", "bom", "sbom", "updates", "fleet"];

const SBOM_LAYERS = [
  "all",
  "host_dpkg",
  "host_pip",
  "ros1_dpkg",
  "ros1_pip",
  "ros2_dpkg",
  "ros2_pip",
] as const;

function isDeviceDisplaced(device: RobotDevice): boolean {
  const st = (device.status || "").toLowerCase();
  if (
    st.includes("missing") ||
    st.includes("displaced") ||
    st.includes("unattached") ||
    st.includes("offline") ||
    st.includes("absent") ||
    st.includes("disconnected") ||
    st.includes("not_detected") ||
    st.includes("fault")
  ) {
    return true;
  }
  const text = `${device.subsystem} ${device.make} ${device.model}`.toLowerCase();
  const isCriticalSensor =
    text.includes("ld19") || text.includes("wonderecho") || text.includes("i2c");
  return (
    isCriticalSensor && st !== "online" && st !== "ok" && st !== "attached" && st !== "detected"
  );
}

function getDeviceStatusVariant(device: RobotDevice): "fault" | "amber" | "sky" | "neutral" {
  if (isDeviceDisplaced(device)) return "fault";
  const st = (device.status || "").toLowerCase();
  if (st === "online" || st === "ok" || st === "attached" || st === "detected") return "sky";
  if (st.includes("warn") || st.includes("degraded")) return "amber";
  return "neutral";
}

function getPi5StatusBadge(status: Pi5ComponentStatus): {
  variant: "sky" | "amber" | "fault" | "neutral";
  className: string;
  label: string;
} {
  switch (status) {
    case "ok":
      return {
        variant: "sky",
        className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
        label: "OK",
      };
    case "warning":
      return { variant: "amber", className: "", label: "WARNING" };
    case "fault":
      return { variant: "fault", className: "", label: "FAULT" };
    default:
      return { variant: "neutral", className: "", label: "EMPTY" };
  }
}

function findPmicRailVolts(rails: Pi5PmicRail[], keyword: string): number | null {
  const k = keyword.toUpperCase();
  const match = rails.find((r) => String(r.name || "").toUpperCase().includes(k));
  return match && typeof match.volts === "number" ? match.volts : null;
}

function matchDeviceToComponentId(
  device: RobotDevice,
  components: Pi5HardwareComponentState[]
): string | null {
  const haystack = `${device.subsystem} ${device.make} ${device.model} ${device.bus_type} ${
    device.device_path ?? ""
  } ${device.usb_id ?? ""}`.toLowerCase();

  let bestId: string | null = null;
  let bestScore = 0;
  for (const comp of components) {
    const kws = Array.isArray(comp.bom_match_keywords) ? comp.bom_match_keywords : [];
    let score = 0;
    for (const kw of kws) {
      const k = kw.trim().toLowerCase();
      if (k && haystack.includes(k)) {
        score += Math.max(1, k.length);
      }
    }
    if (score > bestScore) {
      bestScore = score;
      bestId = comp.component_id;
    }
  }
  if (bestId) return bestId;

  if (haystack.includes("ld19") || haystack.includes("lidar") || haystack.includes("cp210")) {
    return "ld19_lidar_module";
  }
  if (haystack.includes("wonderecho") || haystack.includes("audio") || haystack.includes("0c76")) {
    return "wonderecho_pro";
  }
  if (haystack.includes("camera") || haystack.includes("icspring") || haystack.includes("video")) {
    return "camera_icspring";
  }
  if (
    haystack.includes("stm32") ||
    haystack.includes("rrc") ||
    haystack.includes("i2c") ||
    haystack.includes("servo")
  ) {
    return "rrc_hat_stm32";
  }
  if (haystack.includes("wifi") || haystack.includes("wlan") || haystack.includes("bluetooth")) {
    return "wifi_bt_module";
  }
  if (haystack.includes("eth") || haystack.includes("rj45")) {
    return "eth_rj45";
  }
  if (haystack.includes("bcm2712") || haystack.includes("cortex") || haystack.includes("cpu")) {
    return "bcm2712_soc";
  }
  if (haystack.includes("lpddr") || haystack.includes("ram") || haystack.includes("memory")) {
    return "ram_lpddr4x";
  }
  if (haystack.includes("sd") || haystack.includes("mmc") || haystack.includes("storage")) {
    return "microsd_slot";
  }
  if (haystack.includes("rp1")) return "rp1_southbridge";
  if (haystack.includes("pmic") || haystack.includes("da9091")) return "da9091_pmic";
  if (haystack.includes("gpio")) return "gpio_40pin";
  return null;
}

function deviceMatchesComponent(
  device: RobotDevice,
  comp: Pi5HardwareComponentState | null,
  components: Pi5HardwareComponentState[]
): boolean {
  if (!comp) return false;
  const matchedId = matchDeviceToComponentId(device, components);
  if (matchedId === comp.component_id) return true;
  const haystack = `${device.subsystem} ${device.make} ${device.model} ${device.bus_type} ${
    device.device_path ?? ""
  } ${device.usb_id ?? ""}`.toLowerCase();
  return (comp.bom_match_keywords ?? []).some((kw) => {
    const k = kw.trim().toLowerCase();
    return Boolean(k && haystack.includes(k));
  });
}

export function RobotCatalogPanel({
  robots,
  activeRobotId,
  onSelectRobot,
  onRobotsChanged,
  robotNetwork,
  onRefreshNetwork,
  onSwitchActiveIp,
}: RobotCatalogPanelProps) {
  const [activeTab, setActiveTab] = useState<CatalogTabId>("hardware");
  const [hardwareView, setHardwareView] = useState<HardwareViewMode>("3d");

  // Fleet discovery & registration form state
  const [cidrInput, setCidrInput] = useState("192.168.1.0/24");
  const [manualIp, setManualIp] = useState("192.168.1.231");
  const [manualName, setManualName] = useState("PuppyPi-01");
  const [manualSshUser, setManualSshUser] = useState("pi");
  const [manualSshPassword, setManualSshPassword] = useState("raspberrypi");

  // BOM, SBOM & Network state
  const [devices, setDevices] = useState<RobotDevice[]>([]);
  const [sbom, setSbom] = useState<RobotSbomPackage[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [localNetwork, setLocalNetwork] = useState<RobotNetworkTelemetry | null>(null);
  const [refreshingNet, setRefreshingNet] = useState(false);

  // Filters
  const [bomSearch, setBomSearch] = useState("");
  const [bomStatusFilter, setBomStatusFilter] = useState<"all" | "ok" | "fault">("all");
  const [layerFilter, setLayerFilter] = useState<string>("all");
  const [sbomSearch, setSbomSearch] = useState("");
  const [showAllSbom, setShowAllSbom] = useState(false);

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Live Raspberry Pi 5 Diagnostics & Cross-Probing Drawer state
  const [pi5Diag, setPi5Diag] = useState<Pi5HardwareDiagnostics | null>(null);
  const [loadingPi5Diag, setLoadingPi5Diag] = useState(false);
  const [pi5DiagError, setPi5DiagError] = useState<string | null>(null);
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null);
  const [componentDrawerOpen, setComponentDrawerOpen] = useState(false);
  const [inspectedBom, setInspectedBom] = useState<RobotDevice | null>(null);
  const [inspectedSbom, setInspectedSbom] = useState<RobotSbomPackage | null>(null);
  const [ld19VerdictExpanded, setLd19VerdictExpanded] = useState(false);

  const safeRobots = useMemo(() => (Array.isArray(robots) ? robots : []), [robots]);

  const activeRobot = useMemo(
    () => safeRobots.find((r) => r.id === activeRobotId) ?? safeRobots[0] ?? null,
    [safeRobots, activeRobotId]
  );

  // Sync ?tab= and ?focus= safely on client without Next.js useSearchParams Suspense issues
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab") as CatalogTabId | null;
    const focusParam = params.get("focus");
    if (tabParam && VALID_TABS.includes(tabParam)) {
      setActiveTab(tabParam);
    }
    if (focusParam) {
      setActiveTab("hardware");
      setSelectedComponentId(focusParam);
      setComponentDrawerOpen(true);
      if (focusParam === "ld19_lidar_module") {
        setLd19VerdictExpanded(true);
      }
    }
  }, []);

  const handleTabChange = useCallback((nextId: string) => {
    const valid = VALID_TABS.includes(nextId as CatalogTabId)
      ? (nextId as CatalogTabId)
      : "hardware";
    setActiveTab(valid);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", valid);
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  const loadPi5Diagnostics = useCallback(async (robotId: string) => {
    setLoadingPi5Diag(true);
    setPi5DiagError(null);
    try {
      const data = await fetchPi5HardwareDiagnostics(robotId);
      setPi5Diag(data);
      setSelectedComponentId((prev) => {
        if (prev) return prev;
        const firstFault = data.components.find((c) => c.status === "fault");
        if (firstFault) return firstFault.component_id;
        const firstWarn = data.components.find((c) => c.status === "warning");
        if (firstWarn) return firstWarn.component_id;
        return data.components[0]?.component_id ?? "bcm2712_soc";
      });
    } catch (err) {
      setPi5DiagError(
        err instanceof Error ? err.message : "Failed to collect live Raspberry Pi 5 diagnostics"
      );
    } finally {
      setLoadingPi5Diag(false);
    }
  }, []);

  const loadDetail = useCallback(async (robotId: string) => {
    setLoadingDetail(true);
    try {
      const detail = await getRobotDetail(robotId);
      setDevices(Array.isArray(detail?.devices) ? detail.devices : []);
      setSbom(Array.isArray(detail?.sbom) ? detail.sbom : []);
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to load robot BOM & SBOM",
      });
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (activeRobot?.id) {
      void loadDetail(activeRobot.id);
      void loadPi5Diagnostics(activeRobot.id);
    } else {
      setDevices([]);
      setSbom([]);
      setPi5Diag(null);
      setPi5DiagError(null);
    }
  }, [activeRobot?.id, loadDetail, loadPi5Diagnostics]);

  useEffect(() => {
    if (!activeRobot?.id || robotNetwork) return;
    let cancelled = false;
    fetchRobotNetwork(activeRobot.id)
      .then((data) => {
        if (!cancelled) setLocalNetwork(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeRobot?.id, robotNetwork]);

  const effectiveNetwork = robotNetwork ?? localNetwork;

  const handleRefreshNet = async () => {
    if (!activeRobot) return;
    setRefreshingNet(true);
    try {
      if (onRefreshNetwork) {
        await onRefreshNetwork();
      } else {
        const data = await fetchRobotNetwork(activeRobot.id);
        setLocalNetwork(data);
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to refresh network interfaces",
      });
    } finally {
      setRefreshingNet(false);
    }
  };

  const handleUseIp = async (ip: string) => {
    if (!activeRobot) return;
    setBusyAction(`ip-${ip}`);
    setBanner(null);
    try {
      if (onSwitchActiveIp) {
        await onSwitchActiveIp(ip);
      } else {
        await setRobotActiveIp(activeRobot.id, ip);
        onRobotsChanged();
      }
      setBanner({ kind: "ok", text: `Switched active robot control IP to ${ip}.` });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to switch active IP",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleDiscover = async () => {
    setBusyAction("discover");
    setBanner(null);
    try {
      const cidrs = cidrInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const resp = await discoverRobots(cidrs.length > 0 ? cidrs : undefined);
      setBanner({
        kind: "ok",
        text: `LAN Discovery finished — found ${resp.discovered.length} candidate(s), ${resp.robots.length} robot(s) registered.`,
      });
      onRobotsChanged();
      if (resp.robots.length > 0) {
        onSelectRobot(resp.robots[0].id);
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "LAN discovery failed",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleManualRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualIp.trim()) return;
    setBusyAction("register");
    setBanner(null);
    try {
      const resp = await registerRobot({
        ip_address: manualIp.trim(),
        name: manualName.trim() || `PuppyPi (${manualIp.trim()})`,
        model: "Hiwonder PuppyPi",
        ssh_user: manualSshUser.trim() || "pi",
        ssh_password: manualSshPassword || undefined,
        rosbridge_port: 9090,
        video_port: 8080,
      });
      setBanner({
        kind: "ok",
        text: `Registered robot "${resp.robot.name}" at ${resp.robot.ip_address}.`,
      });
      onRobotsChanged();
      onSelectRobot(resp.robot.id);
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Manual robot registration failed",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleCatalogue = async () => {
    if (!activeRobot) return;
    setBusyAction("catalogue");
    setBanner(null);
    try {
      const resp = await catalogueRobot(activeRobot.id);
      setDevices(resp.devices ?? []);
      setSbom(resp.sbom ?? []);
      setBanner({
        kind: "ok",
        text: `SSH Catalogue complete — ${resp.devices?.length ?? 0} hardware devices & ${
          resp.sbom?.length ?? 0
        } SBOM packages indexed into PG18${resp.neo4j_synced ? " + Neo4j" : ""}.`,
      });
      onRobotsChanged();
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "SSH BOM/SBOM catalogue failed",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async (robot: RobotRecord) => {
    setBusyAction(`delete-${robot.id}`);
    setBanner(null);
    try {
      await deleteRobot(robot.id);
      setBanner({ kind: "ok", text: `Removed robot "${robot.name}" from fleet registry.` });
      onRobotsChanged();
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to delete robot",
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleCleanStaleLogs = async () => {
    if (!activeRobot) return;
    setBusyAction("clean-logs");
    setBanner(null);
    try {
      const res = await cleanRobotStaleLogs(activeRobot.id);
      setBanner({
        kind: res.ok ? "ok" : "error",
        text: `Removed ${res.files_removed} old log(s) (${Number(res.reclaimed_mb ?? 0).toFixed(
          1
        )} MB freed${res.disk_use_pct ? ` · MicroSD ${res.disk_use_pct}` : ""}).`,
      });
      await loadPi5Diagnostics(activeRobot.id);
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to clean stale ROS logs on PuppyPi",
      });
    } finally {
      setBusyAction(null);
    }
  };

  // Derived Pi 5 & BOM/SBOM telemetry
  const displacedDevices = useMemo(() => devices.filter(isDeviceDisplaced), [devices]);
  const okDevicesCount = Math.max(0, devices.length - displacedDevices.length);

  const pi5Components = useMemo(
    () => (Array.isArray(pi5Diag?.components) ? pi5Diag!.components : []),
    [pi5Diag]
  );

  const faultComponents = useMemo(
    () => pi5Components.filter((c) => c.status === "fault"),
    [pi5Components]
  );
  const warningComponents = useMemo(
    () => pi5Components.filter((c) => c.status === "warning"),
    [pi5Components]
  );
  const alertComponents = useMemo(
    () => [...faultComponents, ...warningComponents],
    [faultComponents, warningComponents]
  );

  const selectedComponent = useMemo(
    () => pi5Components.find((c) => c.component_id === selectedComponentId) ?? null,
    [pi5Components, selectedComponentId]
  );

  const matchingBomForSelected = useMemo(() => {
    if (!selectedComponent) return [];
    return devices.filter((d) => deviceMatchesComponent(d, selectedComponent, pi5Components));
  }, [devices, selectedComponent, pi5Components]);

  const matchingUsbPortForSelected = useMemo(() => {
    if (!selectedComponentId || !pi5Diag?.usb_ports) return null;
    const map: Record<string, string> = {
      usb2_port_1_1: "1-1",
      usb2_port_1_2: "1-2",
      usb3_port_3_1: "3-1",
      usb3_port_3_2: "3-2",
    };
    const path = map[selectedComponentId];
    return path ? pi5Diag.usb_ports.find((p) => p.port_path === path) ?? null : null;
  }, [selectedComponentId, pi5Diag]);

  const handleSelectComponentAndInspect = useCallback((componentId: string) => {
    setSelectedComponentId(componentId);
    setComponentDrawerOpen(true);
  }, []);

  const pmicRails = useMemo(
    () => (Array.isArray(pi5Diag?.pmic_rails) ? pi5Diag!.pmic_rails : []),
    [pi5Diag]
  );
  const rail3v3 = findPmicRailVolts(pmicRails, "3V3_SYS");
  const rail1v8 = findPmicRailVolts(pmicRails, "1V8_SYS");
  const railVddCore = findPmicRailVolts(pmicRails, "VDD_CORE");
  const usbBudgetMa = pi5Diag?.usb_budget_ma ?? 1600;
  const usbDrawMa = pi5Diag?.usb_total_draw_ma ?? 0;
  const usbPct = Math.min(100, Math.round((usbDrawMa / Math.max(1, usbBudgetMa)) * 100));
  const diskPct = typeof pi5Diag?.disk_used_pct === "number" ? pi5Diag.disk_used_pct : null;

  const filteredBom = useMemo(() => {
    const q = bomSearch.trim().toLowerCase();
    return devices.filter((d) => {
      const displaced = isDeviceDisplaced(d);
      if (bomStatusFilter === "fault" && !displaced) return false;
      if (bomStatusFilter === "ok" && displaced) return false;
      if (!q) return true;
      return `${d.subsystem} ${d.make} ${d.model} ${d.bus_type} ${d.device_path ?? ""} ${
        d.usb_id ?? ""
      }`
        .toLowerCase()
        .includes(q);
    });
  }, [devices, bomSearch, bomStatusFilter]);

  const layerCounts = useMemo(() => {
    const counts: Record<string, number> = { all: sbom.length };
    for (const pkg of sbom) {
      counts[pkg.layer] = (counts[pkg.layer] ?? 0) + 1;
    }
    return counts;
  }, [sbom]);

  const filteredSbom = useMemo(() => {
    const q = sbomSearch.trim().toLowerCase();
    return sbom.filter((pkg) => {
      if (layerFilter !== "all" && pkg.layer !== layerFilter) return false;
      if (!q) return true;
      return (
        String(pkg.name ?? "").toLowerCase().includes(q) ||
        String(pkg.version ?? "").toLowerCase().includes(q) ||
        String(pkg.purl ?? "").toLowerCase().includes(q)
      );
    });
  }, [sbom, layerFilter, sbomSearch]);

  const visibleSbom = showAllSbom ? filteredSbom : filteredSbom.slice(0, 150);

  const hardwareAlertTone: "fault" | "warning" | "ok" | null =
    faultComponents.length > 0
      ? "fault"
      : warningComponents.length > 0
        ? "warning"
        : pi5Diag
          ? "ok"
          : null;

  const headerStatusTone: "ok" | "warning" | "fault" | "idle" = !activeRobot
    ? "idle"
    : faultComponents.length > 0 || displacedDevices.length > 0
      ? "fault"
      : warningComponents.length > 0
        ? "warning"
        : activeRobot.status === "online"
          ? "ok"
          : "idle";

  const headerStatusLabel = !activeRobot
    ? "NO ROBOT"
    : faultComponents.length > 0
      ? `${faultComponents.length} FAULT`
      : warningComponents.length > 0
        ? `${warningComponents.length} WARN`
        : activeRobot.status === "online"
          ? "ALL SYSTEMS NOMINAL"
          : "OFFLINE";

  const tabs: SegmentedTabItem[] = [
    {
      id: "hardware",
      label: "3D & Bus Topology",
      icon: <Cpu className="h-3.5 w-3.5" />,
      count: pi5Components.length || 22,
      alertTone: hardwareAlertTone,
    },
    {
      id: "bom",
      label: "Hardware BOM",
      icon: <HardDrive className="h-3.5 w-3.5" />,
      count: devices.length,
      alertTone: displacedDevices.length > 0 ? "fault" : null,
    },
    {
      id: "sbom",
      label: "Software SBOM",
      icon: <Package className="h-3.5 w-3.5" />,
      count: sbom.length,
    },
    {
      id: "updates",
      label: "Updates & Rollback",
      icon: <ShieldCheck className="h-3.5 w-3.5" />,
    },
    {
      id: "fleet",
      label: "Fleet & Network",
      icon: <Bot className="h-3.5 w-3.5" />,
      count: safeRobots.length,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* 1. STICKY WORKSPACE HEADER WITH LIVE ANIMATED KPIs */}
      <WorkspaceHeader
        badge="FLEET & HARDWARE TWIN"
        title={activeRobot ? activeRobot.name : "Robot Fleet & Hardware Catalog"}
        subtitle={
          activeRobot
            ? `${activeRobot.ip_address} · ${activeRobot.active_ros_distro || "ROS unknown"} · ${
                pi5Diag?.board_model || activeRobot.model
              }`
            : "Discover LAN robots, inspect live Pi 5 PMIC/USB telemetry, 3D BOM twin, and CycloneDX HBOM+SBOM"
        }
        statusTone={headerStatusTone}
        statusLabel={headerStatusLabel}
        sticky
        metrics={
          activeRobot
            ? [
                {
                  label: "EXT5V",
                  value: pi5Diag?.ext5v_volts ?? null,
                  unit: "V",
                  decimals: 2,
                  tone:
                    typeof pi5Diag?.ext5v_volts === "number" && pi5Diag.ext5v_volts < 4.75
                      ? "fault"
                      : "emerald",
                  compact: true,
                },
                {
                  label: "Board Power",
                  value: pi5Diag?.total_pmic_watts ?? null,
                  unit: "W",
                  decimals: 2,
                  tone: "orange",
                  compact: true,
                },
                {
                  label: "CPU Temp",
                  value: pi5Diag?.cpu_temp_c ?? activeRobot.cpu_temp_c ?? null,
                  unit: "°C",
                  decimals: 1,
                  tone:
                    (pi5Diag?.cpu_temp_c ?? 0) >= 75
                      ? "fault"
                      : (pi5Diag?.cpu_temp_c ?? 0) >= 65
                        ? "amber"
                        : "sky",
                  compact: true,
                },
                {
                  label: "USB Draw",
                  value: pi5Diag ? `${usbDrawMa}/${usbBudgetMa}` : "--",
                  unit: "mA",
                  tone: pi5Diag?.usb_over_current ? "fault" : usbPct > 80 ? "amber" : "sky",
                  progressPct: pi5Diag ? usbPct : null,
                  compact: true,
                },
                {
                  label: "BOM OK",
                  value: devices.length > 0 ? `${okDevicesCount}/${devices.length}` : "--",
                  tone: displacedDevices.length > 0 ? "fault" : "emerald",
                  compact: true,
                },
              ]
            : undefined
        }
        actions={
          activeRobot ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                size="sm"
                variant="sky"
                disabled={loadingPi5Diag}
                onClick={() => void loadPi5Diagnostics(activeRobot.id)}
              >
                {loadingPi5Diag ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Refresh Diagnostics
              </Button>
              <Button size="sm" disabled={busyAction !== null} onClick={() => void handleCatalogue()}>
                {busyAction === "catalogue" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Cpu className="h-3.5 w-3.5" />
                )}
                Re-Scan Catalog
              </Button>
              <Button size="sm" variant="secondary" asChild>
                <a href={getRobotCycloneDxUrl(activeRobot.id)} download>
                  <Download className="h-3.5 w-3.5 text-eigenia-orange" />
                  CycloneDX
                </a>
              </Button>
              <Button size="sm" variant="outline" asChild title="Download High-Res PuppyPi Pro 3D Model (.glb)">
                <a href="/models/puppypi-pro.glb" download="puppypi-pro.glb">
                  <Download className="h-3.5 w-3.5 text-eigenia-sky" />
                  PuppyPi .GLB
                </a>
              </Button>
              <Button size="sm" variant="outline" asChild title="Download High-Res PuppyPi Pro 3D Print Mesh (.stl)">
                <a href="/models/puppypi-pro.stl" download="puppypi-pro.stl">
                  <Download className="h-3.5 w-3.5 text-eigenia-muted" />
                  .STL
                </a>
              </Button>
            </div>
          ) : undefined
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
            className="ml-3 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 2. 5 URL-SYNCED SEGMENTED TABS */}
      <SegmentedTabs
        tabs={tabs}
        value={activeTab}
        onValueChange={handleTabChange}
        rightSlot={
          activeTab === "hardware" ? (
            <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-obsidian p-0.5">
              {(
                [
                  { id: "3d", label: "3D Pi 5 Wireframe", Icon: Box },
                  { id: "flow", label: "React Flow Bus Graph", Icon: GitBranch },
                  { id: "split", label: "Split View", Icon: LayoutGrid },
                ] as const
              ).map(({ id, label, Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setHardwareView(id)}
                  className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-mono text-[10px] font-medium transition motion-reduce:transition-none ${
                    hardwareView === id
                      ? "bg-eigenia-orange text-white shadow-sm"
                      : "text-eigenia-muted hover:text-white"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
          ) : undefined
        }
      />

      {/* TAB 1: 3D & BUS TOPOLOGY */}
      {activeTab === "hardware" && (
        <div className="space-y-4">
          {!activeRobot ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
                <Bot className="h-9 w-9 text-eigenia-orange/60" />
                <div className="text-sm font-semibold text-white">No Robot Selected</div>
                <p className="max-w-md text-xs text-eigenia-muted">
                  Switch to the Fleet &amp; Network tab to discover or register a PuppyPi robot.
                </p>
                <Button size="sm" onClick={() => handleTabChange("fleet")}>
                  Open Fleet &amp; Network
                </Button>
              </CardContent>
            </Card>
          ) : (
            <>
              {pi5DiagError && (
                <div className="flex items-center gap-2 rounded-md border border-eigenia-fault/45 bg-eigenia-fault/15 px-3 py-2 font-mono text-[11px] text-eigenia-fault">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  <span>{pi5DiagError}</span>
                </div>
              )}

              {/* Live PMIC & Power Budget Strip */}
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-8">
                <AnimatedMetric
                  label="EXT5V Rail"
                  value={pi5Diag?.ext5v_volts ?? null}
                  unit="V"
                  decimals={3}
                  tone="emerald"
                  compact
                />
                <AnimatedMetric
                  label="3V3_SYS"
                  value={rail3v3}
                  unit="V"
                  decimals={3}
                  tone="sky"
                  compact
                />
                <AnimatedMetric
                  label="1V8_SYS"
                  value={rail1v8}
                  unit="V"
                  decimals={3}
                  tone="sky"
                  compact
                />
                <AnimatedMetric
                  label="VDD_CORE"
                  value={railVddCore}
                  unit="V"
                  decimals={3}
                  tone="sky"
                  compact
                />
                <AnimatedMetric
                  label="Board Watts"
                  value={pi5Diag?.total_pmic_watts ?? null}
                  unit="W"
                  decimals={2}
                  tone="orange"
                  compact
                />
                <AnimatedMetric
                  label="CPU Temp"
                  value={pi5Diag?.cpu_temp_c ?? null}
                  unit="°C"
                  decimals={1}
                  tone={
                    (pi5Diag?.cpu_temp_c ?? 0) >= 75
                      ? "fault"
                      : (pi5Diag?.cpu_temp_c ?? 0) >= 65
                        ? "amber"
                        : "default"
                  }
                  compact
                />
                <AnimatedMetric
                  label="Throttled"
                  value={pi5Diag ? pi5Diag.throttled_hex : "--"}
                  tone={pi5Diag && pi5Diag.throttled_flags.length > 0 ? "fault" : "emerald"}
                  compact
                />
                <AnimatedMetric
                  label="MicroSD"
                  value={diskPct !== null ? Math.round(diskPct) : null}
                  unit="%"
                  tone={diskPct !== null && diskPct >= 85 ? "amber" : "default"}
                  progressPct={diskPct}
                  compact
                />
              </div>

              {/* USB Power Budget Bar + Alert Quick-Jump Chips */}
              <div className="flex flex-col gap-2.5 rounded-lg border border-white/10 bg-eigenia-shell px-3.5 py-2.5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap items-center gap-2.5 font-mono text-[11px]">
                  <Usb className="h-3.5 w-3.5 text-eigenia-sky" />
                  <span className="text-eigenia-muted">USB Budget:</span>
                  <span className="font-semibold tabular-nums text-white">
                    {usbDrawMa} / {usbBudgetMa} mA ({usbPct}%)
                  </span>
                  <div className="h-2 w-28 overflow-hidden rounded-full bg-white/10">
                    <div
                      className={`h-full transition-all duration-300 motion-reduce:transition-none ${
                        pi5Diag?.usb_over_current || usbPct > 90
                          ? "bg-eigenia-fault"
                          : usbPct > 75
                            ? "bg-eigenia-amber"
                            : "bg-eigenia-sky"
                      }`}
                      style={{ width: `${usbPct}%` }}
                    />
                  </div>
                  <Badge
                    variant={pi5Diag?.usb_max_current_enable ? "sky" : "amber"}
                    className="font-mono text-[9px]"
                  >
                    usb_max_current_enable={pi5Diag?.usb_max_current_enable ? "1" : "0"}
                  </Badge>
                  <Button
                    size="sm"
                    variant={diskPct !== null && diskPct >= 85 ? "default" : "secondary"}
                    className="h-6 px-2 font-mono text-[10px]"
                    disabled={busyAction !== null}
                    onClick={() => void handleCleanStaleLogs()}
                    title="Safely delete rotated ROS logs older than 24h on PuppyPi MicroSD"
                  >
                    {busyAction === "clean-logs" ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    {busyAction === "clean-logs" ? "Cleaning Logs..." : "Clean Stale Logs"}
                  </Button>
                </div>

                {alertComponents.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-[10px] uppercase text-eigenia-muted">
                      Inspect Alerts:
                    </span>
                    {alertComponents.map((c) => (
                      <button
                        key={c.component_id}
                        type="button"
                        onClick={() => handleSelectComponentAndInspect(c.component_id)}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] transition ${
                          selectedComponentId === c.component_id
                            ? "border-eigenia-orange bg-eigenia-orange/25 text-white"
                            : c.status === "fault"
                              ? "border-eigenia-fault/50 bg-eigenia-fault/15 text-eigenia-fault hover:bg-eigenia-fault/25"
                              : "border-eigenia-amber/50 bg-eigenia-amber/15 text-eigenia-amber hover:bg-eigenia-amber/25"
                        }`}
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            c.status === "fault"
                              ? "animate-pulse bg-eigenia-fault"
                              : "bg-eigenia-amber"
                          }`}
                        />
                        {c.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Expandable LD19 Converter Verdict Banner */}
              {pi5Diag?.ld19_verdict && !pi5Diag.ld19_verdict.detected && (
                <div className="rounded-lg border border-eigenia-fault/55 bg-eigenia-fault/10">
                  <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5">
                    <button
                      type="button"
                      onClick={() => setLd19VerdictExpanded((v) => !v)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      {ld19VerdictExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-eigenia-fault" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-eigenia-fault" />
                      )}
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-eigenia-fault" />
                      <span className="text-xs font-semibold text-eigenia-fault">
                        LD19 LiDAR Verdict:
                      </span>
                      <span className="truncate font-mono text-[11px] text-white">
                        {pi5Diag.ld19_verdict.summary}
                      </span>
                    </button>
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-6 px-2.5 font-mono text-[10px]"
                      onClick={() => handleSelectComponentAndInspect("ld19_lidar_module")}
                    >
                      Inspect LD19 Drawer
                    </Button>
                  </div>

                  {ld19VerdictExpanded &&
                    Array.isArray(pi5Diag.ld19_verdict.likely_causes) &&
                    pi5Diag.ld19_verdict.likely_causes.length > 0 && (
                      <ul className="list-disc space-y-1 border-t border-eigenia-fault/30 px-7 py-2.5 font-mono text-[11px] text-eigenia-ink">
                        {pi5Diag.ld19_verdict.likely_causes.map((cause, idx) => (
                          <li key={`ld19-cause-${idx}`}>{cause}</li>
                        ))}
                      </ul>
                    )}
                </div>
              )}

              {/* Primary Interactive Stage: 3D Pi 5 Wireframe | React Flow Bus Graph | Split View */}
              {hardwareView === "3d" && (
                <Pi5HardwareTwin3D
                  diagnostics={pi5Diag}
                  selectedComponentId={selectedComponentId}
                  onSelectComponent={handleSelectComponentAndInspect}
                />
              )}

              {hardwareView === "flow" && (
                <Pi5TopologyFlow
                  diagnostics={pi5Diag}
                  selectedComponentId={selectedComponentId}
                  onSelectComponent={handleSelectComponentAndInspect}
                  heightClassName="h-[540px]"
                />
              )}

              {hardwareView === "split" && (
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <Pi5HardwareTwin3D
                    diagnostics={pi5Diag}
                    selectedComponentId={selectedComponentId}
                    onSelectComponent={handleSelectComponentAndInspect}
                  />
                  <Pi5TopologyFlow
                    diagnostics={pi5Diag}
                    selectedComponentId={selectedComponentId}
                    onSelectComponent={handleSelectComponentAndInspect}
                    heightClassName="h-[520px]"
                  />
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* TAB 2: HARDWARE BOM */}
      {activeTab === "bom" && (
        <div className="space-y-4">
          {displacedDevices.length > 0 && (
            <div className="flex items-start gap-2.5 rounded-lg border border-eigenia-fault/50 bg-eigenia-fault/15 p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-eigenia-fault" />
              <div className="space-y-1">
                <div className="text-xs font-semibold text-eigenia-fault">
                  {displacedDevices.length} Displaced / Unattached Hardware Sensor(s) Detected
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {displacedDevices.map((d) => (
                    <Badge key={d.id} variant="fault">
                      {d.subsystem}: {d.make} {d.model} ({d.status})
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          )}

          <InteractiveSurface
            title={`Hardware Bill of Materials (HBOM · ${filteredBom.length} / ${devices.length})`}
            subtitle="Click any device row to open full metadata & jump straight to its 3D Pi 5 / Bus Topology node"
            accent="orange"
            headerRight={
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative w-56">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
                  <Input
                    value={bomSearch}
                    onChange={(e) => setBomSearch(e.target.value)}
                    placeholder="Filter subsystem, bus, USB ID..."
                    className="h-7 pl-8 font-mono text-[11px]"
                  />
                </div>
                {(
                  [
                    { id: "all", label: `All (${devices.length})` },
                    { id: "ok", label: `OK (${okDevicesCount})` },
                    { id: "fault", label: `Fault (${displacedDevices.length})` },
                  ] as const
                ).map((f) => (
                  <Button
                    key={f.id}
                    size="sm"
                    variant={bomStatusFilter === f.id ? "default" : "secondary"}
                    className="h-7 px-2 font-mono text-[10px]"
                    onClick={() => setBomStatusFilter(f.id)}
                  >
                    {f.label}
                  </Button>
                ))}
                {loadingDetail && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-eigenia-sky" />
                )}
              </div>
            }
            contentClassName="p-0 overflow-x-auto"
          >
            {filteredBom.length === 0 ? (
              <div className="p-8 text-center text-xs text-eigenia-muted">
                {devices.length === 0
                  ? 'No hardware devices catalogued yet. Click "Re-Scan Catalog" above.'
                  : "No hardware devices match the active search or status filter."}
              </div>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="border-b border-white/10 bg-eigenia-obsidian font-mono text-[10px] uppercase text-eigenia-muted">
                  <tr>
                    <th className="px-4 py-2.5">Subsystem</th>
                    <th className="px-4 py-2.5">Make / Model</th>
                    <th className="px-4 py-2.5">Bus</th>
                    <th className="px-4 py-2.5">Path / USB ID</th>
                    <th className="px-4 py-2.5 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {filteredBom.map((d) => {
                    const displaced = isDeviceDisplaced(d);
                    const isSelected = inspectedBom?.id === d.id;
                    return (
                      <tr
                        key={d.id}
                        onClick={() => setInspectedBom(d)}
                        className={`cursor-pointer transition-colors motion-reduce:transition-none ${
                          isSelected
                            ? "bg-eigenia-orange/15 ring-1 ring-inset ring-eigenia-orange text-white"
                            : displaced
                              ? "bg-eigenia-fault/10 text-white hover:bg-eigenia-fault/20"
                              : "hover:bg-eigenia-sky/10"
                        }`}
                      >
                        <td className="px-4 py-2.5 font-mono text-[11px] font-medium text-white">
                          {d.subsystem}
                        </td>
                        <td className="px-4 py-2.5 font-medium text-white">
                          {d.make} {d.model}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[10px] text-eigenia-muted">
                          {d.bus_type}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[10px] text-eigenia-muted">
                          {[d.device_path, d.usb_id].filter(Boolean).join(" · ") || "—"}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <Badge variant={getDeviceStatusVariant(d)}>
                            {displaced ? `DISPLACED · ${d.status}` : d.status}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </InteractiveSurface>
        </div>
      )}

      {/* TAB 3: SOFTWARE SBOM */}
      {activeTab === "sbom" && (
        <InteractiveSurface
          title={`Software Bill of Materials (SBOM · ${filteredSbom.length} / ${sbom.length})`}
          subtitle="Click any package row to inspect full PURL & layer metadata"
          accent="sky"
          headerRight={
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-eigenia-muted" />
              <Input
                placeholder="Search package, version, purl..."
                value={sbomSearch}
                onChange={(e) => setSbomSearch(e.target.value)}
                className="h-7 pl-8 font-mono text-[11px]"
              />
            </div>
          }
          contentClassName="space-y-3"
        >
          <div className="flex flex-wrap gap-1.5">
            {SBOM_LAYERS.map((layer) => (
              <Button
                key={layer}
                size="sm"
                variant={layerFilter === layer ? "default" : "secondary"}
                className="h-6 px-2 font-mono text-[10px]"
                onClick={() => setLayerFilter(layer)}
              >
                {layer} ({layerCounts[layer] ?? 0})
              </Button>
            ))}
          </div>

          <div className="max-h-[540px] overflow-auto rounded-md border border-white/10">
            {visibleSbom.length === 0 ? (
              <div className="p-8 text-center text-xs text-eigenia-muted">
                No SBOM packages match the active filter.
              </div>
            ) : (
              <>
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 border-b border-white/10 bg-eigenia-obsidian font-mono text-[10px] uppercase text-eigenia-muted">
                    <tr>
                      <th className="px-3.5 py-2">Package</th>
                      <th className="px-3.5 py-2">Version</th>
                      <th className="px-3.5 py-2">Layer</th>
                      <th className="px-3.5 py-2">PURL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 font-mono text-[11px]">
                    {visibleSbom.map((pkg) => (
                      <tr
                        key={pkg.id}
                        onClick={() => setInspectedSbom(pkg)}
                        className="cursor-pointer transition-colors hover:bg-eigenia-sky/10"
                      >
                        <td className="px-3.5 py-2 font-medium text-white">{pkg.name}</td>
                        <td className="px-3.5 py-2 tabular-nums text-eigenia-sky">{pkg.version}</td>
                        <td className="px-3.5 py-2">
                          <Badge variant="neutral" className="text-[9px]">
                            {pkg.layer}
                          </Badge>
                        </td>
                        <td className="max-w-sm truncate px-3.5 py-2 text-[10px] text-eigenia-muted">
                          {pkg.purl || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {filteredSbom.length > 150 && (
                  <div className="border-t border-white/10 p-2 text-center">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowAllSbom((v) => !v)}
                    >
                      {showAllSbom
                        ? "Collapse to first 150 packages"
                        : `Show all ${filteredSbom.length} matching packages`}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </InteractiveSurface>
      )}

      {/* TAB 4: UPDATES & ROLLBACK */}
      {activeTab === "updates" && (
        <div>
          {!activeRobot ? (
            <Card>
              <CardContent className="p-8 text-center text-xs text-eigenia-muted">
                Select a robot to run live PyPI/APT package update checks and rollback snapshots.
              </CardContent>
            </Card>
          ) : (
            <UpdateAndFeatureCheckPanel robot={activeRobot} />
          )}
        </div>
      )}

      {/* TAB 5: FLEET & NETWORK */}
      {activeTab === "fleet" && (
        <div className="space-y-4">
          {/* Discovery + Manual Registration */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <InteractiveSurface
              title="Auto-Discover LAN Robots"
              subtitle="Parallel subnet probe for ROSBridge (9090), Web Video (8080), SSH (22), and Hiwonder UDP (9027)"
              accent="orange"
              className="xl:col-span-5"
            >
              <div className="flex gap-2">
                <Input
                  value={cidrInput}
                  onChange={(e) => setCidrInput(e.target.value)}
                  placeholder="192.168.1.0/24"
                  className="font-mono text-xs"
                />
                <Button disabled={busyAction !== null} onClick={() => void handleDiscover()}>
                  {busyAction === "discover" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Radar className="h-3.5 w-3.5" />
                  )}
                  Auto-Discover
                </Button>
              </div>
            </InteractiveSurface>

            <InteractiveSurface
              title="Manual Add Robot IP"
              subtitle="Register a PuppyPi host directly with encrypted PG18 SSH credentials"
              accent="sky"
              className="xl:col-span-7"
            >
              <form onSubmit={handleManualRegister} className="grid grid-cols-1 gap-2 sm:grid-cols-5">
                <Input
                  value={manualIp}
                  onChange={(e) => setManualIp(e.target.value)}
                  placeholder="192.168.1.231"
                  className="font-mono text-xs"
                />
                <Input
                  value={manualName}
                  onChange={(e) => setManualName(e.target.value)}
                  placeholder="Robot Name"
                  className="text-xs"
                />
                <Input
                  value={manualSshUser}
                  onChange={(e) => setManualSshUser(e.target.value)}
                  placeholder="SSH User (pi)"
                  className="font-mono text-xs"
                />
                <Input
                  type="password"
                  value={manualSshPassword}
                  onChange={(e) => setManualSshPassword(e.target.value)}
                  placeholder="SSH Password"
                  className="font-mono text-xs"
                />
                <Button type="submit" variant="sky" disabled={busyAction !== null || !manualIp.trim()}>
                  {busyAction === "register" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <PlusCircle className="h-3.5 w-3.5" />
                  )}
                  Add Robot
                </Button>
              </form>
            </InteractiveSurface>
          </div>

          {/* Live Wi-Fi & Ethernet IP Switcher */}
          {activeRobot && (
            <InteractiveSurface
              title={`Active Network Interfaces — ${activeRobot.name}`}
              subtitle="Switch active control IP between Wi-Fi and Ethernet seamlessly"
              accent="emerald"
              headerRight={
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-7 text-[11px]"
                  disabled={refreshingNet}
                  onClick={() => void handleRefreshNet()}
                >
                  {refreshingNet ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3 w-3" />
                  )}
                  Refresh IPs
                </Button>
              }
            >
              <div className="flex flex-wrap items-center gap-2">
                <div
                  className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-mono text-[11px] ${
                    effectiveNetwork?.wifi?.enabled
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                      : "border-white/10 bg-eigenia-obsidian text-eigenia-muted"
                  }`}
                >
                  {effectiveNetwork?.wifi?.enabled ? (
                    <Wifi className="h-3.5 w-3.5" />
                  ) : (
                    <WifiOff className="h-3.5 w-3.5" />
                  )}
                  <span>
                    Wi-Fi: {effectiveNetwork?.wifi?.enabled ? "ON" : "OFF"}
                    {effectiveNetwork?.wifi?.ipv4 ? ` ${effectiveNetwork.wifi.ipv4}` : ""}
                    {effectiveNetwork?.wifi?.ssid ? ` (${effectiveNetwork.wifi.ssid})` : ""}
                  </span>
                  {effectiveNetwork?.wifi?.ipv4 &&
                    effectiveNetwork.wifi.ipv4 !== activeRobot.ip_address && (
                      <Button
                        size="sm"
                        variant="default"
                        className="ml-1 h-5 px-1.5 text-[9px]"
                        disabled={busyAction !== null}
                        onClick={() => void handleUseIp(effectiveNetwork.wifi!.ipv4!)}
                      >
                        Use IP
                      </Button>
                    )}
                  {effectiveNetwork?.wifi?.ipv4 === activeRobot.ip_address && (
                    <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                  )}
                </div>

                {(Array.isArray(effectiveNetwork?.ethernet) && effectiveNetwork.ethernet.length > 0
                  ? effectiveNetwork.ethernet
                  : [{ ifname: "eth1", enabled: false, state: "down", ipv4: null }]
                ).map((eth) => (
                  <div
                    key={eth.ifname}
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-mono text-[11px] ${
                      eth.enabled
                        ? "border-eigenia-sky/40 bg-eigenia-sky/10 text-eigenia-sky"
                        : "border-white/10 bg-eigenia-obsidian text-eigenia-muted"
                    }`}
                  >
                    <Cable className="h-3.5 w-3.5" />
                    <span>
                      {eth.ifname.toUpperCase()}: {eth.enabled ? "ON" : "OFF"}
                      {eth.ipv4 ? ` ${eth.ipv4}` : ""}
                    </span>
                    {eth.ipv4 && eth.ipv4 !== activeRobot.ip_address && (
                      <Button
                        size="sm"
                        variant="sky"
                        className="ml-1 h-5 px-1.5 text-[9px]"
                        disabled={busyAction !== null}
                        onClick={() => void handleUseIp(eth.ipv4!)}
                      >
                        Use IP
                      </Button>
                    )}
                    {eth.ipv4 === activeRobot.ip_address && (
                      <CheckCircle2 className="h-3 w-3 text-eigenia-sky" />
                    )}
                  </div>
                ))}
              </div>
            </InteractiveSurface>
          )}

          {/* Fleet Registry Cards */}
          <InteractiveSurface
            title={`Registered Robot Fleet (${safeRobots.length})`}
            headerRight={
              <Button size="sm" variant="ghost" onClick={onRobotsChanged}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            }
          >
            {safeRobots.length === 0 ? (
              <div className="rounded border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center text-xs text-eigenia-muted">
                No robots registered yet. Click Auto-Discover or add `192.168.1.231`.
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                {safeRobots.map((r) => {
                  const selected = r.id === activeRobot?.id;
                  return (
                    <div
                      key={r.id}
                      onClick={() => onSelectRobot(r.id)}
                      className={`cursor-pointer rounded-lg border p-3.5 transition-all duration-200 hover:-translate-y-0.5 motion-reduce:transition-none ${
                        selected
                          ? "border-eigenia-orange bg-eigenia-orange/10 shadow-sm shadow-eigenia-orange/15"
                          : "border-white/10 bg-eigenia-obsidian hover:border-eigenia-sky/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold text-white">{r.name}</div>
                          <div className="font-mono text-[10px] text-eigenia-sky">{r.ip_address}</div>
                        </div>
                        <Badge variant={r.status === "online" ? "sky" : "amber"}>{r.status}</Badge>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-1 font-mono text-[10px] text-eigenia-muted">
                        <span>{r.model}</span>
                        <span>{r.active_ros_distro || "ROS unknown"}</span>
                      </div>
                      {r.serial_number && (
                        <div className="mt-1 truncate font-mono text-[9px] text-eigenia-muted">
                          SN: {r.serial_number}
                        </div>
                      )}
                      <div className="mt-2.5 flex items-center justify-between border-t border-white/10 pt-2">
                        <Badge variant={selected ? "default" : "neutral"} className="text-[9px]">
                          {selected ? "ACTIVE ROBOT" : "Click to Select"}
                        </Badge>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 px-2 text-[10px]"
                          disabled={busyAction !== null}
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDelete(r);
                          }}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </InteractiveSurface>
        </div>
      )}

      {/* SLIDE-OVER DRAWER 1: 3D / REACT FLOW COMPONENT INSPECTOR */}
      <SlideOverDrawer
        open={componentDrawerOpen && Boolean(selectedComponent)}
        onClose={() => setComponentDrawerOpen(false)}
        title={selectedComponent?.name || "Hardware Component"}
        subtitle={
          selectedComponent
            ? `${selectedComponent.component_id} · ${selectedComponent.category.toUpperCase()}`
            : undefined
        }
        badge={selectedComponent ? getPi5StatusBadge(selectedComponent.status).label : undefined}
        badgeVariant={
          selectedComponent ? getPi5StatusBadge(selectedComponent.status).variant : "neutral"
        }
        footer={
          matchingBomForSelected.length > 0 ? (
            <Button
              size="sm"
              variant="sky"
              className="w-full"
              onClick={() => {
                setComponentDrawerOpen(false);
                setInspectedBom(matchingBomForSelected[0]);
                handleTabChange("bom");
              }}
            >
              Open Matching Entry in Hardware BOM
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          ) : undefined
        }
      >
        {selectedComponent && (
          <div className="space-y-4">
            <p className="text-xs leading-relaxed text-eigenia-ink">
              {selectedComponent.summary}
            </p>

            {/* Live Metrics */}
            {selectedComponent.metrics && Object.keys(selectedComponent.metrics).length > 0 && (
              <div className="space-y-1.5 rounded-lg border border-white/10 bg-eigenia-obsidian p-3">
                <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-sky">
                  Live Telemetry Metrics
                </div>
                <div className="divide-y divide-white/5 font-mono text-xs">
                  {Object.entries(selectedComponent.metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between gap-2 py-1.5">
                      <span className="text-eigenia-muted">{k}</span>
                      <span className="truncate text-right font-semibold tabular-nums text-white">
                        {v === null || v === undefined ? "—" : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* USB Port Flap & Power Details if a USB port is selected */}
            {matchingUsbPortForSelected && (
              <div className="space-y-1.5 rounded-lg border border-eigenia-sky/30 bg-eigenia-sky/10 p-3 font-mono text-[11px]">
                <div className="text-[10px] font-semibold uppercase text-eigenia-sky">
                  USB Port Enumeration ({matchingUsbPortForSelected.bus_label})
                </div>
                <div className="grid grid-cols-2 gap-1.5 text-eigenia-ink">
                  <div>Power Draw: {matchingUsbPortForSelected.max_power_ma} mA</div>
                  <div>dmesg Flaps: {matchingUsbPortForSelected.flap_count}</div>
                  <div>VID:PID: {matchingUsbPortForSelected.vid_pid || "None"}</div>
                  <div>Driver: {matchingUsbPortForSelected.driver || "None"}</div>
                </div>
                {matchingUsbPortForSelected.device_nodes.length > 0 && (
                  <div className="text-[10px] text-white">
                    Nodes: {matchingUsbPortForSelected.device_nodes.join(", ")}
                  </div>
                )}
              </div>
            )}

            {/* Troubleshooting Guidance */}
            {selectedComponent.troubleshooting && (
              <div className="rounded-lg border border-eigenia-amber/40 bg-eigenia-amber/10 p-3">
                <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase text-eigenia-amber">
                  <Wrench className="h-3.5 w-3.5" />
                  Troubleshooting &amp; Recovery Advice
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-white">
                  {selectedComponent.troubleshooting}
                </p>
              </div>
            )}

            {/* Matching Hardware BOM Rows */}
            <div className="space-y-2">
              <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                Matched Hardware BOM Entries ({matchingBomForSelected.length})
              </div>
              {matchingBomForSelected.length === 0 ? (
                <div className="rounded border border-dashed border-white/10 p-3 font-mono text-[11px] text-eigenia-muted">
                  No catalogued BOM entry mapped yet (run Re-Scan Catalog).
                </div>
              ) : (
                matchingBomForSelected.map((bom) => (
                  <div
                    key={bom.id}
                    className="rounded-md border border-eigenia-orange/35 bg-eigenia-obsidian p-3 font-mono text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-white">
                        {bom.make} {bom.model}
                      </span>
                      <Badge variant={getDeviceStatusVariant(bom)}>{bom.status}</Badge>
                    </div>
                    <div className="mt-1 text-[10px] text-eigenia-muted">
                      {bom.subsystem} · {bom.bus_type}
                      {bom.device_path ? ` · ${bom.device_path}` : ""}
                      {bom.usb_id ? ` · ${bom.usb_id}` : ""}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </SlideOverDrawer>

      {/* SLIDE-OVER DRAWER 2: BOM ROW DETAIL INSPECTOR */}
      <SlideOverDrawer
        open={Boolean(inspectedBom)}
        onClose={() => setInspectedBom(null)}
        title={inspectedBom ? `${inspectedBom.make} ${inspectedBom.model}` : "BOM Device"}
        subtitle={inspectedBom ? `${inspectedBom.subsystem} · ${inspectedBom.bus_type}` : undefined}
        badge={inspectedBom?.status}
        badgeVariant={inspectedBom ? getDeviceStatusVariant(inspectedBom) : "neutral"}
        footer={
          inspectedBom ? (
            <Button
              size="sm"
              className="w-full"
              onClick={() => {
                const matchedId = matchDeviceToComponentId(inspectedBom, pi5Components);
                setInspectedBom(null);
                handleTabChange("hardware");
                if (matchedId) {
                  setSelectedComponentId(matchedId);
                  setComponentDrawerOpen(true);
                }
              }}
            >
              Inspect in 3D / Topology
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          ) : undefined
        }
      >
        {inspectedBom && (
          <div className="space-y-4 font-mono text-xs">
            <div className="divide-y divide-white/10 rounded-lg border border-white/10 bg-eigenia-obsidian px-3">
              <div className="flex justify-between py-2">
                <span className="text-eigenia-muted">Subsystem</span>
                <span className="text-white">{inspectedBom.subsystem}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-eigenia-muted">Bus Type</span>
                <span className="text-white">{inspectedBom.bus_type}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-eigenia-muted">Device Path</span>
                <span className="text-eigenia-sky">{inspectedBom.device_path || "—"}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-eigenia-muted">USB ID</span>
                <span className="text-white">{inspectedBom.usb_id || "—"}</span>
              </div>
            </div>

            {inspectedBom.metadata && Object.keys(inspectedBom.metadata).length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] uppercase tracking-wider text-eigenia-muted">
                  Raw Hardware Metadata
                </div>
                <pre className="max-h-72 overflow-auto rounded-lg border border-white/10 bg-eigenia-obsidian p-3 text-[10px] text-eigenia-ink whitespace-pre-wrap">
                  {JSON.stringify(inspectedBom.metadata, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </SlideOverDrawer>

      {/* SLIDE-OVER DRAWER 3: SBOM PACKAGE INSPECTOR */}
      <SlideOverDrawer
        open={Boolean(inspectedSbom)}
        onClose={() => setInspectedSbom(null)}
        title={inspectedSbom?.name || "SBOM Package"}
        subtitle={inspectedSbom ? `Version ${inspectedSbom.version}` : undefined}
        badge={inspectedSbom?.layer}
        badgeVariant="sky"
      >
        {inspectedSbom && (
          <div className="space-y-3 font-mono text-xs">
            <div className="divide-y divide-white/10 rounded-lg border border-white/10 bg-eigenia-obsidian px-3">
              <div className="flex justify-between gap-2 py-2">
                <span className="text-eigenia-muted">Package</span>
                <span className="text-white">{inspectedSbom.name}</span>
              </div>
              <div className="flex justify-between gap-2 py-2">
                <span className="text-eigenia-muted">Version</span>
                <span className="text-eigenia-sky">{inspectedSbom.version}</span>
              </div>
              <div className="flex justify-between gap-2 py-2">
                <span className="text-eigenia-muted">Layer</span>
                <span className="text-white">{inspectedSbom.layer}</span>
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wider text-eigenia-muted">
                Package URL (PURL)
              </div>
              <div className="break-all rounded-lg border border-white/10 bg-eigenia-obsidian p-3 text-[11px] text-eigenia-ink">
                {inspectedSbom.purl || "Not specified"}
              </div>
            </div>
          </div>
        )}
      </SlideOverDrawer>
    </div>
  );
}
