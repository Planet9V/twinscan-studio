"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Camera,
  CheckCircle2,
  Compass,
  Download,
  Eye,
  Layers,
  Loader2,
  Move,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCw,
  Scaling,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  RoomStudioViewport,
  type RoomStudioViewportHandle,
} from "@/components/room-studio/RoomStudioViewport";
import { API_URL } from "@/lib/api";
import {
  analyzeRoomPhoto,
  createRoomObject,
  createRoomProject,
  deleteRoomObject,
  deleteRoomPhoto,
  generateRoomObject3D,
  getRoomProject,
  listRoomProjects,
  stitchRoomSurface,
  updateRoomObject,
  updateRoomProject,
  uploadRoomPhoto,
  uploadRoomSplat,
  type Object3DEngine,
  type RoomCaptureCoach,
  type RoomObjectPose,
  type RoomStudioObject,
  type RoomStudioPhoto,
  type RoomStudioProject,
  type RoomSurface,
  type SupportType,
} from "@/lib/roomStudioApi";
import { cn } from "@/lib/utils";

const SURFACE_OPTIONS: Array<{ id: RoomSurface; label: string }> = [
  { id: "north_wall", label: "North Wall" },
  { id: "east_wall", label: "East Wall" },
  { id: "south_wall", label: "South Wall" },
  { id: "west_wall", label: "West Wall" },
  { id: "floor", label: "Floor" },
  { id: "object_closeup", label: "Object Close-Up" },
  { id: "overview", label: "Room Overview" },
];

const ENGINE_OPTIONS: Array<{ id: Object3DEngine; label: string; hint: string }> = [
  { id: "local_depth3d", label: "Instant Local 3D (.glb)", hint: "Offline, <1s, free" },
  { id: "fal-ai/trellis-2", label: "TRELLIS-2 (fal.ai Pro 360°)", hint: "Full 360° PBR mesh" },
  { id: "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d", label: "Hunyuan3D v3.1 Pro (fal.ai)", hint: "Ultra-detailed PBR" },
  { id: "fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d", label: "Hunyuan3D v3.1 Rapid (fal.ai)", hint: "Fast 360° PBR" },
  { id: "tripo3d/tripo/v2.5/image-to-3d", label: "Tripo v2.5 (fal.ai)", hint: "Clean game-ready mesh" },
];

