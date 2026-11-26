"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Archive,
  CheckCircle2,
  Database,
  Eye,
  EyeOff,
  FileText,
  FolderPlus,
  HardDrive,
  KeyRound,
  Layers,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  XCircle,
  Zap,
} from "lucide-react";
import {
  OpenRouterModelPicker,
  type ModelCategoryKey,
} from "@/components/admin/OpenRouterModelPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { InteractiveSurface } from "@/components/ui/InteractiveSurface";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  archiveTwinSnapshot,
  createSpace,
  deleteSpace,
  deleteStoredFile,
  fetchAdminAudit,
  fetchAdminSettings,
  fetchVisionUsage,
  getFileUrl,
  listStoredFiles,
  reconcileNeo4j,
  refreshOpenRouterModels,
  reindexEmbeddings,
  saveAdminSettings,
  scrubStorage,
  testAllConnections,
  testOpenRouterKey,
  uploadStoredFile,
} from "@/lib/api";
import type {
  AdminSettingItem,
  OpenRouterCatalogResponse,
  OpenRouterKeyTestResult,
  SpaceRecord,
  StorageStats,
  StoredFileRecord,
} from "@/lib/types";

const OPENROUTER_MODEL_SETTING_CATEGORIES: Record<string, ModelCategoryKey> = {
  openrouter_default_vision_model: "vision",
  openrouter_secondary_vision_model: "vision",
  openrouter_research_model: "web_research",
  openrouter_embedding_model: "embedding",
};

function formatUsdAmount(val?: number | null): string {
  if (val === null || val === undefined || !Number.isFinite(val)) return "Unlimited";
  return `$${val.toFixed(val < 1 && val > 0 ? 4 : 2)}`;
}

