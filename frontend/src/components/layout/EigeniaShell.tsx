"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Battery,
  BookOpen,
  Bot,
  Cable,
  ChevronLeft,
  ChevronRight,
  Command,
  Cpu,
  Gamepad2,
  LayoutDashboard,
  MapPin,
  Mic,
  Network,
  OctagonAlert,
  Plus,
  Radar,
  Rocket,
  Route,
  ScanFace,
  Settings2,
  Sparkles,
  Wifi,
  WifiOff,
  X,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { useStudio } from "@/context/StudioContext";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  shortLabel: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/welcome", label: "Showcase", shortLabel: "Showcase", icon: Rocket },
  { href: "/", label: "Mission Control", shortLabel: "Mission", icon: LayoutDashboard },
  { href: "/twin", label: "Spatial LiDAR Twin", shortLabel: "Twin", icon: Radar },
  { href: "/control", label: "Robot Control & FPV", shortLabel: "Control", icon: Gamepad2 },
  { href: "/voice", label: "Voice & OX Assistant", shortLabel: "Voice", icon: Mic },
  { href: "/vision", label: "AI Vision & People", shortLabel: "Vision", icon: ScanFace },
  { href: "/patrol", label: "Autonomous Patrol", shortLabel: "Patrol", icon: Route },
  { href: "/catalog", label: "Fleet BOM & SBOM", shortLabel: "Catalog", icon: Cpu },
  { href: "/architect", label: "Lab Architect", shortLabel: "Architect", icon: Sparkles },
  { href: "/graph", label: "Knowledge Graph", shortLabel: "Graph", icon: Network },
  { href: "/config", label: "Robot Config & Admin", shortLabel: "Config", icon: Settings2 },
  { href: "/wiki", label: "Wiki & Wizard", shortLabel: "Wiki", icon: BookOpen },
];

function formatBattery(batteryMv?: number | null): { label: string; variant: "sky" | "amber" | "fault" } | null {
  if (batteryMv == null || Number.isNaN(batteryMv) || batteryMv <= 0) return null;
  const volts = batteryMv / 1000;
  const pct = Math.max(0, Math.min(100, Math.round(((volts - 6.4) / 2.0) * 100)));
  const variant = volts < 7.0 ? "fault" : volts < 7.4 ? "amber" : "sky";
  return { label: `${volts.toFixed(2)}V · ${pct}%`, variant };
}

