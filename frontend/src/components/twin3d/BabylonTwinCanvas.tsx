"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  ArcRotateCamera,
  Color3,
  Color4,
  DirectionalLight,
  Engine,
  GlowLayer,
  HemisphericLight,
  HighlightLayer,
  Material,
  Mesh,
  MeshBuilder,
  PBRMaterial,
  PointsCloudSystem,
  Scene,
  StandardMaterial,
  Texture,
  Vector3,
  VertexData,
} from "@babylonjs/core";
import { Camera, Compass, Eye, Layers, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { resolveBackendAssetUrl } from "@/lib/api";
import { loadPuppyPiStlVertexArrays } from "@/lib/puppyModelLoader";
import type {
  EquipmentAsset,
  FocusTarget,
  LidarFrame,
  ScenePanelRecord,
  SceneRenderMode,
  SpatialDarkZone,
} from "@/lib/types";

interface BabylonTwinCanvasProps {
  frame: LidarFrame | null;
  equipment: EquipmentAsset[];
  darkZones: SpatialDarkZone[];
  selectedEquipmentId: string | null;
  focusTarget: FocusTarget | null;
  onSelectEquipment: (id: string) => void;
  scenePanels?: ScenePanelRecord[];
  sceneRenderMode?: SceneRenderMode;
  hiddenPanelIds?: string[];
}

export default function BabylonTwinCanvas({
  frame,
  equipment,
  darkZones,
  selectedEquipmentId,
  focusTarget,
  onSelectEquipment,
  scenePanels = [],
  sceneRenderMode = "solid",
  hiddenPanelIds = [],
}: BabylonTwinCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const cameraRef = useRef<ArcRotateCamera | null>(null);
  const sceneRef = useRef<Scene | null>(null);
  const dynamicMeshesRef = useRef<Mesh[]>([]);
  const dynamicMaterialsRef = useRef<Material[]>([]);
  const scenePanelMeshesRef = useRef<Mesh[]>([]);
  const scenePanelMaterialsRef = useRef<Material[]>([]);
  const scenePanelTexturesRef = useRef<Texture[]>([]);
  const pcsRef = useRef<PointsCloudSystem | null>(null);
  const pcsBuildTokenRef = useRef<number>(0);
  const highlightRef = useRef<HighlightLayer | null>(null);
  const puppyStlMeshRef = useRef<Mesh | null>(null);
  const puppyStlMatRef = useRef<PBRMaterial | null>(null);
  const prevPanelCountRef = useRef<number>(0);
  const onSelectRef = useRef(onSelectEquipment);
  onSelectRef.current = onSelectEquipment;

  const [webglError, setWebglError] = useState<string | null>(null);
  const [showDarkZones, setShowDarkZones] = useState(true);
  const [showPointCloud, setShowPointCloud] = useState(true);
  const [cameraPreset, setCameraPreset] = useState<"iso" | "top" | "rover" | "wall">("iso");

  // Initialize Babylon.js WebGL Engine with stencil buffer for HighlightLayer + GlowLayer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let engine: Engine | null = null;
    try {
      engine = new Engine(canvas, true, { stencil: true, preserveDrawingBuffer: true });
    } catch (err) {
      console.error("[BabylonTwinCanvas] WebGL engine initialization failed:", err);
      setWebglError("Babylon.js WebGL engine could not be initialized in this browser.");
      return;
    }

    setWebglError(null);
    const scene = new Scene(engine);
    scene.clearColor = new Color4(0.043, 0.051, 0.063, 1.0); // Eigenia #0b0d10

    const camera = new ArcRotateCamera(
      "eigeniaCam",
      -Math.PI / 2.2,
      Math.PI / 3.1,
      11.5,
      Vector3.Zero(),
      scene
    );
    camera.attachControl(canvas, true);
    camera.lowerRadiusLimit = 2.0;
    camera.upperRadiusLimit = 28.0;
    camera.wheelDeltaPercentage = 0.02;

    const hemi = new HemisphericLight("hemi", new Vector3(0, 1, 0), scene);
    hemi.intensity = 0.95;
    hemi.diffuse = new Color3(0.9, 0.94, 1.0);
    hemi.groundColor = new Color3(0.18, 0.22, 0.28);

    const dir = new DirectionalLight("dir", new Vector3(-0.6, -1, -0.5), scene);
    dir.position = new Vector3(6, 12, 6);
    dir.intensity = 1.35;

    // Ground plane with subtle architectural grid
    const ground = MeshBuilder.CreateGround("ground", { width: 22, height: 22, subdivisions: 22 }, scene);
    const groundMat = new StandardMaterial("groundMat", scene);
    groundMat.diffuseColor = new Color3(0.055, 0.063, 0.075);
    groundMat.specularColor = new Color3(0.05, 0.05, 0.05);
    groundMat.wireframe = false;
    ground.material = groundMat;

    const gridWire = MeshBuilder.CreateGround("gridWire", { width: 22, height: 22, subdivisions: 22 }, scene);
    gridWire.position.y = 0.005;
    const wireMat = new StandardMaterial("wireMat", scene);
    wireMat.emissiveColor = new Color3(0.11, 0.17, 0.24);
    wireMat.wireframe = true;
    wireMat.alpha = 0.28;
    gridWire.material = wireMat;

    // LiDAR origin emitter tower in Eigenia Signal Orange
    const originMesh = MeshBuilder.CreateCylinder("lidarOrigin", { diameter: 0.28, height: 0.36 }, scene);
    originMesh.position = new Vector3(0, 0.18, 0);
    const originMat = new StandardMaterial("originMat", scene);
    originMat.emissiveColor = Color3.FromHexString("#E05A10");
    originMesh.material = originMat;

    const glow = new GlowLayer("eigeniaGlow", scene, { blurKernelSize: 32 });
    glow.intensity = 0.65;

    const highlight = new HighlightLayer("eigeniaHighlight", scene);

    scene.onPointerDown = () => {
      const pick = scene.pick(scene.pointerX, scene.pointerY);
      const eqId = pick?.pickedMesh?.metadata?.equipmentId as string | undefined;
      if (eqId) onSelectRef.current(eqId);
    };

    sceneRef.current = scene;
    cameraRef.current = camera;
    highlightRef.current = highlight;

    let stlDisposed = false;
    void loadPuppyPiStlVertexArrays(0.46, true)
      .then((geo) => {
        if (stlDisposed || scene.isDisposed) return;
        const stlMesh = new Mesh("puppyHighResStl", scene);
        const vdata = new VertexData();
        vdata.positions = geo.positions;
        vdata.normals = geo.normals;
        vdata.indices = geo.indices;
        vdata.applyToMesh(stlMesh);

        const stlMat = new PBRMaterial("puppyHighResStlMat", scene);
        stlMat.albedoColor = Color3.FromHexString("#d4dce6");
        stlMat.emissiveColor = Color3.FromHexString("#431906");
        stlMat.metallic = 0.58;
        stlMat.roughness = 0.34;
        stlMesh.material = stlMat;
        stlMesh.position = new Vector3(0, 0.01, 0);

        puppyStlMeshRef.current = stlMesh;
        puppyStlMatRef.current = stlMat;
      })
      .catch(() => {
        // Keep clean procedural fallback avatar on load error
      });

    engine.runRenderLoop(() => {
      if (!scene.isDisposed) {
        scene.render();
      }
    });

    const onResize = () => engine?.resize();
    window.addEventListener("resize", onResize);

    return () => {
      stlDisposed = true;
      puppyStlMeshRef.current?.dispose();
      puppyStlMatRef.current?.dispose();
      puppyStlMeshRef.current = null;
      puppyStlMatRef.current = null;
      pcsBuildTokenRef.current += 1;
      window.removeEventListener("resize", onResize);
      pcsRef.current?.dispose();
      pcsRef.current = null;
      for (const m of dynamicMeshesRef.current) {
        m.dispose();
      }
      dynamicMeshesRef.current = [];
      for (const mat of dynamicMaterialsRef.current) {
        mat.dispose();
      }
      dynamicMaterialsRef.current = [];
      for (const m of scenePanelMeshesRef.current) {
        m.dispose();
      }
      scenePanelMeshesRef.current = [];
      for (const mat of scenePanelMaterialsRef.current) {
        mat.dispose();
      }
      scenePanelMaterialsRef.current = [];
      for (const tex of scenePanelTexturesRef.current) {
        tex.dispose();
      }
      scenePanelTexturesRef.current = [];
      highlight.dispose();
      glow.dispose();
      scene.dispose();
      engine?.dispose();
      sceneRef.current = null;
      cameraRef.current = null;
      highlightRef.current = null;
    };
  }, []);

  // Fly camera to focused dark zone or incomplete asset
  useEffect(() => {
    const cam = cameraRef.current;
    if (!cam || !focusTarget) return;
    cam.setTarget(new Vector3(focusTarget.x, 0.7, focusTarget.y));
    cam.radius = 5.5;
  }, [focusTarget]);

  // Auto-frame when first real-room panel is captured (0 -> >=1)
  useEffect(() => {
    const prev = prevPanelCountRef.current;
    const count = Array.isArray(scenePanels) ? scenePanels.length : 0;
    prevPanelCountRef.current = count;
    if (prev === 0 && count > 0) {
      setCameraPreset("wall");
    }
  }, [scenePanels]);

  // Apply camera presets
  useEffect(() => {
    const cam = cameraRef.current;
    if (!cam) return;
    if (cameraPreset === "top") {
      cam.alpha = -Math.PI / 2;
      cam.beta = 0.05;
      cam.radius = 12.5;
    } else if (cameraPreset === "rover") {
      cam.alpha = -Math.PI / 2;
      cam.beta = Math.PI / 2.25;
      cam.radius = 4.2;
      cam.setTarget(new Vector3(0, 0.45, 0));
    } else if (cameraPreset === "wall") {
      const hidden = new Set(hiddenPanelIds);
      const visible = (Array.isArray(scenePanels) ? scenePanels : []).filter((p) => !hidden.has(p.id));
      const latest = visible[visible.length - 1] ?? scenePanels[scenePanels.length - 1];
      if (latest && (latest.mesh?.positions?.length ?? 0) >= 3) {
        const pos = latest.mesh.positions;
        const n = Math.floor(pos.length / 3);
        let sx = 0;
        let sy = 0;
        let sz = 0;
        for (let i = 0; i < n; i++) {
          sx += pos[i * 3];
          sy += pos[i * 3 + 1];
          sz += -pos[i * 3 + 2]; // right-handed -> Babylon left-handed Z
        }
        const cx = sx / n;
        const cy = sy / n;
        const cz = sz / n;
        const rx = latest.pose?.x ?? 0;
        const rz = latest.pose?.y ?? 0;
        cam.setTarget(new Vector3(cx, cy, cz));
        cam.alpha = Math.atan2(rz - cz, rx - cx);
        cam.beta = Math.PI / 2.25;
        cam.radius = Math.max(2.2, (latest.mean_distance_m || 1.8) + 0.9);
      } else {
        cam.alpha = -Math.PI / 2;
        cam.beta = Math.PI / 2.25;
        cam.radius = 3.2;
        cam.setTarget(new Vector3(0, 0.5, 1.8));
      }
    } else {
      cam.alpha = -Math.PI / 2.2;
      cam.beta = Math.PI / 3.1;
      cam.radius = 11.5;
      cam.setTarget(Vector3.Zero());
    }
  }, [cameraPreset, scenePanels, hiddenPanelIds]);

  // Dedicated Babylon 3D Real-Room Textured Relief Panels effect (independent of 10Hz LiDAR updates!)
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || scene.isDisposed) return;

    const disposePanels = () => {
      for (const m of scenePanelMeshesRef.current) {
        m.dispose();
      }
      scenePanelMeshesRef.current = [];
      for (const mat of scenePanelMaterialsRef.current) {
        mat.dispose();
      }
      scenePanelMaterialsRef.current = [];
      for (const tex of scenePanelTexturesRef.current) {
        tex.dispose();
      }
      scenePanelTexturesRef.current = [];
    };

    disposePanels();

    const hidden = new Set(hiddenPanelIds);
    const visible = (Array.isArray(scenePanels) ? scenePanels : []).filter(
      (p) => !hidden.has(p.id) && (p.mesh?.positions?.length ?? 0) >= 9 && (p.mesh?.indices?.length ?? 0) >= 3
    );
    if (visible.length === 0) return;

    for (const panel of visible) {
      const meshData = panel.mesh;
      const vCount = Math.floor(meshData.positions.length / 3);
      const bPositions = new Array<number>(vCount * 3);
      for (let i = 0; i < vCount; i++) {
        bPositions[i * 3] = meshData.positions[i * 3];
        bPositions[i * 3 + 1] = meshData.positions[i * 3 + 1];
        bPositions[i * 3 + 2] = -meshData.positions[i * 3 + 2];
      }

      const bNormals = new Array<number>(vCount * 3);
      if (meshData.normals && meshData.normals.length === meshData.positions.length) {
        for (let i = 0; i < vCount; i++) {
          bNormals[i * 3] = meshData.normals[i * 3];
          bNormals[i * 3 + 1] = meshData.normals[i * 3 + 1];
          bNormals[i * 3 + 2] = -meshData.normals[i * 3 + 2];
        }
      }

      // Flip winding [i0, i1, i2] -> [i0, i2, i1] for Babylon left-handed coordinates
      const triCount = Math.floor(meshData.indices.length / 3);
      const bIndices = new Array<number>(triCount * 3);
      for (let t = 0; t < triCount; t++) {
        bIndices[t * 3] = meshData.indices[t * 3];
        bIndices[t * 3 + 1] = meshData.indices[t * 3 + 2];
        bIndices[t * 3 + 2] = meshData.indices[t * 3 + 1];
      }

      const applyGeometry = (targetMesh: Mesh) => {
        const vd = new VertexData();
        vd.positions = bPositions;
        vd.indices = bIndices;
        if (meshData.uvs && meshData.uvs.length > 0) {
          vd.uvs = meshData.uvs;
        }
        if (meshData.normals && meshData.normals.length === meshData.positions.length) {
          vd.normals = bNormals;
        } else {
          const computed: number[] = [];
          VertexData.ComputeNormals(bPositions, bIndices, computed);
          vd.normals = computed;
        }
        vd.applyToMesh(targetMesh);
      };

      if (sceneRenderMode === "wireframe") {
        const backMesh = new Mesh(`scenePanelBack_${panel.id}`, scene);
        applyGeometry(backMesh);
        const backMat = new StandardMaterial(`scenePanelBackMat_${panel.id}`, scene);
        backMat.diffuseColor = Color3.FromHexString("#0b1220");
        backMat.emissiveColor = Color3.FromHexString("#070c16");
        backMat.alpha = 0.25;
        backMat.backFaceCulling = false;
        backMesh.material = backMat;
        scenePanelMeshesRef.current.push(backMesh);
        scenePanelMaterialsRef.current.push(backMat);

        const wireMesh = new Mesh(`scenePanel_${panel.id}`, scene);
        applyGeometry(wireMesh);
        const wireMat = new StandardMaterial(`scenePanelWireMat_${panel.id}`, scene);
        wireMat.emissiveColor = Color3.FromHexString("#38bdf8");
        wireMat.diffuseColor = Color3.FromHexString("#E05A10");
        wireMat.wireframe = true;
        wireMat.backFaceCulling = false;
        wireMesh.material = wireMat;
        scenePanelMeshesRef.current.push(wireMesh);
        scenePanelMaterialsRef.current.push(wireMat);
      } else {
        const panelMesh = new Mesh(`scenePanel_${panel.id}`, scene);
        applyGeometry(panelMesh);

        const texUrl = resolveBackendAssetUrl(panel.texture_url);
        const normalUrl = resolveBackendAssetUrl(panel.normal_map_url);
        let tex: Texture | null = null;
        if (texUrl) {
          tex = new Texture(texUrl, scene, false, true);
          scenePanelTexturesRef.current.push(tex);
        }
        let normalTex: Texture | null = null;
        if (normalUrl) {
          normalTex = new Texture(normalUrl, scene, false, true);
          normalTex.level = 0.85;
          scenePanelTexturesRef.current.push(normalTex);
        }

        const pbr = new PBRMaterial(`scenePanelPbr_${panel.id}`, scene);
        if (tex) {
          pbr.albedoTexture = tex;
        } else {
          pbr.albedoColor = Color3.FromHexString("#cbd5e1");
        }
        if (normalTex) {
          pbr.bumpTexture = normalTex;
        }
        pbr.backFaceCulling = false;

        if (sceneRenderMode === "translucent") {
          pbr.metallic = 0.08;
          pbr.roughness = 0.65;
          pbr.alpha = 0.45;
          pbr.transparencyMode = Material.MATERIAL_ALPHABLEND;
          pbr.needDepthPrePass = false;
        } else {
          pbr.metallic = 0.05;
          pbr.roughness = 0.82;
          pbr.emissiveColor = new Color3(0.06, 0.06, 0.06);
        }

        panelMesh.material = pbr;
        scenePanelMeshesRef.current.push(panelMesh);
        scenePanelMaterialsRef.current.push(pbr);
      }
    }

    return () => {
      disposePanels();
    };
  }, [scenePanels, sceneRenderMode, hiddenPanelIds]);

  // Rebuild walls, PBR equipment cabinets, Dark Zones, NBV beacons, anomalies, and GPU point cloud
  useEffect(() => {
    const scene = sceneRef.current;
    const highlight = highlightRef.current;
    if (!scene || !highlight || scene.isDisposed) return;

    // Dispose previous dynamic meshes & materials cleanly (prevents 10Hz GPU shader/material leaks)
    for (const m of dynamicMeshesRef.current) {
      highlight.removeMesh(m);
      m.dispose();
    }
    dynamicMeshesRef.current = [];
    for (const mat of dynamicMaterialsRef.current) {
      mat.dispose();
    }
    dynamicMaterialsRef.current = [];

    const wallHeight = frame?.wall_height_m || 2.8;
    const walls = Array.isArray(frame?.walls) ? frame.walls : [];
    const safeEquipment = Array.isArray(equipment) ? equipment : [];
    const safeDarkZones = Array.isArray(darkZones) ? darkZones : [];
    const anomalies = Array.isArray(frame?.anomalies) ? frame.anomalies : [];

    const wallPbr = new PBRMaterial("wallPbr", scene);
    wallPbr.albedoColor = Color3.FromHexString("#222731");
    wallPbr.emissiveColor = Color3.FromHexString("#0b0f16");
    wallPbr.metallic = 0.2;
    wallPbr.roughness = 0.6;
    wallPbr.alpha = 0.82;
    dynamicMaterialsRef.current.push(wallPbr);

    const railMat = new StandardMaterial("railMat", scene);
    railMat.emissiveColor = Color3.FromHexString("#38bdf8");
    dynamicMaterialsRef.current.push(railMat);

    // 1. Extruded Architectural Walls + glowing Eigenia Sky top rail
    walls.forEach((w, idx) => {
      const length = Math.max(w.length_m || 0.08, 0.08);
      const wall = MeshBuilder.CreateBox(`wall_${idx}`, { width: length, height: wallHeight, depth: 0.14 }, scene);
      const cx = (w.x1 + w.x2) / 2;
      const cy = (w.y1 + w.y2) / 2;
      const angle = Math.atan2(w.y2 - w.y1, w.x2 - w.x1);
      wall.position = new Vector3(cx, wallHeight / 2, cy);
      wall.rotation.y = -angle;
      wall.material = wallPbr;
      dynamicMeshesRef.current.push(wall);

      const rail = MeshBuilder.CreateBox(`rail_${idx}`, { width: length, height: 0.035, depth: 0.16 }, scene);
      rail.position = new Vector3(cx, wallHeight + 0.02, cy);
      rail.rotation.y = -angle;
      rail.material = railMat;
      dynamicMeshesRef.current.push(rail);
    });

    // 2. PBR Equipment Twins with Completeness HighlightLayer halos
    safeEquipment.forEach((eq) => {
      const h = eq.height_m || 1.6;
      const box = MeshBuilder.CreateBox(
        `eq_${eq.id}`,
        { width: eq.width_m || 0.75, height: h, depth: eq.depth_m || 0.75 },
        scene
      );
      box.position = new Vector3(eq.x, h / 2, eq.y);
      box.rotation.y = -((eq.yaw_deg || 0) * Math.PI) / 180;

      const mat = new PBRMaterial(`eqMat_${eq.id}`, scene);
      const status = eq.completeness?.status ?? "INCOMPLETE";
      const hex =
        eq.id === selectedEquipmentId
          ? "#38bdf8"
          : status === "DARK"
          ? "#ef4444"
          : status === "INCOMPLETE"
          ? "#f59e0b"
          : "#E05A10";
      mat.albedoColor = Color3.FromHexString(hex);
      mat.metallic = 0.55;
      mat.roughness = 0.35;
      mat.alpha = 0.88;
      box.material = mat;
      dynamicMaterialsRef.current.push(mat);

      if (eq.id === selectedEquipmentId) {
        highlight.addMesh(box, Color3.FromHexString("#38bdf8"));
      } else if (status === "DARK") {
        highlight.addMesh(box, Color3.FromHexString("#ef4444"));
      } else if (status === "INCOMPLETE") {
        highlight.addMesh(box, Color3.FromHexString("#f59e0b"));
      }

      box.isPickable = true;
      box.metadata = { equipmentId: eq.id };
      dynamicMeshesRef.current.push(box);
    });

    // 3. Spatial Dark-Zone shadow volumes & glowing Next-Best-View (NBV) waypoint beacons
    if (showDarkZones && safeDarkZones.length > 0) {
      const darkMat = new StandardMaterial("darkZoneMat", scene);
      darkMat.diffuseColor = Color3.FromHexString("#ef4444");
      darkMat.emissiveColor = Color3.FromHexString("#7f1d1d");
      darkMat.alpha = 0.24;
      dynamicMaterialsRef.current.push(darkMat);

      const nbvMat = new StandardMaterial("nbvMat", scene);
      nbvMat.emissiveColor = Color3.FromHexString("#f59e0b");
      dynamicMaterialsRef.current.push(nbvMat);

      safeDarkZones.forEach((dz, idx) => {
        const radius = Math.max(0.4, Math.sqrt(Math.max(0.1, dz.area_m2) / Math.PI));
        const shadowDisc = MeshBuilder.CreateCylinder(
          `dark_${idx}`,
          { diameter: radius * 2, height: 0.08, tessellation: 24 },
          scene
        );
        shadowDisc.position = new Vector3(dz.centroid_x, 0.04, dz.centroid_y);
        shadowDisc.material = darkMat;
        highlight.addMesh(shadowDisc, Color3.FromHexString("#f59e0b"));
        dynamicMeshesRef.current.push(shadowDisc);

        const nbvBeacon = MeshBuilder.CreateCylinder(
          `nbv_${idx}`,
          { diameterTop: 0.04, diameterBottom: 0.22, height: 0.65, tessellation: 12 },
          scene
        );
        nbvBeacon.position = new Vector3(dz.nbv_x, 0.34, dz.nbv_y);
        nbvBeacon.material = nbvMat;
        dynamicMeshesRef.current.push(nbvBeacon);
      });
    }

    // 4. Physical Change Anomalies
    if (anomalies.length > 0) {
      const anomMat = new StandardMaterial("anomMat", scene);
      anomMat.emissiveColor = Color3.FromHexString("#ef4444");
      anomMat.wireframe = true;
      dynamicMaterialsRef.current.push(anomMat);
      anomalies.forEach((a, idx) => {
        const cyl = MeshBuilder.CreateCylinder(`anom_${idx}`, { diameter: 0.75, height: 1.1 }, scene);
        cyl.position = new Vector3(a.centroid_x, 0.55, a.centroid_y);
        cyl.material = anomMat;
        highlight.addMesh(cyl, Color3.FromHexString("#ef4444"));
        dynamicMeshesRef.current.push(cyl);
      });
    }

    // 4b. Add-On A: Live 3D PuppyPi Avatar Mirror (body + 4 legs + translucent orange FOV cone)
    const pose = frame?.robot_pose;
    const robotBodyMat = new PBRMaterial("puppyBodyMat", scene);
    robotBodyMat.albedoColor = Color3.FromHexString("#202632");
    robotBodyMat.emissiveColor = Color3.FromHexString(pose?.live ? "#522107" : "#1f0e04");
    robotBodyMat.metallic = 0.55;
    robotBodyMat.roughness = 0.35;
    dynamicMaterialsRef.current.push(robotBodyMat);

    const robotAccentMat = new StandardMaterial("puppyAccentMat", scene);
    robotAccentMat.emissiveColor = Color3.FromHexString("#E05A10");
    dynamicMaterialsRef.current.push(robotAccentMat);

    const fovMat = new StandardMaterial("puppyFovMat", scene);
    fovMat.emissiveColor = Color3.FromHexString("#E05A10");
    fovMat.alpha = pose?.live ? 0.2 : 0.11;
    fovMat.backFaceCulling = false;
    dynamicMaterialsRef.current.push(fovMat);

    const rx = pose?.x ?? 0;
    const rz = pose?.y ?? 0;
    const yawRad = -((pose?.yaw_deg ?? 0) * Math.PI) / 180;
    const pitchRad = ((pose?.pitch_deg ?? 0) * Math.PI) / 180;
    const rollRad = ((pose?.roll_deg ?? 0) * Math.PI) / 180;

    const puppyBody = MeshBuilder.CreateBox("puppyBody", { width: 0.42, height: 0.11, depth: 0.24 }, scene);
    puppyBody.position = new Vector3(rx, 0.24, rz);
    puppyBody.rotation = new Vector3(rollRad, yawRad, pitchRad);
    puppyBody.material = robotBodyMat;
    dynamicMeshesRef.current.push(puppyBody);

    if (puppyStlMeshRef.current && puppyStlMatRef.current) {
      puppyBody.isVisible = false;
      const stlMesh = puppyStlMeshRef.current;
      const stlMat = puppyStlMatRef.current;
      stlMesh.position = new Vector3(rx, 0.01, rz);
      stlMesh.rotation = new Vector3(rollRad, yawRad, pitchRad);
      stlMat.wireframe = sceneRenderMode === "wireframe";
      stlMat.alpha = sceneRenderMode === "translucent" ? 0.48 : 1.0;
      stlMat.emissiveColor = Color3.FromHexString(
        sceneRenderMode === "wireframe" ? "#38bdf8" : pose?.live ? "#522107" : "#1f0e04"
      );
    } else {
      const puppyCowl = MeshBuilder.CreateBox("puppyCowl", { width: 0.34, height: 0.03, depth: 0.18 }, scene);
      puppyCowl.parent = puppyBody;
      puppyCowl.position = new Vector3(0, 0.07, 0);
      puppyCowl.material = robotAccentMat;
      dynamicMeshesRef.current.push(puppyCowl);

      [
        [0.14, 0.11],
        [0.14, -0.11],
        [-0.14, 0.11],
        [-0.14, -0.11],
      ].forEach(([lx, lz], idx) => {
        const leg = MeshBuilder.CreateBox(`puppyLeg_${idx}`, { width: 0.05, height: 0.2, depth: 0.045 }, scene);
        leg.parent = puppyBody;
        leg.position = new Vector3(lx, -0.12, lz);
        leg.material = robotBodyMat;
        dynamicMeshesRef.current.push(leg);
      });
    }

    const fovCone = MeshBuilder.CreateCylinder(
      "puppyFovCone",
      { diameterTop: 1.35, diameterBottom: 0.05, height: 1.5, tessellation: 16 },
      scene
    );
    fovCone.parent = puppyBody;
    fovCone.rotation.z = -Math.PI / 2;
    fovCone.position = new Vector3(0.95, 0.02, 0);
    fovCone.material = fovMat;
    dynamicMeshesRef.current.push(fovCone);

    // 4c. Glowing 3D Moving-Object Markers
    const activeMoving = (Array.isArray(frame?.moving_objects) ? frame.moving_objects : []).filter(
      (t) => t.is_moving
    );
    if (activeMoving.length > 0) {
      const moverMat = new StandardMaterial("moverMat", scene);
      moverMat.emissiveColor = Color3.FromHexString("#10b981");
      moverMat.alpha = 0.88;
      dynamicMaterialsRef.current.push(moverMat);

      activeMoving.forEach((track) => {
        const orb = MeshBuilder.CreateSphere(`mover_${track.track_id}`, { diameter: 0.32, segments: 14 }, scene);
        orb.position = new Vector3(track.x, 0.55, track.y);
        orb.material = moverMat;
        highlight.addMesh(orb, Color3.FromHexString("#E05A10"));
        dynamicMeshesRef.current.push(orb);

        const baseRing = MeshBuilder.CreateCylinder(
          `moverRing_${track.track_id}`,
          { diameter: 0.52, height: 0.04, tessellation: 20 },
          scene
        );
        baseRing.position = new Vector3(track.x, 0.03, track.y);
        baseRing.material = robotAccentMat;
        dynamicMeshesRef.current.push(baseRing);
      });
    }

    // 5. GPU PointsCloudSystem (PCS) for live LD19 sweep with async cancellation token
    const token = ++pcsBuildTokenRef.current;
    pcsRef.current?.dispose();
    pcsRef.current = null;
    const pts = Array.isArray(frame?.points) ? frame.points : [];
    if (showPointCloud && pts.length > 0) {
      const pcs = new PointsCloudSystem("lidarPCS", 4, scene);
      pcs.addPoints(pts.length, (particle: { position: Vector3; color: Color4 | null }, i: number) => {
        const [x, y, intensity] = pts[i];
        particle.position = new Vector3(x, 0.45, y);
        const t = Math.max(0, Math.min(1, intensity / 255));
        particle.color = new Color4(
          (56 + t * (224 - 56)) / 255,
          (189 + t * (90 - 189)) / 255,
          (248 + t * (16 - 248)) / 255,
          1.0
        );
      });
      pcs
        .buildMeshAsync()
        .then(() => {
          if (token !== pcsBuildTokenRef.current || scene.isDisposed) {
            pcs.dispose();
          } else {
            pcsRef.current = pcs;
          }
        })
        .catch(() => {
          pcs.dispose();
        });
    }
  }, [frame, equipment, darkZones, selectedEquipmentId, showDarkZones, showPointCloud, sceneRenderMode]);

  const visiblePanelCount = (Array.isArray(scenePanels) ? scenePanels : []).filter(
    (p) => !hiddenPanelIds.includes(p.id)
  ).length;

  return (
    <div className="relative flex h-[560px] w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge variant="default">
            <Sparkles className="h-3 w-3" /> BABYLON.JS PBR + GLOW + STENCIL
          </Badge>
          <Button
            size="sm"
            variant={cameraPreset === "iso" ? "default" : "secondary"}
            onClick={() => setCameraPreset("iso")}
          >
            Isometric
          </Button>
          <Button
            size="sm"
            variant={cameraPreset === "top" ? "default" : "secondary"}
            onClick={() => setCameraPreset("top")}
          >
            <Compass className="h-3.5 w-3.5" /> Top CAD
          </Button>
          <Button
            size="sm"
            variant={cameraPreset === "rover" ? "default" : "secondary"}
            onClick={() => setCameraPreset("rover")}
          >
            <Eye className="h-3.5 w-3.5" /> PuppyPi POV
          </Button>
          {scenePanels.length > 0 && (
            <Button
              size="sm"
              variant={cameraPreset === "wall" ? "default" : "secondary"}
              onClick={() => setCameraPreset("wall")}
            >
              <Camera className="h-3.5 w-3.5" /> Front Wall
            </Button>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant={showDarkZones ? "sky" : "outline"}
            onClick={() => setShowDarkZones((v) => !v)}
          >
            <Layers className="h-3.5 w-3.5" /> Dark Zones & NBV ({darkZones.length})
          </Button>
          <Button
            size="sm"
            variant={showPointCloud ? "sky" : "outline"}
            onClick={() => setShowPointCloud((v) => !v)}
          >
            LiDAR PCS
          </Button>
        </div>
      </div>

      {webglError ? (
        <div className="flex flex-1 items-center justify-center p-6 font-mono text-xs text-eigenia-amber">
          {webglError}
        </div>
      ) : (
        <canvas ref={canvasRef} className="h-full w-full flex-1 outline-none" />
      )}

      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-2">
        <Badge variant="fault">Red Halo = DARK Asset (&lt;45%)</Badge>
        <Badge variant="amber">Amber Halo = INCOMPLETE / NBV Beacon</Badge>
        <Badge variant="default">Orange PBR = VERIFIED Twin</Badge>
        {visiblePanelCount > 0 && (
          <Badge variant="sky">
            3D Panels: {visiblePanelCount} ({sceneRenderMode})
          </Badge>
        )}
      </div>
    </div>
  );
}