interface AdminConfigPanelProps {
  spaces: SpaceRecord[];
  activeSpaceId: string;
  onSelectSpace: (id: string) => void;
  onSpacesChanged: () => void;
  onSettingsChanged: () => void;
  section?: "all" | "ai" | "databases";
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let val = bytes;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return `${val.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

export function AdminConfigPanel({
  spaces,
  activeSpaceId,
  onSelectSpace,
  onSpacesChanged,
  onSettingsChanged,
  section = "all",
}: AdminConfigPanelProps) {
  const [adminToken, setAdminToken] = useState("");
  const [adminTokenRequired, setAdminTokenRequired] = useState(false);
  const [dbSubTab, setDbSubTab] = useState<"ops" | "storage" | "spaces" | "ledgers">("ops");

  // Settings state
  const [settings, setSettings] = useState<AdminSettingItem[]>([]);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [revealedSecrets, setRevealedSecrets] = useState<Record<string, boolean>>({});
  const [embeddingDrift, setEmbeddingDrift] = useState<{
    active_model: string;
    drifted_asset_count: number;
    total_assets: number;
  } | null>(null);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);

  // Live OpenRouter models & inline API key test state
  const [liveModels, setLiveModels] = useState<OpenRouterCatalogResponse | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [testingKey, setTestingKey] = useState(false);
  const [keyTestResult, setKeyTestResult] = useState<OpenRouterKeyTestResult | null>(null);

  // Diagnostics results
  const [connResult, setConnResult] = useState<{
    postgres: Record<string, unknown>;
    neo4j: Record<string, unknown>;
    openrouter: Record<string, unknown>;
  } | null>(null);
  const [statusBanner, setStatusBanner] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // Spaces manager state
  const [newSpaceName, setNewSpaceName] = useState("");
  const [newSpaceFacility, setNewSpaceFacility] = useState("Eigenia Lab");
  const [newSpaceDesc, setNewSpaceDesc] = useState("");

  // File storage browser state
  const [files, setFiles] = useState<StoredFileRecord[]>([]);
  const [filesScopeAll, setFilesScopeAll] = useState(false);
  const [uploadCategory, setUploadCategory] = useState("equipment_photo");

  // Audit & Usage state
  const [auditEntries, setAuditEntries] = useState<
    { id: string; key: string; old_preview: string; new_preview: string; source_ip: string; changed_at: string }[]
  >([]);
  const [usageEntries, setUsageEntries] = useState<
    { id: string; operation: string; model: string; latency_ms: number; confidence: number; created_at: string }[]
  >([]);

  const loadSettings = useCallback(async () => {
    try {
      const resp = await fetchAdminSettings();
      const loadedSettings = Array.isArray(resp?.settings) ? resp.settings : [];
      setSettings(loadedSettings);
      setAdminTokenRequired(Boolean(resp?.admin_token_required));
      setStorageStats(resp?.storage ?? null);
      setEmbeddingDrift(resp?.embedding_drift ?? null);
      const nextDraft: Record<string, string> = {};
      for (const item of loadedSettings) {
        nextDraft[item.key] = item.is_secret ? "" : String(item.value ?? "");
      }
      setDraftValues(nextDraft);
    } catch (err) {
      setStatusBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to load admin settings",
      });
    }
  }, []);

  const loadFiles = useCallback(async () => {
    try {
      const resp = await listStoredFiles(filesScopeAll ? undefined : activeSpaceId || undefined);
      setFiles(Array.isArray(resp?.files) ? resp.files : []);
      setStorageStats(resp?.stats ?? null);
    } catch (err) {
      setStatusBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to load PG18 stored files",
      });
    }
  }, [activeSpaceId, filesScopeAll]);

  const loadLedgers = useCallback(async () => {
    try {
      const [auditResp, usageResp] = await Promise.all([fetchAdminAudit(), fetchVisionUsage()]);
      setAuditEntries(Array.isArray(auditResp?.entries) ? auditResp.entries : []);
      setUsageEntries(Array.isArray(usageResp?.entries) ? usageResp.entries : []);
    } catch {
      // Non-fatal on initial load
    }
  }, []);

  const loadModelCatalog = useCallback(async (forceRefresh = false) => {
    setCatalogLoading(true);
    try {
      const resp = await refreshOpenRouterModels(forceRefresh);
      setLiveModels(resp);
    } catch {
      // Non-fatal on initial background fetch
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadLedgers();
    void loadModelCatalog(false);
  }, [loadSettings, loadLedgers, loadModelCatalog]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  const groupedSettings = useMemo(() => {
    const groups: Record<string, AdminSettingItem[]> = {};
    for (const item of settings) {
      const cat = item.category || "general";
      if (section === "ai" && !["vision", "spatial", "general"].includes(cat)) continue;
      if (section === "databases" && !["neo4j", "storage"].includes(cat)) continue;
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(item);
    }
    return groups;
  }, [settings, section]);

  const runAction = async (key: string, fn: () => Promise<void>) => {
    setBusyAction(key);
    setStatusBanner(null);
    try {
      await fn();
    } catch (err) {
      setStatusBanner({
        kind: "error",
        text: err instanceof Error ? err.message : `Action ${key} failed`,
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveSettings = () =>
    runAction("save-settings", async () => {
      const payload: Record<string, string> = {};
      for (const item of settings) {
        const val = draftValues[item.key] ?? "";
        if (item.is_secret) {
          if (val.trim()) payload[item.key] = val.trim();
        } else if (val !== item.value) {
          payload[item.key] = val;
        }
      }
      if (Object.keys(payload).length === 0) {
        setStatusBanner({ kind: "ok", text: "No modified settings to save." });
        return;
      }
      const resp = await saveAdminSettings(payload, adminToken);
      setStatusBanner({
        kind: "ok",
        text: `Persisted ${resp.updated_count} setting(s) to PostgreSQL 18 (Fernet-encrypted secrets active).`,
      });
      await Promise.all([loadSettings(), loadLedgers()]);
      onSettingsChanged();
    });

  const handleRefreshModels = (forceRefresh = true) =>
    runAction("refresh-models", async () => {
      const resp = await refreshOpenRouterModels(forceRefresh);
      setLiveModels(resp);
      setStatusBanner({
        kind: "ok",
        text: `Loaded ${resp.count} OpenRouter models (${resp.source}).`,
      });
    });

  const handleTestOpenRouterKey = async () => {
    setTestingKey(true);
    try {
      const draftKey = draftValues["openrouter_api_key"]?.trim() || undefined;
      const draftBaseUrl = draftValues["openrouter_base_url"]?.trim() || undefined;
      const res = await testOpenRouterKey({
        api_key: draftKey,
        base_url: draftBaseUrl,
      });
      setKeyTestResult(res);
    } catch (err) {
      setKeyTestResult({
        ok: false,
        status: "error",
        http_status: null,
        latency_ms: 0,
        key_source: draftValues["openrouter_api_key"]?.trim() ? "draft" : "saved",
        error: err instanceof Error ? err.message : "Failed to reach OpenRouter key verification endpoint",
      });
    } finally {
      setTestingKey(false);
    }
  };

  const handleTestConnections = () =>
    runAction("test-connections", async () => {
      const resp = await testAllConnections();
      setConnResult(resp);
      setStatusBanner({
        kind: "ok",
        text: `Diagnostics complete — PG18: ${String(resp.postgres.status ?? "ok")}, Neo4j: ${String(
          resp.neo4j.status ?? "unknown"
        )}, OpenRouter: ${String(resp.openrouter.status ?? "unknown")}.`,
      });
    });

  const handleReconcileNeo4j = () =>
    runAction("reconcile-neo4j", async () => {
      const resp = await reconcileNeo4j(adminToken);
      setStatusBanner({
        kind: "ok",
        text: `Neo4j reconciled from PostgreSQL 18 (${JSON.stringify(resp)}).`,
      });
    });

  const handleReindexPgvector = () =>
    runAction("reindex-pgvector", async () => {
      const resp = await reindexEmbeddings(adminToken);
      setStatusBanner({
        kind: "ok",
        text: `Re-indexed ${resp.reindexed_count} assets using embedding model ${resp.embedding_model}.`,
      });
      await loadSettings();
    });

  const handleArchiveSnapshot = () =>
    runAction("archive-snapshot", async () => {
      if (!activeSpaceId) throw new Error("Select an active space before archiving a snapshot.");
      const resp = await archiveTwinSnapshot(activeSpaceId);
      setStorageStats(resp.storage);
      setStatusBanner({
        kind: "ok",
        text: `Archived ${resp.archived_files.length} twin snapshot artifact(s) into PostgreSQL 18.`,
      });
      await loadFiles();
    });

  const handleScrubStorage = () =>
    runAction("scrub-storage", async () => {
      const resp = await scrubStorage(adminToken);
      setStorageStats(resp.stats);
      setStatusBanner({
        kind: "ok",
        text: `SHA-256 scrub verified ${resp.verified_blobs} blobs (${resp.corrupted_blobs} corrupted, ${resp.pruned_orphans} orphans pruned).`,
      });
      await loadFiles();
    });

  const handleCreateSpace = () =>
    runAction("create-space", async () => {
      if (!newSpaceName.trim()) throw new Error("Space name is required.");
      const created = await createSpace({
        name: newSpaceName.trim(),
        facility: newSpaceFacility.trim() || "Eigenia Facility",
        description: newSpaceDesc.trim(),
      });
      setNewSpaceName("");
      setNewSpaceDesc("");
      setStatusBanner({ kind: "ok", text: `Created space "${created.name}".` });
      onSpacesChanged();
      onSelectSpace(created.id);
    });

  const handleDeleteSpace = (space: SpaceRecord) =>
    runAction(`delete-space-${space.id}`, async () => {
      const resp = await deleteSpace(space.id);
      setStatusBanner({ kind: "ok", text: `Deleted space "${space.name}".` });
      onSpacesChanged();
      if (resp.active_space_id) onSelectSpace(resp.active_space_id);
    });

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await runAction("upload-file", async () => {
      const resp = await uploadStoredFile({
        file,
        category: uploadCategory,
        spaceId: activeSpaceId || undefined,
      });
      setStorageStats(resp.stats);
      setStatusBanner({
        kind: "ok",
        text: `Stored "${resp.file.filename}" (${formatBytes(resp.file.size_bytes)}${
          resp.file.deduplicated ? ", deduplicated" : ""
        }).`,
      });
      await loadFiles();
    });
    e.target.value = "";
  };

  const handleDeleteFile = (fileId: string, filename: string) =>
    runAction(`delete-file-${fileId}`, async () => {
      await deleteStoredFile(fileId, adminToken);
      setStatusBanner({ kind: "ok", text: `Removed "${filename}" from PostgreSQL 18 storage.` });
      await loadFiles();
    });

  const dedupPct = useMemo(() => {
    if (!storageStats || storageStats.logical_bytes <= 0) return 0;
    return Math.round((storageStats.dedup_savings_bytes / storageStats.logical_bytes) * 100);
  }, [storageStats]);

  const defaultTabsValue = section === "databases" ? "ops" : "settings";

  return (
    <div className="flex flex-col gap-4">
      {/* Header & Admin Guard */}
      <InteractiveSurface
        accent={section === "ai" ? "orange" : "sky"}
        title={
          section === "ai"
            ? "AI & OpenRouter Model Configuration"
            : section === "databases"
              ? "PostgreSQL 18 Storage, Neo4j Knowledge Graph & System Diagnostics"
              : "Kaizen PostgreSQL 18 Platform Admin & Content-Addressed Storage"
        }
        subtitle={
          section === "ai"
            ? "Fernet-encrypted OpenRouter API key, live 500+ model catalog picker, Vision/Research defaults, and usage ledger."
            : "PostgreSQL 18 SHA-256 deduplicated blobs, pgvector embedding index, Neo4j parity, and audit log."
        }
        headerRight={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={adminTokenRequired ? "amber" : "sky"}>
              <ShieldCheck className="h-3 w-3" />
              {adminTokenRequired ? "X-Admin-Token Enforced" : "Local Admin Open"}
            </Badge>
            <div className="flex items-center gap-1.5">
              <KeyRound className="h-3.5 w-3.5 text-eigenia-muted" />
              <Input
                type="password"
                placeholder="Optional X-Admin-Token"
                value={adminToken}
                onChange={(e) => setAdminToken(e.target.value)}
                className="w-44 font-mono text-[11px]"
              />
            </div>
          </div>
        }
      >
        {section === "databases" && (
          <SegmentedTabs
            value={dbSubTab}
            onValueChange={(next) => setDbSubTab(next as "ops" | "storage" | "spaces" | "ledgers")}
            tabs={[
              {
                id: "ops",
                label: "Diagnostics & Sync",
                icon: <Activity className="h-3.5 w-3.5" />,
                alertTone: embeddingDrift && embeddingDrift.drifted_asset_count > 0 ? "warning" : null,
              },
              {
                id: "storage",
                label: "PG18 File Storage",
                icon: <HardDrive className="h-3.5 w-3.5" />,
                count: storageStats?.file_count ?? files.length,
              },
              {
                id: "spaces",
                label: "Managed Spaces",
                icon: <Layers className="h-3.5 w-3.5" />,
                count: spaces.length,
              },
              {
                id: "ledgers",
                label: "Audit & DB Config",
                icon: <FileText className="h-3.5 w-3.5" />,
                count: auditEntries.length,
              },
            ]}
          />
        )}
      </InteractiveSurface>

      {statusBanner && (
        <div
          className={`flex items-center justify-between rounded-md border px-3 py-2 font-mono text-xs ${
            statusBanner.kind === "ok"
              ? "border-eigenia-sky/40 bg-eigenia-sky/10 text-eigenia-sky"
              : "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault"
          }`}
        >
          <span>{statusBanner.text}</span>
          <button
            type="button"
            onClick={() => setStatusBanner(null)}
            className="ml-3 text-[10px] uppercase opacity-75 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      <Tabs
        value={section === "all" ? undefined : section === "ai" ? "settings" : dbSubTab}
        defaultValue={defaultTabsValue}
        className="w-full"
      >
        {section === "all" && (
          <TabsList className="flex h-auto flex-wrap">
            <TabsTrigger value="settings">
              <KeyRound className="h-3.5 w-3.5" />
              API Keys & Settings
            </TabsTrigger>
            <TabsTrigger value="ops">
              <Activity className="h-3.5 w-3.5" />
              Diagnostics & Sync
              {embeddingDrift && embeddingDrift.drifted_asset_count > 0 && (
                <Badge variant="amber" className="ml-1 px-1 py-0 text-[9px]">
                  {embeddingDrift.drifted_asset_count} drift
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="spaces">
              <Layers className="h-3.5 w-3.5" />
              Spaces ({spaces.length})
            </TabsTrigger>
            <TabsTrigger value="storage">
              <HardDrive className="h-3.5 w-3.5" />
              PG18 File Storage ({storageStats?.file_count ?? files.length})
            </TabsTrigger>
            <TabsTrigger value="ledgers">
              <FileText className="h-3.5 w-3.5" />
              Audit & Usage
            </TabsTrigger>
          </TabsList>
        )}

        {/* TAB 1: API KEYS & SETTINGS */}
        <TabsContent value="settings" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-surface p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={busyAction !== null} onClick={handleSaveSettings}>
                {busyAction === "save-settings" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save Encrypted Settings
              </Button>
              <Button variant="sky" disabled={busyAction !== null} onClick={() => void handleRefreshModels(true)}>
                {busyAction === "refresh-models" || catalogLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Refresh Live OpenRouter Models
              </Button>
            </div>
            <Button variant="ghost" size="sm" onClick={loadSettings}>
              <RefreshCw className="h-3.5 w-3.5" />
              Reload
            </Button>
          </div>

          {liveModels && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-shell px-3.5 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-eigenia-orange" />
                <span className="text-xs font-semibold text-white">OpenRouter Catalog</span>
                <Badge variant={liveModels.source === "openrouter-live" ? "sky" : "amber"}>
                  {liveModels.source}
                </Badge>
                <Badge variant="neutral" className="tabular-nums">
                  {liveModels.count} models
                </Badge>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
                <Badge variant="default" className="tabular-nums">
                  Vision: {liveModels.category_counts?.vision ?? liveModels.models.filter((m) => m.categories?.includes("vision")).length}
                </Badge>
                <Badge variant="sky" className="tabular-nums">
                  Web Research: {liveModels.category_counts?.web_research ?? liveModels.models.filter((m) => m.categories?.includes("web_research")).length}
                </Badge>
                <Badge variant="amber" className="tabular-nums">
                  Reasoning: {liveModels.category_counts?.reasoning ?? liveModels.models.filter((m) => m.categories?.includes("reasoning")).length}
                </Badge>
                <Badge variant="neutral" className="tabular-nums">
                  Embedding: {liveModels.category_counts?.embedding ?? liveModels.models.filter((m) => m.categories?.includes("embedding")).length}
                </Badge>
                <Badge
                  variant="sky"
                  className="border-emerald-500/40 bg-emerald-500/15 tabular-nums text-emerald-400"
                >
                  Free: {liveModels.category_counts?.free ?? liveModels.models.filter((m) => m.pricing?.is_free).length}
                </Badge>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {Object.entries(groupedSettings).map(([category, items]) => (
              <Card key={category}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span>{category} Configuration</span>
                    <Badge variant="neutral">{items.length} keys</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {items.map((item) => {
                    const revealed = Boolean(revealedSecrets[item.key]);
                    const pickerCategory = OPENROUTER_MODEL_SETTING_CATEGORIES[item.key];
                    const isOpenRouterKey = item.key === "openrouter_api_key";

                    return (
                      <div key={item.key} className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <label className="font-mono text-[11px] font-medium text-white">
                            {item.key}
                          </label>
                          <div className="flex items-center gap-1">
                            {item.is_secret && (
                              <Badge variant={item.is_set ? "sky" : "amber"} className="text-[9px]">
                                {item.is_set ? "Fernet Set" : "Unset"}
                              </Badge>
                            )}
                            {item.persisted && (
                              <Badge variant="neutral" className="text-[9px]">
                                PG18
                              </Badge>
                            )}
                          </div>
                        </div>

                        {pickerCategory ? (
                          <OpenRouterModelPicker
                            value={draftValues[item.key] ?? ""}
                            onChange={(modelId) =>
                              setDraftValues((prev) => ({ ...prev, [item.key]: modelId }))
                            }
                            models={liveModels?.models ?? []}
                            loading={busyAction === "refresh-models" || catalogLoading}
                            defaultCategory={pickerCategory}
                            onRefreshModels={() => void handleRefreshModels(true)}
                            placeholder={`Select ${pickerCategory.replace("_", " ")} model...`}
                          />
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <Input
                              type={item.is_secret && !revealed ? "password" : "text"}
                              value={draftValues[item.key] ?? ""}
                              placeholder={
                                item.is_secret
                                  ? item.is_set
                                    ? `Masked (${item.value}) — type to rotate`
                                    : "Enter secret value..."
                                  : ""
                              }
                              onChange={(e) =>
                                setDraftValues((prev) => ({ ...prev, [item.key]: e.target.value }))
                              }
                              className="font-mono text-[11px]"
                            />
                            {item.is_secret && (
                              <Button
                                type="button"
                                size="icon"
                                variant="secondary"
                                onClick={() =>
                                  setRevealedSecrets((prev) => ({
                                    ...prev,
                                    [item.key]: !prev[item.key],
                                  }))
                                }
                              >
                                {revealed ? (
                                  <EyeOff className="h-3.5 w-3.5" />
                                ) : (
                                  <Eye className="h-3.5 w-3.5" />
                                )}
                              </Button>
                            )}
                            {isOpenRouterKey && (
                              <Button
                                type="button"
                                size="sm"
                                variant="sky"
                                disabled={testingKey}
                                onClick={() => void handleTestOpenRouterKey()}
                                className="shrink-0"
                              >
                                {testingKey ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Zap className="h-3.5 w-3.5" />
                                )}
                                {testingKey ? "Testing..." : "Test Key"}
                              </Button>
                            )}
                          </div>
                        )}

                        {isOpenRouterKey && keyTestResult && (
                          <div
                            className={`rounded-md border p-2.5 text-xs ${
                              keyTestResult.ok
                                ? "border-emerald-500/40 bg-emerald-500/10"
                                : "border-eigenia-fault/45 bg-eigenia-fault/15"
                            }`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-1.5">
                              <div className="flex flex-wrap items-center gap-1.5">
                                {keyTestResult.ok ? (
                                  <Badge
                                    variant="sky"
                                    className="border-emerald-500/45 bg-emerald-500/20 tabular-nums text-emerald-400"
                                  >
                                    <CheckCircle2 className="h-3 w-3" />
                                    KEY VALID · {Math.round(keyTestResult.latency_ms)} ms
                                  </Badge>
                                ) : (
                                  <Badge variant="fault" className="tabular-nums">
                                    <XCircle className="h-3 w-3" />
                                    {keyTestResult.http_status
                                      ? `KEY INVALID (${keyTestResult.http_status})`
                                      : keyTestResult.status === "unconfigured"
                                        ? "NO KEY SET"
                                        : "KEY ERROR"}
                                  </Badge>
                                )}
                                <Badge variant="neutral" className="text-[9px]">
                                  {keyTestResult.key_source === "draft" ? "Draft Key" : "Saved PG18 Key"}
                                </Badge>
                                {keyTestResult.ok && (
                                  <Badge
                                    variant={keyTestResult.is_free_tier ? "amber" : "sky"}
                                    className="text-[9px]"
                                  >
                                    {keyTestResult.is_free_tier ? "Free Tier" : "Paid"}
                                  </Badge>
                                )}
                              </div>
                              {keyTestResult.label && (
                                <span className="font-mono text-[10px] text-white">
                                  {keyTestResult.label}
                                </span>
                              )}
                            </div>

                            {keyTestResult.ok ? (
                              <div className="mt-2 grid grid-cols-3 gap-2 rounded bg-eigenia-obsidian/70 px-2.5 py-1.5 font-mono text-[10px]">
                                <div>
                                  <div className="text-eigenia-muted">Usage</div>
                                  <div className="font-semibold tabular-nums text-white">
                                    {keyTestResult.usage_usd !== null &&
                                    keyTestResult.usage_usd !== undefined
                                      ? formatUsdAmount(keyTestResult.usage_usd)
                                      : "$0.00"}
                                  </div>
                                </div>
                                <div>
                                  <div className="text-eigenia-muted">Credit Limit</div>
                                  <div className="font-semibold tabular-nums text-eigenia-sky">
                                    {formatUsdAmount(
                                      keyTestResult.limit_usd ?? keyTestResult.total_credits_usd
                                    )}
                                  </div>
                                </div>
                                <div>
                                  <div className="text-eigenia-muted">Remaining</div>
                                  <div className="font-semibold tabular-nums text-emerald-400">
                                    {formatUsdAmount(keyTestResult.limit_remaining_usd)}
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <div className="mt-1.5 font-mono text-[10px] text-eigenia-fault">
                                {keyTestResult.error || "OpenRouter rejected this API key."}
                              </div>
                            )}
                          </div>
                        )}

                        {item.description && (
                          <p className="text-[10px] text-eigenia-muted">{item.description}</p>
                        )}
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* TAB 2: DIAGNOSTICS & SYNC */}
        <TabsContent value="ops" className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Connectivity Diagnostics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-eigenia-muted">
                  Verify live links across PostgreSQL 18 + pgvector, Neo4j 5 Bolt, and OpenRouter Vision API.
                </p>
                <Button
                  className="w-full"
                  variant="sky"
                  disabled={busyAction !== null}
                  onClick={handleTestConnections}
                >
                  {busyAction === "test-connections" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Activity className="h-3.5 w-3.5" />
                  )}
                  Test All Connections (PG18 + Neo4j + OpenRouter)
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>pgvector Embedding Index</CardTitle>
                  <Badge
                    variant={
                      (embeddingDrift?.drifted_asset_count ?? 0) > 0 ? "amber" : "sky"
                    }
                    className="tabular-nums"
                  >
                    Drift: {embeddingDrift?.drifted_asset_count ?? 0}/{embeddingDrift?.total_assets ?? 0}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="font-mono text-[11px] text-eigenia-muted">
                  Active model: <span className="text-white">{embeddingDrift?.active_model || "fallback"}</span>
                </div>
                <Button
                  className="w-full"
                  disabled={busyAction !== null}
                  onClick={handleReindexPgvector}
                >
                  {busyAction === "reindex-pgvector" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  Re-Index pgvector
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Knowledge Graph & Snapshots</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button
                  className="w-full"
                  variant="secondary"
                  disabled={busyAction !== null}
                  onClick={handleReconcileNeo4j}
                >
                  {busyAction === "reconcile-neo4j" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Database className="h-3.5 w-3.5" />
                  )}
                  Reconcile PG18 → Neo4j
                </Button>
                <Button
                  className="w-full"
                  variant="secondary"
                  disabled={busyAction !== null}
                  onClick={handleArchiveSnapshot}
                >
                  {busyAction === "archive-snapshot" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Archive className="h-3.5 w-3.5" />
                  )}
                  Archive Twin Snapshot to PG18
                </Button>
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={busyAction !== null}
                  onClick={handleScrubStorage}
                >
                  {busyAction === "scrub-storage" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ShieldCheck className="h-3.5 w-3.5" />
                  )}
                  SHA-256 Storage Scrub
                </Button>
              </CardContent>
            </Card>
          </div>

          {connResult && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {(["postgres", "neo4j", "openrouter"] as const).map((svc) => {
                const info = connResult[svc] ?? {};
                const ok = String(info.status) === "connected" || String(info.status) === "ok";
                return (
                  <Card key={svc}>
                    <CardHeader className="flex flex-row items-center justify-between">
                      <CardTitle>{svc.toUpperCase()}</CardTitle>
                      <Badge variant={ok ? "sky" : "fault"}>
                        {String(info.status ?? "unknown")}
                      </Badge>
                    </CardHeader>
                    <CardContent>
                      <pre className="overflow-x-auto rounded bg-eigenia-obsidian p-2 font-mono text-[10px] text-eigenia-muted">
                        {JSON.stringify(info, null, 2)}
                      </pre>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* TAB 3: MULTI-SPACE MANAGER */}
        <TabsContent value="spaces" className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Managed Facility Spaces</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {(Array.isArray(spaces) ? spaces : []).map((sp) => {
                const isActive = sp.id === activeSpaceId;
                const wallCount = Array.isArray(sp.walls) ? sp.walls.length : 0;
                const areaM2 = typeof sp.metrics?.area_m2 === "number" ? sp.metrics.area_m2 : null;
                return (
                  <div
                    key={sp.id}
                    className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 ${
                      isActive
                        ? "border-eigenia-orange bg-eigenia-orange/10"
                        : "border-white/10 bg-eigenia-obsidian"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-white">{sp.name}</span>
                        {isActive && <Badge variant="default">Active</Badge>}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] text-eigenia-muted">
                        {sp.facility} · {wallCount} walls ·{" "}
                        {areaM2 !== null ? `${areaM2.toFixed(1)} m²` : "unmeasured"}
                      </div>
                      {sp.description && (
                        <div className="mt-0.5 text-[11px] text-eigenia-muted">{sp.description}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        size="sm"
                        variant={isActive ? "secondary" : "sky"}
                        disabled={isActive}
                        onClick={() => onSelectSpace(sp.id)}
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        {isActive ? "Selected" : "Switch"}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={spaces.length <= 1 || busyAction !== null}
                        onClick={() => handleDeleteSpace(sp)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FolderPlus className="h-3.5 w-3.5 text-eigenia-orange" />
                Create New Space
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">Space Name</label>
                <Input
                  placeholder="e.g. Substation Bay 4"
                  value={newSpaceName}
                  onChange={(e) => setNewSpaceName(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">Facility</label>
                <Input
                  placeholder="e.g. Eigenia Robotics Lab"
                  value={newSpaceFacility}
                  onChange={(e) => setNewSpaceFacility(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-eigenia-muted">Description</label>
                <Input
                  placeholder="Optional zone notes"
                  value={newSpaceDesc}
                  onChange={(e) => setNewSpaceDesc(e.target.value)}
                />
              </div>
              <Button
                className="w-full"
                disabled={busyAction !== null || !newSpaceName.trim()}
                onClick={handleCreateSpace}
              >
                {busyAction === "create-space" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FolderPlus className="h-3.5 w-3.5" />
                )}
                Create Space
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 4: PG18 FILE STORAGE BROWSER */}
        <TabsContent value="storage" className="space-y-4">
          {storageStats && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Card>
                <CardContent className="p-3">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">Stored Files</div>
                  <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-white">
                    {storageStats.file_count}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-3">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">Unique Blobs</div>
                  <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-eigenia-sky">
                    {storageStats.unique_blob_count}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-3">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">Physical Size</div>
                  <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-white">
                    {formatBytes(storageStats.physical_bytes)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-3">
                  <div className="font-mono text-[10px] uppercase text-eigenia-muted">Dedup Savings</div>
                  <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-eigenia-orange">
                    {formatBytes(storageStats.dedup_savings_bytes)} ({dedupPct}%)
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          <Card>
            <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <CardTitle>PostgreSQL 18 Content-Addressed Blobs (SHA-256)</CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant={filesScopeAll ? "secondary" : "sky"}
                  onClick={() => setFilesScopeAll(false)}
                >
                  Active Space
                </Button>
                <Button
                  size="sm"
                  variant={filesScopeAll ? "sky" : "secondary"}
                  onClick={() => setFilesScopeAll(true)}
                >
                  All Spaces
                </Button>
                <select
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                  className="h-8 rounded-md border border-white/15 bg-eigenia-obsidian px-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-eigenia-orange"
                >
                  <option value="equipment_photo">equipment_photo</option>
                  <option value="datasheet">datasheet</option>
                  <option value="twin_snapshot">twin_snapshot</option>
                  <option value="robot_bom">robot_bom</option>
                  <option value="other">other</option>
                </select>
                <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md bg-eigenia-orange px-3 text-xs font-medium text-white hover:bg-eigenia-orange/90">
                  <Upload className="h-3.5 w-3.5" />
                  Upload Blob
                  <input type="file" className="hidden" onChange={handleUploadFile} />
                </label>
              </div>
            </CardHeader>
            <CardContent>
              {files.length === 0 ? (
                <div className="rounded-md border border-dashed border-white/10 bg-eigenia-obsidian/60 p-6 text-center text-xs text-eigenia-muted">
                  No files stored in this scope yet. Upload a nameplate image, datasheet, or archive a twin snapshot.
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {files.map((f) => {
                    const contentType = String(f.content_type || "");
                    const isImage = contentType.startsWith("image/");
                    const href = getFileUrl(String(f.url || ""));
                    return (
                      <div
                        key={f.id}
                        className="flex flex-col justify-between gap-2 rounded-md border border-white/10 bg-eigenia-obsidian p-3"
                      >
                        <div className="space-y-2">
                          {isImage && (
                            <a href={href} target="_blank" rel="noreferrer" className="block overflow-hidden rounded border border-white/10 bg-eigenia-shell">
                              <img
                                src={href}
                                alt={f.filename}
                                className="h-28 w-full object-cover"
                              />
                            </a>
                          )}
                          <div className="flex items-start justify-between gap-2">
                            <a
                              href={href}
                              target="_blank"
                              rel="noreferrer"
                              className="truncate text-xs font-semibold text-white hover:text-eigenia-sky"
                            >
                              {f.filename}
                            </a>
                            <Badge variant="neutral" className="shrink-0 text-[9px]">
                              {f.category}
                            </Badge>
                          </div>
                          <div className="font-mono text-[10px] text-eigenia-muted">
                            {formatBytes(Number(f.size_bytes ?? 0))} · {contentType || "application/octet-stream"}
                          </div>
                          <div className="truncate font-mono text-[9px] text-eigenia-muted">
                            sha256: {String(f.sha256 || "").slice(0, 16)}…
                          </div>
                        </div>
                        <div className="flex items-center justify-between border-t border-white/10 pt-2">
                          <span className="font-mono text-[9px] text-eigenia-muted">
                            {new Date(f.created_at).toLocaleString()}
                          </span>
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-6 px-2 text-[10px]"
                            disabled={busyAction !== null}
                            onClick={() => handleDeleteFile(f.id, f.filename)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 5: AUDIT & VISION USAGE LEDGER */}
        <TabsContent value="ledgers" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Config Audit Log ({auditEntries.length})</CardTitle>
              <Button size="sm" variant="ghost" onClick={loadLedgers}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </CardHeader>
            <CardContent className="max-h-96 space-y-2 overflow-y-auto">
              {auditEntries.length === 0 ? (
                <div className="text-xs text-eigenia-muted">No configuration mutations logged yet.</div>
              ) : (
                auditEntries.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded border border-white/10 bg-eigenia-obsidian p-2.5 font-mono text-[10px]"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-eigenia-orange">{entry.key}</span>
                      <span className="text-eigenia-muted">{entry.source_ip}</span>
                    </div>
                    <div className="mt-1 text-eigenia-ink">
                      {entry.old_preview || "<empty>"} → {entry.new_preview || "<empty>"}
                    </div>
                    <div className="mt-0.5 text-[9px] text-eigenia-muted">
                      {new Date(entry.changed_at).toLocaleString()}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Vision & Research Usage Ledger ({usageEntries.length})</CardTitle>
              <Badge variant="sky">Telemetry</Badge>
            </CardHeader>
            <CardContent className="max-h-96 space-y-2 overflow-y-auto">
              {usageEntries.length === 0 ? (
                <div className="text-xs text-eigenia-muted">No OpenRouter vision or research calls logged yet.</div>
              ) : (
                usageEntries.map((u) => (
                  <div
                    key={u.id}
                    className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian p-2.5 font-mono text-[10px]"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-white">{u.model}</div>
                      <div className="text-eigenia-muted">
                        {u.operation} · {new Date(u.created_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <Badge variant="neutral" className="tabular-nums">
                        {Math.round(u.latency_ms)}ms
                      </Badge>
                      <Badge variant="sky" className="tabular-nums">
                        {Math.round(u.confidence * 100)}%
                      </Badge>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
