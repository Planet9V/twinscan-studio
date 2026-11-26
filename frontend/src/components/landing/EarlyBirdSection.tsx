"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Award,
  BookOpen,
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  Flame,
  Loader2,
  Lock,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  claimEarlyBirdSpot,
  getEarlyBirdStatus,
  type EarlyBirdClaimResponse,
  type EarlyBirdStatus,
} from "@/lib/wikiApi";

const ROLE_OPTIONS = [
  "Maker",
  "Robotics Engineer",
  "Educator",
  "Student",
  "Researcher",
  "Founder",
] as const;

const HARDWARE_CHIPS = [
  "Hiwonder PuppyPi Pro",
  "Raspberry Pi 5 8GB",
  "Raspberry Pi Zero 2 W",
  "BBC micro:bit v2.21",
  "LD19 LiDAR",
  "Local RTSP Cams",
] as const;

const DEFAULT_PERKS = [
  "Lifetime Founding Maker badge + sequential EIGENIA-MAKER-XX Founder Code",
  "Full unrestricted local self-host access: 3D Twin, AI Lab Architect, Autonomous Patrol & Wiki",
  "Priority hardware driver onboarding for your robot, LiDAR, SBC, or micro:bit rig",
  "Direct design review & schematic feedback channel with the Eigenia robotics team",
  "Early access to upcoming multi-robot swarm orchestration & WebGPU Gaussian splatting",
  "100% cloud-free sovereignty guarantee — zero telemetry lock-in, zero forced subscriptions",
];

const FALLBACK_STATUS: EarlyBirdStatus = {
  campaign: "Eigenia Early Bird Maker Founders (First 50)",
  total_spots: 50,
  claimed_spots: 0,
  remaining_spots: 50,
  is_open: true,
  perks: DEFAULT_PERKS,
  recent_makers: [],
};

const STORAGE_KEY = "eigenia_early_bird_founder_pass_v1";

/**
 * EarlyBirdSection renders the live 50-spot Early Bird Maker Founders campaign
 * with real PostgreSQL-backed spot counters, recent anonymized founding makers,
 * interactive reservation form, and instant Founder Pass certificate.
 */
