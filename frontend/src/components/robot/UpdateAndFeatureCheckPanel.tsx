"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Download,
  History,
  Layers,
  Loader2,
  PackageCheck,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  Terminal,
  Wrench,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchRobotUpdateHistory,
  runRobotUpdateApply,
  runRobotUpdateCheck,
  runRobotUpdateDownload,
  runRobotUpdateDryRun,
  runRobotUpdateRollback,
  runRobotUpdateTests,
  type FeatureReadinessItem,
  type LibraryUpdateItem,
  type RobotRecord,
  type RobotUpdateJobRecord,
  type RobotUpdateSnapshot,
  type SmokeTestReport,
  type UpdateActionResponse,
  type UpdateCheckReport,
} from "@/lib/robotApi";

interface UpdateAndFeatureCheckPanelProps {
  robot: RobotRecord | null;
}

const ABI_SENSITIVE_SET = new Set([
  "torch",
  "torchvision",
  "torchaudio",
  "opencv-python",
  "opencv-python-headless",
  "opencv-contrib-python",
  "mediapipe",
  "numpy",
  "scipy",
  "onnxruntime",
]);

function isAbiSensitivePackage(name: string): boolean {
  return ABI_SENSITIVE_SET.has(name.toLowerCase().replace(/_/g, "-"));
}

