"use client";

import React from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import {
  ArrowRight,
  BookOpen,
  Bot,
  Box,
  Compass,
  Cpu,
  Database,
  Eye,
  Flame,
  Layers,
  Mic,
  Navigation,
  Radar,
  Rocket,
  ShieldCheck,
  Sparkles,
  Wand2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { EarlyBirdSection } from "@/components/landing/EarlyBirdSection";
import { LandingArchitectureFlow } from "@/components/landing/LandingArchitectureFlow";

const LandingHeroTwin3D = dynamic(
  () => import("@/components/landing/LandingHeroTwin3D").then((m) => m.LandingHeroTwin3D),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[470px] items-center justify-center rounded-2xl border border-eigenia-orange/30 bg-eigenia-obsidian font-mono text-xs text-eigenia-muted">
        Booting Live Three.js PuppyPi Pro 3D Digital Twin...
      </div>
    ),
  }
);

const PROOF_METRICS = [
  { value: "2.16 cm", label: "LD19 + Depth V2 3D RMSE", tone: "text-eigenia-orange" },
  { value: "100%", label: "Local & Cloud-Free Docker", tone: "text-emerald-400" },
  { value: "6", label: "Hardware Envelopes", tone: "text-eigenia-sky" },
  { value: "Dual 3D", label: "Three.js + Babylon.js 9", tone: "text-eigenia-sky" },
  { value: "50 Spots", label: "Early Bird Maker Founders", tone: "text-eigenia-amber" },
] as const;

const PUPPYPI_WORKFLOW = [
  {
    step: "01",
    title: "Unbox & 1-Click ROS 2 Auto-Boot",
    subtitle: "Hiwonder PuppyPi Pro · Pi 5 8GB",
    description:
      "Connect on LAN, auto-discover ROSBridge + SSH, flip ROS 1 Noetic → ROS 2 Humble CycloneDDS with persistent auto-boot, and verify all 22 Pi 5 PMIC rails & USB ports on the 3D Hardware BOM Twin.",
    metric: "6.9 Hz /scan · 0-flap USB 2.0",
    href: "/catalog",
    cta: "Inspect Pi 5 3D BOM",
    Icon: Cpu,
  },
  {
    step: "02",
    title: "Zero-Move 3D Room Scan & .GLB Export",
    subtitle: "Camera + LD19 + Depth Anything V2",
    description:
      "Hit Capture Front Wall (or 8-stop 360° Scan) to run 5-pass composite enhancement — burst alignment, CLAHE, Flip-TTA depth, LD19 residual warp & PBR normal map — then export a full-room binary .glb.",
    metric: "2.16 cm RMSE · Solid/X-Ray/Wire",
    href: "/twin",
    cta: "Launch 3D Twin",
    Icon: Box,
  },
  {
    step: "03",
    title: "Autonomous Dark-Zone Exploration & RTH",
    subtitle: "5-Sector VFH + Low-Battery Return-to-Home",
    description:
      "PuppyPi targets red Spatial Dark Zones autonomously, tilts body pitch Up/Level/Down to scan floor-to-ceiling, catalogs objects into Spatial Memory, and auto-returns to AprilTag #0 Home Base at 7.10V.",
    metric: "95% 2S LiPo · Global E-STOP",
    href: "/patrol?tab=explore",
    cta: "Open Frontier Explorer",
    Icon: Navigation,
  },
  {
    step: "04",
    title: "Expand with Pi 5 Workbench & micro:bit",
    subtitle: "5-Tier AI Lab Architect Co-Design",
    description:
      "Drop your owned Pi 5, Pi Zero 2 W Blink Sync clip harvester, LAN cameras, and BBC micro:bit v2.21 onto the Co-Design Canvas — dial creativity from Tier 1 to Tier 5 and wire live 2D + 3D blueprints.",
    metric: "500+ OpenRouter or Offline",
    href: "/architect",
    cta: "Open Lab Architect",
    Icon: Wand2,
  },
] as const;

