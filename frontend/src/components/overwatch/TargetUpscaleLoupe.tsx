"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Cpu, Loader2, Sparkles, ZoomIn } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { upscaleOverwatchRoi, type UpscaleRoiResult } from "@/lib/overwatchApi";

interface TargetUpscaleLoupeProps {
  cameraId: string;
  targetLabel: string;
  bboxNorm: [number, number, number, number];
}

export function TargetUpscaleLoupe({
  cameraId,
  targetLabel,
  bboxNorm,
}: TargetUpscaleLoupeProps): React.JSX.Element {
  const [busyMode, setBusyMode] = useState<"local" | "fal" | null>(null);
  const [falModel, setFalModel] = useState<"fal-ai/esrgan" | "fal-ai/clarity-upscaler">("fal-ai/esrgan");
  const [result, setResult] = useState<UpscaleRoiResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runUpscale = async (mode: "local" | "fal") => {
    setBusyMode(mode);
    setError(null);
    try {
      const res = await upscaleOverwatchRoi({
        camera_id: cameraId,
        bbox_norm: bboxNorm,
        mode,
        scale: 2,
        model: mode === "fal" ? falModel : undefined,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ROI enhancement failed.");
    } finally {
      setBusyMode(null);
    }
  };

  return (
    <Card className="border-white/10 bg-slate-950/90">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 border-b border-white/10 py-2.5">
        <div className="flex items-center gap-2">
          <ZoomIn className="h-4 w-4 text-cyan-400" />
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-slate-200">
            Target ROI Loupe: {targetLabel}
          </CardTitle>
          <Badge variant="neutral" className="font-mono text-[10px]">
            {cameraId}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="sm"
            variant="secondary"
            disabled={busyMode !== null}
            onClick={() => runUpscale("local")}
            className="h-7 cursor-pointer text-xs"
          >
            {busyMode === "local" ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Cpu className="mr-1 h-3 w-3" />}
            Local 2× CLAHE ($0)
          </Button>
          <select
            value={falModel}
            onChange={(e) => setFalModel(e.target.value as "fal-ai/esrgan" | "fal-ai/clarity-upscaler")}
            className="h-7 rounded-md border border-white/15 bg-slate-900 px-2 font-mono text-[11px] text-slate-200"
            aria-label="fal.ai upscale model"
          >
            <option value="fal-ai/esrgan">fal-ai/esrgan</option>
            <option value="fal-ai/clarity-upscaler">fal-ai/clarity-upscaler</option>
          </select>
          <Button
            size="sm"
            variant="sky"
            disabled={busyMode !== null}
            onClick={() => runUpscale("fal")}
            className="h-7 cursor-pointer text-xs"
          >
            {busyMode === "fal" ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Sparkles className="mr-1 h-3 w-3" />}
            AI Upscale (fal.ai)
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-3">
        {error && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
            <span>{error}</span>
            {error.toLowerCase().includes("fal_api_key") && (
              <Link href="/config" className="font-semibold text-cyan-300 underline">
                Add fal_api_key in /config →
              </Link>
            )}
          </div>
        )}

        {result ? (
          <div className="space-y-2">
            {result.ai_generated_warning && (
              <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-950/40 px-2.5 py-1.5 text-[11px] font-medium text-amber-200">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                <span>AI-ENHANCED — Verify fine text, serials, or faces against the untouched Raw Crop.</span>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <div className="flex items-center justify-between font-mono text-[10px] text-slate-400">
                  <span>RAW CROP</span>
                  <span>
                    {result.raw_size[0]}×{result.raw_size[1]}
                  </span>
                </div>
                <div className="flex aspect-video items-center justify-center overflow-hidden rounded border border-white/10 bg-black">
                  <img src={result.raw_crop_b64} alt="Raw ROI crop" className="max-h-full max-w-full object-contain" />
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between font-mono text-[10px] text-cyan-300">
                  <span>{result.method === "fal_ai_upscale" ? result.model : "LOCAL LANCZOS+CLAHE"}</span>
                  <span>
                    {result.enhanced_size[0]}×{result.enhanced_size[1]} · {result.latency_ms}ms
                  </span>
                </div>
                <div className="flex aspect-video items-center justify-center overflow-hidden rounded border border-cyan-500/30 bg-black">
                  <img src={result.enhanced_b64} alt="Enhanced ROI crop" className="max-h-full max-w-full object-contain" />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-xs text-slate-400">
            Click <strong className="text-slate-200">Local 2× CLAHE</strong> for instant offline clarity enhancement or{" "}
            <strong className="text-cyan-300">AI Upscale (fal.ai)</strong> for cloud super-resolution on this target ROI.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