function getLibraryStatusBadge(status: string) {
  const s = (status || "").toLowerCase();
  if (s === "up_to_date") {
    return (
      <Badge variant="sky" className="text-[9px]">
        <CheckCircle2 className="h-2.5 w-2.5" />
        Up to Date
      </Badge>
    );
  }
  if (s === "update_available") {
    return (
      <Badge variant="amber" className="text-[9px]">
        <AlertTriangle className="h-2.5 w-2.5" />
        Update Available
      </Badge>
    );
  }
  if (s === "not_installed") {
    return (
      <Badge variant="neutral" className="text-[9px]">
        Not Installed
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" className="text-[9px]">
      {status || "Unknown"}
    </Badge>
  );
}

function getFeatureStatusBadge(status: string) {
  const s = (status || "").toLowerCase();
  if (s === "ready") {
    return (
      <Badge
        variant="sky"
        className="border-emerald-500/40 bg-emerald-500/15 text-[9px] text-emerald-400"
      >
        <CheckCircle2 className="h-2.5 w-2.5" />
        READY
      </Badge>
    );
  }
  if (s === "warning") {
    return (
      <Badge variant="amber" className="text-[9px]">
        <AlertTriangle className="h-2.5 w-2.5" />
        ATTENTION
      </Badge>
    );
  }
  return (
    <Badge variant="fault" className="text-[9px]">
      <XCircle className="h-2.5 w-2.5" />
      MISSING
    </Badge>
  );
}

function getSmokeStatusBadge(status: string) {
  const s = (status || "").toLowerCase();
  if (s === "pass") {
    return (
      <Badge
        variant="sky"
        className="border-emerald-500/40 bg-emerald-500/15 text-[9px] text-emerald-400"
      >
        <CheckCircle2 className="h-2.5 w-2.5" />
        PASS
      </Badge>
    );
  }
  if (s === "warn") {
    return (
      <Badge variant="amber" className="text-[9px]">
        <AlertTriangle className="h-2.5 w-2.5" />
        WARN
      </Badge>
    );
  }
  return (
    <Badge variant="fault" className="text-[9px]">
      <XCircle className="h-2.5 w-2.5" />
      FAIL
    </Badge>
  );
}

export function UpdateAndFeatureCheckPanel({ robot }: UpdateAndFeatureCheckPanelProps) {
  const [report, setReport] = useState<UpdateCheckReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Safe Update Executor, Smoke Tests & Rollback state
  const [track, setTrack] = useState<"ros_pip" | "host_apt">("ros_pip");
  const [selectedPackages, setSelectedPackages] = useState<string[]>([]);
  const [allowAbiSensitive, setAllowAbiSensitive] = useState(false);
  const [execBusy, setExecBusy] = useState<string | null>(null);
  const [execResult, setExecResult] = useState<UpdateActionResponse | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);

  // Update History & Snapshots
  const [jobs, setJobs] = useState<RobotUpdateJobRecord[]>([]);
  const [snapshots, setSnapshots] = useState<RobotUpdateSnapshot[]>([]);
  const [selectedRollbackTag, setSelectedRollbackTag] = useState<string>("");

  const robotId = robot?.id ?? null;

  const loadHistory = useCallback(async (id: string) => {
    try {
      const hist = await fetchRobotUpdateHistory(id);
      setJobs(Array.isArray(hist.jobs) ? hist.jobs : []);
      const snaps = Array.isArray(hist.snapshots) ? hist.snapshots : [];
      setSnapshots(snaps);
      setSelectedRollbackTag((prev) => {
        if (prev && snaps.some((s) => s.tag === prev)) return prev;
        return snaps[0]?.tag ?? "";
      });
    } catch {
      // Non-fatal if history endpoint is offline
    }
  }, []);

  const executeCheck = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await runRobotUpdateCheck(id);
        setReport(data);
        await loadHistory(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Update & feature check failed");
      } finally {
        setLoading(false);
      }
    },
    [loadHistory]
  );

  useEffect(() => {
    if (!robotId) {
      setReport(null);
      setError(null);
      setJobs([]);
      setSnapshots([]);
      setExecResult(null);
      setSelectedPackages([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    runRobotUpdateCheck(robotId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Update & feature check failed");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    void loadHistory(robotId);
    return () => {
      cancelled = true;
    };
  }, [robotId, loadHistory]);

  const libraries: LibraryUpdateItem[] = useMemo(
    () => (Array.isArray(report?.libraries) ? report.libraries : []),
    [report]
  );

  const updatableRobotPipNames = useMemo(
    () =>
      libraries
        .filter((l) => (l.scope || "robot") === "robot" && l.status === "update_available")
        .map((l) => l.name),
    [libraries]
  );

  const selectedHasAbi = useMemo(
    () => selectedPackages.some((pkg) => isAbiSensitivePackage(pkg)),
    [selectedPackages]
  );

  const togglePackageSelection = (pkgName: string) => {
    setSelectedPackages((prev) =>
      prev.includes(pkgName) ? prev.filter((p) => p !== pkgName) : [...prev, pkgName]
    );
  };

  const selectSafeUpdatable = () => {
    setSelectedPackages(updatableRobotPipNames.filter((name) => !isAbiSensitivePackage(name)));
  };

  const runExecutorAction = async (
    actionKey: string,
    fn: () => Promise<UpdateActionResponse>,
    refreshAfter = false
  ) => {
    if (!robotId) return;
    setExecBusy(actionKey);
    setExecError(null);
    try {
      const res = await fn();
      setExecResult(res);
      if (!res.ok && res.error) {
        setExecError(res.error);
      }
      await loadHistory(robotId);
      if (refreshAfter) {
        await executeCheck(robotId);
      }
    } catch (err) {
      setExecError(err instanceof Error ? err.message : `Update action "${actionKey}" failed`);
    } finally {
      setExecBusy(null);
    }
  };

  if (!robot) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-xs text-eigenia-muted">
          Select a PuppyPi robot to run live PyPI update checks, ROS/OS lifecycle audit, safe updates, and 6-point hardware smoke tests.
        </CardContent>
      </Card>
    );
  }

  const lifecycle = (report?.ros_lifecycle ?? {}) as Record<string, unknown>;
  const isEol =
    lifecycle.is_eol === true ||
    String(lifecycle.active_mode ?? "").toLowerCase() === "ros1";
  const aptCount =
    typeof lifecycle.apt_upgradable_count === "number"
      ? lifecycle.apt_upgradable_count
      : typeof report?.summary?.apt_upgradable_count === "number"
        ? (report.summary.apt_upgradable_count as number)
        : null;
  const advisory = String(
    lifecycle.advisory ?? lifecycle.warning ?? lifecycle.recommendation ?? ""
  );
  const hostOs = String(
    lifecycle.host_os ?? lifecycle.ubuntu_or_debian ?? "Debian GNU/Linux 12 (bookworm)"
  );
  const activeDistro = String(
    lifecycle.active_distro ?? robot.active_ros_distro ?? "ROS 1 Noetic"
  );
  const supportStatus = String(
    lifecycle.support_status ?? lifecycle.status ?? (isEol ? "EOL (May 2025)" : "LTS Active")
  );

  const newerRos2Raw = lifecycle.newer_ros2_releases ?? lifecycle.newer_ros_distros;
  const newerRos2List: { distro: string; status: string }[] = Array.isArray(newerRos2Raw)
    ? newerRos2Raw.map((item) =>
        typeof item === "string"
          ? { distro: item, status: "Available ROS 2 Release" }
          : {
              distro: String((item as Record<string, unknown>).distro ?? ""),
              status: String((item as Record<string, unknown>).status ?? ""),
            }
      )
    : [
        { distro: "ROS 2 Humble", status: "LTS Active through May 2027 (Pre-installed)" },
        { distro: "ROS 2 Jazzy", status: "LTS Active through May 2029 (Ubuntu 24.04)" },
        { distro: "ROS 2 Kilted", status: "Latest STS Release (Ubuntu 24.04)" },
      ];

  const twinscanStack: LibraryUpdateItem[] = Array.isArray(report?.twinscan_stack)
    ? (report.twinscan_stack as unknown as LibraryUpdateItem[])
    : [];
  const features: FeatureReadinessItem[] = Array.isArray(report?.features)
    ? report.features
    : [];

  const summary = (report?.summary ?? {}) as Record<string, unknown>;
  const readyCount = Number(
    summary.ready_features ?? summary.features_ready ?? features.filter((f) => f.status === "ready").length
  );
  const warnCount = Number(
    summary.warning_features ?? summary.features_warning ?? features.filter((f) => f.status === "warning").length
  );
  const missingCount = Number(
    summary.missing_features ?? summary.features_missing ?? features.filter((f) => f.status === "missing").length
  );
  const updatesAvail = Number(
    summary.updates_available ??
      libraries.filter((l) => l.status === "update_available").length
  );

  const activeSmokeReport: SmokeTestReport | null =
    execResult?.smoke_tests ?? jobs.find((j) => j.smoke_tests)?.smoke_tests ?? null;

  const canRunPipTrack = track !== "ros_pip" || selectedPackages.length > 0;
  const abiBlocked = track === "ros_pip" && selectedHasAbi && !allowAbiSensitive;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2">
            <PackageCheck className="h-4 w-4 text-eigenia-orange" />
            Live Update Audit, Safe Update Executor & 6-Point Smoke Tests
          </CardTitle>
          <p className="mt-1 text-xs text-eigenia-muted">
            Dry-run preview, wheel/.deb pre-download, automatic Docker rollback snapshots, 6-point hardware verification, and live PyPI/OS audit.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {report?.checked_at && (
            <span className="font-mono text-[10px] text-eigenia-muted">
              Checked {new Date(report.checked_at).toLocaleTimeString()}
            </span>
          )}
          <Button
            size="sm"
            variant="default"
            disabled={loading}
            onClick={() => void executeCheck(robot.id)}
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {loading ? "Auditing PyPI & Hardware..." : "Run Update & Feature Check"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-md border border-eigenia-fault/40 bg-eigenia-fault/15 px-3 py-2 font-mono text-xs text-eigenia-fault">
            {error}
          </div>
        )}

        {loading && !report && (
          <div className="flex items-center justify-center gap-2 rounded-md border border-white/10 bg-eigenia-obsidian p-8 text-xs text-eigenia-muted">
            <Loader2 className="h-4 w-4 animate-spin text-eigenia-orange" />
            Querying PyPI JSON API, ROS lifecycle metadata, and PuppyPi hardware telemetry...
          </div>
        )}

        {report && (
          <>
            {/* Summary KPI Strip */}
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5">
                <div className="font-mono text-[9px] uppercase text-emerald-300">Features Ready</div>
                <div className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-emerald-400">
                  {readyCount}
                </div>
              </div>
              <div className="rounded-md border border-eigenia-amber/35 bg-eigenia-amber/10 p-2.5">
                <div className="font-mono text-[9px] uppercase text-eigenia-amber">Needs Attention</div>
                <div className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-eigenia-amber">
                  {warnCount}
                </div>
              </div>
              <div className="rounded-md border border-eigenia-fault/35 bg-eigenia-fault/10 p-2.5">
                <div className="font-mono text-[9px] uppercase text-eigenia-fault">Missing</div>
                <div className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-eigenia-fault">
                  {missingCount}
                </div>
              </div>
              <div className="rounded-md border border-eigenia-orange/35 bg-eigenia-orange/10 p-2.5">
                <div className="font-mono text-[9px] uppercase text-eigenia-orange">PyPI Updates</div>
                <div className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-white">
                  {updatesAvail}
                </div>
              </div>
              <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-2.5">
                <div className="font-mono text-[9px] uppercase text-eigenia-muted">Host APT Upgradable</div>
                <div className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-eigenia-sky">
                  {aptCount !== null ? aptCount : "—"}
                </div>
              </div>
            </div>

            {/* ROS & OS Lifecycle Banner */}
            <div
              className={`rounded-md border p-3.5 ${
                isEol
                  ? "border-eigenia-amber/50 bg-eigenia-amber/10"
                  : "border-eigenia-orange/50 bg-eigenia-orange/15"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  {isEol ? (
                    <ShieldAlert className="h-4 w-4 text-eigenia-amber" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-eigenia-orange" />
                  )}
                  <span className="text-xs font-semibold text-white">
                    ROS & OS Lifecycle — {activeDistro}
                  </span>
                  <Badge variant={isEol ? "fault" : "default"}>{supportStatus}</Badge>
                  <Badge variant="neutral" className="font-mono">
                    {hostOs}
                  </Badge>
                  {aptCount !== null && (
                    <Badge variant={aptCount > 0 ? "amber" : "sky"} className="tabular-nums">
                      {aptCount} apt upgradable
                    </Badge>
                  )}
                </div>
              </div>

              {advisory && (
                <p className="mt-2 text-xs leading-relaxed text-eigenia-ink">{advisory}</p>
              )}

              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {newerRos2List.map((rel) => (
                  <span
                    key={rel.distro}
                    className="rounded border border-white/10 bg-eigenia-obsidian/80 px-2 py-0.5 font-mono text-[10px] text-eigenia-muted"
                  >
                    <strong className="text-white">{rel.distro}:</strong> {rel.status}
                  </span>
                ))}
              </div>
            </div>

            {/* SAFE UPDATE EXECUTOR, SMOKE TESTER & ROLLBACK */}
            <div className="space-y-3 rounded-lg border border-eigenia-orange/45 bg-eigenia-obsidian p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white">
                    <ShieldAlert className="h-4 w-4 text-eigenia-orange" />
                    Safe Update Executor, 6-Point Smoke Tests & Rollback
                  </div>
                  <p className="mt-0.5 text-[11px] text-eigenia-muted">
                    Select libraries below (for pip) or switch to Debian 12 apt track, preview via Dry-Run, then Snapshot + Apply & Test.
                  </p>
                </div>

                {/* Track Selector Pills */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <Button
                    size="sm"
                    variant={track === "ros_pip" ? "default" : "secondary"}
                    className="h-7 text-[11px]"
                    onClick={() => setTrack("ros_pip")}
                  >
                    Robot ROS Python (pip · Auto Snapshot)
                  </Button>
                  <Button
                    size="sm"
                    variant={track === "host_apt" ? "sky" : "secondary"}
                    className="h-7 text-[11px]"
                    onClick={() => setTrack("host_apt")}
                  >
                    PuppyPi Host OS (Debian 12 apt)
                  </Button>
                </div>
              </div>

              {/* Selection Summary & ABI Safety Gate */}
              {track === "ros_pip" && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/10 bg-eigenia-shell px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono text-[11px] text-eigenia-muted">
                      Selected pip packages:{" "}
                      <strong className="text-white">{selectedPackages.length}</strong>
                    </span>
                    {selectedPackages.map((pkg) => (
                      <Badge
                        key={pkg}
                        variant={isAbiSensitivePackage(pkg) ? "amber" : "sky"}
                        className="text-[9px]"
                      >
                        {pkg}
                        {isAbiSensitivePackage(pkg) ? " · ABI" : ""}
                      </Badge>
                    ))}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 text-[10px]"
                      onClick={selectSafeUpdatable}
                    >
                      Select Safe Updatable
                    </Button>
                    {selectedPackages.length > 0 && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-[10px]"
                        onClick={() => setSelectedPackages([])}
                      >
                        Clear
                      </Button>
                    )}
                  </div>

                  <label className="inline-flex cursor-pointer items-center gap-2 rounded border border-eigenia-amber/35 bg-eigenia-amber/10 px-2.5 py-1 text-[11px] text-eigenia-amber">
                    <input
                      type="checkbox"
                      checked={allowAbiSensitive}
                      onChange={(e) => setAllowAbiSensitive(e.target.checked)}
                      className="h-3.5 w-3.5 accent-eigenia-orange"
                    />
                    Allow ABI-sensitive upgrades (`torch`, `opencv`, `mediapipe`, `numpy`, `scipy`)
                  </label>
                </div>
              )}

              {/* Step-by-Step Action Buttons */}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={execBusy !== null || !canRunPipTrack}
                  onClick={() =>
                    void runExecutorAction("dry-run", () =>
                      runRobotUpdateDryRun(robot.id, {
                        track,
                        packages: track === "ros_pip" ? selectedPackages : undefined,
                      })
                    )
                  }
                >
                  {execBusy === "dry-run" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Search className="h-3.5 w-3.5" />
                  )}
                  1. Dry-Run Preview
                </Button>

                <Button
                  size="sm"
                  variant="sky"
                  disabled={execBusy !== null || !canRunPipTrack}
                  onClick={() =>
                    void runExecutorAction("download", () =>
                      runRobotUpdateDownload(robot.id, {
                        track,
                        packages: track === "ros_pip" ? selectedPackages : undefined,
                      })
                    )
                  }
                >
                  {execBusy === "download" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                  2. Download Only
                </Button>

                <Button
                  size="sm"
                  variant="default"
                  disabled={execBusy !== null || !canRunPipTrack || abiBlocked}
                  onClick={() =>
                    void runExecutorAction(
                      "apply",
                      () =>
                        runRobotUpdateApply(robot.id, {
                          track,
                          packages: track === "ros_pip" ? selectedPackages : undefined,
                          allow_abi_sensitive: allowAbiSensitive,
                          run_tests: true,
                        }),
                      true
                    )
                  }
                >
                  {execBusy === "apply" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  3. Snapshot + Apply & Test
                </Button>

                <Button
                  size="sm"
                  variant="outline"
                  disabled={execBusy !== null}
                  onClick={() =>
                    void runExecutorAction("smoke-tests", () =>
                      runRobotUpdateTests(
                        robot.id,
                        selectedPackages.length > 0 ? selectedPackages : undefined
                      )
                    )
                  }
                >
                  {execBusy === "smoke-tests" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Activity className="h-3.5 w-3.5 text-eigenia-sky" />
                  )}
                  Run 6-Point Smoke Tests
                </Button>
              </div>

              {abiBlocked && (
                <div className="rounded border border-eigenia-amber/45 bg-eigenia-amber/10 px-2.5 py-1.5 font-mono text-[10px] text-eigenia-amber">
                  ABI safety gate active: check &quot;Allow ABI-sensitive upgrades&quot; to apply native C/C++ packages (`torch`/`opencv`/`mediapipe`/`numpy`/`scipy`).
                </div>
              )}

              {/* Rollback Snapshot Selector */}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-white/10 bg-eigenia-shell p-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <RotateCcw className="h-3.5 w-3.5 text-eigenia-amber" />
                  <span className="font-mono text-[11px] font-medium text-white">
                    Rollback Snapshots ({snapshots.length})
                  </span>
                  <select
                    value={selectedRollbackTag}
                    onChange={(e) => setSelectedRollbackTag(e.target.value)}
                    disabled={snapshots.length === 0}
                    className="h-7 rounded-md border border-white/15 bg-eigenia-obsidian px-2 font-mono text-[11px] text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange disabled:opacity-50"
                  >
                    {snapshots.length === 0 ? (
                      <option value="">No pre-update-* snapshots yet</option>
                    ) : (
                      snapshots.map((s) => (
                        <option key={s.tag} value={s.tag}>
                          {s.tag}
                          {s.created ? ` (${s.created})` : ""}
                          {s.size ? ` · ${s.size}` : ""}
                        </option>
                      ))
                    )}
                  </select>
                </div>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={execBusy !== null || !selectedRollbackTag}
                  onClick={() =>
                    void runExecutorAction(
                      "rollback",
                      () =>
                        runRobotUpdateRollback(robot.id, {
                          rollback_tag: selectedRollbackTag,
                        }),
                      true
                    )
                  }
                >
                  {execBusy === "rollback" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCcw className="h-3.5 w-3.5" />
                  )}
                  Rollback Snapshot
                </Button>
              </div>

              {execError && (
                <div className="rounded border border-eigenia-fault/45 bg-eigenia-fault/15 px-3 py-2 font-mono text-[11px] text-eigenia-fault">
                  {execError}
                </div>
              )}

              {/* Latest Action Result Banner & Planned Packages Preview */}
              {execResult && (
                <div className="space-y-2.5 rounded-md border border-white/10 bg-eigenia-shell p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant={execResult.ok ? "sky" : "fault"}>
                        {execResult.action.toUpperCase()} · {execResult.ok ? "OK" : "FAILED"}
                      </Badge>
                      <Badge variant="neutral">{execResult.track}</Badge>
                      {execResult.container && (
                        <Badge variant="default" className="font-mono text-[9px]">
                          {execResult.container}
                        </Badge>
                      )}
                      {execResult.rollback_tag && (
                        <Badge variant="amber" className="font-mono text-[9px]">
                          Snapshot: {execResult.rollback_tag}
                        </Badge>
                      )}
                      {typeof execResult.upgradable_count === "number" && (
                        <Badge variant="sky" className="tabular-nums text-[9px]">
                          {execResult.upgradable_count} planned
                        </Badge>
                      )}
                    </div>
                    {(execResult.stdout_tail || execResult.stderr_tail) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 font-mono text-[10px]"
                        onClick={() => setShowLogs((v) => !v)}
                      >
                        <Terminal className="h-3 w-3" />
                        {showLogs ? "Hide Logs" : "Show stdout/stderr"}
                        {showLogs ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </Button>
                    )}
                  </div>

                  {Array.isArray(execResult.abi_sensitive_packages) &&
                    execResult.abi_sensitive_packages.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-eigenia-amber">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>ABI-sensitive packages flagged:</span>
                        {execResult.abi_sensitive_packages.map((p) => (
                          <Badge key={p} variant="amber" className="text-[9px]">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    )}

                  {Array.isArray(execResult.protected_blocked) &&
                    execResult.protected_blocked.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-eigenia-fault">
                        <XCircle className="h-3.5 w-3.5" />
                        <span>Protected system packages blocked from removal:</span>
                        {execResult.protected_blocked.map((p) => (
                          <Badge key={p} variant="fault" className="text-[9px]">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    )}

                  {Array.isArray(execResult.packages) && execResult.packages.length > 0 && (
                    <div className="max-h-44 overflow-auto rounded border border-white/10">
                      <table className="w-full text-left font-mono text-[10px]">
                        <thead className="sticky top-0 border-b border-white/10 bg-eigenia-obsidian text-eigenia-muted">
                          <tr>
                            <th className="px-2 py-1">Package</th>
                            <th className="px-2 py-1">Current</th>
                            <th className="px-2 py-1">Candidate</th>
                            <th className="px-2 py-1 text-right">Flag</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                          {execResult.packages.slice(0, 60).map((pkg) => (
                            <tr key={pkg.name}>
                              <td className="px-2 py-1 text-white">{pkg.name}</td>
                              <td className="px-2 py-1 text-eigenia-muted">
                                {pkg.current_version || "—"}
                              </td>
                              <td className="px-2 py-1 text-eigenia-sky">
                                {pkg.candidate_version || "latest"}
                              </td>
                              <td className="px-2 py-1 text-right">
                                {pkg.is_security && (
                                  <Badge variant="fault" className="text-[8px]">
                                    SECURITY
                                  </Badge>
                                )}
                                {isAbiSensitivePackage(pkg.name) && (
                                  <Badge variant="amber" className="text-[8px]">
                                    ABI-SENSITIVE
                                  </Badge>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {showLogs && (execResult.stdout_tail || execResult.stderr_tail) && (
                    <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                      {execResult.stdout_tail && (
                        <div className="space-y-1">
                          <div className="font-mono text-[9px] uppercase text-eigenia-sky">stdout</div>
                          <pre className="max-h-48 overflow-auto rounded border border-white/10 bg-eigenia-obsidian p-2 font-mono text-[10px] text-eigenia-ink whitespace-pre-wrap">
                            {execResult.stdout_tail}
                          </pre>
                        </div>
                      )}
                      {execResult.stderr_tail && (
                        <div className="space-y-1">
                          <div className="font-mono text-[9px] uppercase text-eigenia-fault">stderr</div>
                          <pre className="max-h-48 overflow-auto rounded border border-eigenia-fault/30 bg-eigenia-obsidian p-2 font-mono text-[10px] text-eigenia-fault whitespace-pre-wrap">
                            {execResult.stderr_tail}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* 6-Point Post-Update Smoke Test Scorecard */}
              {activeSmokeReport && Array.isArray(activeSmokeReport.checks) && (
                <div className="space-y-2 rounded-md border border-white/10 bg-eigenia-shell p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-mono text-[11px] font-semibold text-white">
                      <Activity className="h-3.5 w-3.5 text-eigenia-sky" />
                      6-Point Post-Update Smoke Test Scorecard
                    </div>
                    <Badge
                      variant={activeSmokeReport.passed ? "sky" : "fault"}
                      className={
                        activeSmokeReport.passed
                          ? "border-emerald-500/40 bg-emerald-500/15 tabular-nums text-emerald-400"
                          : "tabular-nums"
                      }
                    >
                      {activeSmokeReport.passed_count}/{activeSmokeReport.total_count} PASSED
                    </Badge>
                  </div>
                  <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {activeSmokeReport.checks.map((chk) => (
                      <div
                        key={chk.id || chk.name}
                        className="flex flex-col justify-between gap-1 rounded border border-white/10 bg-eigenia-obsidian p-2.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-white">{chk.name}</span>
                          {getSmokeStatusBadge(chk.status)}
                        </div>
                        <div className="font-mono text-[10px] text-eigenia-muted">{chk.detail}</div>
                        {typeof chk.latency_ms === "number" && (
                          <div className="font-mono text-[9px] tabular-nums text-eigenia-sky">
                            {Math.round(chk.latency_ms)} ms
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent Update Jobs Ledger */}
              {jobs.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                    <History className="h-3 w-3 text-eigenia-orange" />
                    Recent Update Jobs ({jobs.length})
                  </div>
                  <div className="max-h-40 overflow-auto rounded-md border border-white/10">
                    <table className="w-full text-left font-mono text-[10px]">
                      <thead className="sticky top-0 border-b border-white/10 bg-eigenia-shell text-eigenia-muted">
                        <tr>
                          <th className="px-2.5 py-1.5">Action / Track</th>
                          <th className="px-2.5 py-1.5">Status</th>
                          <th className="px-2.5 py-1.5">Packages / Tag</th>
                          <th className="px-2.5 py-1.5 text-right">Time</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {jobs.slice(0, 10).map((job) => (
                          <tr key={job.id} className="hover:bg-white/[0.02]">
                            <td className="px-2.5 py-1.5 text-white">
                              {job.action} · <span className="text-eigenia-muted">{job.track}</span>
                            </td>
                            <td className="px-2.5 py-1.5">
                              <Badge
                                variant={
                                  job.status === "succeeded" || job.status === "ok"
                                    ? "sky"
                                    : job.status === "blocked" || job.status === "failed"
                                      ? "fault"
                                      : "neutral"
                                }
                                className="text-[8px]"
                              >
                                {job.status}
                              </Badge>
                            </td>
                            <td className="max-w-xs truncate px-2.5 py-1.5 text-eigenia-muted">
                              {Array.isArray(job.packages) && job.packages.length > 0
                                ? job.packages.join(", ")
                                : job.rollback_tag || "—"}
                            </td>
                            <td className="px-2.5 py-1.5 text-right text-eigenia-muted">
                              {job.created_at ? new Date(job.created_at).toLocaleTimeString() : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Hardware & Feature Readiness Matrix */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                <Wrench className="h-3 w-3 text-eigenia-orange" />
                Hardware & Feature Readiness Matrix ({features.length})
              </div>
              <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-3">
                {features.map((feat) => (
                  <div
                    key={feat.feature}
                    className="flex flex-col justify-between gap-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3"
                  >
                    <div className="space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-xs font-semibold text-white">{feat.feature}</span>
                        {getFeatureStatusBadge(feat.status)}
                      </div>
                      <div className="font-mono text-[10px] text-eigenia-sky">{feat.detail}</div>
                    </div>
                    {feat.fix_hint && (
                      <div className="border-t border-white/10 pt-1.5 text-[10px] leading-relaxed text-eigenia-muted">
                        {feat.fix_hint}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Library & TwinScan Stack Update Matrix */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {/* Python AI / CV / Backend Libraries (Selectable checkboxes on Robot pip libs) */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  <Cpu className="h-3 w-3 text-eigenia-sky" />
                  Robot & Backend Python Libraries (Select to Update)
                </div>
                <div className="overflow-x-auto rounded-md border border-white/10">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-white/10 bg-eigenia-obsidian font-mono text-[10px] uppercase text-eigenia-muted">
                      <tr>
                        <th className="w-8 px-2 py-2 text-center">Sel</th>
                        <th className="px-2.5 py-2">Package</th>
                        <th className="px-2.5 py-2">Installed</th>
                        <th className="px-2.5 py-2">Latest</th>
                        <th className="px-2.5 py-2 text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5 font-mono text-[11px]">
                      {libraries.map((lib) => {
                        const isRobotScope = (lib.scope || "robot") === "robot";
                        const canSelect = isRobotScope && lib.status === "update_available";
                        const abiSensitive = isAbiSensitivePackage(lib.name);
                        const checked = selectedPackages.includes(lib.name);

                        return (
                          <tr
                            key={`${lib.scope ?? "lib"}-${lib.name}`}
                            className={checked ? "bg-eigenia-orange/10" : "hover:bg-white/[0.02]"}
                          >
                            <td className="px-2 py-1.5 text-center">
                              {canSelect ? (
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => togglePackageSelection(lib.name)}
                                  className="h-3.5 w-3.5 cursor-pointer accent-eigenia-orange"
                                  aria-label={`Select ${lib.name} for upgrade`}
                                />
                              ) : (
                                <span className="text-[10px] text-eigenia-muted">—</span>
                              )}
                            </td>
                            <td className="px-2.5 py-1.5">
                              <div className="flex flex-wrap items-center gap-1">
                                <span className="font-medium text-white">{lib.name}</span>
                                <span className="text-[9px] text-eigenia-muted">
                                  ({lib.scope || "robot"})
                                </span>
                                {isRobotScope && abiSensitive && (
                                  <Badge variant="amber" className="px-1 py-0 text-[8px]">
                                    ABI-SENSITIVE
                                  </Badge>
                                )}
                              </div>
                            </td>
                            <td className="px-2.5 py-1.5 tabular-nums text-eigenia-ink">
                              {lib.installed || "—"}
                            </td>
                            <td className="px-2.5 py-1.5 tabular-nums text-eigenia-sky">
                              {lib.latest || "—"}
                            </td>
                            <td className="px-2.5 py-1.5 text-right">
                              {getLibraryStatusBadge(lib.status)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* TwinScan Modernized Platform Stack */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                  <Layers className="h-3 w-3 text-eigenia-orange" />
                  Eigenia TwinScan Stack Status
                </div>
                <div className="overflow-x-auto rounded-md border border-white/10">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-white/10 bg-eigenia-obsidian font-mono text-[10px] uppercase text-eigenia-muted">
                      <tr>
                        <th className="px-2.5 py-2">Component</th>
                        <th className="px-2.5 py-2">Installed</th>
                        <th className="px-2.5 py-2">Latest</th>
                        <th className="px-2.5 py-2 text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5 font-mono text-[11px]">
                      {twinscanStack.map((item) => (
                        <tr key={item.name} className="hover:bg-white/[0.02]">
                          <td className="px-2.5 py-1.5 font-medium text-white">{item.name}</td>
                          <td className="px-2.5 py-1.5 tabular-nums text-eigenia-ink">
                            {item.installed || "—"}
                          </td>
                          <td className="px-2.5 py-1.5 tabular-nums text-eigenia-sky">
                            {item.latest || "—"}
                          </td>
                          <td className="px-2.5 py-1.5 text-right">
                            {getLibraryStatusBadge(item.status)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
