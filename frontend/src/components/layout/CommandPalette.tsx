"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  Bot,
  Command,
  CornerDownLeft,
  Cpu,
  Crosshair,
  Database,
  Gamepad2,
  LayoutDashboard,
  MapPin,
  Mic,
  Network,
  OctagonAlert,
  Radar,
  Rocket,
  Route,
  ScanFace,
  Search,
  Settings2,
  Sparkles,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useStudio } from "@/context/StudioContext";
import { cn } from "@/lib/utils";

interface PaletteItem {
  id: string;
  group: "Pages" | "Deep Tabs" | "Saved Rooms" | "Robots" | "Quick Actions";
  label: string;
  subtitle?: string;
  keywords: string;
  icon: React.ReactNode;
  badge?: string;
  danger?: boolean;
  onSelect: () => void;
}

function fuzzyMatch(query: string, text: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const hay = text.toLowerCase();
  if (hay.includes(q)) return true;
  const tokens = q.split(/\s+/).filter(Boolean);
  return tokens.every((tok) => hay.includes(tok));
}

export function CommandPalette(): React.JSX.Element | null {
  const router = useRouter();
  const {
    spaces,
    activeSpaceId,
    setActiveSpaceId,
    robots,
    activeRobotId,
    setActiveRobotId,
    setUiRosPreview,
    handleGlobalEstop,
  } = useStudio();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onCustomOpen = () => {
      setOpen(true);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("eigenia:open-command-palette", onCustomOpen);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("eigenia:open-command-palette", onCustomOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      const t = window.setTimeout(() => inputRef.current?.focus(), 15);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  const items = useMemo<PaletteItem[]>(() => {
    const go = (href: string) => {
      setOpen(false);
      router.push(href);
    };

    const pageItems: PaletteItem[] = [
      {
        id: "page-welcome",
        group: "Pages",
        label: "Maker Showcase & Early Bird",
        subtitle: "Interactive 3D PuppyPi Pro showcase, architecture & First-50 Maker Founders",
        keywords: "welcome landing showcase early bird founder puppypi demo /welcome",
        icon: <Rocket className="h-4 w-4 text-eigenia-orange" />,
        badge: "/welcome",
        onSelect: () => go("/welcome"),
      },
      {
        id: "page-home",
        group: "Pages",
        label: "Mission Control",
        subtitle: "Fleet overview, LAN discovery, live KPIs & dark-zone alerts",
        keywords: "home dashboard mission control overview /",
        icon: <LayoutDashboard className="h-4 w-4 text-eigenia-orange" />,
        badge: "/",
        onSelect: () => go("/"),
      },
      {
        id: "page-twin",
        group: "Pages",
        label: "Rooms & 3D Map",
        subtitle: "2D Radar, 3D Three.js, Babylon.js 9 PBR & Real-Room Digital Twin",
        keywords: "rooms map twin lidar 3d radar room scan babylon three /twin",
        icon: <Radar className="h-4 w-4 text-eigenia-sky" />,
        badge: "/twin",
        onSelect: () => go("/twin"),
      },
      {
        id: "page-overwatch",
        group: "Pages",
        label: "Overwatch Cameras",
        subtitle: "Multi-camera 4K USB + MacBook + PuppyPi BEV frustum overlap, GDOP & 4-pt homography",
        keywords: "overwatch camera 4k macbook triangulation frustum overlap gdop homography upscale /overwatch",
        icon: <Crosshair className="h-4 w-4 text-cyan-400" />,
        badge: "/overwatch",
        onSelect: () => go("/overwatch"),
      },
      {
        id: "page-explore",
        group: "Pages",
        label: "Explore & Map",
        subtitle: "Zero-waypoint autonomous dark-zone exploration, 3D mapping & battery-safe RTH",
        keywords: "explore autonomous frontier map dark zone rth /explore",
        icon: <Sparkles className="h-4 w-4 text-cyan-400" />,
        badge: "/explore",
        onSelect: () => go("/explore"),
      },
      {
        id: "page-flash",
        group: "Pages",
        label: "Device Flasher",
        subtitle: "Flash Raspberry Pi 3/4/5, Arduino, ESP32, Pico & micro:bit with headless SSH/Wi-Fi",
        keywords: "flash sd card pi5 pi4 pi3 arduino esp32 pico microbit imager /flash",
        icon: <Cpu className="h-4 w-4 text-cyan-400" />,
        badge: "/flash",
        onSelect: () => go("/flash"),
      },
      {
        id: "page-control",
        group: "Pages",
        label: "Robot Control & FPV",
        subtitle: "Live MJPEG stream, velocity pad, 28 actions, gait & servos",
        keywords: "control drive fpv joystick stance gait servo /control",
        icon: <Gamepad2 className="h-4 w-4 text-eigenia-sky" />,
        badge: "/control",
        onSelect: () => go("/control"),
      },
      {
        id: "page-voice",
        group: "Pages",
        label: "Voice & OX Assistant",
        subtitle: "Hands-free Hey OX wake word, personalities & WonderEcho Pro",
        keywords: "voice ox assistant piper whisper mic speaker /voice",
        icon: <Mic className="h-4 w-4 text-eigenia-orange" />,
        badge: "/voice",
        onSelect: () => go("/voice"),
      },
      {
        id: "page-vision",
        group: "Pages",
        label: "AI Vision & People",
        subtitle: "Face recognition, YOLO11n animals/objects, spatial memory & sentry",
        keywords: "vision face yolo sentry memory people /vision",
        icon: <ScanFace className="h-4 w-4 text-eigenia-sky" />,
        badge: "/vision",
        onSelect: () => go("/vision"),
      },
      {
        id: "page-patrol",
        group: "Pages",
        label: "Autonomous Patrol",
        subtitle: "Multi-waypoint 2D route planner & 5-sector LD19 obstacle avoidance",
        keywords: "patrol waypoint autonomy vfh obstacle /patrol",
        icon: <Route className="h-4 w-4 text-eigenia-amber" />,
        badge: "/patrol",
        onSelect: () => go("/patrol"),
      },
      {
        id: "page-catalog",
        group: "Pages",
        label: "Fleet BOM & SBOM",
        subtitle: "3D Pi 5 hardware twin, PMIC power, CycloneDX SBOM & safe updates",
        keywords: "catalog bom sbom pi5 hardware diagnostics updates /catalog",
        icon: <Cpu className="h-4 w-4 text-eigenia-amber" />,
        badge: "/catalog",
        onSelect: () => go("/catalog"),
      },
      {
        id: "page-architect",
        group: "Pages",
        label: "Lab Architect",
        subtitle: "Human-AI Hardware Co-Design, 3D Assembly, Inventory, micro:bit & Local Cameras",
        keywords: "architect codesign lab hardware inventory microbit pizero blink blueprints ideas /architect",
        icon: <Sparkles className="h-4 w-4 text-eigenia-orange" />,
        badge: "/architect",
        onSelect: () => go("/architect"),
      },
      {
        id: "page-graph",
        group: "Pages",
        label: "Knowledge Graph",
        subtitle: "G_CPDT asset topology, Neo4j sync & pgvector semantic search",
        keywords: "graph neo4j pgvector topology knowledge /graph",
        icon: <Network className="h-4 w-4 text-eigenia-sky" />,
        badge: "/graph",
        onSelect: () => go("/graph"),
      },
      {
        id: "page-config",
        group: "Pages",
        label: "Robot Config & Admin",
        subtitle: "OpenRouter models, ROS 1/2 switching, Wi-Fi & PG18 storage",
        keywords: "config admin settings openrouter wifi ros postgres /config",
        icon: <Settings2 className="h-4 w-4 text-eigenia-orange" />,
        badge: "/config",
        onSelect: () => go("/config"),
      },
      {
        id: "page-wiki",
        group: "Pages",
        label: "Wiki & Onboarding Wizard",
        subtitle: "Interactive 4-step Maker Wizard, complete docs, site tree & troubleshooting",
        keywords: "wiki docs documentation wizard onboarding guide help faq support /wiki",
        icon: <BookOpen className="h-4 w-4 text-eigenia-sky" />,
        badge: "/wiki",
        onSelect: () => go("/wiki"),
      },
    ];

    const deepTabItems: PaletteItem[] = [
      {
        id: "tab-cat-hardware",
        group: "Deep Tabs",
        label: "Catalog → 3D & Bus Topology",
        subtitle: "3D Raspberry Pi 5 BOM Twin + React Flow Bus Graph",
        keywords: "catalog 3d pi5 bus topology pmic power usb ld19",
        icon: <Cpu className="h-4 w-4 text-eigenia-orange" />,
        badge: "/catalog?tab=hardware",
        onSelect: () => go("/catalog?tab=hardware"),
      },
      {
        id: "tab-cat-bom",
        group: "Deep Tabs",
        label: "Catalog → Hardware BOM",
        subtitle: "Searchable hardware devices & cross-probe table",
        keywords: "catalog hardware bom devices sensors",
        icon: <Cpu className="h-4 w-4 text-eigenia-sky" />,
        badge: "/catalog?tab=bom",
        onSelect: () => go("/catalog?tab=bom"),
      },
      {
        id: "tab-cat-sbom",
        group: "Deep Tabs",
        label: "Catalog → Software SBOM",
        subtitle: "Debian dpkg, Python pip & ROS package inventory",
        keywords: "catalog software sbom packages cyclonedx purl",
        icon: <Cpu className="h-4 w-4 text-eigenia-sky" />,
        badge: "/catalog?tab=sbom",
        onSelect: () => go("/catalog?tab=sbom"),
      },
      {
        id: "tab-cat-updates",
        group: "Deep Tabs",
        label: "Catalog → Safe Updates",
        subtitle: "Dry-run, download, docker snapshot apply, smoke test & rollback",
        keywords: "catalog safe updates rollback smoke test apt pip",
        icon: <Sparkles className="h-4 w-4 text-eigenia-amber" />,
        badge: "/catalog?tab=updates",
        onSelect: () => go("/catalog?tab=updates"),
      },
      {
        id: "tab-cat-fleet",
        group: "Deep Tabs",
        label: "Catalog → Fleet & Network",
        subtitle: "LAN discovery, manual robot registration & IP switching",
        keywords: "catalog fleet network discover ip wifi ethernet",
        icon: <Bot className="h-4 w-4 text-eigenia-sky" />,
        badge: "/catalog?tab=fleet",
        onSelect: () => go("/catalog?tab=fleet"),
      },
      {
        id: "tab-voice-live",
        group: "Deep Tabs",
        label: "Voice → Live Conversation",
        subtitle: "Hands-free Hey OX transcript & quick TTS",
        keywords: "voice live conversation chat hey ox",
        icon: <Mic className="h-4 w-4 text-eigenia-orange" />,
        badge: "/voice?tab=live",
        onSelect: () => go("/voice?tab=live"),
      },
      {
        id: "tab-voice-personas",
        group: "Deep Tabs",
        label: "Voice → Personalities",
        subtitle: "Dog, Cat, Marvin, Dad-Joke Nerd, Lab & Custom personas",
        keywords: "voice personalities marvin dog cat nerd custom piper",
        icon: <Sparkles className="h-4 w-4 text-eigenia-amber" />,
        badge: "/voice?tab=personas",
        onSelect: () => go("/voice?tab=personas"),
      },
      {
        id: "tab-voice-diag",
        group: "Deep Tabs",
        label: "Voice → Audio Pipeline",
        subtitle: "7-stage React Flow voice pipeline & 6-step mic diagnostics",
        keywords: "voice audio pipeline diagnostics flow mic test alsa",
        icon: <Mic className="h-4 w-4 text-eigenia-sky" />,
        badge: "/voice?tab=diagnostics",
        onSelect: () => go("/voice?tab=diagnostics"),
      },
      {
        id: "tab-ctrl-actions",
        group: "Deep Tabs",
        label: "Control → Stances & Actions",
        subtitle: "Quick stances & searchable 28 verified PuppyPi ActionGroups",
        keywords: "control stances actions wave sit bow moonwalk",
        icon: <Gamepad2 className="h-4 w-4 text-eigenia-orange" />,
        badge: "/control?tab=actions",
        onSelect: () => go("/control?tab=actions"),
      },
      {
        id: "tab-ctrl-motion",
        group: "Deep Tabs",
        label: "Control → Gait & Servos",
        subtitle: "Auto-gait, stride, height/roll/pitch & 8-servo trim sliders",
        keywords: "control gait servos motion trot walk amble",
        icon: <Gamepad2 className="h-4 w-4 text-eigenia-sky" />,
        badge: "/control?tab=motion",
        onSelect: () => go("/control?tab=motion"),
      },
      {
        id: "tab-cfg-ai",
        group: "Deep Tabs",
        label: "Config → OpenRouter Models",
        subtitle: "API key tester & 501-model catalog picker",
        keywords: "config openrouter models api key vision llm embedding",
        icon: <Sparkles className="h-4 w-4 text-eigenia-orange" />,
        badge: "/config?tab=ai",
        onSelect: () => go("/config?tab=ai"),
      },
      {
        id: "tab-cfg-robot",
        group: "Deep Tabs",
        label: "Config → Robot OS & ROS 1/2",
        subtitle: "Wi-Fi, passwords, servos, ROS 1 Noetic <-> ROS 2 Humble",
        keywords: "config robot os ros1 ros2 humble noetic wifi ssh",
        icon: <Zap className="h-4 w-4 text-eigenia-orange" />,
        badge: "/config?tab=robot",
        onSelect: () => go("/config?tab=robot"),
      },
      {
        id: "tab-cfg-db",
        group: "Deep Tabs",
        label: "Config → Databases",
        subtitle: "PostgreSQL 18 blob storage, pgvector & Neo4j status",
        keywords: "config databases postgres pg18 neo4j storage files",
        icon: <Database className="h-4 w-4 text-eigenia-sky" />,
        badge: "/config?tab=databases",
        onSelect: () => go("/config?tab=databases"),
      },
      {
        id: "tab-patrol-explore",
        group: "Deep Tabs",
        label: "Patrol → Autonomous Explore & Map",
        subtitle: "Frontier dark-zone explorer, multi-pitch 3D mapper & low-battery RTH",
        keywords: "patrol explore map autonomous frontier dark zone rth return home battery",
        icon: <Route className="h-4 w-4 text-eigenia-orange" />,
        badge: "/patrol?tab=explore",
        onSelect: () => go("/patrol?tab=explore"),
      },
      {
        id: "tab-arch-studio",
        group: "Deep Tabs",
        label: "Lab Architect → Co-Design Canvas",
        subtitle: "2D Wiring + 3D Hardware Assembly + 5-Tier Creativity Dial",
        keywords: "architect studio canvas codesign wiring 3d creativity dial",
        icon: <Sparkles className="h-4 w-4 text-eigenia-orange" />,
        badge: "/architect?tab=studio",
        onSelect: () => go("/architect?tab=studio"),
      },
      {
        id: "tab-arch-ideas",
        group: "Deep Tabs",
        label: "Lab Architect → Idea Generator",
        subtitle: "AI project brainstorming tuned to your lab inventory",
        keywords: "architect ideas generator brainstorm projects lab",
        icon: <Sparkles className="h-4 w-4 text-eigenia-amber" />,
        badge: "/architect?tab=ideas",
        onSelect: () => go("/architect?tab=ideas"),
      },
      {
        id: "tab-arch-inventory",
        group: "Deep Tabs",
        label: "Lab Architect → Lab Inventory",
        subtitle: "Owned hardware parts, wishlist, quantities & starter kit seed",
        keywords: "architect inventory wishlist parts hardware pi5 microbit pizero",
        icon: <Cpu className="h-4 w-4 text-eigenia-sky" />,
        badge: "/architect?tab=inventory",
        onSelect: () => go("/architect?tab=inventory"),
      },
      {
        id: "tab-arch-profiles",
        group: "Deep Tabs",
        label: "Lab Architect → Board Profiles & IoT",
        subtitle: "6 device profiles, micro:bit LED studio & local camera/Pi Zero harvester",
        keywords: "architect profiles iot microbit blink pizero camera local",
        icon: <Cpu className="h-4 w-4 text-eigenia-orange" />,
        badge: "/architect?tab=profiles",
        onSelect: () => go("/architect?tab=profiles"),
      },
      {
        id: "tab-arch-blueprints",
        group: "Deep Tabs",
        label: "Lab Architect → Saved Blueprints",
        subtitle: "Saved hardware architectures, versions & Markdown build specs",
        keywords: "architect blueprints saved specs markdown export",
        icon: <Sparkles className="h-4 w-4 text-eigenia-sky" />,
        badge: "/architect?tab=blueprints",
        onSelect: () => go("/architect?tab=blueprints"),
      },
      {
        id: "tab-wiki-wizard",
        group: "Deep Tabs",
        label: "Interactive Onboarding Wizard",
        subtitle: "4-step PuppyPi Pro & maker hardware setup with live system readiness check",
        keywords: "wiki wizard onboarding setup checklist puppypi readiness",
        icon: <Rocket className="h-4 w-4 text-eigenia-orange" />,
        badge: "/wiki?tab=wizard",
        onSelect: () => go("/wiki?tab=wizard"),
      },
      {
        id: "tab-wiki-docs",
        group: "Deep Tabs",
        label: "Complete Documentation Wiki",
        subtitle: "Principal onboarding, Zero-to-Hero, User/Admin/Dev guides & runbooks",
        keywords: "wiki docs documentation guides manual reference glossary",
        icon: <BookOpen className="h-4 w-4 text-eigenia-sky" />,
        badge: "/wiki?tab=docs",
        onSelect: () => go("/wiki?tab=docs"),
      },
      {
        id: "tab-wiki-sitetree",
        group: "Deep Tabs",
        label: "Interactive Site Tree",
        subtitle: "Visual React Flow map of all 12 Eigenia workspaces & backend engines",
        keywords: "wiki sitetree site tree map routes topology reactflow",
        icon: <Network className="h-4 w-4 text-eigenia-amber" />,
        badge: "/wiki?tab=sitetree",
        onSelect: () => go("/wiki?tab=sitetree"),
      },
    ];

    const roomItems: PaletteItem[] = spaces.map((sp) => ({
      id: `room-${sp.id}`,
      group: "Saved Rooms",
      label: sp.name,
      subtitle: `${sp.facility}${sp.panel_count != null ? ` · ${sp.panel_count} panels` : ""}`,
      keywords: `room space scene ${sp.name} ${sp.facility}`,
      icon: <MapPin className="h-4 w-4 text-eigenia-sky" />,
      badge: sp.id === activeSpaceId ? "ACTIVE" : "LOAD",
      onSelect: () => {
        setActiveSpaceId(sp.id);
        go("/twin");
      },
    }));

    const robotItems: PaletteItem[] = robots.map((r) => ({
      id: `robot-${r.id}`,
      group: "Robots",
      label: r.name,
      subtitle: `${r.ip_address} · ${r.active_ros_distro || "ROS"} · ${r.status}`,
      keywords: `robot puppypi ${r.name} ${r.ip_address} ${r.model}`,
      icon: <Bot className="h-4 w-4 text-eigenia-orange" />,
      badge: r.id === activeRobotId ? "ACTIVE" : "SELECT",
      onSelect: () => {
        setActiveRobotId(r.id);
        setOpen(false);
      },
    }));

    const quickActionItems: PaletteItem[] = [
      {
        id: "act-ros2",
        group: "Quick Actions",
        label: "Switch UI Preview → ROS 2 (Orange Mode)",
        subtitle: "Preview ROS 2 Humble CycloneDDS theme & controls",
        keywords: "action preview ros2 humble orange mode switch",
        icon: <Zap className="h-4 w-4 text-eigenia-orange" />,
        badge: "ROS 2",
        onSelect: () => {
          setUiRosPreview("ros2");
          setOpen(false);
        },
      },
      {
        id: "act-ros1",
        group: "Quick Actions",
        label: "Switch UI Preview → ROS 1 (Obsidian Mode)",
        subtitle: "Preview ROS 1 Noetic theme & Hiwonder CV controls",
        keywords: "action preview ros1 noetic obsidian mode switch",
        icon: <Zap className="h-4 w-4 text-eigenia-sky" />,
        badge: "ROS 1",
        onSelect: () => {
          setUiRosPreview("ros1");
          setOpen(false);
        },
      },
      {
        id: "act-estop",
        group: "Quick Actions",
        label: "Trigger Global E-STOP",
        subtitle: "Immediately zero velocity & halt active PuppyPi motion",
        keywords: "estop emergency stop halt safety kill",
        icon: <OctagonAlert className="h-4 w-4 text-eigenia-fault" />,
        badge: "SAFETY",
        danger: true,
        onSelect: () => {
          void handleGlobalEstop();
          setOpen(false);
        },
      },
    ];

    return [...pageItems, ...deepTabItems, ...roomItems, ...robotItems, ...quickActionItems];
  }, [
    spaces,
    activeSpaceId,
    setActiveSpaceId,
    robots,
    activeRobotId,
    setActiveRobotId,
    setUiRosPreview,
    handleGlobalEstop,
    router,
  ]);

  const filtered = useMemo(
    () =>
      items.filter((item) =>
        fuzzyMatch(query, `${item.group} ${item.label} ${item.subtitle ?? ""} ${item.keywords}`)
      ),
    [items, query]
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    const el = itemRefs.current[activeIndex];
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (filtered.length > 0 ? (prev + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) =>
        filtered.length > 0 ? (prev - 1 + filtered.length) % filtered.length : 0
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[activeIndex];
      if (target) target.onSelect();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  if (!open) return null;

  // Group filtered items while preserving global flat index for keyboard highlight
  const grouped: { group: PaletteItem["group"]; entries: { item: PaletteItem; flatIdx: number }[] }[] =
    [];
  filtered.forEach((item, flatIdx) => {
    let bucket = grouped.find((g) => g.group === item.group);
    if (!bucket) {
      bucket = { group: item.group, entries: [] };
      grouped.push(bucket);
    }
    bucket.entries.push({ item, flatIdx });
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Eigenia Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]"
    >
      <div
        onClick={() => setOpen(false)}
        aria-hidden="true"
        className="fixed inset-0 bg-black/65 backdrop-blur-sm"
      />

      <div className="relative z-10 flex w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-eigenia-orange/45 bg-eigenia-shell shadow-[0_24px_80px_rgba(0,0,0,0.75)]">
        {/* Search Header */}
        <div className="flex items-center gap-2.5 border-b border-white/10 bg-eigenia-obsidian px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-eigenia-orange" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Jump to page, tab, saved room, robot, or quick action..."
            className="flex-1 bg-transparent font-mono text-xs text-white placeholder:text-eigenia-muted focus:outline-none"
          />
          <Badge variant="neutral" className="text-[9px]">
            ESC
          </Badge>
        </div>

        {/* Results */}
        <div className="max-h-[58vh] overflow-y-auto p-2">
          {grouped.length === 0 ? (
            <div className="py-10 text-center font-mono text-xs text-eigenia-muted">
              No matches for &ldquo;{query}&rdquo;
            </div>
          ) : (
            grouped.map(({ group, entries }) => (
              <div key={group} className="mb-2 last:mb-0">
                <div className="px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-eigenia-muted">
                  {group}
                </div>
                <div className="space-y-0.5">
                  {entries.map(({ item, flatIdx }) => {
                    const isActive = flatIdx === activeIndex;
                    return (
                      <button
                        key={item.id}
                        ref={(el) => {
                          itemRefs.current[flatIdx] = el;
                        }}
                        type="button"
                        onMouseEnter={() => setActiveIndex(flatIdx)}
                        onClick={() => item.onSelect()}
                        className={cn(
                          "flex w-full items-center justify-between gap-3 rounded-md border px-2.5 py-2 text-left transition-colors",
                          isActive
                            ? item.danger
                              ? "border-eigenia-fault/60 bg-eigenia-fault/20 text-white"
                              : "border-eigenia-orange/50 bg-eigenia-orange/15 text-white"
                            : "border-transparent text-eigenia-ink hover:bg-white/5"
                        )}
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span className="shrink-0">{item.icon}</span>
                          <div className="min-w-0">
                            <div className="truncate text-xs font-medium text-white">
                              {item.label}
                            </div>
                            {item.subtitle && (
                              <div className="truncate font-mono text-[10px] text-eigenia-muted">
                                {item.subtitle}
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="flex shrink-0 items-center gap-2">
                          {item.badge && (
                            <Badge variant={item.danger ? "fault" : isActive ? "default" : "neutral"}>
                              {item.badge}
                            </Badge>
                          )}
                          {isActive && (
                            <CornerDownLeft className="h-3.5 w-3.5 text-eigenia-orange" />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer Key Hints */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 bg-eigenia-obsidian/90 px-4 py-2 font-mono text-[10px] text-eigenia-muted">
          <div className="flex items-center gap-2">
            <Command className="h-3 w-3 text-eigenia-orange" />
            <span>Eigenia Command Palette</span>
          </div>
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>Esc Close</span>
          </div>
        </div>
      </div>
    </div>
  );
}
