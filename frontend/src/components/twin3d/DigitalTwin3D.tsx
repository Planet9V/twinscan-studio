"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, Camera, Compass, Eye, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { resolveBackendAssetUrl } from "@/lib/api";
import {
  applyPuppyCadRenderMode,
  disposePuppyThreeMaterials,
  loadPuppyPiThreeModel,
} from "@/lib/puppyModelLoader";
import type {
  EquipmentAsset,
  FocusTarget,
  LidarFrame,
  ScenePanelRecord,
  SceneRenderMode,
  SpatialDarkZone,
} from "@/lib/types";

interface DigitalTwin3DProps {
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

function disposeMaterial(mat: THREE.Material) {
  const m = mat as THREE.Material & {
    map?: THREE.Texture | null;
    normalMap?: THREE.Texture | null;
  };
  if (m.map) {
    m.map.dispose();
    m.map = null;
  }
  if (m.normalMap) {
    m.normalMap.dispose();
    m.normalMap = null;
  }
  mat.dispose();
}

function disposeObject3D(root: THREE.Object3D) {
  root.traverse((obj) => {
    if (
      obj instanceof THREE.Mesh ||
      obj instanceof THREE.Points ||
      obj instanceof THREE.Line ||
      obj instanceof THREE.LineSegments
    ) {
      obj.geometry?.dispose();
      const mat = obj.material;
      if (Array.isArray(mat)) {
        mat.forEach((m) => disposeMaterial(m));
      } else if (mat) {
        disposeMaterial(mat);
      }
    }
  });
}

function computePanelCenter(panel: ScenePanelRecord): [number, number, number] {
  const pos = panel.mesh?.positions ?? [];
  if (pos.length < 3) {
    const d = panel.mean_distance_m || 1.8;
    const yawRad = ((panel.pose?.yaw_deg ?? 0) * Math.PI) / 180;
    return [
      (panel.pose?.x ?? 0) + Math.sin(yawRad) * d,
      Math.max(0.5, panel.pose?.z ?? 0.5),
      -(panel.pose?.y ?? 0) - Math.cos(yawRad) * d,
    ];
  }
  let sx = 0;
  let sy = 0;
  let sz = 0;
  const count = Math.floor(pos.length / 3);
  for (let i = 0; i < count; i++) {
    sx += pos[i * 3];
    sy += pos[i * 3 + 1];
    sz += pos[i * 3 + 2];
  }
  return [sx / count, sy / count, sz / count];
}

export default function DigitalTwin3D({
  frame,
  equipment,
  darkZones,
  selectedEquipmentId,
  focusTarget,
  onSelectEquipment,
  scenePanels = [],
  sceneRenderMode = "solid",
  hiddenPanelIds = [],
}: DigitalTwin3DProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const dynamicGroupRef = useRef<THREE.Group | null>(null);
  const pointsGroupRef = useRef<THREE.Group | null>(null);
  const scenePanelsGroupRef = useRef<THREE.Group | null>(null);
  const puppyHighResAnchorRef = useRef<THREE.Group | null>(null);
  const puppyHighResLoadedRef = useRef<boolean>(false);
  const pickableMeshesRef = useRef<THREE.Mesh[]>([]);
  const prevPanelCountRef = useRef<number>(0);
  const onSelectRef = useRef(onSelectEquipment);
  onSelectRef.current = onSelectEquipment;

  const [webglError, setWebglError] = useState<string | null>(null);
  const [showDarkZones, setShowDarkZones] = useState(true);
  const [showPointCloud, setShowPointCloud] = useState(true);
  const [cameraPreset, setCameraPreset] = useState<"iso" | "top" | "rover" | "wall">("iso");

  // Initialize direct Three.js WebGLRenderer + OrbitControls (Next.js 15 App Router safe)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer | null = null;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    } catch (err) {
      console.error("[DigitalTwin3D] WebGL initialization failed:", err);
      setWebglError("WebGL 3D context could not be initialized in this browser.");
      return;
    }

    setWebglError(null);
    const width = Math.max(container.clientWidth, 320);
    const height = Math.max(container.clientHeight, 320);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.setClearColor(0x0b0d10, 1);
    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0b0d10");

    const camera = new THREE.PerspectiveCamera(48, width / height, 0.1, 120);
    camera.position.set(0, 7.5, 8.5);
    cameraRef.current = camera;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxDistance = 32;
    controls.minDistance = 1.5;
    controls.target.set(0, 0.4, 0);
    controls.update();
    controlsRef.current = controls;

