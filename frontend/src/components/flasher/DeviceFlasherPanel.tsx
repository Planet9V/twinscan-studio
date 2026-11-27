"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Cpu,
  HardDrive,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Usb,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createFlashJob,
  getBoardOsCatalog,
  listFlashPlatforms,
  listRemovableDevices,
  previewHeadlessProvision,
  type FlashJob,
  type FlashPlatform,
  type OsCatalogImage,
  type RemovableDevice,
} from "@/lib/flasherApi";
import { cn } from "@/lib/utils";

export function DeviceFlasherPanel(): React.JSX.Element {
  const [platforms, setPlatforms] = useState<FlashPlatform[]>([]);
  const [selectedBoard, setSelectedBoard] = useState<string>("pi5");
  const [catalogSource, setCatalogSource] = useState<string>("");
  const [images, setImages] = useState<OsCatalogImage[]>([]);
  const [selectedImage, setSelectedImage] = useState<OsCatalogImage | null>(null);
  const [loadingImages, setLoadingImages] = useState(false);

  const [hostOnline, setHostOnline] = useState(false);
  const [hostTools, setHostTools] = useState<Record<string, boolean>>({});
  const [devices, setDevices] = useState<RemovableDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [confirmToken, setConfirmToken] = useState<string>("");

  // Headless Pi provisioning
  const [hostname, setHostname] = useState("eigenia-pi5");
  const [username, setUsername] = useState("pi");
  const [wifiSsid, setWifiSsid] = useState("");
  const [wifiPassword, setWifiPassword] = useState("");
  const [role, setRole] = useState("overwatch_cam_node");
  const [scriptPreview, setScriptPreview] = useState<string | null>(null);

  const [busyFlash, setBusyFlash] = useState(false);
  const [activeJob, setActiveJob] = useState<FlashJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshDevices = useCallback(async () => {
    try {
      const inv = await listRemovableDevices();
      setHostOnline(inv.host_bridge_online);
      setHostTools(inv.host?.tools ?? {});
      setDevices(inv.devices);
      if (inv.devices.length > 0 && !inv.devices.some((d) => d.device_id === selectedDeviceId)) {
        setSelectedDeviceId(inv.devices[0].device_id);
      }
    } catch {
      // ignore transient poll error
    }
  }, [selectedDeviceId]);

  useEffect(() => {
    void listFlashPlatforms().then(setPlatforms).catch(() => {});
    void refreshDevices();
    const t = window.setInterval(() => void refreshDevices(), 4000);
    return () => window.clearInterval(t);
  }, [refreshDevices]);

  useEffect(() => {
    setLoadingImages(true);
    setSelectedImage(null);
    void getBoardOsCatalog(selectedBoard)
      .then((res) => {
        setCatalogSource(res.source);
        setImages(res.images);
        const rec = res.images.find((i) => i.recommended) ?? res.images[0] ?? null;
        setSelectedImage(rec);
      })
      .catch(() => {})
      .finally(() => setLoadingImages(false));
  }, [selectedBoard]);

  const activePlatform = platforms.find((p) => p.id === selectedBoard);
  const activeDevice = devices.find((d) => d.device_id === selectedDeviceId) ?? null;

  const handlePreviewScript = async () => {
    setError(null);
    try {
      const res = await previewHeadlessProvision({
        hostname,
        username,
        wifi_ssid: wifiSsid || undefined,
        wifi_password: wifiPassword || undefined,
        role,
        twinscan_url: typeof window !== "undefined" ? window.location.origin.replace(":3000", ":8000") : undefined,
      });
      setScriptPreview(res.firstrun_sh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Provisioning preview failed.");
    }
  };

  const handleQueueFlash = async () => {
    if (!selectedImage || !activeDevice) return;
    setBusyFlash(true);
    setError(null);
    try {
      const job = await createFlashJob({
        board_id: selectedBoard,
        image_url: selectedImage.url || "custom",
        image_name: selectedImage.name,
        device_id: activeDevice.device_id,
        confirmation_token: confirmToken.trim(),
        provision: activePlatform?.supports_headless_provision
          ? {
              hostname,
              username,
              wifi_ssid: wifiSsid || undefined,
              wifi_password: wifiPassword || undefined,
              role,
            }
          : undefined,
      });
      setActiveJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue flash job.");
    } finally {
      setBusyFlash(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4 lg:p-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-slate-950/95 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md border border-cyan-500/50 bg-cyan-500/15">
            <HardDrive className="h-4 w-4 text-cyan-400" />
          </div>
          <div>
            <h1 className="font-mono text-sm font-bold uppercase tracking-wider text-white">
              Universal Hardware Flasher &amp; Provisioner
            </h1>
            <p className="text-xs text-slate-400">
              Flash Raspberry Pi 3 / 4 / 5, Arduino, ESP32, Pi Pico &amp; micro:bit with Poka-Yoke removable-media safety.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={hostOnline ? "sky" : "neutral"} className="font-mono text-[10px]">
            HOST BRIDGE: {hostOnline ? "ONLINE" : "STANDBY"}
          </Badge>
          {hostTools.rpi_imager && (
            <Badge variant="neutral" className="border-emerald-500/40 font-mono text-[10px] text-emerald-300">
              rpi-imager ready
            </Badge>
          )}
          <Button size="sm" variant="outline" onClick={() => void refreshDevices()} className="cursor-pointer">
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Scan USB Drives
          </Button>
        </div>
      </div>

      {/* Step 1: Select Board */}
      <Card className="border-white/10 bg-slate-950/90">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs uppercase tracking-wider text-cyan-300">
            <Cpu className="h-4 w-4" /> Step 1 · Select Target Hardware Platform
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {platforms.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setSelectedBoard(p.id)}
              className={cn(
                "cursor-pointer rounded-lg border p-3 text-left transition",
                selectedBoard === p.id
                  ? "border-cyan-400 bg-cyan-950/40 text-white"
                  : "border-white/10 bg-slate-900/60 text-slate-300 hover:border-white/25"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold">{p.name}</span>
                <Badge variant="neutral" className="font-mono text-[9px]">
                  {p.recommended_storage_gb}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">{p.description}</p>
            </button>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-12">
        {/* Step 2: OS / Firmware Catalog */}
        <Card className="border-white/10 bg-slate-950/90 lg:col-span-6">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-cyan-300">
              Step 2 · Choose OS / Firmware ({images.length})
            </CardTitle>
            {catalogSource && (
              <Badge variant="neutral" className="font-mono text-[10px]">
                {catalogSource}
              </Badge>
            )}
          </CardHeader>
          <CardContent className="max-h-[340px] space-y-2 overflow-y-auto">
            {loadingImages ? (
              <div className="flex items-center gap-2 py-8 text-xs text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin text-cyan-400" /> Loading official OS catalog…
              </div>
            ) : (
              images.map((img) => (
                <button
                  key={img.id}
                  type="button"
                  onClick={() => setSelectedImage(img)}
                  className={cn(
                    "w-full cursor-pointer rounded-md border p-2.5 text-left transition",
                    selectedImage?.id === img.id
                      ? "border-cyan-400 bg-cyan-950/35"
                      : "border-white/10 bg-slate-900/60 hover:border-white/25"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-white">{img.name}</span>
                    <div className="flex items-center gap-1.5">
                      {img.recommended && (
                        <Badge variant="sky" className="font-mono text-[9px]">
                          RECOMMENDED
                        </Badge>
                      )}
                      {img.download_mb && (
                        <span className="font-mono text-[10px] text-slate-400 tabular-nums">
                          {img.download_mb} MB
                        </span>
                      )}
                    </div>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">{img.description}</p>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Step 3 & 4: Headless Provisioning + Removable Target Confirm */}
        <div className="space-y-4 lg:col-span-6">
          {activePlatform?.supports_headless_provision && (
            <Card className="border-white/10 bg-slate-950/90">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs uppercase tracking-wider text-cyan-300">
                  Step 3 · Headless Boot Provisioning (SSH + Wi-Fi + TwinScan Role)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-2.5">
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">Hostname</label>
                    <Input value={hostname} onChange={(e) => setHostname(e.target.value)} className="h-8 font-mono text-xs" />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">SSH Username</label>
                    <Input value={username} onChange={(e) => setUsername(e.target.value)} className="h-8 font-mono text-xs" />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">Wi-Fi SSID (optional)</label>
                    <Input value={wifiSsid} onChange={(e) => setWifiSsid(e.target.value)} placeholder="Leave blank for Ethernet" className="h-8 text-xs" />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">Wi-Fi Password</label>
                    <Input type="password" value={wifiPassword} onChange={(e) => setWifiPassword(e.target.value)} className="h-8 text-xs" />
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    className="h-8 rounded-md border border-white/15 bg-slate-900 px-2 font-mono text-xs text-slate-200"
                    aria-label="TwinScan node role"
                  >
                    <option value="overwatch_cam_node">Role: Overwatch LAN Camera Node</option>
                    <option value="ros2_sensor_node">Role: ROS 2 Sensor / LiDAR Node</option>
                    <option value="minimal_ssh">Role: Minimal Headless SSH</option>
                  </select>
                  <Button size="sm" variant="outline" onClick={() => void handlePreviewScript()} className="cursor-pointer">
                    <Terminal className="mr-1.5 h-3.5 w-3.5" /> Preview firstrun.sh
                  </Button>
                </div>
                {scriptPreview && (
                  <pre className="max-h-32 overflow-auto rounded border border-white/10 bg-black/70 p-2 font-mono text-[10px] text-emerald-300">
                    {scriptPreview}
                  </pre>
                )}
              </CardContent>
            </Card>
          )}

          {/* Step 4: Poka-Yoke Removable Target & Confirm */}
          <Card className="border-white/10 bg-slate-950/90">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-xs uppercase tracking-wider text-amber-300">
                <Usb className="h-4 w-4" /> Step 4 · Select Removable Target &amp; Confirm
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {devices.length === 0 ? (
                <div className="rounded-md border border-white/10 bg-slate-900/70 p-3 text-xs text-slate-300">
                  <p className="font-semibold text-white">No removable USB SD cards or serial boards reported yet.</p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    Insert a microSD card or Arduino/ESP32 and run{" "}
                    <code className="rounded bg-black/60 px-1.5 py-0.5 font-mono text-cyan-300">
                      .venv/bin/python -m src.bridge.host_flash_bridge
                    </code>{" "}
                    on your Mac/Windows host (internal system disks like disk0 / C: are permanently blocked).
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {devices.map((d) => (
                    <button
                      key={d.device_id}
                      type="button"
                      onClick={() => setSelectedDeviceId(d.device_id)}
                      className={cn(
                        "flex w-full cursor-pointer items-center justify-between rounded-md border px-3 py-2 text-left text-xs",
                        selectedDeviceId === d.device_id
                          ? "border-amber-400 bg-amber-950/30 text-white"
                          : "border-white/10 bg-slate-900/60 text-slate-300"
                      )}
                    >
                      <div>
                        <div className="font-mono font-bold">
                          {d.device_path} · {d.label}
                        </div>
                        <div className="font-mono text-[10px] text-slate-400">
                          {d.kind} {d.size_gb > 0 ? `· ${d.size_gb} GB Removable` : "· USB Serial"}
                        </div>
                      </div>
                      <ShieldCheck className="h-4 w-4 text-emerald-400" />
                    </button>
                  ))}

                  {activeDevice && (
                    <div className="space-y-2 pt-1">
                      <label className="block text-[11px] text-amber-200">
                        Poka-Yoke Safety: Type <strong className="font-mono">{activeDevice.device_id}</strong> to confirm
                        erasing &amp; flashing removable media:
                      </label>
                      <div className="flex gap-2">
                        <Input
                          value={confirmToken}
                          onChange={(e) => setConfirmToken(e.target.value)}
                          placeholder={`Type ${activeDevice.device_id}`}
                          className="h-8 font-mono text-xs"
                        />
                        <Button
                          size="sm"
                          variant="default"
                          disabled={busyFlash || !selectedImage || confirmToken.trim() !== activeDevice.device_id}
                          onClick={() => void handleQueueFlash()}
                          className="cursor-pointer shrink-0"
                        >
                          {busyFlash ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
                          Queue Flash Job
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 rounded-md border border-red-500/40 bg-red-950/40 px-3 py-2 text-xs text-red-200">
                  <ShieldAlert className="h-4 w-4 shrink-0 text-red-400" />
                  <span>{error}</span>
                </div>
              )}

              {activeJob && (
                <div className="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-200">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                  <span>
                    Job <strong className="font-mono">{activeJob.job_id.slice(0, 8)}</strong> ({activeJob.status}):{" "}
                    {activeJob.image_name} → <strong className="font-mono">{activeJob.target.device_path}</strong>
                  </span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