export function RoomTwinStudio(): React.JSX.Element {
  const viewportRef = useRef<RoomStudioViewportHandle | null>(null);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const splatInputRef = useRef<HTMLInputElement | null>(null);

  const [projects, setProjects] = useState<RoomStudioProject[]>([]);
  const [project, setProject] = useState<RoomStudioProject | null>(null);
  const [coach, setCoach] = useState<RoomCaptureCoach | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyMsg, setBusyMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Floating Spatial HUD states
  const [leftOpen, setLeftOpen] = useState(true);
  const [leftTab, setLeftTab] = useState<"photos" | "objects" | "room">("photos");
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [showShell, setShowShell] = useState(true);
  const [showObjects, setShowObjects] = useState(true);
  const [showPhotoGhosts, setShowPhotoGhosts] = useState(true);
  const [showNbvGhosts, setShowNbvGhosts] = useState(true);
  const [transformMode, setTransformMode] = useState<"translate" | "rotate" | "scale">("translate");

  // Photo upload form states
  const [uploadSurface, setUploadSurface] = useState<RoomSurface>("west_wall");
  const [uploadName, setUploadName] = useState("");
  const [uploadTags, setUploadTags] = useState("");

  // Interactive Box-to-Tag modal on a photo (e.g., draw a box around a guitar!)
  const [boxingPhoto, setBoxingPhoto] = useState<RoomStudioPhoto | null>(null);
  const [boxDragStart, setBoxDragStart] = useState<[number, number] | null>(null);
  const [boxNorm, setBoxNorm] = useState<[number, number, number, number]>([0.25, 0.2, 0.75, 0.8]);
  const [newObjName, setNewObjName] = useState("Acoustic Guitar");
  const [newObjSupport, setNewObjSupport] = useState<SupportType>("WALL_MOUNTED");
  const [newObjW, setNewObjW] = useState("0.40");
  const [newObjH, setNewObjH] = useState("1.00");
  const [newObjD, setNewObjD] = useState("0.14");

  // 3D Generation Engine selector
  const [selectedEngine, setSelectedEngine] = useState<Object3DEngine>("local_depth3d");

  // New Room form
  const [newRoomOpen, setNewRoomOpen] = useState(false);
  const [newRoomName, setNewRoomName] = useState("Music & Guitar Room");
  const [roomW, setRoomW] = useState("4.6");
  const [roomL, setRoomL] = useState("4.2");
  const [roomH, setRoomH] = useState("2.6");

  const loadProjects = useCallback(async (selectId?: string) => {
    setLoading(true);
    try {
      const res = await listRoomProjects();
      const list = res.projects || [];
      setProjects(list);
      const targetId = selectId || list[0]?.id;
      if (targetId) {
        const detail = await getRoomProject(targetId);
        setProject(detail.project);
        setCoach(detail.coach);
        setRoomW(String(detail.project.width_m));
        setRoomL(String(detail.project.length_m));
        setRoomH(String(detail.project.height_m));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Room Twin Studio.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const handleSelectProject = async (pid: string) => {
    setSelectedObjectId(null);
    try {
      const detail = await getRoomProject(pid);
      setProject(detail.project);
      setCoach(detail.coach);
      setRoomW(String(detail.project.width_m));
      setRoomL(String(detail.project.length_m));
      setRoomH(String(detail.project.height_m));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed switching room.");
    }
  };

  const handleCreateRoom = async () => {
    setBusyMsg("Creating room...");
    setError(null);
    try {
      const res = await createRoomProject({
        name: newRoomName.trim() || "New Studio Room",
        width_m: Number(roomW) || 4.6,
        length_m: Number(roomL) || 4.2,
        height_m: Number(roomH) || 2.6,
      });
      setNewRoomOpen(false);
      await loadProjects(res.project.id);
      setNotice(`Created room "${res.project.name}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed creating room.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleUploadPhotoFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !project) return;
    e.target.value = "";
    setBusyMsg(`Uploading ${file.name}...`);
    setError(null);
    setNotice(null);
    try {
      const res = await uploadRoomPhoto(project.id, file, {
        name: uploadName.trim() || file.name.replace(/\.[^.]+$/, ""),
        surface: uploadSurface,
        tags: uploadTags,
      });
      setProject(res.project);
      setCoach(res.coach);
      setUploadName("");
      setUploadTags("");
      setNotice(`Uploaded "${res.photo.name}" to ${res.photo.surface.replace("_", " ")}. Click AI Detect or Tag Object to extract 3D assets!`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Photo upload failed.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleUploadSplatFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !project) return;
    e.target.value = "";
    setBusyMsg(`Importing 3D backdrop ${file.name}...`);
    setError(null);
    try {
      const res = await uploadRoomSplat(project.id, file);
      setProject(res.project);
      setNotice(`Loaded 3D backdrop "${file.name}" into viewport.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "3D backdrop upload failed.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleAnalyzePhoto = async (photo: RoomStudioPhoto) => {
    if (!project) return;
    setBusyMsg(`AI Vision extracting objects from "${photo.name}"...`);
    setError(null);
    setNotice(null);
    try {
      const res = await analyzeRoomPhoto(project.id, photo.id);
      setProject(res.project);
      setCoach(res.coach);
      setLeftTab("objects");
      setNotice(`${res.summary} (${res.created_objects.length} objects placed into the 3D room)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Vision analysis failed.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleStitchSurface = async (surface: string) => {
    if (!project) return;
    setBusyMsg(`Stitching high-res texture for ${surface.replace("_", " ")}...`);
    setError(null);
    try {
      const res = await stitchRoomSurface(project.id, surface);
      setProject(res.project);
      setNotice(`Stitched ${surface.replace("_", " ")} via ${res.method}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wall stitching failed.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleCreateBoxedObject = async () => {
    if (!project || !boxingPhoto) return;
    setBusyMsg(`Tagging "${newObjName}" into 3D scene...`);
    setError(null);
    try {
      const res = await createRoomObject(project.id, {
        source_photo_id: boxingPhoto.id,
        name: newObjName.trim() || "Tagged Object",
        category: "prop",
        support_type: newObjSupport,
        support_surface: boxingPhoto.surface,
        bbox_norm: boxNorm,
        dimensions_m: [
          Math.max(0.05, Number(newObjW) || 0.35),
          Math.max(0.05, Number(newObjH) || 0.45),
          Math.max(0.04, Number(newObjD) || 0.15),
        ],
      });
      setProject(res.project);
      setCoach(res.coach);
      setBoxingPhoto(null);
      setSelectedObjectId(res.object.id);
      setLeftTab("objects");
      setNotice(`Placed "${res.object.name}" in 3D! Click Generate 3D (.glb) in the right inspector.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed tagging object.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleGenerate3D = async (obj: RoomStudioObject, engine: Object3DEngine) => {
    if (!project) return;
    setBusyMsg(
      engine === "local_depth3d"
        ? `Synthesizing Instant 3D .glb for "${obj.name}"...`
        : `Generating Full-360° PBR .glb via ${engine} for "${obj.name}" (15–30s)...`
    );
    setError(null);
    setNotice(null);
    try {
      const res = await generateRoomObject3D(project.id, obj.id, engine);
      setProject(res.project);
      setCoach(res.coach);
      setNotice(`Converted "${obj.name}" to a real Three.js .glb mesh (${engine})!`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "3D generation failed.");
    } finally {
      setBusyMsg(null);
    }
  };

  const handleCommitPose = async (objectId: string, pose: RoomObjectPose) => {
    if (!project) return;
    try {
      const res = await updateRoomObject(project.id, objectId, { pose });
      setProject(res.project);
    } catch {
      // Non-fatal
    }
  };

  const handleSnapObject = async (obj: RoomStudioObject, mode: "floor" | "desk" | "wall") => {
    if (!project) return;
    const [, oh, od] = obj.dimensions_m || [0.35, 0.45, 0.15];
    const p = { ...obj.pose };
    if (mode === "floor") {
      p.y = Number((oh * 0.5).toFixed(3));
    } else if (mode === "desk") {
      p.y = Number((0.76 + oh * 0.5).toFixed(3));
    } else if (mode === "wall") {
      const surf = obj.support_surface;
      const W = project.width_m;
      const L = project.length_m;
      if (surf === "west_wall") {
        p.x = Number((-W / 2 + od / 2 + 0.02).toFixed(3));
        p.ry = 90;
      } else if (surf === "east_wall") {
        p.x = Number((W / 2 - od / 2 - 0.02).toFixed(3));
        p.ry = -90;
      } else if (surf === "south_wall") {
        p.z = Number((L / 2 - od / 2 - 0.02).toFixed(3));
        p.ry = 180;
      } else {
        p.z = Number((-L / 2 + od / 2 + 0.02).toFixed(3));
        p.ry = 0;
      }
    }
    const res = await updateRoomObject(project.id, obj.id, { pose: p });
    setProject(res.project);
  };

  const selectedObject = project?.objects.find((o) => o.id === selectedObjectId) ?? null;

  if (loading || !project) {
    return (
      <div className="flex h-[calc(100vh-5.5rem)] items-center justify-center rounded-2xl border border-white/10 bg-slate-950 text-slate-300">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-cyan-400" />
        Initializing Spatial Room Twin Studio...
      </div>
    );
  }

  return (
    <div className="relative h-[calc(100vh-5.5rem)] min-h-[620px] w-full overflow-hidden rounded-2xl border border-white/10 bg-slate-950 shadow-2xl">
      {/* FULL-BLEED THREE.JS r187 SPATIAL VIEWPORT */}
      <RoomStudioViewport
        ref={viewportRef}
        project={project}
        ghostCameras={coach?.ghost_cameras ?? []}
        selectedObjectId={selectedObjectId}
        showShell={showShell}
        showObjects={showObjects}
        showPhotoGhosts={showPhotoGhosts}
        showNbvGhosts={showNbvGhosts}
        transformMode={transformMode}
        onSelectObject={(oid) => {
          setSelectedObjectId(oid);
          const found = project.objects.find((o) => o.id === oid);
          if (found) {
            viewportRef.current?.flyToPose(
              [found.pose.x * 0.4 + 1.2, Math.max(1.0, found.pose.y + 0.45), found.pose.z * 0.4 + 1.4],
              [found.pose.x, found.pose.y, found.pose.z]
            );
          }
        }}
        onObjectTransformCommit={(oid, pose) => void handleCommitPose(oid, pose)}
      />

      {/* Hidden File Inputs */}
      <input
        ref={photoInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        onChange={(e) => void handleUploadPhotoFile(e)}
        className="hidden"
      />
      <input
        ref={splatInputRef}
        type="file"
        accept=".spz,.ply,.splat,.ksplat,.glb"
        onChange={(e) => void handleUploadSplatFile(e)}
        className="hidden"
      />

      {/* FLOATING TOP GLASSMORPHIC STUDIO BAR */}
      <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex flex-wrap items-center justify-between gap-2">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-xl border border-white/15 bg-slate-950/75 px-3 py-2 shadow-2xl backdrop-blur-md">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setLeftOpen((v) => !v)}
            className="h-7 px-2 text-slate-300 hover:text-white cursor-pointer"
            title={leftOpen ? "Collapse Studio Panel" : "Expand Studio Panel"}
          >
            {leftOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </Button>
          <Sparkles className="h-4 w-4 text-cyan-400" />
          <select
            aria-label="Select room project"
            value={project.id}
            onChange={(e) => void handleSelectProject(e.target.value)}
            className="h-7 rounded-md border border-white/15 bg-slate-900/90 px-2 text-xs font-semibold text-slate-100"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.width_m}×{p.length_m}m)
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setNewRoomOpen(true)}
            className="h-7 gap-1 px-2 text-[11px] cursor-pointer"
          >
            <Plus className="h-3 w-3" /> New Room
          </Button>
        </div>

        {/* Center Layer & Gizmo Pills */}
        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-xl border border-white/15 bg-slate-950/75 px-2.5 py-1.5 shadow-2xl backdrop-blur-md">
          {(
            [
              { label: "Room Shell", active: showShell, toggle: () => setShowShell((v) => !v) },
              { label: "3D Objects", active: showObjects, toggle: () => setShowObjects((v) => !v) },
              { label: "Photo Ghosts", active: showPhotoGhosts, toggle: () => setShowPhotoGhosts((v) => !v) },
              { label: "AI Guide", active: showNbvGhosts, toggle: () => setShowNbvGhosts((v) => !v) },
            ] as const
          ).map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={item.toggle}
              className={cn(
                "rounded-lg px-2 py-1 text-[11px] font-medium transition-all duration-300 cursor-pointer",
                item.active
                  ? "bg-cyan-500/20 text-cyan-200 ring-1 ring-cyan-400/40"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              {item.label}
            </button>
          ))}

          <div className="mx-1 h-4 w-px bg-white/15" />

          {(
            [
              { id: "translate", icon: Move, title: "Move Object" },
              { id: "rotate", icon: RotateCw, title: "Rotate Object" },
              { id: "scale", icon: Scaling, title: "Scale Object" },
            ] as const
          ).map(({ id, icon: Icon, title }) => (
            <button
              key={id}
              type="button"
              title={title}
              onClick={() => setTransformMode(id)}
              className={cn(
                "rounded-md p-1.5 transition-colors cursor-pointer",
                transformMode === id ? "bg-cyan-600 text-white" : "text-slate-400 hover:text-white"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>

        {/* Right Actions: Import 3DGS & Export Full Room GLB */}
        <div className="pointer-events-auto flex items-center gap-1.5 rounded-xl border border-white/15 bg-slate-950/75 px-2.5 py-1.5 shadow-2xl backdrop-blur-md">
          <Button
            size="sm"
            variant="outline"
            onClick={() => splatInputRef.current?.click()}
            className="h-7 gap-1 text-[11px] cursor-pointer"
          >
            <Layers className="h-3.5 w-3.5 text-violet-400" />
            Import 3DGS / PLY
          </Button>
          <Button
            size="sm"
            onClick={() => viewportRef.current?.exportFullRoomGlb()}
            className="h-7 gap-1 bg-emerald-600 text-[11px] text-white hover:bg-emerald-500 cursor-pointer"
          >
            <Download className="h-3.5 w-3.5" />
            Export Room .glb
          </Button>
        </div>
      </div>

      {/* FLOATING STATUS / ERROR TOAST */}
      {(busyMsg || error || notice) && (
        <div className="pointer-events-none absolute inset-x-0 top-16 z-30 flex justify-center px-4">
          <div
            className={cn(
              "pointer-events-auto flex items-center gap-2 rounded-full border px-4 py-1.5 text-xs shadow-2xl backdrop-blur-md",
              error
                ? "border-red-500/50 bg-red-950/85 text-red-200"
                : busyMsg
                  ? "border-cyan-500/50 bg-slate-950/90 text-cyan-200"
                  : "border-emerald-500/50 bg-emerald-950/85 text-emerald-200"
            )}
          >
            {busyMsg ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
            ) : !error ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            ) : null}
            <span>{busyMsg || error || notice}</span>
            {!busyMsg && (
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setNotice(null);
                }}
                className="ml-1 text-slate-400 hover:text-white cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* LEFT FLOATING GLASS RAIL: CAPTURE PHOTOS, SCENE GRAPH OBJECTS, ROOM SHELL */}
      {leftOpen && (
        <div className="absolute bottom-16 left-3 top-16 z-20 flex w-80 flex-col rounded-2xl border border-white/15 bg-slate-950/78 text-slate-100 shadow-2xl backdrop-blur-md transition-all duration-300">
          <div className="grid grid-cols-3 gap-1 border-b border-white/10 p-2">
            {(
              [
                { id: "photos", label: `Photos (${project.photos.length})` },
                { id: "objects", label: `Objects (${project.objects.length})` },
                { id: "room", label: "Room Shell" },
              ] as const
            ).map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setLeftTab(t.id)}
                className={cn(
                  "rounded-lg py-1.5 text-[11px] font-semibold transition-colors cursor-pointer",
                  leftTab === t.id
                    ? "bg-cyan-600/80 text-white"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {/* TAB A: PHOTO UPLOAD, TAGGING, STITCHING & VISION */}
            {leftTab === "photos" && (
              <>
                <div className="space-y-2 rounded-xl border border-white/10 bg-slate-900/60 p-2.5">
                  <div className="text-[11px] font-semibold text-cyan-300">
                    Upload &amp; Tag Room Photo
                  </div>
                  <select
                    aria-label="Target wall or surface"
                    value={uploadSurface}
                    onChange={(e) => setUploadSurface(e.target.value as RoomSurface)}
                    className="h-8 w-full rounded-md border border-white/15 bg-slate-950 px-2 text-xs text-slate-200"
                  >
                    {SURFACE_OPTIONS.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <Input
                    value={uploadName}
                    onChange={(e) => setUploadName(e.target.value)}
                    placeholder="Photo name (e.g. West Wall Guitar)"
                    className="h-7 bg-slate-950 text-xs"
                  />
                  <Input
                    value={uploadTags}
                    onChange={(e) => setUploadTags(e.target.value)}
                    placeholder="Tags (guitar, lamp, mug, books)"
                    className="h-7 bg-slate-950 text-xs"
                  />
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      onClick={() => photoInputRef.current?.click()}
                      className="h-8 flex-1 gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
                    >
                      <Upload className="h-3.5 w-3.5" />
                      Upload Photo
                    </Button>
                    {project.photos.filter((p) => p.surface === uploadSurface).length >= 2 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void handleStitchSurface(uploadSurface)}
                        className="h-8 px-2 text-[11px] cursor-pointer"
                        title="Stitch all photos on this wall"
                      >
                        Stitch
                      </Button>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  {project.photos.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-white/15 p-4 text-center text-xs text-slate-400">
                      Upload photos of each wall or object (guitar, desk, lamp, mug) to build your high-resolution Three.js Digital Twin.
                    </div>
                  ) : (
                    project.photos.map((photo) => (
                      <div
                        key={photo.id}
                        className="overflow-hidden rounded-xl border border-white/10 bg-slate-900/70"
                      >
                        <div className="relative aspect-video w-full bg-black">
                          <img
                            src={`${API_URL}${photo.url}`}
                            alt={photo.name}
                            className="h-full w-full object-cover"
                          />
                          <Badge variant="sky" className="absolute left-2 top-2 text-[9px]">
                            {photo.surface.replace("_", " ")}
                          </Badge>
                          <button
                            type="button"
                            onClick={() =>
                              viewportRef.current?.flyToPose(
                                [photo.camera_pose.x, photo.camera_pose.y, photo.camera_pose.z],
                                [0, 1.1, 0]
                              )
                            }
                            title="Fly to camera viewpoint"
                            className="absolute right-2 top-2 rounded-md bg-black/70 p-1 text-cyan-300 hover:bg-cyan-600 hover:text-white cursor-pointer"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="space-y-2 p-2">
                          <div className="flex items-center justify-between gap-1">
                            <span className="truncate text-xs font-semibold text-slate-100">
                              {photo.name}
                            </span>
                            <button
                              type="button"
                              onClick={async () => {
                                const res = await deleteRoomPhoto(project.id, photo.id);
                                setProject(res.project);
                                setCoach(res.coach);
                              }}
                              className="text-slate-500 hover:text-red-400 cursor-pointer"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                          <div className="flex gap-1.5">
                            <Button
                              size="sm"
                              onClick={() => void handleAnalyzePhoto(photo)}
                              className="h-7 flex-1 gap-1 bg-violet-600/90 text-[11px] text-white hover:bg-violet-500 cursor-pointer"
                            >
                              <Wand2 className="h-3 w-3" /> AI Detect
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setBoxingPhoto(photo);
                                setNewObjSupport(photo.surface.endsWith("_wall") ? "WALL_MOUNTED" : "ON_SURFACE");
                              }}
                              className="h-7 flex-1 gap-1 text-[11px] cursor-pointer"
                            >
                              <Box className="h-3 w-3" /> Box Object
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}

            {/* TAB B: COMPOSITIONAL 3D SCENE GRAPH OBJECTS */}
            {leftTab === "objects" && (
              <div className="space-y-2">
                {project.objects.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-white/15 p-4 text-center text-xs text-slate-400">
                    No 3D objects yet. Upload a photo and click <strong>AI Detect</strong> or <strong>Box Object</strong> (e.g. guitar on wall, mug, lamp).
                  </div>
                ) : (
                  project.objects.map((obj) => {
                    const isSel = obj.id === selectedObjectId;
                    return (
                      <div
                        key={obj.id}
                        onClick={() => {
                          setSelectedObjectId(obj.id);
                          viewportRef.current?.flyToPose(
                            [obj.pose.x * 0.4 + 1.2, Math.max(1.0, obj.pose.y + 0.45), obj.pose.z * 0.4 + 1.4],
                            [obj.pose.x, obj.pose.y, obj.pose.z]
                          );
                        }}
                        className={cn(
                          "flex items-center gap-2.5 rounded-xl border p-2 transition-all cursor-pointer",
                          isSel
                            ? "border-cyan-400 bg-cyan-950/50"
                            : "border-white/10 bg-slate-900/70 hover:border-white/25"
                        )}
                      >
                        {obj.crop_b64 ? (
                          <img
                            src={obj.crop_b64}
                            alt={obj.name}
                            className="h-11 w-11 shrink-0 rounded-lg border border-white/10 object-cover"
                          />
                        ) : (
                          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-slate-950">
                            <Box className="h-4 w-4 text-cyan-400" />
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-semibold text-slate-100">{obj.name}</div>
                          <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                            <span>{obj.support_type.replace("_", " ")}</span>
                            <span>·</span>
                            <span className={obj.mesh_url ? "text-emerald-400" : "text-amber-300"}>
                              {obj.mesh_url ? "3D .glb Ready" : "Proxy Box"}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}

            {/* TAB C: ROOM METRIC DIMENSIONS */}
            {leftTab === "room" && (
              <div className="space-y-3 rounded-xl border border-white/10 bg-slate-900/60 p-3">
                <div className="text-xs font-semibold text-cyan-300">Metric Room Shell Dimensions</div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="mb-1 block text-[10px] text-slate-400">Width X (m)</label>
                    <Input value={roomW} onChange={(e) => setRoomW(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] text-slate-400">Length Z (m)</label>
                    <Input value={roomL} onChange={(e) => setRoomL(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] text-slate-400">Height Y (m)</label>
                    <Input value={roomH} onChange={(e) => setRoomH(e.target.value)} className="h-8 bg-slate-950 font-mono text-xs" />
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={async () => {
                    const res = await updateRoomProject(project.id, {
                      width_m: Number(roomW) || 4.6,
                      length_m: Number(roomL) || 4.2,
                      height_m: Number(roomH) || 2.6,
                    });
                    setProject(res.project);
                    setCoach(res.coach);
                    setNotice("Updated room shell dimensions.");
                  }}
                  className="w-full bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
                >
                  Apply Room Dimensions
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* RIGHT FLOATING GLASS OBJECT INSPECTOR & 3D .GLB CONVERTER */}
      {selectedObject && (
        <div className="absolute bottom-16 right-3 top-16 z-20 flex w-80 flex-col rounded-2xl border border-cyan-500/30 bg-slate-950/82 p-3.5 text-slate-100 shadow-2xl backdrop-blur-md">
          <div className="flex items-center justify-between border-b border-white/10 pb-2.5">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-white">{selectedObject.name}</div>
              <div className="text-[10px] text-slate-400">
                {selectedObject.support_type} · {selectedObject.support_surface.replace("_", " ")}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelectedObjectId(null)}
              className="text-slate-400 hover:text-white cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-3 flex-1 space-y-3 overflow-y-auto">
            {selectedObject.crop_b64 && (
              <div className="overflow-hidden rounded-xl border border-white/10 bg-black">
                <img
                  src={selectedObject.crop_b64}
                  alt={selectedObject.name}
                  className="max-h-40 w-full object-contain"
                />
              </div>
            )}

            {/* Photo -> Three.js 3D .glb Converter */}
            <div className="space-y-2 rounded-xl border border-cyan-500/25 bg-cyan-950/20 p-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-cyan-300">Convert Photo → Three.js 3D (.glb)</span>
                {selectedObject.mesh_url && (
                  <Badge variant="sky" className="text-[9px]">
                    {selectedObject.mesh_engine}
                  </Badge>
                )}
              </div>
              <select
                aria-label="3D generation engine"
                value={selectedEngine}
                onChange={(e) => setSelectedEngine(e.target.value as Object3DEngine)}
                className="h-8 w-full rounded-md border border-white/15 bg-slate-950 px-2 text-xs text-slate-200"
              >
                {ENGINE_OPTIONS.map((eng) => (
                  <option key={eng.id} value={eng.id}>
                    {eng.label} — {eng.hint}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                onClick={() => void handleGenerate3D(selectedObject, selectedEngine)}
                className="h-8 w-full gap-1.5 bg-cyan-600 text-xs text-white hover:bg-cyan-500 cursor-pointer"
              >
                <Sparkles className="h-3.5 w-3.5" />
                {selectedObject.mesh_url ? "Re-Generate 3D .glb" : "Generate 3D .glb Now"}
              </Button>
            </div>

            {/* Physics Support Snapping */}
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold text-slate-300">Physics Surface Snap</div>
              <div className="grid grid-cols-3 gap-1.5">
                <Button size="sm" variant="outline" onClick={() => void handleSnapObject(selectedObject, "wall")} className="h-7 text-[10px] cursor-pointer">
                  Snap Wall
                </Button>
                <Button size="sm" variant="outline" onClick={() => void handleSnapObject(selectedObject, "desk")} className="h-7 text-[10px] cursor-pointer">
                  Snap Desk
                </Button>
                <Button size="sm" variant="outline" onClick={() => void handleSnapObject(selectedObject, "floor")} className="h-7 text-[10px] cursor-pointer">
                  Snap Floor
                </Button>
              </div>
              <p className="text-[10px] text-slate-400">
                Use the 3D gizmo in the viewport (Move / Rotate / Scale) to fine-tune placement; changes save automatically.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-white/10 bg-slate-900/60 p-2 font-mono text-[10px] text-slate-300">
              <div>X: {selectedObject.pose.x.toFixed(2)}m</div>
              <div>Y: {selectedObject.pose.y.toFixed(2)}m</div>
              <div>Z: {selectedObject.pose.z.toFixed(2)}m</div>
            </div>
          </div>

          <div className="mt-3 border-t border-white/10 pt-2.5">
            <Button
              size="sm"
              variant="destructive"
              onClick={async () => {
                const res = await deleteRoomObject(project.id, selectedObject.id);
                setProject(res.project);
                setCoach(res.coach);
                setSelectedObjectId(null);
              }}
              className="h-7 w-full gap-1.5 text-xs cursor-pointer"
            >
              <Trash2 className="h-3.5 w-3.5" /> Remove Object
            </Button>
          </div>
        </div>
      )}

      {/* BOTTOM FLOATING AI NEXT-BEST-VIEW CAPTURE COACH PILL */}
      {coach && (
        <div className="pointer-events-none absolute inset-x-3 bottom-3 z-20 flex justify-center">
          <div className="pointer-events-auto flex max-w-4xl flex-wrap items-center gap-3 rounded-2xl border border-amber-500/30 bg-slate-950/82 px-4 py-2 text-xs text-slate-200 shadow-2xl backdrop-blur-md">
            <div className="flex items-center gap-2">
              <Compass className="h-4 w-4 text-amber-400" />
              <span className="font-semibold text-amber-300">AI Capture Coach</span>
              <Badge variant="sky" className="font-mono text-[10px]">
                {coach.coverage_pct}% Twin Coverage
              </Badge>
            </div>
            <span className="flex-1 text-[11px] text-slate-300">{coach.next_instruction}</span>
            {coach.ghost_cameras[0] && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const g = coach.ghost_cameras[0];
                  setUploadSurface(g.surface as RoomSurface);
                  viewportRef.current?.flyToPose(
                    [g.pose.x * 1.4, g.pose.y + 0.5, g.pose.z * 1.4],
                    [0, 1.1, 0]
                  );
                }}
                className="h-7 gap-1 border-amber-400/40 text-[11px] text-amber-200 hover:bg-amber-950/60 cursor-pointer"
              >
                <Camera className="h-3 w-3" /> Show Next Shot
              </Button>
            )}
          </div>
        </div>
      )}

      {/* INTERACTIVE PHOTO OBJECT BOXING MODAL */}
      {boxingPhoto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-3xl space-y-4 rounded-2xl border border-white/15 bg-slate-950 p-4 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">Box an Object on &ldquo;{boxingPhoto.name}&rdquo;</h3>
                <p className="text-xs text-slate-400">
                  Click and drag around an object (e.g. a guitar hanging on the wall, lamp, mug) to extract it into Three.js.
                </p>
              </div>
              <Button size="icon" variant="ghost" onClick={() => setBoxingPhoto(null)} className="cursor-pointer">
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div
              onPointerDown={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                const u = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
                const v = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
                setBoxDragStart([u, v]);
              }}
              onPointerMove={(e) => {
                if (!boxDragStart) return;
                const r = e.currentTarget.getBoundingClientRect();
                const u = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
                const v = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
                setBoxNorm([
                  Math.min(boxDragStart[0], u),
                  Math.min(boxDragStart[1], v),
                  Math.max(boxDragStart[0], u),
                  Math.max(boxDragStart[1], v),
                ]);
              }}
              onPointerUp={() => setBoxDragStart(null)}
              className="relative aspect-video w-full cursor-crosshair select-none overflow-hidden rounded-xl border border-white/15 bg-black"
            >
              <img
                src={`${API_URL}${boxingPhoto.url}`}
                alt={boxingPhoto.name}
                draggable={false}
                className="h-full w-full object-contain"
              />
              <div
                style={{
                  left: `${boxNorm[0] * 100}%`,
                  top: `${boxNorm[1] * 100}%`,
                  width: `${Math.max(2, (boxNorm[2] - boxNorm[0]) * 100)}%`,
                  height: `${Math.max(2, (boxNorm[3] - boxNorm[1]) * 100)}%`,
                }}
                className="pointer-events-none absolute rounded border-2 border-cyan-400 bg-cyan-400/15"
              />
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <div className="sm:col-span-2">
                <label className="mb-1 block text-[10px] text-slate-400">Object Name</label>
                <Input value={newObjName} onChange={(e) => setNewObjName(e.target.value)} className="h-8 bg-slate-900 text-xs" />
              </div>
              <div>
                <label className="mb-1 block text-[10px] text-slate-400">Placement</label>
                <select
                  value={newObjSupport}
                  onChange={(e) => setNewObjSupport(e.target.value as SupportType)}
                  className="h-8 w-full rounded-md border border-white/15 bg-slate-900 px-2 text-xs text-slate-200"
                >
                  <option value="WALL_MOUNTED">Wall Mounted</option>
                  <option value="ON_SURFACE">On Desk/Table</option>
                  <option value="ON_FLOOR">On Floor</option>
                  <option value="CEILING">Ceiling</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[10px] text-slate-400">W × H (m)</label>
                <div className="flex gap-1">
                  <Input value={newObjW} onChange={(e) => setNewObjW(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
                  <Input value={newObjH} onChange={(e) => setNewObjH(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-[10px] text-slate-400">Depth (m)</label>
                <Input value={newObjD} onChange={(e) => setNewObjD(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setBoxingPhoto(null)} className="cursor-pointer">
                Cancel
              </Button>
              <Button size="sm" onClick={() => void handleCreateBoxedObject()} className="bg-cyan-600 text-white hover:bg-cyan-500 cursor-pointer">
                Place Object in 3D Room
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* NEW ROOM MODAL */}
      {newRoomOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-4 rounded-2xl border border-white/15 bg-slate-950 p-5 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Create New High-Fidelity Room Twin</h3>
              <Button size="icon" variant="ghost" onClick={() => setNewRoomOpen(false)} className="cursor-pointer">
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">Room Name</label>
                <Input value={newRoomName} onChange={(e) => setNewRoomName(e.target.value)} className="h-8 bg-slate-900 text-xs" />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Width (m)</label>
                  <Input value={roomW} onChange={(e) => setRoomW(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Length (m)</label>
                  <Input value={roomL} onChange={(e) => setRoomL(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Height (m)</label>
                  <Input value={roomH} onChange={(e) => setRoomH(e.target.value)} className="h-8 bg-slate-900 font-mono text-xs" />
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setNewRoomOpen(false)} className="cursor-pointer">
                Cancel
              </Button>
              <Button size="sm" onClick={() => void handleCreateRoom()} className="bg-cyan-600 text-white hover:bg-cyan-500 cursor-pointer">
                Create Room
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