const CAPABILITY_PILLARS = [
  {
    title: "Real-Room 3D Fusion",
    badge: "THREE.JS + BABYLON 9",
    desc: "Photorealistic textured 3D room walls with PBR normal maps, Solid/Translucent/Wireframe switching, and single-file Full-Room .glb export.",
    href: "/twin",
    Icon: Layers,
    accent: "orange" as const,
  },
  {
    title: "AI Vision, Spatial Memory & Sentry",
    badge: "YOLO11N + SFACE 128-D",
    desc: "Enroll faces, detect pets & objects, curate Active/Archived room sightings in Bento/Grid/Line views, and arm Autonomous Sentry Guard Mode.",
    href: "/vision",
    Icon: Eye,
    accent: "sky" as const,
  },
  {
    title: "Hands-Free 'Hey OX' Voice Studio",
    badge: "PIPER OFFLINE + WHISPER",
    desc: "Talk naturally to OX with 5 built-in personalities, camera-aware replies, anti-clipping WonderEcho EQ, and a live 7-stage React Flow audio pipeline.",
    href: "/voice",
    Icon: Mic,
    accent: "emerald" as const,
  },
  {
    title: "3D Pi 5 Power & Bus Diagnostics",
    badge: "DA9091 PMIC + 22 NODES",
    desc: "Cross-probe live EXT5V, Board Watts, USB mA budgets, and dmesg port flaps across a millimeter-accurate 3D Pi 5 PCB and React Flow bus graph.",
    href: "/catalog",
    Icon: ShieldCheck,
    accent: "amber" as const,
  },
  {
    title: "5-Tier Human-AI Lab Architect",
    badge: "CO-DESIGN + MICRO:BIT",
    desc: "Evaluate ideas across 4 specialist lenses, paint the micro:bit 5×5 LED matrix live, and harvest local camera clips cloud-free via Pi Zero 2 W.",
    href: "/architect",
    Icon: Flame,
    accent: "orange" as const,
  },
  {
    title: "PostgreSQL 18 + Neo4j G_CPDT",
    badge: "ZERO LOCK-IN",
    desc: "SHA-256 deduplicated blob storage, pgvector semantic search, Neo4j spatial knowledge graph, and 6 open industrial standards exports.",
    href: "/graph",
    Icon: Database,
    accent: "sky" as const,
  },
] as const;

const TIMELINE_STEPS = [
  { step: "Idea", detail: "5-Tier Creativity Dial" },
  { step: "Co-Design", detail: "2D Wiring + 3D CAD" },
  { step: "Wire", detail: "PMIC & 3.3V Guardrails" },
  { step: "Scan", detail: "Camera + LD19 + Depth V2" },
  { step: "Patrol", detail: "Dark-Zone NBV + RTH" },
  { step: "Ship", detail: ".GLB · CycloneDX · DEXPI" },
] as const;