    // Lighting
    const ambient = new THREE.AmbientLight(0xffffff, 0.75);
    scene.add(ambient);

    const dirLight = new THREE.DirectionalLight(0xe2e8f0, 1.15);
    dirLight.position.set(6, 12, 8);
    scene.add(dirLight);

    const pointLight = new THREE.PointLight(0x38bdf8, 0.9, 30);
    pointLight.position.set(0, 3.2, 0);
    scene.add(pointLight);

    // Metric grid
    const gridHelper = new THREE.GridHelper(24, 48, 0x293242, 0x1e2430);
    scene.add(gridHelper);

    // LiDAR origin sensor beacon
    const originGeo = new THREE.CylinderGeometry(0.14, 0.16, 0.3, 24);
    const originMat = new THREE.MeshStandardMaterial({
      color: 0xe05a10,
      emissive: 0xe05a10,
      emissiveIntensity: 0.45,
    });
    const originMesh = new THREE.Mesh(originGeo, originMat);
    originMesh.position.set(0, 0.15, 0);
    scene.add(originMesh);

    const dynamicGroup = new THREE.Group();
    const pointsGroup = new THREE.Group();
    const scenePanelsGroup = new THREE.Group();
    const puppyHighResAnchor = new THREE.Group();
    scene.add(dynamicGroup);
    scene.add(pointsGroup);
    scene.add(scenePanelsGroup);
    scene.add(puppyHighResAnchor);
    dynamicGroupRef.current = dynamicGroup;
    pointsGroupRef.current = pointsGroup;
    scenePanelsGroupRef.current = scenePanelsGroup;
    puppyHighResAnchorRef.current = puppyHighResAnchor;
    puppyHighResLoadedRef.current = false;

    let unmounted = false;
    void loadPuppyPiThreeModel(0.46)
      .then((highResPuppy) => {
        if (unmounted) {
          disposePuppyThreeMaterials(highResPuppy);
          return;
        }
        applyPuppyCadRenderMode(highResPuppy, "solid", true);
        puppyHighResAnchor.add(highResPuppy);
        puppyHighResLoadedRef.current = true;
      })
      .catch(() => {
        // Keep procedural fallback avatar when model asset is unavailable
      });

