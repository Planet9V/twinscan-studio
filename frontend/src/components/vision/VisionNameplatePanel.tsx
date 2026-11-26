"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Bot,
  Camera,
  CheckCircle2,
  Cpu,
  Loader2,
  MapPin,
  ScanBarcode,
  Sparkles,
  Upload,
} from "lucide-react";
import { OpenRouterModelPicker } from "@/components/admin/OpenRouterModelPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  analyzeEquipmentImage,
  getFileUrl,
  pinEquipmentAsset,
  refreshOpenRouterModels,
} from "@/lib/api";
import { snapRobotCameraToVision } from "@/lib/robotApi";
import type { EquipmentVisionResult, OpenRouterModelInfo, VisionModelOption } from "@/lib/types";

interface VisionNameplatePanelProps {
  spaceId: string;
  models: VisionModelOption[];
  defaultModel: string;
  openrouterConfigured: boolean;
  pendingPin: { x: number; y: number; width_m?: number; depth_m?: number } | null;
  onPinUpdated: (pin: { x: number; y: number }) => void;
  onAssetPinned: () => void;
  activeRobotId?: string | null;
}

export function VisionNameplatePanel({
  spaceId,
  models,
  defaultModel,
  openrouterConfigured,
  pendingPin,
  onPinUpdated,
  onAssetPinned,
  activeRobotId,
}: VisionNameplatePanelProps) {
  const [selectedModel, setSelectedModel] = useState(defaultModel || "google/gemini-2.5-flash");
  const [catalogModels, setCatalogModels] = useState<OpenRouterModelInfo[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [consensus, setConsensus] = useState(false);
  const [cameraYawDeg, setCameraYawDeg] = useState(0);
  const [contextHint, setContextHint] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [snappingFpv, setSnappingFpv] = useState(false);
  const [pinning, setPinning] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageFileId, setImageFileId] = useState<string | null>(null);
  const [result, setResult] = useState<EquipmentVisionResult | null>(null);
  const [poseInfo, setPoseInfo] = useState<{ distance_m: number; bearing_deg: number; confidence: number } | null>(
    null
  );

  // Editable placement form state
  const [formState, setFormState] = useState({
    name: "",
    manufacturer: "",
    model_number: "",
    serial_number: "",
    equipment_type: "PLC",
    dexpi_class: "ProgrammableLogicController",
    inferred_cpe_23: "",
    voltage_rating: "",
    asset_tags: "",
    mac_addresses: "",
    x: 0,
    y: 0,
    yaw_deg: 0,
    width_m: 0.75,
    depth_m: 0.75,
    height_m: 1.6,
  });

  const loadCatalog = useCallback(async (forceRefresh = false) => {
    setCatalogLoading(true);
    try {
      const resp = await refreshOpenRouterModels(forceRefresh);
      if (Array.isArray(resp?.models) && resp.models.length > 0) {
        setCatalogModels(resp.models);
      }
    } catch {
      // Fallback cleanly to `models` prop
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog(false);
  }, [loadCatalog]);

  useEffect(() => {
    if (defaultModel) {
      setSelectedModel(defaultModel);
    }
  }, [defaultModel]);

  useEffect(() => {
    if (pendingPin) {
      setFormState((prev) => ({
        ...prev,
        x: Number(pendingPin.x.toFixed(3)),
        y: Number(pendingPin.y.toFixed(3)),
        width_m: pendingPin.width_m ? Number(pendingPin.width_m.toFixed(2)) : prev.width_m,
        depth_m: pendingPin.depth_m ? Number(pendingPin.depth_m.toFixed(2)) : prev.depth_m,
      }));
    }
  }, [pendingPin]);

  const applyVisionResponse = (resp: {
    extraction: EquipmentVisionResult;
    image_file_id: string;
    image_url: string;
    suggested_pose: {
      x: number;
      y: number;
      distance_m: number;
      bearing_deg: number;
      supporting_points: number;
      confidence: number;
    };
  }) => {
    const ext = resp.extraction;
    const pose = resp.suggested_pose ?? {
      x: 0,
      y: 0,
      distance_m: 0,
      bearing_deg: 0,
      supporting_points: 0,
      confidence: 0,
    };
    const safeAssetTags = Array.isArray(ext?.asset_tags) ? ext.asset_tags : [];
    const safeMacs = Array.isArray(ext?.mac_addresses) ? ext.mac_addresses : [];
    setResult(ext);
    setImageFileId(resp.image_file_id || null);
    setImageUrl(resp.image_url ? getFileUrl(resp.image_url) : null);
    setPoseInfo({
      distance_m: Number(pose.distance_m ?? 0),
      bearing_deg: Number(pose.bearing_deg ?? 0),
      confidence: Number(pose.confidence ?? 0),
    });
    onPinUpdated({ x: Number(pose.x ?? 0), y: Number(pose.y ?? 0) });
    setFormState({
      name: ext?.name || "",
      manufacturer: ext?.manufacturer || "",
      model_number: ext?.model_number || "",
      serial_number: ext?.serial_number || "",
      equipment_type: ext?.equipment_type || "PLC",
      dexpi_class: ext?.dexpi_class || "Equipment",
      inferred_cpe_23: ext?.inferred_cpe_23 || "",
      voltage_rating: ext?.voltage_rating || "",
      asset_tags: safeAssetTags.join(", "),
      mac_addresses: safeMacs.join(", "),
      x: Number(Number(pose.x ?? 0).toFixed(3)),
      y: Number(Number(pose.y ?? 0).toFixed(3)),
      yaw_deg: cameraYawDeg,
      width_m: 0.75,
      depth_m: 0.75,
      height_m: 1.6,
    });
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAnalyzing(true);
    setErrorMsg(null);
    try {
      const resp = await analyzeEquipmentImage({
        file,
        model: selectedModel,
        consensus,
        contextHint,
        cameraYawDeg,
      });
      applyVisionResponse(resp);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Vision analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSnapFromPuppyPi = async () => {
    if (!activeRobotId) return;
    setSnappingFpv(true);
    setErrorMsg(null);
    try {
      const resp = await snapRobotCameraToVision(activeRobotId, {
        topic: "/usb_cam/image_raw",
        model: selectedModel,
        consensus,
        contextHint,
        cameraYawDeg,
      });
      applyVisionResponse(resp);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "PuppyPi FPV vision capture failed");
    } finally {
      setSnappingFpv(false);
    }
  };

  const handlePinSubmit = async () => {
    if (!spaceId || !formState.name.trim()) return;
    setPinning(true);
    setErrorMsg(null);
    try {
      await pinEquipmentAsset(spaceId, {
        name: formState.name,
        equipment_type: formState.equipment_type,
        dexpi_class: formState.dexpi_class,
        manufacturer: formState.manufacturer || "Unknown",
        model_number: formState.model_number || "Unknown",
        serial_number: formState.serial_number || null,
        inferred_cpe_23: formState.inferred_cpe_23 || null,
        voltage_rating: formState.voltage_rating || null,
        asset_tags: formState.asset_tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        mac_addresses: formState.mac_addresses
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        barcodes: result?.barcodes ?? [],
        x: Number(formState.x),
        y: Number(formState.y),
        z: 0,
        yaw_deg: Number(formState.yaw_deg),
        width_m: Number(formState.width_m),
        depth_m: Number(formState.depth_m),
        height_m: Number(formState.height_m),
        confidence: result?.confidence ?? 0.9,
        model_used: result?.model_used ?? selectedModel,
        image_file_id: imageFileId,
        image_url: imageUrl,
        raw_notes: result?.raw_notes ?? "",
      });
      onAssetPinned();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to pin asset");
    } finally {
      setPinning(false);
    }
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5 text-eigenia-orange" />
            OpenRouter Vision & Asset Pin
          </CardTitle>
          <Badge variant={openrouterConfigured ? "sky" : "amber"}>
            {openrouterConfigured ? "OpenRouter Live" : "Stage-1 Local"}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3 overflow-y-auto">
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-eigenia-muted">OpenRouter Vision Model</label>
          <OpenRouterModelPicker
            value={selectedModel}
            onChange={setSelectedModel}
            models={
              catalogModels.length > 0
                ? catalogModels
                : Array.isArray(models)
                  ? models
                  : []
            }
            loading={catalogLoading}
            defaultCategory="vision"
            onRefreshModels={() => void loadCatalog(true)}
            compact
          />
        </div>

        <div className="flex items-center justify-between rounded border border-white/10 bg-eigenia-obsidian px-2.5 py-2">
          <div>
            <div className="text-xs font-medium text-white">Dual-Model Consensus</div>
            <div className="text-[10px] text-eigenia-muted">Cross-check Serial & Model via 2nd VLM</div>
          </div>
          <Switch checked={consensus} onCheckedChange={setConsensus} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-eigenia-muted">Camera Yaw (deg)</label>
            <Input
              type="number"
              value={cameraYawDeg}
              onChange={(e) => setCameraYawDeg(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="text-[10px] text-eigenia-muted">Operator Hint</label>
            <Input
              placeholder="e.g. Rack B2 PLC"
              value={contextHint}
              onChange={(e) => setContextHint(e.target.value)}
            />
          </div>
        </div>

        {/* Snap directly from active PuppyPi FPV Camera */}
        <Button
          type="button"
          variant="sky"
          className="w-full"
          disabled={!activeRobotId || snappingFpv || analyzing}
          onClick={handleSnapFromPuppyPi}
        >
          {snappingFpv ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Bot className="h-3.5 w-3.5" />
          )}
          {snappingFpv
            ? "Capturing PuppyPi FPV + Running Vision..."
            : activeRobotId
              ? "Snap from PuppyPi FPV"
              : "Snap from PuppyPi FPV (Select Robot)"}
        </Button>

        <label className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-eigenia-orange/50 bg-eigenia-obsidian/80 p-3 text-center transition hover:border-eigenia-orange">
          <div className="flex items-center gap-2 text-xs font-medium text-white">
            <Camera className="h-4 w-4 text-eigenia-orange" />
            <Upload className="h-4 w-4 text-eigenia-sky" />
            {analyzing ? "Running CLAHE + zxing-cpp + OpenRouter..." : "Scan Nameplate / Equipment Photo"}
          </div>
          <span className="text-[10px] text-eigenia-muted">
            Extracts Make, Model, Serial, DataMatrix, CPE-2.3 & Raycasts onto LiDAR
          </span>
          <input type="file" accept="image/*" capture="environment" className="hidden" onChange={handleFileChange} />
        </label>

        {errorMsg && (
          <div className="rounded border border-eigenia-fault/40 bg-eigenia-fault/15 p-2 font-mono text-[11px] text-eigenia-fault">
            {errorMsg}
          </div>
        )}

        {imageUrl && (
          <div className="relative overflow-hidden rounded border border-white/15 bg-eigenia-obsidian">
            <img src={imageUrl} alt="Equipment capture" className="max-h-40 w-full object-contain" />
            {result?.detected_boxes && Array.isArray(result.detected_boxes) && result.detected_boxes.length > 0 && (
              <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1000 1000" preserveAspectRatio="none">
                {result.detected_boxes.map((b, idx) => {
                  if (!Array.isArray(b.bbox_norm) || b.bbox_norm.length < 4) return null;
                  const [ymin, xmin, ymax, xmax] = b.bbox_norm;
                  return (
                    <rect
                      key={idx}
                      x={xmin}
                      y={ymin}
                      width={Math.max(10, xmax - xmin)}
                      height={Math.max(10, ymax - ymin)}
                      fill="rgba(224,90,16,0.12)"
                      stroke="#E05A10"
                      strokeWidth="8"
                    />
                  );
                })}
              </svg>
            )}
          </div>
        )}

        {result && (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="sky">
              <Cpu className="h-3 w-3" /> {Math.round(result.confidence * 100)}% conf
            </Badge>
            {(Array.isArray(result.barcodes) ? result.barcodes : []).map((b, i) => (
              <Badge key={i} variant="default">
                <ScanBarcode className="h-3 w-3" /> {b.format}: {b.text}
              </Badge>
            ))}
            {result.consensus_verified && (
              <Badge variant="sky">
                <CheckCircle2 className="h-3 w-3" /> Consensus Verified
              </Badge>
            )}
            {poseInfo && (
              <Badge variant="amber">
                Raycast {poseInfo.distance_m.toFixed(2)}m @ {poseInfo.bearing_deg.toFixed(0)}°
              </Badge>
            )}
          </div>
        )}

        <div className="space-y-2 border-t border-white/10 pt-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-eigenia-muted">
            Verified Asset Identity & Coordinates
          </div>
          <Input
            placeholder="Asset Name (e.g. Siemens S7-1500 PLC)"
            value={formState.name}
            onChange={(e) => setFormState({ ...formState, name: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder="Manufacturer"
              value={formState.manufacturer}
              onChange={(e) => setFormState({ ...formState, manufacturer: e.target.value })}
            />
            <Input
              placeholder="Model Number"
              value={formState.model_number}
              onChange={(e) => setFormState({ ...formState, model_number: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder="Serial Number"
              value={formState.serial_number}
              onChange={(e) => setFormState({ ...formState, serial_number: e.target.value })}
            />
            <Input
              placeholder="DEXPI Class"
              value={formState.dexpi_class}
              onChange={(e) => setFormState({ ...formState, dexpi_class: e.target.value })}
            />
          </div>
          <Input
            placeholder="NIST CPE 2.3 (e.g. cpe:2.3:h:siemens:...)"
            className="font-mono text-[11px]"
            value={formState.inferred_cpe_23}
            onChange={(e) => setFormState({ ...formState, inferred_cpe_23: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder="Asset Tags (comma-sep)"
              value={formState.asset_tags}
              onChange={(e) => setFormState({ ...formState, asset_tags: e.target.value })}
            />
            <Input
              placeholder="MAC / IP Labels"
              value={formState.mac_addresses}
              onChange={(e) => setFormState({ ...formState, mac_addresses: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="font-mono text-[10px] text-eigenia-muted">X (m)</label>
              <Input
                type="number"
                step="0.05"
                value={formState.x}
                onChange={(e) => setFormState({ ...formState, x: Number(e.target.value) })}
              />
            </div>
            <div>
              <label className="font-mono text-[10px] text-eigenia-muted">Y (m)</label>
              <Input
                type="number"
                step="0.05"
                value={formState.y}
                onChange={(e) => setFormState({ ...formState, y: Number(e.target.value) })}
              />
            </div>
            <div>
              <label className="font-mono text-[10px] text-eigenia-muted">Yaw (°)</label>
              <Input
                type="number"
                value={formState.yaw_deg}
                onChange={(e) => setFormState({ ...formState, yaw_deg: Number(e.target.value) })}
              />
            </div>
          </div>

          <Button className="w-full" disabled={pinning || !formState.name.trim()} onClick={handlePinSubmit}>
            <MapPin className="h-3.5 w-3.5" />
            {pinning ? "Indexing pgvector & Syncing Neo4j..." : "Pin Equipment to Twin + Knowledge Graph"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