export function EigeniaShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [newRoomOpen, setNewRoomOpen] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomFacility, setNewRoomFacility] = useState("");
  const [creatingRoom, setCreatingRoom] = useState(false);
  const [newRoomError, setNewRoomError] = useState<string | null>(null);
  const newRoomRef = useRef<HTMLDivElement | null>(null);

  const {
    spaces,
    activeSpaceId,
    setActiveSpaceId,
    createNewSpace,
    robots,
    activeRobotId,
    setActiveRobotId,
    activeRobot,
    robotRosMode,
    robotRosLabel,
    activeRosMode,
    uiRosPreview,
    setUiRosPreview,
    robotNetwork,
    frame,
    wsConnected,
    dbBackend,
    handleGlobalEstop,
    estopActive,
  } = useStudio();

  const isRos2 = activeRosMode === "ros2";
  const isPreviewing = uiRosPreview !== null && uiRosPreview !== robotRosMode;
  const battery = formatBattery(activeRobot?.battery_mv);

  const wifi = robotNetwork?.wifi ?? null;
  const wifiEnabled = Boolean(wifi?.enabled && wifi?.ipv4);
  const activeEth =
    (robotNetwork?.ethernet ?? []).find((e) => e.enabled && e.ipv4) ??
    (robotNetwork?.ethernet ?? [])[0] ??
    null;
  const ethEnabled = Boolean(activeEth?.enabled && activeEth?.ipv4);

  const handleSelectRosToggle = (target: "ros1" | "ros2") => {
    setUiRosPreview(target === robotRosMode ? null : target);
  };

  useEffect(() => {
    if (!newRoomOpen) return;
    const onDocDown = (e: MouseEvent) => {
      if (newRoomRef.current && !newRoomRef.current.contains(e.target as Node)) {
        setNewRoomOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNewRoomOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [newRoomOpen]);

  const handleQuickCreateRoom = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newRoomName.trim();
    if (!trimmed) {
      setNewRoomError("Enter a room name");
      return;
    }
    setCreatingRoom(true);
    setNewRoomError(null);
    try {
      await createNewSpace({
        name: trimmed,
        facility: newRoomFacility.trim() || "Eigenia Lab",
      });
      setNewRoomName("");
      setNewRoomFacility("");
      setNewRoomOpen(false);
    } catch (err) {
      setNewRoomError(err instanceof Error ? err.message : "Failed to create room");
    } finally {
      setCreatingRoom(false);
    }
  };

  if (pathname === "/welcome") {
    return (
      <div className="min-h-screen w-full bg-eigenia-obsidian text-eigenia-ink">
        {children}
        <CommandPalette />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative flex min-h-screen w-full text-eigenia-ink transition-colors duration-300",
        isRos2
          ? "bg-[linear-gradient(155deg,rgba(224,90,16,0.44)_0%,rgba(224,90,16,0.20)_45%,rgba(14,16,19,0.96)_100%)]"
          : "bg-eigenia-obsidian"
      )}
    >
      {/* Non-blocking Ambient Orange Glow Overlay in ROS 2 Mode */}
      {isRos2 && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-0 bg-[radial-gradient(ellipse_at_top_center,rgba(224,90,16,0.34),transparent_65%)]"
        />
      )}

      {/* Collapsible Left Navigation Rail */}
      <aside
        className={cn(
          "sticky top-0 z-20 flex h-screen shrink-0 flex-col border-r transition-all duration-200",
          isRos2
            ? "border-eigenia-orange/60 bg-gradient-to-b from-eigenia-orange/25 via-eigenia-shell/95 to-eigenia-obsidian/95 shadow-[inset_-2px_0_16px_rgba(224,90,16,0.28)]"
            : "border-white/10 bg-eigenia-shell/95",
          collapsed ? "w-16" : "w-60"
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center justify-between border-b px-3",
            isRos2 ? "border-eigenia-orange/50" : "border-white/10"
          )}
        >
          <Link href="/" className="flex items-center gap-2.5 overflow-hidden">
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded border",
                isRos2
                  ? "border-eigenia-orange bg-eigenia-orange/35 shadow-[0_0_12px_rgba(224,90,16,0.45)]"
                  : "border-eigenia-orange/60 bg-eigenia-orange/15"
              )}
            >
              <Radar className="h-4 w-4 text-eigenia-orange" />
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <div className="truncate font-mono text-xs font-bold tracking-wider text-white">
                  EIGENIA <span className="text-eigenia-orange">//</span>
                </div>
                <div className="truncate font-mono text-[10px] tracking-widest text-eigenia-muted">
                  {isRos2 ? "ROS 2 HUMBLE CMD" : "TWINSCAN CMD"}
                </div>
              </div>
            )}
          </Link>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            className="h-7 w-7 shrink-0"
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive =
              item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                className={cn(
                  "group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-xs font-medium transition-colors",
                  isActive
                    ? isRos2
                      ? "border border-eigenia-orange bg-eigenia-orange/30 text-white shadow-[0_0_12px_rgba(224,90,16,0.22)]"
                      : "border border-eigenia-orange/50 bg-eigenia-orange/20 text-white"
                    : "border border-transparent text-eigenia-muted hover:bg-white/5 hover:text-white"
                )}
              >
                {isActive && (
                  <span className="absolute inset-y-1.5 left-0 w-1 rounded-r bg-eigenia-orange" />
                )}
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    isActive ? "text-eigenia-orange" : "text-eigenia-muted group-hover:text-eigenia-sky"
                  )}
                />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Footer System Metadata */}
        <div className={cn("border-t p-3", isRos2 ? "border-eigenia-orange/50" : "border-white/10")}>
          {collapsed ? (
            <div className="flex flex-col items-center gap-1.5">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  wsConnected ? "bg-eigenia-sky" : "bg-eigenia-fault"
                )}
                title={wsConnected ? "Stream Live" : "Reconnecting"}
              />
              <span className="font-mono text-[9px] font-bold text-eigenia-orange">
                {isRos2 ? "R2" : "R1"}
              </span>
            </div>
          ) : (
            <div className="space-y-1.5 font-mono text-[10px]">
              <div className="flex items-center justify-between text-eigenia-muted">
                <span>UI MODE</span>
                <span className={isRos2 ? "font-bold text-eigenia-orange" : "text-eigenia-sky"}>
                  {isRos2 ? "ROS 2 HUMBLE" : "ROS 1 NOETIC"}
                </span>
              </div>
              <div className="flex items-center justify-between text-eigenia-muted">
                <span>ROBOT ROS</span>
                <span className="truncate text-white">{robotRosLabel}</span>
              </div>
              <div className="flex items-center justify-between text-eigenia-muted">
                <span>DATA ENGINE</span>
                <span className="truncate text-white">{dbBackend}</span>
              </div>
              <div className="flex items-center justify-between text-eigenia-muted">
                <span>FLEET UNITS</span>
                <span className="text-eigenia-sky">{robots.length} registered</span>
              </div>
              <div className="flex items-center justify-between text-eigenia-muted">
                <span>LIDAR SWEEP</span>
                <span className="text-white">{Number(frame?.rpm ?? 0).toFixed(0)} RPM</span>
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* Main Column: Top Telemetry Bar + ROS 2 Active Banner + Page Content */}
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header
          className={cn(
            "sticky top-0 z-30 flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5 backdrop-blur",
            isRos2
              ? "border-eigenia-orange/70 bg-gradient-to-r from-eigenia-orange/30 via-eigenia-shell/95 to-eigenia-orange/20 shadow-[0_2px_24px_rgba(224,90,16,0.32)]"
              : "border-white/10 bg-eigenia-shell/95"
          )}
        >
          {/* Left: Brand & Selectors */}
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="font-mono text-xs font-bold tracking-wider text-white">
              EIGENIA <span className="text-eigenia-orange">//</span> TWINSCAN
            </span>

            {/* Active Space Selector + Quick "+ New Room" Popover */}
            <div ref={newRoomRef} className="relative flex items-center gap-1.5">
              <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-eigenia-obsidian px-2 py-1">
                <MapPin className="h-3.5 w-3.5 text-eigenia-sky" />
                <select
                  aria-label="Active Space"
                  value={activeSpaceId}
                  onChange={(e) => setActiveSpaceId(e.target.value)}
                  className="bg-transparent font-mono text-[11px] text-white focus:outline-none"
                >
                  {spaces.length === 0 ? (
                    <option value="" className="bg-eigenia-obsidian text-eigenia-muted">
                      Loading Space...
                    </option>
                  ) : (
                    spaces.map((sp) => (
                      <option key={sp.id} value={sp.id} className="bg-eigenia-obsidian text-white">
                        {sp.facility} / {sp.name}
                      </option>
                    ))
                  )}
                </select>
              </div>

              <Button
                type="button"
                size="sm"
                variant={newRoomOpen ? "default" : "secondary"}
                onClick={() => {
                  setNewRoomOpen((v) => !v);
                  setNewRoomError(null);
                }}
                className="h-7 px-2 font-mono text-[10px]"
                title="Create and switch to a new room scene"
              >
                <Plus className="h-3 w-3" />
                New Room
              </Button>

              {newRoomOpen && (
                <form
                  onSubmit={(e) => void handleQuickCreateRoom(e)}
                  className="absolute left-0 top-9 z-50 w-72 space-y-2.5 rounded-lg border border-eigenia-orange/50 bg-eigenia-shell p-3 shadow-2xl"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-white">
                      Create New Room
                    </span>
                    <button
                      type="button"
                      onClick={() => setNewRoomOpen(false)}
                      aria-label="Close new room popover"
                      className="text-eigenia-muted hover:text-white"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="space-y-1">
                    <label className="font-mono text-[10px] text-eigenia-muted">Room Name *</label>
                    <Input
                      autoFocus
                      placeholder="e.g. Office North, Lab Bay 2"
                      value={newRoomName}
                      onChange={(e) => setNewRoomName(e.target.value)}
                      className="h-8 text-xs"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="font-mono text-[10px] text-eigenia-muted">
                      Floor / Facility (optional)
                    </label>
                    <Input
                      placeholder="e.g. Eigenia Lab · Floor 1"
                      value={newRoomFacility}
                      onChange={(e) => setNewRoomFacility(e.target.value)}
                      className="h-8 text-xs"
                    />
                  </div>

                  {newRoomError && (
                    <div className="rounded border border-eigenia-fault/40 bg-eigenia-fault/15 px-2 py-1 font-mono text-[10px] text-eigenia-fault">
                      {newRoomError}
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-1.5 pt-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setNewRoomOpen(false)}
                    >
                      Cancel
                    </Button>
                    <Button type="submit" size="sm" disabled={creatingRoom || !newRoomName.trim()}>
                      {creatingRoom ? "Creating..." : "Create Room"}
                    </Button>
                  </div>
                </form>
              )}
            </div>

            {/* Active Robot Selector */}
            <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-eigenia-obsidian px-2 py-1">
              <Bot className="h-3.5 w-3.5 text-eigenia-orange" />
              <select
                aria-label="Active Robot"
                value={activeRobotId ?? ""}
                onChange={(e) => setActiveRobotId(e.target.value || null)}
                className="bg-transparent font-mono text-[11px] text-white focus:outline-none"
              >
                {robots.length === 0 ? (
                  <option value="" className="bg-eigenia-obsidian text-eigenia-muted">
                    No Robot Connected
                  </option>
                ) : (
                  robots.map((r) => (
                    <option key={r.id} value={r.id} className="bg-eigenia-obsidian text-white">
                      {r.name} ({r.ip_address})
                    </option>
                  ))
                )}
              </select>
            </div>

            {/* Compact ⌘K Command Palette Trigger Pill */}
            <button
              type="button"
              onClick={() =>
                window.dispatchEvent(new CustomEvent("eigenia:open-command-palette"))
              }
              title="Open Command Palette (⌘K / Ctrl+K)"
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-white/15 bg-eigenia-obsidian px-2.5 font-mono text-[10px] text-eigenia-muted transition-colors hover:border-eigenia-sky/50 hover:text-white"
            >
              <Command className="h-3 w-3 text-eigenia-orange" />
              <span className="hidden md:inline">Search</span>
              <span className="rounded bg-white/10 px-1 py-0.5 text-[9px] text-white">⌘K</span>
            </button>
          </div>

          {/* Right: Live Network, 1-Click [ROS 1 | ROS 2] Switcher, Stream, Battery & Global E-STOP */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Live Wi-Fi & Ethernet Telemetry Pills */}
            {activeRobot && (
              <>
                <Link href="/config" title="Manage PuppyPi Wi-Fi & Network Interfaces">
                  <Badge variant={wifiEnabled ? "sky" : "neutral"} className="cursor-pointer hover:opacity-90">
                    {wifiEnabled ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
                    {wifiEnabled
                      ? `Wi-Fi: ON ${wifi?.ipv4}${wifi?.ssid ? ` (${wifi.ssid})` : ""}`
                      : "Wi-Fi: OFF"}
                  </Badge>
                </Link>

                <Link href="/config" title="Manage PuppyPi Ethernet Interfaces">
                  <Badge variant={ethEnabled ? "amber" : "neutral"} className="cursor-pointer hover:opacity-90">
                    <Cable className="h-3 w-3" />
                    {ethEnabled ? `ETH: ON ${activeEth?.ipv4}` : "ETH: OFF"}
                  </Badge>
                </Link>
              </>
            )}

            {/* Top-Bar Instant 1-Click Segmented [ ROS 1 | ROS 2 ] Switcher */}
            <div className="flex items-center gap-1.5">
              <div
                role="group"
                aria-label="ROS Mode Switcher"
                className={cn(
                  "inline-flex items-center rounded-md border p-0.5 font-mono text-[10px]",
                  isRos2
                    ? "border-eigenia-orange/70 bg-eigenia-obsidian/90"
                    : "border-white/15 bg-eigenia-obsidian"
                )}
              >
                <button
                  type="button"
                  onClick={() => handleSelectRosToggle("ros1")}
                  className={cn(
                    "rounded px-2 py-0.5 font-bold tracking-wide transition-all",
                    !isRos2
                      ? "bg-eigenia-sky/25 text-eigenia-sky ring-1 ring-eigenia-sky/60"
                      : "text-eigenia-muted hover:text-white"
                  )}
                >
                  ROS 1
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectRosToggle("ros2")}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-0.5 font-bold tracking-wide transition-all",
                    isRos2
                      ? "bg-eigenia-orange text-white shadow-[0_0_10px_rgba(224,90,16,0.65)]"
                      : "text-eigenia-muted hover:text-eigenia-orange"
                  )}
                >
                  <Zap className="h-2.5 w-2.5" />
                  ROS 2
                </button>
              </div>

              {activeRobot && (
                <Badge variant="neutral" className="hidden sm:inline-flex">
                  Robot: {robotRosLabel}
                </Badge>
              )}
            </div>

            <Badge variant={wsConnected ? "sky" : "fault"}>
              <Activity className="h-3 w-3" />
              {wsConnected ? "STREAM LIVE" : "RECONNECTING"}
            </Badge>

            {activeRobot && (
              <>
                {battery ? (
                  <Badge variant={battery.variant}>
                    <Battery className="h-3 w-3" />
                    {battery.label}
                  </Badge>
                ) : (
                  <Badge variant={activeRobot.status === "online" ? "sky" : "neutral"}>
                    <Battery className="h-3 w-3" />
                    {String(activeRobot.status || "unknown").toUpperCase()}
                  </Badge>
                )}
              </>
            )}

            <Button
              size="sm"
              onClick={() => void handleGlobalEstop()}
              className={cn(
                "border border-eigenia-fault bg-eigenia-fault font-mono text-[11px] font-bold tracking-wider text-white hover:bg-eigenia-fault/90",
                estopActive && "animate-pulse ring-2 ring-white"
              )}
              title="Emergency Stop: zeroes velocity and returns active PuppyPi to safe stance"
            >
              <OctagonAlert className="h-3.5 w-3.5" />
              {estopActive ? "E-STOP SENT" : "E-STOP"}
            </Button>
          </div>
        </header>

        {/* Full-Width Unmistakable ROS 2 Active Banner */}
        {isRos2 && (
          <div className="relative z-20 flex flex-wrap items-center justify-between gap-2 border-b border-eigenia-orange/80 bg-gradient-to-r from-eigenia-orange/50 via-eigenia-orange/35 to-eigenia-orange/50 px-4 py-2 font-mono text-[11px] text-white shadow-[0_4px_20px_rgba(224,90,16,0.28)]">
            <div className="flex flex-wrap items-center gap-2">
              <Zap className="h-4 w-4 text-white" />
              <span className="font-bold tracking-wider text-white">
                ROS 2 HUMBLE // CYCLONEDDS ACTIVE · Ubuntu 22.04 LTS · Nav2 + slam_toolbox + MoveIt 2
              </span>
              {isPreviewing ? (
                <Badge variant="amber" className="border-white/40 bg-eigenia-obsidian/70 text-eigenia-amber">
                  PREVIEWING
                </Badge>
              ) : (
                <Badge variant="default" className="border-white/50 bg-eigenia-orange text-white">
                  LIVE ON ROBOT
                </Badge>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="default" asChild>
                <Link href="/config">Apply ROS 2 to Robot</Link>
              </Button>
              {uiRosPreview && (
                <Button size="sm" variant="secondary" onClick={() => setUiRosPreview(null)}>
                  Exit Preview
                </Button>
              )}
            </div>
          </div>
        )}

        <main
          className={cn(
            "relative z-10 flex-1 p-4 md:p-5 transition-colors duration-300",
            isRos2 && "bg-eigenia-orange/[0.08] ring-1 ring-inset ring-eigenia-orange/30"
          )}
        >
          {children}
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