    // Raycast click picking on equipment boxes
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const handlePointerDown = (e: PointerEvent) => {
      if (!renderer) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickableMeshesRef.current, false);
      const eqId = hits[0]?.object?.userData?.equipmentId as string | undefined;
      if (eqId) {
        onSelectRef.current(eqId);
      }
    };
    renderer.domElement.addEventListener("pointerdown", handlePointerDown);

    // Resize handling
    const handleResize = () => {
      if (!container || !renderer) return;
      const w = Math.max(container.clientWidth, 320);
      const h = Math.max(container.clientHeight, 320);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const resizeObs = new ResizeObserver(handleResize);
    resizeObs.observe(container);

    let rafId = 0;
    const animate = () => {
      rafId = window.requestAnimationFrame(animate);
      controls.update();
      renderer?.render(scene, camera);
    };
    animate();

    return () => {
      unmounted = true;
      window.cancelAnimationFrame(rafId);
      resizeObs.disconnect();
      renderer?.domElement.removeEventListener("pointerdown", handlePointerDown);
      controls.dispose();
      disposeObject3D(dynamicGroup);
      disposeObject3D(pointsGroup);
      disposeObject3D(scenePanelsGroup);
      disposePuppyThreeMaterials(puppyHighResAnchor);
      puppyHighResAnchor.clear();
      originGeo.dispose();
      originMat.dispose();
      gridHelper.dispose();
      renderer?.dispose();
      dynamicGroupRef.current = null;
      pointsGroupRef.current = null;
      scenePanelsGroupRef.current = null;
      puppyHighResAnchorRef.current = null;
      puppyHighResLoadedRef.current = false;
      cameraRef.current = null;
      controlsRef.current = null;
      pickableMeshesRef.current = [];
    };
  }, []);

  // Auto-frame when the first real-room 3D panel is captured (0 -> >=1)
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
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    if (cameraPreset === "top") {
      camera.position.set(0, 14, 0.01);
      controls.target.set(0, 0, 0);
    } else if (cameraPreset === "rover") {
      camera.position.set(0, 1.3, 3.6);
      controls.target.set(0, 0.45, -2.0);
    } else if (cameraPreset === "wall") {
      const hidden = new Set(hiddenPanelIds);
      const visible = (Array.isArray(scenePanels) ? scenePanels : []).filter((p) => !hidden.has(p.id));
      const latest = visible[visible.length - 1] ?? scenePanels[scenePanels.length - 1];
      if (latest) {
        const [cx, cy, cz] = computePanelCenter(latest);
        const px = latest.pose?.x ?? 0;
        const pz = -(latest.pose?.y ?? 0);
        const dx = px - cx;
        const dz = pz - cz;
        const dist = Math.hypot(dx, dz) || 1.8;
        const backScale = Math.max(1.25, (dist + 0.9) / dist);
        camera.position.set(cx + dx * backScale, Math.max(0.9, cy + 0.45), cz + dz * backScale);
        controls.target.set(cx, cy, cz);
      } else {
        camera.position.set(0, 1.1, 1.6);
        controls.target.set(0, 0.6, -1.8);
      }
    } else {
      camera.position.set(0, 7.5, 8.5);
      controls.target.set(0, 0.4, 0);
    }
    controls.update();
  }, [cameraPreset, scenePanels, hiddenPanelIds]);

  // Dedicated 3D real-room textured relief panels effect (independent of 10Hz LiDAR updates!)
  useEffect(() => {
    const group = scenePanelsGroupRef.current;
    if (!group) return;

    let cancelled = false;
    const loadedTextures: THREE.Texture[] = [];

    disposeObject3D(group);
    group.clear();

    const hidden = new Set(hiddenPanelIds);
    const visible = (Array.isArray(scenePanels) ? scenePanels : []).filter(
      (p) => !hidden.has(p.id) && (p.mesh?.positions?.length ?? 0) >= 9 && (p.mesh?.indices?.length ?? 0) >= 3
    );
    if (visible.length === 0) return;

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");

    for (const panel of visible) {
      const meshData = panel.mesh;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(meshData.positions, 3));
      if (meshData.normals && meshData.normals.length === meshData.positions.length) {
        geo.setAttribute("normal", new THREE.Float32BufferAttribute(meshData.normals, 3));
      }
      if (meshData.uvs && meshData.uvs.length > 0) {
        geo.setAttribute("uv", new THREE.Float32BufferAttribute(meshData.uvs, 2));
      }
      geo.setIndex(meshData.indices);
      if (!meshData.normals || meshData.normals.length !== meshData.positions.length) {
        geo.computeVertexNormals();
      }

      if (sceneRenderMode === "wireframe") {
        const backGeo = geo.clone();
        const backMat = new THREE.MeshBasicMaterial({
          color: 0x0b1220,
          transparent: true,
          opacity: 0.25,
          side: THREE.DoubleSide,
          depthWrite: false,
        });
        group.add(new THREE.Mesh(backGeo, backMat));

        const wireMat = new THREE.MeshBasicMaterial({
          color: 0x38bdf8,
          wireframe: true,
          transparent: true,
          opacity: 0.88,
        });
        group.add(new THREE.Mesh(geo, wireMat));

        const edgeGeo = new THREE.EdgesGeometry(geo, 36);
        const edgeMat = new THREE.LineBasicMaterial({
          color: 0xe05a10,
          transparent: true,
          opacity: 0.55,
        });
        group.add(new THREE.LineSegments(edgeGeo, edgeMat));
      } else {
        const texUrl = resolveBackendAssetUrl(panel.texture_url);
        const normalUrl = resolveBackendAssetUrl(panel.normal_map_url);
        const mat =
          sceneRenderMode === "translucent"
            ? new THREE.MeshStandardMaterial({
                color: 0xffffff,
                transparent: true,
                opacity: 0.45,
                depthWrite: false,
                roughness: 0.55,
                metalness: 0.1,
                side: THREE.DoubleSide,
              })
            : new THREE.MeshStandardMaterial({
                color: 0xffffff,
                roughness: 0.78,
                metalness: 0.06,
                side: THREE.DoubleSide,
              });

        if (texUrl) {
          loader.load(
            texUrl,
            (tex) => {
              if (cancelled) {
                tex.dispose();
                return;
              }
              tex.colorSpace = THREE.SRGBColorSpace;
              tex.needsUpdate = true;
              loadedTextures.push(tex);
              mat.map = tex;
              mat.needsUpdate = true;
            },
            undefined,
            (err) => {
              console.error("[DigitalTwin3D] Texture load error:", texUrl, err);
            }
          );
        }

        if (normalUrl) {
          loader.load(
            normalUrl,
            (nTex) => {
              if (cancelled) {
                nTex.dispose();
                return;
              }
              nTex.colorSpace = THREE.NoColorSpace;
              nTex.needsUpdate = true;
              loadedTextures.push(nTex);
              mat.normalMap = nTex;
              mat.normalScale = new THREE.Vector2(1.15, 1.15);
              mat.needsUpdate = true;
            },
            undefined,
            (err) => {
              console.error("[DigitalTwin3D] Normal map load error:", normalUrl, err);
            }
          );
        }

        const panelMesh = new THREE.Mesh(geo, mat);
        panelMesh.name = `scenePanel_${panel.id}`;
        group.add(panelMesh);
      }
    }

    return () => {
      cancelled = true;
      for (const tex of loadedTextures) {
        tex.dispose();
      }
      disposeObject3D(group);
      group.clear();
    };
  }, [scenePanels, sceneRenderMode, hiddenPanelIds]);

  // Smoothly focus camera on selected focusTarget
  useEffect(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls || !focusTarget) return;
    camera.position.set(focusTarget.x + 3.5, 4.5, -focusTarget.y + 4.0);
    controls.target.set(focusTarget.x, 0.7, -focusTarget.y);
    controls.update();
  }, [focusTarget]);

  // Update walls, dark zones, equipment boxes, and anomalies
  useEffect(() => {
    const group = dynamicGroupRef.current;
    if (!group) return;

    disposeObject3D(group);
    group.clear();
    const pickables: THREE.Mesh[] = [];

    const wallHeight = frame?.wall_height_m || 2.8;
    const walls = Array.isArray(frame?.walls) ? frame.walls : [];
    const safeEquipment = Array.isArray(equipment) ? equipment : [];
    const safeDarkZones = Array.isArray(darkZones) ? darkZones : [];
    const anomalies = Array.isArray(frame?.anomalies) ? frame.anomalies : [];

    // 1. Extruded RANSAC walls + glowing Eigenia Sky top rail
    if (walls.length > 0) {
      const wallMat = new THREE.MeshStandardMaterial({
        color: 0x15171b,
        transparent: true,
        opacity: 0.76,
      });
      const railMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });

      for (const w of walls) {
        const len = Math.max(w.length_m || 0.08, 0.08);
        const cx = (w.x1 + w.x2) / 2;
        const cy = (w.y1 + w.y2) / 2;
        const angle = Math.atan2(w.y2 - w.y1, w.x2 - w.x1);

        const wallGroup = new THREE.Group();
        wallGroup.position.set(cx, wallHeight / 2, -cy);
        wallGroup.rotation.y = angle;

        const wallMesh = new THREE.Mesh(new THREE.BoxGeometry(len, wallHeight, 0.12), wallMat);
        const railMesh = new THREE.Mesh(new THREE.BoxGeometry(len, 0.03, 0.13), railMat);
        railMesh.position.y = wallHeight / 2 + 0.015;

        wallGroup.add(wallMesh);
        wallGroup.add(railMesh);
        group.add(wallGroup);
      }
    }

    // 2. Spatial Dark Zones & Next-Best-View waypoint beacons
    if (showDarkZones && safeDarkZones.length > 0) {
      const darkMat = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        transparent: true,
        opacity: 0.28,
      });
      const nbvMat = new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: 0xf59e0b,
        emissiveIntensity: 0.5,
      });

      for (const dz of safeDarkZones) {
        const radius = Math.max(0.35, Math.sqrt(Math.max(0.1, dz.area_m2) / Math.PI));
        const disc = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.06, 20), darkMat);
        disc.position.set(dz.centroid_x, 0.04, -dz.centroid_y);
        group.add(disc);

        const beacon = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.55, 12), nbvMat);
        beacon.position.set(dz.nbv_x, 0.35, -dz.nbv_y);
        group.add(beacon);
      }
    }

    // 3. Placed equipment twins colored by completeness status
    for (const eq of safeEquipment) {
      const isSelected = eq.id === selectedEquipmentId;
      const status = eq.completeness?.status ?? "INCOMPLETE";
      const h = eq.height_m || 1.6;
      const colorHex = isSelected
        ? 0x38bdf8
        : status === "DARK"
        ? 0xef4444
        : status === "INCOMPLETE"
        ? 0xf59e0b
        : 0xe05a10;

      const box = new THREE.Mesh(
        new THREE.BoxGeometry(eq.width_m || 0.75, h, eq.depth_m || 0.75),
        new THREE.MeshStandardMaterial({
          color: colorHex,
          transparent: true,
          opacity: isSelected ? 0.9 : 0.72,
        })
      );
      box.position.set(eq.x, h / 2, -eq.y);
      box.rotation.y = ((eq.yaw_deg || 0) * Math.PI) / 180;
      box.userData = { equipmentId: eq.id };
      group.add(box);
      pickables.push(box);
    }

    // 4. Physical change anomalies
    if (anomalies.length > 0) {
      const anomMat = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        transparent: true,
        opacity: 0.55,
        wireframe: true,
      });
      for (const a of anomalies) {
        const cyl = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 1.0, 20), anomMat);
        cyl.position.set(a.centroid_x, 0.5, -a.centroid_y);
        group.add(cyl);
      }
    }

    // 5. Add-On A: Live 3D PuppyPi Avatar Mirror (High-Res 10,022-Tri GLB + orange camera FOV cone)
    const pose = frame?.robot_pose;
    const puppyGroup = new THREE.Group();
    puppyGroup.position.set(pose?.x ?? 0, 0.24, -(pose?.y ?? 0));
    puppyGroup.rotation.order = "YXZ";
    puppyGroup.rotation.y = ((pose?.yaw_deg ?? 0) * Math.PI) / 180;
    puppyGroup.rotation.x = ((pose?.pitch_deg ?? 0) * Math.PI) / 180;
    puppyGroup.rotation.z = -((pose?.roll_deg ?? 0) * Math.PI) / 180;

    const accentMat = new THREE.MeshStandardMaterial({
      color: 0xe05a10,
      emissive: 0xe05a10,
      emissiveIntensity: 0.45,
    });

    if (puppyHighResAnchorRef.current && puppyHighResLoadedRef.current) {
      puppyHighResAnchorRef.current.position.set(pose?.x ?? 0, 0.01, -(pose?.y ?? 0));
      puppyHighResAnchorRef.current.rotation.order = "YXZ";
      puppyHighResAnchorRef.current.rotation.y = ((pose?.yaw_deg ?? 0) * Math.PI) / 180;
      puppyHighResAnchorRef.current.rotation.x = ((pose?.pitch_deg ?? 0) * Math.PI) / 180;
      puppyHighResAnchorRef.current.rotation.z = -((pose?.roll_deg ?? 0) * Math.PI) / 180;
      applyPuppyCadRenderMode(puppyHighResAnchorRef.current, sceneRenderMode, Boolean(pose?.live));
    } else {
      const bodyMat = new THREE.MeshStandardMaterial({
        color: 0x1e2430,
        emissive: 0xe05a10,
        emissiveIntensity: pose?.live ? 0.28 : 0.12,
        metalness: 0.5,
        roughness: 0.35,
      });
      const legMat = new THREE.MeshStandardMaterial({
        color: 0x94a3b8,
        metalness: 0.6,
        roughness: 0.3,
      });

      const body = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.11, 0.24), bodyMat);
      puppyGroup.add(body);
      const cowl = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.03, 0.18), accentMat);
      cowl.position.set(0, 0.07, 0);
      puppyGroup.add(cowl);

      const legOffsets: [number, number][] = [
        [0.14, 0.11],
        [0.14, -0.11],
        [-0.14, 0.11],
        [-0.14, -0.11],
      ];
      for (const [lx, lz] of legOffsets) {
        const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, 0.045), legMat);
        leg.position.set(lx, -0.12, lz);
        puppyGroup.add(leg);
      }
    }

    // Translucent orange camera FOV cone pointing forward along +X
    const fovCone = new THREE.Mesh(
      new THREE.ConeGeometry(0.72, 1.55, 16, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xe05a10,
        transparent: true,
        opacity: pose?.live ? 0.22 : 0.12,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
    );
    fovCone.rotation.z = Math.PI / 2;
    fovCone.position.set(0.98, 0.02, 0);
    puppyGroup.add(fovCone);
    group.add(puppyGroup);

    // 6. Glowing 3D Moving-Object Markers & Trails
    const movingTracks = Array.isArray(frame?.moving_objects) ? frame.moving_objects : [];
    const activeMoving = movingTracks.filter((t) => t.is_moving);
    if (activeMoving.length > 0) {
      const moverMat = new THREE.MeshStandardMaterial({
        color: 0x10b981,
        emissive: 0x10b981,
        emissiveIntensity: 0.75,
        transparent: true,
        opacity: 0.85,
      });
      const vecMat = new THREE.LineBasicMaterial({ color: 0xe05a10 });
      const trailMat = new THREE.LineBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.6 });

      for (const track of activeMoving) {
        const orb = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 16), moverMat);
        orb.position.set(track.x, 0.55, -track.y);
        group.add(orb);

        const ring = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.025, 10, 24), accentMat);
        ring.rotation.x = Math.PI / 2;
        ring.position.set(track.x, 0.06, -track.y);
        group.add(ring);

        // Velocity vector line
        const vPts = [
          new THREE.Vector3(track.x, 0.55, -track.y),
          new THREE.Vector3(track.x + track.vx * 0.9, 0.55, -(track.y + track.vy * 0.9)),
        ];
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(vPts), vecMat));

        // Motion trail line
        if (Array.isArray(track.trail) && track.trail.length >= 2) {
          const tPts = track.trail.map(([px, py]) => new THREE.Vector3(px, 0.08, -py));
          group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(tPts), trailMat));
        }
      }
    }

    pickableMeshesRef.current = pickables;
  }, [frame, equipment, darkZones, selectedEquipmentId, showDarkZones, sceneRenderMode]);

  // Update live LiDAR point cloud
  useEffect(() => {
    const group = pointsGroupRef.current;
    if (!group) return;

    disposeObject3D(group);
    group.clear();

    const pts = Array.isArray(frame?.points) ? frame.points : [];
    if (!showPointCloud || pts.length === 0) return;

    const positions = new Float32Array(pts.length * 3);
    const colors = new Float32Array(pts.length * 3);
    for (let i = 0; i < pts.length; i++) {
      const [x, y, intensity] = pts[i];
      positions[i * 3] = x;
      positions[i * 3 + 1] = 0.45;
      positions[i * 3 + 2] = -y;
      const t = Math.max(0, Math.min(1, intensity / 255));
      colors[i * 3] = (56 + t * (224 - 56)) / 255;
      colors[i * 3 + 1] = (189 + t * (90 - 189)) / 255;
      colors[i * 3 + 2] = (248 + t * (16 - 248)) / 255;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.PointsMaterial({ size: 0.085, vertexColors: true, sizeAttenuation: true });
    group.add(new THREE.Points(geo, mat));
  }, [frame, showPointCloud]);

  const selectedAsset = equipment.find((e) => e.id === selectedEquipmentId) ?? null;
  const visiblePanelCount = (Array.isArray(scenePanels) ? scenePanels : []).filter(
    (p) => !hiddenPanelIds.includes(p.id)
  ).length;

  return (
    <div className="relative flex h-[560px] w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge variant="sky">
            <Box className="h-3 w-3" /> THREE.JS DIRECT WEBGL
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
            <Layers className="h-3.5 w-3.5" /> Dark Zones ({darkZones.length})
          </Button>
          <Button
            size="sm"
            variant={showPointCloud ? "sky" : "outline"}
            onClick={() => setShowPointCloud((v) => !v)}
          >
            LiDAR Points
          </Button>
        </div>
      </div>

      {webglError ? (
        <div className="flex flex-1 items-center justify-center p-6 font-mono text-xs text-eigenia-amber">
          {webglError}
        </div>
      ) : (
        <div ref={containerRef} className="h-full w-full flex-1" />
      )}

      {selectedAsset && (
        <div className="pointer-events-none absolute right-3 top-14 rounded border border-eigenia-sky/40 bg-eigenia-shell/95 px-2.5 py-1.5 font-mono text-[10px] text-white shadow">
          <div className="font-semibold text-eigenia-orange">{selectedAsset.name}</div>
          <div className="text-eigenia-muted">
            {selectedAsset.manufacturer} · {selectedAsset.model_number} ·{" "}
            {selectedAsset.completeness?.completeness_pct ?? 50}%
          </div>
        </div>
      )}

      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-2">
        <Badge variant="sky">Walls: {frame?.walls?.length ?? 0}</Badge>
        <Badge variant="amber">Dark Zones: {darkZones.length}</Badge>
        <Badge variant="default">Assets: {equipment.length}</Badge>
        {visiblePanelCount > 0 && (
          <Badge variant="sky">
            3D Panels: {visiblePanelCount} ({sceneRenderMode})
          </Badge>
        )}
        {(frame?.anomalies?.length ?? 0) > 0 && (
          <Badge variant="fault">Anomalies: {frame?.anomalies?.length}</Badge>
        )}
      </div>
    </div>
  );
}