export function EarlyBirdSection() {
  const [status, setStatus] = useState<EarlyBirdStatus>(FALLBACK_STATUS);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [liveConnected, setLiveConnected] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("Maker");
  const [hardwareStack, setHardwareStack] = useState("Hiwonder PuppyPi Pro, Raspberry Pi 5 8GB");
  const [projectGoal, setProjectGoal] = useState("");

  // Submission & certificate state
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [claimedPass, setClaimedPass] = useState<EarlyBirdClaimResponse | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const data = await getEarlyBirdStatus();
      setStatus({
        ...data,
        perks: data.perks.length > 0 ? data.perks : DEFAULT_PERKS,
      });
      setLiveConnected(true);
    } catch {
      setLiveConnected(false);
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as EarlyBirdClaimResponse;
        if (parsed && parsed.founder_code && parsed.spot_number) {
          setClaimedPass(parsed);
        }
      }
    } catch {
      // Ignore storage read errors
    }
  }, [fetchStatus]);

  const toggleHardwareChip = (chip: string) => {
    const tokens = hardwareStack
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const exists = tokens.some((t) => t.toLowerCase() === chip.toLowerCase());
    if (exists) {
      setHardwareStack(
        tokens.filter((t) => t.toLowerCase() !== chip.toLowerCase()).join(", ")
      );
    } else {
      setHardwareStack([...tokens, chip].join(", "));
    }
  };

  const handleCopyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    } catch {
      // Clipboard fallback ignored
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setErrorMsg(null);

    const trimmedName = name.trim();
    const trimmedEmail = email.trim().toLowerCase();
    const trimmedHardware = hardwareStack.trim() || "Raspberry Pi 5";

    if (trimmedName.length < 2) {
      setErrorMsg("Please enter your name (at least 2 characters).");
      return;
    }
    if (!trimmedEmail || !trimmedEmail.includes("@") || !trimmedEmail.includes(".")) {
      setErrorMsg("Please enter a valid email address.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await claimEarlyBirdSpot({
        name: trimmedName,
        email: trimmedEmail,
        role,
        hardware_stack: trimmedHardware,
        project_goal: projectGoal.trim() || undefined,
      });
      setClaimedPass(res);
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(res));
      } catch {
        // Ignore storage write errors
      }
      await fetchStatus();
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Unable to claim your spot right now. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const totalSpots = Math.max(1, status.total_spots || 50);
  const claimedSpots = Math.min(totalSpots, Math.max(0, status.claimed_spots));
  const remainingSpots = Math.max(0, status.remaining_spots);
  const progressPct = Math.min(100, Math.round((claimedSpots / totalSpots) * 100));
  const perks = status.perks.length > 0 ? status.perks : DEFAULT_PERKS;

  return (
    <section
      id="early-bird"
      className="relative overflow-hidden border-t border-white/10 bg-[#0b0d10] py-24"
    >
      {/* Ambient radial orange + sky glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-[#E05A10]/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 right-0 h-80 w-80 rounded-full bg-[#38bdf8]/10 blur-3xl"
      />

      <div className="relative mx-auto max-w-7xl px-6">
        {/* Section Header */}
        <div className="mb-12 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl space-y-3">
            <div className="flex flex-wrap items-center gap-2.5">
              <Badge className="border border-[#E05A10]/40 bg-[#E05A10]/15 px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-[#E05A10]">
                <Flame className="mr-1.5 h-3.5 w-3.5" />
                Strictly Limited · First {totalSpots} Makers
              </Badge>
              <Badge
                variant="neutral"
                className={`font-mono text-[11px] ${
                  liveConnected
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border-white/15 bg-white/5 text-slate-400"
                }`}
              >
                <span
                  className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${
                    liveConnected ? "animate-pulse bg-emerald-400" : "bg-slate-400"
                  }`}
                />
                {liveConnected ? "LIVE PG18 LEDGER" : "LOCAL PREVIEW"}
              </Badge>
            </div>

            <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Early Bird Founding Makers{" "}
              <span className="text-[#E05A10]">Cohort #01</span>
            </h2>
            <p className="text-sm leading-relaxed text-slate-300 sm:text-base">
              We are onboarding the first{" "}
              <span className="font-mono font-semibold text-white">50</span>{" "}
              robotics makers, lab educators, and hardware hackers into the
              Eigenia TwinScan Founding Cohort. Atomic PostgreSQL seat lock —
              once spot <span className="font-mono text-[#E05A10]">#50</span> is
              claimed, the cohort closes automatically.
            </p>
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void fetchStatus()}
            disabled={loadingStatus}
            className="w-fit border-white/15 bg-[#15171b] font-mono text-xs text-slate-300 hover:border-[#E05A10]/50 hover:bg-[#1a1d23] hover:text-white"
          >
            <RefreshCw
              className={`mr-1.5 h-3.5 w-3.5 ${loadingStatus ? "animate-spin" : ""}`}
            />
            Refresh Live Count
          </Button>
        </div>

        {/* Main 2-Column Layout */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
          {/* LEFT COLUMN: Live Scarcity Meter + Perks + Recent Makers */}
          <div className="space-y-6 lg:col-span-6">
            {/* Live Scarcity Meter Card */}
            <Card className="border-white/10 bg-[#15171b]/90 shadow-2xl">
              <CardContent className="space-y-5 p-6">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="font-mono text-[11px] uppercase tracking-widest text-slate-400">
                      Founding Seats Remaining
                    </div>
                    <div className="mt-1 flex items-baseline gap-2.5">
                      <span className="font-mono text-5xl font-bold tracking-tight text-white">
                        {remainingSpots}
                      </span>
                      <span className="font-mono text-sm text-slate-400">
                        / {totalSpots} open
                      </span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-white/10 bg-[#0E1013] px-4 py-3 text-right">
                    <div className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
                      Seats Claimed
                    </div>
                    <div className="mt-0.5 font-mono text-xl font-semibold text-[#E05A10]">
                      {claimedSpots} of {totalSpots}
                    </div>
                    <div className="font-mono text-[10px] text-slate-500">
                      {status.is_open ? "ACCEPTING FOUNDERS" : "COHORT FULL"}
                    </div>
                  </div>
                </div>

                {/* Progress Bar */}
                <div className="space-y-2">
                  <div className="h-3 w-full overflow-hidden rounded-full border border-white/10 bg-[#0b0d10]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[#E05A10] via-[#f59e0b] to-[#38bdf8] transition-all duration-700"
                      style={{ width: `${Math.max(progressPct, claimedSpots > 0 ? 4 : 0)}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between font-mono text-[11px] text-slate-400">
                    <span>Spot #01</span>
                    <span className="text-[#f59e0b]">{progressPct}% allocated</span>
                    <span>Hard Cap #50</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* 6 Founder Perks */}
            <Card className="border-white/10 bg-[#15171b]/80">
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center gap-2">
                  <Award className="h-4 w-4 text-[#E05A10]" />
                  <h3 className="font-mono text-xs font-semibold uppercase tracking-wider text-white">
                    What The First 50 Founders Unlock
                  </h3>
                </div>
                <ul className="space-y-3">
                  {perks.map((perk, idx) => (
                    <li
                      key={`${idx}-${perk.slice(0, 24)}`}
                      className="flex items-start gap-3 text-sm text-slate-300"
                    >
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#38bdf8]" />
                      <span>{perk}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            {/* Recent Founding Makers Ticker */}
            <Card className="border-white/10 bg-[#0E1013]">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-[#38bdf8]" />
                    <span className="font-mono text-xs font-semibold uppercase tracking-wider text-white">
                      Recent Founding Makers
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-slate-500">
                    PRIVACY-SAFE · NO EMAILS SHOWN
                  </span>
                </div>

                {status.recent_makers.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-white/10 bg-[#15171b]/60 px-4 py-4 text-center font-mono text-xs text-slate-400">
                    Be the first maker to lock in{" "}
                    <span className="text-[#E05A10]">EIGENIA-MAKER-01</span> →
                  </div>
                ) : (
                  <div className="space-y-2">
                    {status.recent_makers.slice(0, 5).map((maker) => (
                      <div
                        key={`${maker.spot_number}-${maker.display_name}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-[#15171b] px-3.5 py-2.5 text-xs"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="rounded border border-[#E05A10]/40 bg-[#E05A10]/15 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[#E05A10]">
                            #{String(maker.spot_number).padStart(2, "0")}
                          </span>
                          <span className="font-medium text-white">
                            {maker.display_name}
                          </span>
                          <span className="rounded bg-white/5 px-2 py-0.5 font-mono text-[10px] text-slate-300">
                            {maker.role}
                          </span>
                        </div>
                        <span className="max-w-[220px] truncate font-mono text-[11px] text-[#38bdf8]">
                          {maker.hardware_stack}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* RIGHT COLUMN: Reservation Form OR Instant Founder Pass Certificate */}
          <div className="lg:col-span-6">
            {claimedPass ? (
              <Card className="h-full border-[#E05A10]/50 bg-gradient-to-b from-[#15171b] to-[#0E1013] shadow-[0_0_50px_rgba(224,90,16,0.18)]">
                <CardContent className="flex h-full flex-col justify-between space-y-6 p-7">
                  <div className="space-y-5">
                    <div className="flex items-center justify-between">
                      <Badge className="border border-emerald-500/40 bg-emerald-500/15 px-3 py-1 font-mono text-[11px] text-emerald-300">
                        <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />
                        FOUNDING PASS VERIFIED
                      </Badge>
                      <span className="font-mono text-xs text-slate-400">
                        SPOT #{String(claimedPass.spot_number).padStart(2, "0")} /{" "}
                        {claimedPass.total_spots}
                      </span>
                    </div>

                    <div>
                      <h3 className="text-2xl font-bold tracking-tight text-white">
                        Welcome to Cohort #01, {claimedPass.display_name}
                      </h3>
                      <p className="mt-1.5 text-sm text-slate-300">
                        Your Founding Maker seat is locked in PostgreSQL 18.
                        Save your Founder Code below for priority hardware
                        onboarding and early releases.
                      </p>
                    </div>

                    {/* Glowing Certificate Box */}
                    <div className="rounded-xl border border-[#E05A10]/40 bg-[#0b0d10] p-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400">
                            Official Founder Pass Code
                          </div>
                          <div className="mt-1 font-mono text-2xl font-bold tracking-wider text-[#E05A10] sm:text-3xl">
                            {claimedPass.founder_code}
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void handleCopyCode(claimedPass.founder_code)}
                          className="border-[#E05A10]/40 bg-[#E05A10]/10 font-mono text-xs text-[#E05A10] hover:bg-[#E05A10]/20 hover:text-white"
                        >
                          {copiedCode ? (
                            <>
                              <Check className="mr-1.5 h-3.5 w-3.5" />
                              Copied
                            </>
                          ) : (
                            <>
                              <Copy className="mr-1.5 h-3.5 w-3.5" />
                              Copy Code
                            </>
                          )}
                        </Button>
                      </div>

                      <div className="mt-5 grid grid-cols-1 gap-3 border-t border-white/10 pt-4 sm:grid-cols-2">
                        <div>
                          <div className="font-mono text-[10px] uppercase text-slate-500">
                            Role
                          </div>
                          <div className="mt-0.5 text-sm font-medium text-white">
                            {claimedPass.role}
                          </div>
                        </div>
                        <div>
                          <div className="font-mono text-[10px] uppercase text-slate-500">
                            Hardware Rig
                          </div>
                          <div className="mt-0.5 text-sm font-medium text-[#38bdf8]">
                            {claimedPass.hardware_stack}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Next Actions */}
                  <div className="space-y-3 pt-2">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <Button
                        asChild
                        className="w-full bg-[#E05A10] font-semibold text-white hover:bg-[#c84d0c]"
                      >
                        <Link href="/wiki?tab=wizard">
                          <BookOpen className="mr-2 h-4 w-4" />
                          Start Onboarding Wizard
                        </Link>
                      </Button>
                      <Button
                        asChild
                        variant="outline"
                        className="w-full border-white/15 bg-[#15171b] text-white hover:border-[#38bdf8]/50 hover:bg-[#1b1f27]"
                      >
                        <Link href="/">
                          Launch Command Center
                          <ArrowRight className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setClaimedPass(null);
                        try {
                          window.localStorage.removeItem(STORAGE_KEY);
                        } catch {
                          // ignore
                        }
                      }}
                      className="w-full text-center font-mono text-[11px] text-slate-500 underline-offset-4 hover:text-slate-300 hover:underline"
                    >
                      Register a teammate or claim another pass
                    </button>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card className="h-full border-white/10 bg-[#15171b]/95 shadow-2xl">
                <CardContent className="p-7">
                  <div className="mb-6 flex items-center justify-between">
                    <div>
                      <h3 className="text-xl font-bold text-white">
                        Reserve Your Founding Maker Spot
                      </h3>
                      <p className="mt-1 text-xs text-slate-400">
                        Instant sequential pass · Zero credit card · 100% local
                        self-host stack
                      </p>
                    </div>
                    <Sparkles className="h-5 w-5 shrink-0 text-[#E05A10]" />
                  </div>

                  {!status.is_open ? (
                    <div className="rounded-xl border border-[#f59e0b]/40 bg-[#f59e0b]/10 p-6 text-center">
                      <Lock className="mx-auto mb-3 h-8 w-8 text-[#f59e0b]" />
                      <h4 className="text-base font-semibold text-white">
                        Cohort #01 (50/50) is Full
                      </h4>
                      <p className="mt-2 text-xs leading-relaxed text-slate-300">
                        All 50 Founding Maker spots have been claimed. You can
                        still run Eigenia TwinScan Studio locally and walk
                        through the complete PuppyPi Pro Wiki right now.
                      </p>
                      <Button
                        asChild
                        className="mt-4 bg-[#E05A10] text-white hover:bg-[#c84d0c]"
                      >
                        <Link href="/wiki?tab=wizard">
                          Open Maker Onboarding Wizard
                          <ArrowRight className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  ) : (
                    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
                      {errorMsg && (
                        <div className="flex items-start gap-2.5 rounded-lg border border-[#ef4444]/40 bg-[#ef4444]/10 px-3.5 py-2.5 text-xs text-red-200">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#ef4444]" />
                          <span>{errorMsg}</span>
                        </div>
                      )}

                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                          <label
                            htmlFor="eb-name"
                            className="block font-mono text-[11px] uppercase tracking-wider text-slate-300"
                          >
                            Full Name *
                          </label>
                          <Input
                            id="eb-name"
                            type="text"
                            required
                            minLength={2}
                            placeholder="Ada Lovelace"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="border-white/15 bg-[#0b0d10] text-sm text-white placeholder:text-slate-500 focus-visible:ring-[#E05A10]"
                          />
                        </div>

                        <div className="space-y-1.5">
                          <label
                            htmlFor="eb-email"
                            className="block font-mono text-[11px] uppercase tracking-wider text-slate-300"
                          >
                            Email *
                          </label>
                          <Input
                            id="eb-email"
                            type="email"
                            required
                            placeholder="ada@makerlab.io"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="border-white/15 bg-[#0b0d10] text-sm text-white placeholder:text-slate-500 focus-visible:ring-[#E05A10]"
                          />
                        </div>
                      </div>

                      {/* Role Selector */}
                      <div className="space-y-2">
                        <span className="block font-mono text-[11px] uppercase tracking-wider text-slate-300">
                          Maker Role
                        </span>
                        <div className="flex flex-wrap gap-2">
                          {ROLE_OPTIONS.map((option) => {
                            const active = role === option;
                            return (
                              <button
                                key={option}
                                type="button"
                                onClick={() => setRole(option)}
                                className={`rounded-md border px-2.5 py-1.5 font-mono text-xs transition ${
                                  active
                                    ? "border-[#E05A10] bg-[#E05A10]/20 text-white"
                                    : "border-white/10 bg-[#0b0d10] text-slate-400 hover:border-white/25 hover:text-slate-200"
                                }`}
                              >
                                {option}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Hardware Stack Input + Quick Chips */}
                      <div className="space-y-2">
                        <label
                          htmlFor="eb-hardware"
                          className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-slate-300"
                        >
                          <Cpu className="h-3.5 w-3.5 text-[#38bdf8]" />
                          Your Hardware Stack
                        </label>
                        <Input
                          id="eb-hardware"
                          type="text"
                          placeholder="Hiwonder PuppyPi Pro, Raspberry Pi 5, LD19 LiDAR..."
                          value={hardwareStack}
                          onChange={(e) => setHardwareStack(e.target.value)}
                          className="border-white/15 bg-[#0b0d10] text-sm text-white placeholder:text-slate-500 focus-visible:ring-[#38bdf8]"
                        />
                        <div className="flex flex-wrap gap-1.5">
                          {HARDWARE_CHIPS.map((chip) => {
                            const selected = hardwareStack
                              .toLowerCase()
                              .includes(chip.toLowerCase());
                            return (
                              <button
                                key={chip}
                                type="button"
                                onClick={() => toggleHardwareChip(chip)}
                                className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] transition ${
                                  selected
                                    ? "border-[#38bdf8]/60 bg-[#38bdf8]/15 text-[#38bdf8]"
                                    : "border-white/10 bg-[#0E1013] text-slate-400 hover:border-white/25 hover:text-slate-200"
                                }`}
                              >
                                {selected ? "✓ " : "+ "}
                                {chip}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Project Goal */}
                      <div className="space-y-1.5">
                        <label
                          htmlFor="eb-goal"
                          className="block font-mono text-[11px] uppercase tracking-wider text-slate-300"
                        >
                          What Are You Building?{" "}
                          <span className="text-slate-500">(Optional)</span>
                        </label>
                        <textarea
                          id="eb-goal"
                          rows={3}
                          placeholder="e.g., Autonomous PuppyPi Pro lab patrol with LD19 SLAM + micro:bit environmental sensor nodes..."
                          value={projectGoal}
                          onChange={(e) => setProjectGoal(e.target.value)}
                          className="w-full rounded-md border border-white/15 bg-[#0b0d10] px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-[#E05A10] focus:outline-none focus:ring-1 focus:ring-[#E05A10]"
                        />
                      </div>

                      <Button
                        type="submit"
                        disabled={submitting}
                        className="h-11 w-full bg-[#E05A10] text-sm font-semibold text-white shadow-[0_0_24px_rgba(224,90,16,0.35)] hover:bg-[#c84d0c]"
                      >
                        {submitting ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Locking Your Spot in PostgreSQL 18...
                          </>
                        ) : (
                          <>
                            Claim Founding Maker Spot (#
                            {String(Math.min(totalSpots, claimedSpots + 1)).padStart(2, "0")}/
                            {totalSpots})
                            <ArrowRight className="ml-2 h-4 w-4" />
                          </>
                        )}
                      </Button>

                      <p className="text-center font-mono text-[10px] text-slate-500">
                        Stored locally in your Eigenia PostgreSQL 18 instance ·
                        1 spot per email · Emails are never displayed publicly.
                      </p>
                    </form>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