export function MakerLandingPage() {
  return (
    <div className="min-h-screen bg-eigenia-obsidian text-white">
      {/* 1. STICKY CINEMA-GRADE TOP NAV */}
      <header className="sticky top-0 z-40 border-b border-white/10 bg-eigenia-obsidian/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Link href="/welcome" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-eigenia-orange/60 bg-eigenia-orange/15">
              <Radar className="h-4 w-4 text-eigenia-orange" />
            </div>
            <div>
              <div className="font-mono text-xs font-bold tracking-widest text-white">
                EIGENIA // TWINSCAN
              </div>
              <div className="font-mono text-[9px] uppercase tracking-wider text-eigenia-muted">
                Cyber-Physical Maker Studio
              </div>
            </div>
          </Link>

          <nav className="hidden items-center gap-5 font-mono text-[11px] text-eigenia-muted lg:flex">
            <a href="#hero-3d" className="transition hover:text-white">
              3D Twin
            </a>
            <a href="#architecture" className="transition hover:text-white">
              Architecture
            </a>
            <a href="#puppypi-example" className="transition hover:text-white">
              PuppyPi Example
            </a>
            <a
              href="#early-bird"
              className="inline-flex items-center gap-1 text-eigenia-amber transition hover:text-eigenia-orange"
            >
              <Sparkles className="h-3 w-3" />
              Early Bird (50)
            </a>
          </nav>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="ghost" asChild className="hidden sm:inline-flex">
              <Link href="/wiki?tab=wizard">
                <Compass className="h-3.5 w-3.5 text-eigenia-sky" />
                Onboarding Wizard
              </Link>
            </Button>
            <Button size="sm" variant="secondary" asChild>
              <Link href="/wiki?tab=docs">
                <BookOpen className="h-3.5 w-3.5 text-eigenia-sky" />
                Wiki
              </Link>
            </Button>
            <Button size="sm" variant="default" asChild className="font-semibold">
              <Link href="/">
                Launch Command Center
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-[1440px] flex-col gap-20 px-4 py-10 sm:px-6 sm:py-14">
        {/* 2. HERO SECTION + LIVE THREE.JS PUPPYPI PRO TWIN + VERIFIED PROOF STRIP */}
        <section id="hero-3d" className="space-y-8">
          <div className="grid grid-cols-1 items-center gap-8 xl:grid-cols-12">
            <div className="space-y-6 xl:col-span-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="default" className="font-mono text-[10px]">
                  <Sparkles className="h-3 w-3" />
                  100% LOCAL · ZERO CLOUD LOCK-IN
                </Badge>
                <Badge
                  variant="sky"
                  className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
                >
                  PROVEN LIVE ON PUPPYPI PRO
                </Badge>
              </div>

              <h1 className="text-3xl font-bold tracking-tight text-white sm:text-5xl sm:leading-[1.08]">
                Build, Scan &amp; Command{" "}
                <span className="bg-gradient-to-r from-eigenia-orange via-amber-400 to-eigenia-sky bg-clip-text text-transparent">
                  Real Cyber-Physical Robots
                </span>{" "}
                in One Studio.
              </h1>

              <p className="text-sm leading-relaxed text-eigenia-ink sm:text-base">
                Eigenia TwinScan Studio fuses live 360° LD19 LiDAR, monocular 3D depth, offline
                AI vision, hands-free neural voice, and a 5-tier AI Hardware Architect — running
                100% locally in Docker on your workbench with{" "}
                <span className="font-semibold text-white">Hiwonder PuppyPi Pro</span>, Raspberry
                Pi 5, Pi Zero 2 W, micro:bit v2.21, and cloud-free LAN cameras.
              </p>

              <div className="flex flex-wrap items-center gap-3">
                <Button size="lg" variant="default" asChild className="font-semibold">
                  <Link href="/">
                    <Rocket className="h-4 w-4" />
                    Launch Command Center
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
                <Button size="lg" variant="sky" asChild>
                  <Link href="/wiki?tab=wizard">
                    <Compass className="h-4 w-4" />
                    Start 4-Step Wizard
                  </Link>
                </Button>
                <Button size="lg" variant="outline" asChild>
                  <a href="#early-bird">Claim Early Bird (50)</a>
                </Button>
              </div>

              <div className="flex flex-wrap items-center gap-3 pt-1 font-mono text-[11px] text-eigenia-muted">
                <span>Press ⌘K anywhere</span>
                <span>·</span>
                <span>Three.js 0.187 + Babylon.js 9</span>
                <span>·</span>
                <span>PostgreSQL 18 + Neo4j 5</span>
              </div>
            </div>

            <div className="xl:col-span-7">
              <LandingHeroTwin3D />
            </div>
          </div>

          {/* Verified Proof Metrics Strip */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {PROOF_METRICS.map((m) => (
              <div
                key={m.label}
                className="rounded-xl border border-white/10 bg-eigenia-shell p-4 text-center transition hover:border-eigenia-sky/40"
              >
                <div className={`font-mono text-xl font-bold tabular-nums sm:text-2xl ${m.tone}`}>
                  {m.value}
                </div>
                <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  {m.label}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 3. INTERACTIVE REACT FLOW CYBER-PHYSICAL ARCHITECTURE SHOWCASE */}
        <section id="architecture" className="space-y-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1.5">
              <Badge variant="sky" className="font-mono text-[10px]">
                INTERACTIVE SYSTEM TOPOLOGY
              </Badge>
              <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                Every Sensor, AI Engine &amp; Database Wired in Real Time
              </h2>
              <p className="max-w-2xl text-xs text-eigenia-muted sm:text-sm">
                Click any node in the live React Flow cyber-physical pipeline below to inspect
                measured PuppyPi Pro telemetry benchmarks and jump directly into that cockpit.
              </p>
            </div>
            <Button size="sm" variant="secondary" asChild>
              <Link href="/wiki?tab=sitetree">
                Explore Full 12-Route Site Tree
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </div>

          <LandingArchitectureFlow />
        </section>

        {/* 4. FLAGSHIP WORKED EXAMPLE: HIWONDER PUPPYPI PRO */}
        <section id="puppypi-example" className="space-y-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1.5">
              <Badge variant="default" className="font-mono text-[10px]">
                <Bot className="h-3 w-3" />
                FLAGSHIP WORKED EXAMPLE · HIWONDER PUPPYPI PRO
              </Badge>
              <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                From Unboxing PuppyPi Pro to Autonomous 3D Mapping in 4 Steps
              </h2>
              <p className="max-w-2xl text-xs text-eigenia-muted sm:text-sm">
                Every feature in Eigenia TwinScan Studio is battle-tested live on real Raspberry Pi 5
                quadruped hardware — complete with our high-resolution 10,022-triangle PuppyPi CAD
                model.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" asChild>
                <a href="/models/puppypi-pro.glb" download="puppypi-pro.glb">
                  <Box className="h-3.5 w-3.5 text-eigenia-orange" />
                  Download .GLB (253 KB)
                </a>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <a href="/models/puppypi-pro.stl" download="puppypi-pro.stl">
                  <Box className="h-3.5 w-3.5 text-eigenia-sky" />
                  Download .STL (489 KB)
                </a>
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {PUPPYPI_WORKFLOW.map((item) => {
              const Icon = item.Icon;
              return (
                <InteractiveSurface
                  key={item.step}
                  title={item.title}
                  subtitle={item.subtitle}
                  badge={
                    <Badge variant="default" className="font-mono text-[10px]">
                      STEP {item.step}
                    </Badge>
                  }
                  accent={item.step === "01" || item.step === "03" ? "orange" : "sky"}
                  hoverable
                  contentClassName="flex h-full flex-col justify-between gap-4"
                >
                  <div className="space-y-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian">
                      <Icon className="h-5 w-5 text-eigenia-orange" />
                    </div>
                    <p className="text-xs leading-relaxed text-eigenia-ink">{item.description}</p>
                  </div>

                  <div className="space-y-2.5 border-t border-white/10 pt-3">
                    <div className="font-mono text-[10px] text-emerald-400">{item.metric}</div>
                    <Button size="sm" variant="secondary" asChild className="w-full">
                      <Link href={item.href}>
                        {item.cta}
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    </Button>
                  </div>
                </InteractiveSurface>
              );
            })}
          </div>
        </section>

        {/* 5. 6-PILLAR MAKER CAPABILITY BENTO GRID + PROTOTYPING TIMELINE */}
        <section className="space-y-6">
          <div className="space-y-1.5">
            <Badge variant="sky" className="font-mono text-[10px]">
              COMPLETE MAKER STACK
            </Badge>
            <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
              Six Integrated Cockpits, Zero Context Switching
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {CAPABILITY_PILLARS.map((pillar) => {
              const Icon = pillar.Icon;
              return (
                <InteractiveSurface
                  key={pillar.title}
                  title={pillar.title}
                  badge={
                    <Badge variant="neutral" className="font-mono text-[9px]">
                      {pillar.badge}
                    </Badge>
                  }
                  accent={pillar.accent}
                  hoverable
                  contentClassName="flex flex-col justify-between gap-4"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-eigenia-obsidian">
                      <Icon className="h-4 w-4 text-eigenia-sky" />
                    </div>
                    <p className="text-xs leading-relaxed text-eigenia-ink">{pillar.desc}</p>
                  </div>
                  <Link
                    href={pillar.href}
                    className="inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold text-eigenia-orange transition hover:text-white"
                  >
                    Open Cockpit <ArrowRight className="h-3 w-3" />
                  </Link>
                </InteractiveSurface>
              );
            })}
          </div>

          {/* Idea -> Co-Design -> Wire -> Scan -> Patrol -> Ship Timeline Strip */}
          <div className="rounded-xl border border-white/10 bg-eigenia-shell p-4">
            <div className="mb-3 font-mono text-[10px] uppercase tracking-widest text-eigenia-muted">
              End-to-End Hardware Prototyping Loop
            </div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
              {TIMELINE_STEPS.map((st, idx) => (
                <div
                  key={st.step}
                  className="flex flex-col gap-1 rounded-lg border border-white/10 bg-eigenia-obsidian px-3 py-2.5"
                >
                  <div className="flex items-center justify-between font-mono text-[10px]">
                    <span className="font-bold text-eigenia-orange">0{idx + 1}</span>
                    <span className="font-semibold text-white">{st.step}</span>
                  </div>
                  <div className="font-mono text-[10px] text-eigenia-muted">{st.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 6. 50-USER EARLY BIRD MAKER SPECIAL */}
        <EarlyBirdSection />

        {/* 7. CLOSING WIZARD CTA BANNER */}
        <section className="rounded-2xl border border-eigenia-sky/40 bg-gradient-to-r from-eigenia-sky/15 via-eigenia-surface to-eigenia-orange/15 p-6 sm:p-8">
          <div className="flex flex-col items-start justify-between gap-5 lg:flex-row lg:items-center">
            <div className="space-y-2">
              <Badge variant="sky" className="font-mono text-[10px]">
                GUIDED ONBOARDING &amp; LIVE WIKI
              </Badge>
              <h2 className="text-2xl font-bold tracking-tight text-white">
                Ready to Connect Your PuppyPi Pro or Raspberry Pi 5?
              </h2>
              <p className="max-w-2xl text-xs leading-relaxed text-eigenia-ink sm:text-sm">
                Run our 4-Step Interactive Onboarding Wizard to probe Postgres 18, Neo4j 5, live
                LD19 LiDAR, and your robot fleet — and get a personalized blueprint linked to every
                deep-dive Wiki guide.
              </p>
            </div>
            <div className="flex flex-wrap gap-2.5">
              <Button size="lg" variant="default" asChild className="font-semibold">
                <Link href="/wiki?tab=wizard">
                  <Compass className="h-4 w-4" />
                  Launch Onboarding Wizard
                </Link>
              </Button>
              <Button size="lg" variant="secondary" asChild>
                <Link href="/wiki?tab=docs">
                  <BookOpen className="h-4 w-4" />
                  Read Full Wiki
                </Link>
              </Button>
            </div>
          </div>
        </section>
      </main>

      {/* 8. COMPLETE WIKI / WORKSPACE FOOTER */}
      <footer className="mt-10 border-t border-white/10 bg-eigenia-shell">
        <div className="mx-auto grid max-w-[1440px] grid-cols-2 gap-6 px-4 py-10 text-xs sm:px-6 md:grid-cols-4">
          <div className="col-span-2 space-y-2 md:col-span-1">
            <div className="font-mono text-xs font-bold tracking-widest text-white">
              EIGENIA B.V. // TWINSCAN
            </div>
            <p className="leading-relaxed text-eigenia-muted">
              100% local, zero-lock-in robotics &amp; spatial digital twin command center built
              for makers, engineers, and autonomous hardware labs.
            </p>
          </div>
          <div className="space-y-2">
            <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-eigenia-sky">
              Cockpit Workspaces
            </div>
            <ul className="space-y-1.5 text-eigenia-muted">
              <li>
                <Link href="/" className="hover:text-white">
                  Mission Control
                </Link>
              </li>
              <li>
                <Link href="/twin" className="hover:text-white">
                  3D Spatial Twin Studio
                </Link>
              </li>
              <li>
                <Link href="/control" className="hover:text-white">
                  PuppyPi Drive &amp; Stance
                </Link>
              </li>
              <li>
                <Link href="/patrol?tab=explore" className="hover:text-white">
                  Autonomous Patrol &amp; Explorer
                </Link>
              </li>
            </ul>
          </div>
          <div className="space-y-2">
            <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-eigenia-orange">
              AI &amp; Hardware
            </div>
            <ul className="space-y-1.5 text-eigenia-muted">
              <li>
                <Link href="/vision" className="hover:text-white">
                  AI Vision, Memory &amp; Sentry
                </Link>
              </li>
              <li>
                <Link href="/voice" className="hover:text-white">
                  Conversational Voice (OX)
                </Link>
              </li>
              <li>
                <Link href="/catalog" className="hover:text-white">
                  Pi 5 3D BOM &amp; Fleet Catalog
                </Link>
              </li>
              <li>
                <Link href="/architect" className="hover:text-white">
                  5-Tier Lab Architect
                </Link>
              </li>
            </ul>
          </div>
          <div className="space-y-2">
            <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
              Documentation &amp; Setup
            </div>
            <ul className="space-y-1.5 text-eigenia-muted">
              <li>
                <Link href="/wiki?tab=wizard" className="hover:text-white">
                  4-Step Onboarding Wizard
                </Link>
              </li>
              <li>
                <Link href="/wiki?tab=docs" className="hover:text-white">
                  Complete Documentation Wiki
                </Link>
              </li>
              <li>
                <Link href="/wiki?tab=sitetree" className="hover:text-white">
                  Interactive 12-Route Site Tree
                </Link>
              </li>
              <li>
                <Link href="/config" className="hover:text-white">
                  Models, ROS 1/2 &amp; Storage
                </Link>
              </li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  );
}
