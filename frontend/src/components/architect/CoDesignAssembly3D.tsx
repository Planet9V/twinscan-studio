"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  Box,
  Compass,
  Eye,
  Grid3x3,
  Layers,
  Lock,
  Sparkles,
  Tag,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import type { CoDesignLink3D, CoDesignPart3D } from "@/lib/architectApi";
import type { Pi5ComponentStatus } from "@/lib/robotApi";
import {
  applyHardwareRenderMode,
  CAD_STATUS_COLORS,
  createCadOverlayEdges,
} from "@/lib/threeCadMaterials";
import type { SceneRenderMode } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface CoDesignAssembly3DProps {
  parts: CoDesignPart3D[];
  links: CoDesignLink3D[];
  selectedPartId?: string | null;
  onSelectPart?: (partId: string) => void;
  heightClassName?: string;
  title?: string;
}

type CameraPreset = "iso" | "top" | "front";
type LabelMode = "all" | "selected" | "off";

const LINK_COLORS: Record<CoDesignLink3D["link_type"], number> = {
  power_5v: 0xe05a10, // Eigenia Signal Orange
  usb: 0x10b981, // Emerald
  uart_i2c: 0xf59e0b, // Amber
  wifi: 0x38bdf8, // Sky
  ble: 0x7dd3fc, // Light Sky
  video: 0xa78bfa, // Violet
};

const PROFILE_BASE_COLORS: Record<string, number> = {
  puppypi_pi5_ros2: 0x1e293b,
  raspberry_pi_5_node: 0x166534,
  raspberry_pi_zero_2w: 0x15803d,
  microbit_v2_21: 0x18181b,
  local_camera_array: 0x334155,
  generic_sensor_module: 0x0f4c5c,
};

function getPartStatusColor(part: CoDesignPart3D): number {
  if (!part.owned || part.status === "proposed") return CAD_STATUS_COLORS.warning;
  switch (part.status) {
    case "ok":
      return CAD_STATUS_COLORS.ok;
    case "warning":
      return CAD_STATUS_COLORS.warning;
    case "fault":
      return CAD_STATUS_COLORS.fault;
    default:
      return CAD_STATUS_COLORS.wireCyan;
  }
}

function getBaseColorForPart(part: CoDesignPart3D): number {
  if (!part.owned) return 0xf59e0b;
  if (part.profile_id && PROFILE_BASE_COLORS[part.profile_id]) {
    return PROFILE_BASE_COLORS[part.profile_id];
  }
  switch (part.category) {
    case "compute":
      return 0x166534;
    case "microcontroller":
      return 0x18181b;
    case "camera":
      return 0x334155;
    case "sensor":
      return 0x0f4c5c;
    case "actuator":
      return 0x3f3f46;
    case "power":
      return 0x7c2d12;
    default:
      return 0x27272a;
  }
}

function mapStatusForCad(part: CoDesignPart3D): Pi5ComponentStatus {
  if (!part.owned || part.status === "proposed") return "warning";
  if (part.status === "fault") return "fault";
  if (part.status === "warning") return "warning";
  return "ok";
}

interface PartVisualEntry {
  part: CoDesignPart3D;
  group: THREE.Group;
  primaryMesh: THREE.Mesh;
  primaryEdges: THREE.LineSegments;
  detailMeshes: THREE.Mesh[];
  basePos: THREE.Vector3;
  explodeVec: THREE.Vector3;
  baseColor: number;
  statusColor: number;
  labelOffsetY: number;
}

interface HarnessEntry {
  link: CoDesignLink3D;
  object: THREE.Mesh | THREE.Line;
  isWireless: boolean;
}

// Convert real-world meter coords/dims to scene units (1 scene unit = 10cm = 0.1m)
const METERS_TO_UNITS = 10;

function computeSafeDimensions(part: CoDesignPart3D): [number, number, number] {
  const raw = Array.isArray(part.dims_m) && part.dims_m.length >= 3 ? part.dims_m : [0.085, 0.025, 0.056];
  const clamp = (v: number, min: number, max: number) =>
    Math.max(min, Math.min(max, (Number.isFinite(v) ? v : 0.06) * METERS_TO_UNITS));
  return [
    clamp(raw[0], 0.55, 4.2),
    clamp(raw[1], 0.18, 2.4),
    clamp(raw[2], 0.45, 3.6),
  ];
}

function buildModuleDetails(
  part: CoDesignPart3D,
  dims: [number, number, number],
  group: THREE.Group
): THREE.Mesh[] {
  const [w, h, d] = dims;
  const details: THREE.Mesh[] = [];
  const profile = (part.profile_id || "").toLowerCase();
  const category = (part.category || "").toLowerCase();

  const makeDetail = (
    geo: THREE.BufferGeometry,
    color: number,
    pos: [number, number, number],
    emissive = 0x000000,
    emissiveIntensity = 0
  ) => {
    const mat = new THREE.MeshStandardMaterial({
      color,
      emissive,
      emissiveIntensity,
      roughness: 0.4,
      metalness: 0.45,
      transparent: !part.owned,
      opacity: part.owned ? 0.95 : 0.4,
    });
    const m = new THREE.Mesh(geo, mat);
    m.position.set(pos[0], pos[1], pos[2]);
    m.userData.partId = part.id;
    group.add(m);
    details.push(m);
  };

  if (profile.includes("microbit")) {
    // Iconic 5x5 Red LED Matrix + Gold Edge Connector + A/B Buttons
    const ledGeo = new THREE.BoxGeometry(w * 0.06, 0.03, d * 0.06);
    for (let r = 0; r < 5; r++) {
      for (let c = 0; c < 5; c++) {
        const lit = (r + c) % 2 === 0;
        makeDetail(
          ledGeo,
          lit ? 0xef4444 : 0x3f1d1d,
          [(c - 2) * w * 0.11, h / 2 + 0.015, (r - 2) * d * 0.11],
          lit ? 0xef4444 : 0x000000,
          lit ? 0.85 : 0
        );
      }
    }
    // Gold edge strip
    makeDetail(
      new THREE.BoxGeometry(w * 0.92, h * 0.35, d * 0.16),
      0xd97706,
      [0, 0, d * 0.44],
      0xf59e0b,
      0.15
    );
    // A & B tactile buttons
    makeDetail(new THREE.BoxGeometry(w * 0.11, 0.05, d * 0.14), 0x09090b, [-w * 0.36, h / 2 + 0.025, 0]);
    makeDetail(new THREE.BoxGeometry(w * 0.11, 0.05, d * 0.14), 0x09090b, [w * 0.36, h / 2 + 0.025, 0]);
  } else if (profile.includes("puppypi")) {
    // Quadruped chassis accents + top LiDAR turret + 4 leg joints
    makeDetail(
      new THREE.CylinderGeometry(Math.min(w, d) * 0.18, Math.min(w, d) * 0.2, h * 0.45, 20),
      0x0f172a,
      [w * 0.15, h / 2 + h * 0.22, 0],
      0x38bdf8,
      0.25
    );
    // Front camera visor
    makeDetail(
      new THREE.BoxGeometry(w * 0.12, h * 0.38, d * 0.45),
      0x020617,
      [w / 2 + 0.04, 0.05, 0],
      0xe05a10,
      0.3
    );
    // 4 leg struts
    const legGeo = new THREE.BoxGeometry(w * 0.1, h * 0.7, d * 0.1);
    const legCoords: [number, number][] = [
      [-w * 0.35, -d * 0.44],
      [w * 0.35, -d * 0.44],
      [-w * 0.35, d * 0.44],
      [w * 0.35, d * 0.44],
    ];
    legCoords.forEach(([lx, lz]) => {
      makeDetail(legGeo, 0xe05a10, [lx, -h * 0.45, lz]);
    });
  } else if (profile.includes("pi_5") || profile.includes("pi_zero") || category === "compute") {
    // Silver SoC heatspreader + GPIO pin header + USB/Ethernet blocks
    makeDetail(new THREE.BoxGeometry(w * 0.24, 0.06, d * 0.28), 0xcbd5e1, [-w * 0.08, h / 2 + 0.03, 0]);
    makeDetail(new THREE.BoxGeometry(w * 0.65, 0.09, d * 0.12), 0x18181b, [0, h / 2 + 0.045, -d * 0.38]);
    if (!profile.includes("zero")) {
      makeDetail(new THREE.BoxGeometry(w * 0.2, h * 0.9, d * 0.24), 0x94a3b8, [w * 0.38, h * 0.18, -d * 0.2]);
      makeDetail(new THREE.BoxGeometry(w * 0.2, h * 0.9, d * 0.24), 0x94a3b8, [w * 0.38, h * 0.18, d * 0.2]);
    }
  } else if (profile.includes("camera") || category === "camera") {
    // Cylindrical camera lens barrel + dark aperture ring
    const lensRadius = Math.min(h, d) * 0.34;
    const barrel = new THREE.CylinderGeometry(lensRadius, lensRadius * 1.08, w * 0.36, 20);
    barrel.rotateZ(Math.PI / 2);
    makeDetail(barrel, 0x09090b, [w / 2 + w * 0.14, 0, 0], 0x38bdf8, 0.25);
    const glass = new THREE.CylinderGeometry(lensRadius * 0.68, lensRadius * 0.68, 0.04, 18);
    glass.rotateZ(Math.PI / 2);
    makeDetail(glass, 0x0ea5e9, [w / 2 + w * 0.32, 0, 0], 0x38bdf8, 0.55);
  } else if (category === "sensor") {
    // Cylindrical sensor dome / emitter
    makeDetail(
      new THREE.CylinderGeometry(Math.min(w, d) * 0.32, Math.min(w, d) * 0.36, h * 0.55, 18),
      0x38bdf8,
      [0, h / 2 + h * 0.24, 0],
      0x38bdf8,
      0.3
    );
  }

  return details;
}

function buildHarnessMesh(
  start: THREE.Vector3,
  end: THREE.Vector3,
  link: CoDesignLink3D
): THREE.Mesh | THREE.Line {
  const color = LINK_COLORS[link.link_type] ?? 0x38bdf8;
  const isWireless = link.link_type === "wifi" || link.link_type === "ble";
  const mid = start.clone().add(end).multiplyScalar(0.5);
  const dist = start.distanceTo(end);
  mid.y += Math.max(0.35, Math.min(2.0, dist * 0.28 + (isWireless ? 0.55 : 0.15)));

  const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
  if (isWireless) {
    const pts = curve.getPoints(32);
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineDashedMaterial({
      color,
      dashSize: 0.22,
      gapSize: 0.14,
      transparent: true,
      opacity: 0.88,
    });
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    return line;
  }

  const radius = link.link_type === "power_5v" ? 0.042 : 0.03;
  const tubeGeo = new THREE.TubeGeometry(curve, 24, radius, 8, false);
  const tubeMat = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.45,
    roughness: 0.35,
    metalness: 0.2,
    transparent: true,
    opacity: 0.9,
  });
  return new THREE.Mesh(tubeGeo, tubeMat);
}

export function CoDesignAssembly3D({
  parts,
  links,
  selectedPartId = null,
  onSelectPart,
  heightClassName = "h-[460px]",
  title = "3D Co-Design Hardware Assembly",
}: CoDesignAssembly3DProps): React.JSX.Element {
  const [renderMode, setRenderMode] = useState<SceneRenderMode>("translucent");
  const [explodePct, setExplodePct] = useState<number>(18);
  const [labelMode, setLabelMode] = useState<LabelMode>("all");
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("iso");
  const [presetNonce, setPresetNonce] = useState(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const labelElsRef = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const renderModeRef = useRef<SceneRenderMode>(renderMode);
  const explodeRef = useRef<number>(explodePct);
  const selectedIdRef = useRef<string | null>(selectedPartId);
  const labelModeRef = useRef<LabelMode>(labelMode);
  const onSelectRef = useRef(onSelectPart);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);

  renderModeRef.current = renderMode;
  explodeRef.current = explodePct;
  selectedIdRef.current = selectedPartId;
  labelModeRef.current = labelMode;
  onSelectRef.current = onSelectPart;

  const ownedCount = useMemo(() => parts.filter((p) => p.owned).length, [parts]);
  const proposedCount = parts.length - ownedCount;

  // Apply camera preset transitions
  useEffect(() => {
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!cam || !ctrl) return;
    if (cameraPreset === "top") {
      cam.position.set(0.01, 13.5, 0.01);
    } else if (cameraPreset === "front") {
      cam.position.set(0, 3.2, 12.5);
    } else {
      cam.position.set(8.6, 6.8, 9.2);
    }
    ctrl.target.set(0, 0.5, 0);
    ctrl.update();
  }, [cameraPreset, presetNonce]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = Math.max(container.clientWidth, 320);
    const height = Math.max(container.clientHeight, 260);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0d10);
    scene.fog = new THREE.FogExp2(0x0b0d10, 0.018);

    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 120);
    camera.position.set(8.6, 6.8, 9.2);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 3.2;
    controls.maxDistance = 32;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.target.set(0, 0.5, 0);
    controls.update();
    controlsRef.current = controls;

    // Industrial Studio Lighting
    const ambient = new THREE.AmbientLight(0xdbeafe, 0.72);
    scene.add(ambient);
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
    keyLight.position.set(9, 14, 10);
    scene.add(keyLight);
    const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.7);
    rimLight.position.set(-10, 6, -8);
    scene.add(rimLight);
    const orangeAccent = new THREE.PointLight(0xe05a10, 0.9, 24);
    orangeAccent.position.set(5, 4, -5);
    scene.add(orangeAccent);

    // Architectural Bench Grid
    const grid = new THREE.GridHelper(22, 22, 0x38bdf8, 0x1e293b);
    grid.position.y = -0.02;
    scene.add(grid);

    // Compute centroid so explode slider pushes modules cleanly outward
    const scaledPositions = parts.map((p, idx) => {
      const hasCoords = Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z);
      if (hasCoords && (p.x !== 0 || p.y !== 0 || p.z !== 0 || parts.length === 1)) {
        return new THREE.Vector3(
          p.x * METERS_TO_UNITS,
          Math.max(0.3, p.y * METERS_TO_UNITS + 0.4),
          p.z * METERS_TO_UNITS
        );
      }
      const angle = (idx / Math.max(parts.length, 1)) * Math.PI * 2;
      const radius = parts.length <= 1 ? 0 : 3.2;
      return new THREE.Vector3(Math.cos(angle) * radius, 0.6, Math.sin(angle) * radius);
    });

    const centroid = new THREE.Vector3();
    scaledPositions.forEach((v) => centroid.add(v));
    if (scaledPositions.length > 0) centroid.divideScalar(scaledPositions.length);

    // Build Part Visuals
    const entries: PartVisualEntry[] = [];
    const entryMap = new Map<string, PartVisualEntry>();
    const pickableMeshes: THREE.Object3D[] = [];

    parts.forEach((part, idx) => {
      const dims = computeSafeDimensions(part);
      const group = new THREE.Group();
      const basePos = scaledPositions[idx];
      group.position.copy(basePos);

      const baseColor = getBaseColorForPart(part);
      const statusColor = getPartStatusColor(part);

      const boxGeo = new THREE.BoxGeometry(dims[0], dims[1], dims[2]);
      const boxMat = new THREE.MeshStandardMaterial({
        color: baseColor,
        roughness: 0.45,
        metalness: 0.3,
      });
      const primaryMesh = new THREE.Mesh(boxGeo, boxMat);
      primaryMesh.userData.partId = part.id;
      group.add(primaryMesh);

      const primaryEdges = createCadOverlayEdges(boxGeo, statusColor, 0.88);
      group.add(primaryEdges);

      const detailMeshes = buildModuleDetails(part, dims, group);

      // Compute explode vector radially away from centroid + vertical lift
      const dir = basePos.clone().sub(centroid);
      if (dir.lengthSq() < 0.05) {
        dir.set(0, 1.4, 0);
      } else {
        dir.normalize().multiplyScalar(2.4);
        dir.y += 0.6 + (idx % 3) * 0.35;
      }

      scene.add(group);
      pickableMeshes.push(primaryMesh, ...detailMeshes);

      const entry: PartVisualEntry = {
        part,
        group,
        primaryMesh,
        primaryEdges,
        detailMeshes,
        basePos,
        explodeVec: dir,
        baseColor,
        statusColor,
        labelOffsetY: dims[1] / 2 + 0.45,
      };
      entries.push(entry);
      entryMap.set(part.id, entry);
    });

    // Harness Group (rebuilt only when explode % changes)
    const harnessGroup = new THREE.Group();
    scene.add(harnessGroup);
    let harnessEntries: HarnessEntry[] = [];
    let lastBuiltExplode = -1;

    const disposeHarnesses = () => {
      harnessEntries.forEach((h) => {
        h.object.geometry.dispose();
        const mat = h.object.material;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat.dispose();
        harnessGroup.remove(h.object);
      });
      harnessEntries = [];
    };

    const rebuildHarnesses = (explodeFactor: number) => {
      disposeHarnesses();
      links.forEach((link) => {
        const src = entryMap.get(link.source);
        const dst = entryMap.get(link.target);
        if (!src || !dst) return;
        const p1 = src.basePos.clone().addScaledVector(src.explodeVec, explodeFactor);
        const p2 = dst.basePos.clone().addScaledVector(dst.explodeVec, explodeFactor);
        const obj = buildHarnessMesh(p1, p2, link);
        harnessGroup.add(obj);
        harnessEntries.push({
          link,
          object: obj,
          isWireless: link.link_type === "wifi" || link.link_type === "ble",
        });
      });
    };

    // Raycaster Click Selection
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDownPos = { x: 0, y: 0 };

    const onPointerDown = (ev: PointerEvent) => {
      pointerDownPos = { x: ev.clientX, y: ev.clientY };
    };

    const onPointerUp = (ev: PointerEvent) => {
      const dx = ev.clientX - pointerDownPos.x;
      const dy = ev.clientY - pointerDownPos.y;
      if (dx * dx + dy * dy > 36) return; // Ignore orbit drag
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickableMeshes, false);
      if (hits.length > 0) {
        const hitId = hits[0].object.userData.partId as string | undefined;
        if (hitId && onSelectRef.current) {
          onSelectRef.current(hitId);
        }
      }
    };

    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);

    // ResizeObserver
    const ro = new ResizeObserver((obsEntries) => {
      const cr = obsEntries[0]?.contentRect;
      if (!cr || cr.width < 10 || cr.height < 10) return;
      camera.aspect = cr.width / cr.height;
      camera.updateProjectionMatrix();
      renderer.setSize(cr.width, cr.height);
    });
    ro.observe(container);

    // Animation Loop (60 FPS projected labels + pulsing ghost amber for AI-suggested parts)
    let rafId = 0;
    const projVec = new THREE.Vector3();
    const startTime = performance.now();

    const animate = (now: number) => {
      rafId = window.requestAnimationFrame(animate);
      const elapsedSec = (now - startTime) / 1000;
      const explodeFactor = explodeRef.current / 100;
      const mode = renderModeRef.current;
      const selId = selectedIdRef.current;
      const lblMode = labelModeRef.current;

      if (Math.abs(explodeFactor - lastBuiltExplode) > 0.002) {
        entries.forEach((entry) => {
          entry.group.position
            .copy(entry.basePos)
            .addScaledVector(entry.explodeVec, explodeFactor);
        });
        rebuildHarnesses(explodeFactor);
        lastBuiltExplode = explodeFactor;
      }

      // Apply CAD mode + pulsing ghost amber on AI-suggested (owned === false) parts
      const ghostPulse = 0.5 + 0.5 * Math.sin(elapsedSec * 3.1);
      entries.forEach((entry) => {
        const isSelected = entry.part.id === selId;
        if (!entry.part.owned) {
          const mat = entry.primaryMesh.material as THREE.MeshStandardMaterial;
          const edgeMat = entry.primaryEdges.material as THREE.LineBasicMaterial;
          mat.color.setHex(isSelected ? CAD_STATUS_COLORS.selected : CAD_STATUS_COLORS.warning);
          mat.emissive.setHex(isSelected ? CAD_STATUS_COLORS.selected : CAD_STATUS_COLORS.warning);
          mat.emissiveIntensity = isSelected ? 0.6 : 0.25 + ghostPulse * 0.3;
          mat.transparent = true;
          mat.opacity = isSelected ? 0.52 : 0.22 + ghostPulse * 0.22;
          mat.depthWrite = false;
          mat.needsUpdate = true;

          edgeMat.color.setHex(isSelected ? CAD_STATUS_COLORS.selected : CAD_STATUS_COLORS.warning);
          edgeMat.opacity = isSelected ? 1.0 : 0.65 + ghostPulse * 0.35;
          edgeMat.needsUpdate = true;
        } else {
          // Reuse shared Eigenia Three.js CAD material utility
          const cadStatus = mapStatusForCad(entry.part);
          const statusHex =
            cadStatus === "fault"
              ? CAD_STATUS_COLORS.fault
              : cadStatus === "warning"
                ? CAD_STATUS_COLORS.warning
                : entry.statusColor;
          applyHardwareRenderMode(
            entry.primaryMesh,
            entry.primaryEdges,
            mode,
            entry.baseColor,
            statusHex,
            isSelected
          );
        }
      });

      controls.update();
      renderer.render(scene, camera);

      // Update 60 FPS projected DOM labels without React re-renders
      const rectW = renderer.domElement.clientWidth;
      const rectH = renderer.domElement.clientHeight;
      entries.forEach((entry) => {
        const el = labelElsRef.current.get(entry.part.id);
        if (!el) return;
        const show =
          lblMode === "all" || (lblMode === "selected" && entry.part.id === selId);
        if (!show) {
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          return;
        }
        projVec.copy(entry.group.position);
        projVec.y += entry.labelOffsetY;
        projVec.project(camera);
        if (projVec.z > 1) {
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          return;
        }
        const sx = (projVec.x * 0.5 + 0.5) * rectW;
        const sy = (-projVec.y * 0.5 + 0.5) * rectH;
        el.style.opacity = "1";
        el.style.pointerEvents = "auto";
        el.style.transform = `translate3d(${sx.toFixed(1)}px, ${sy.toFixed(1)}px, 0) translate(-50%, -100%)`;
      });
    };

    rafId = window.requestAnimationFrame(animate);

    return () => {
      window.cancelAnimationFrame(rafId);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      controls.dispose();
      disposeHarnesses();
      entries.forEach((entry) => {
        entry.primaryMesh.geometry.dispose();
        (entry.primaryMesh.material as THREE.Material).dispose();
        entry.primaryEdges.geometry.dispose();
        (entry.primaryEdges.material as THREE.Material).dispose();
        entry.detailMeshes.forEach((dm) => {
          dm.geometry.dispose();
          (dm.material as THREE.Material).dispose();
        });
      });
      renderer.dispose();
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [parts, links]);

  return (
    <div
      className={cn(
        "relative flex w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian",
        heightClassName
      )}
    >
      {/* Top Toolbar */}
      <div className="z-10 flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell/90 px-3 py-2 backdrop-blur-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-white">
            {title}
          </span>
          <Badge variant="sky" className="font-mono text-[9px] tabular-nums">
            {ownedCount} Owned
          </Badge>
          {proposedCount > 0 && (
            <Badge variant="amber" className="font-mono text-[9px] tabular-nums">
              <Sparkles className="h-2.5 w-2.5" />
              {proposedCount} AI-Suggested
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Wireframe | Translucent | Solid Mode Switcher */}
          <div
            role="group"
            aria-label="3D Render Mode"
            className="inline-flex items-center rounded-md border border-white/10 bg-eigenia-obsidian p-0.5 font-mono text-[10px]"
          >
            {(
              [
                { id: "wireframe", label: "Wireframe", icon: Grid3x3 },
                { id: "translucent", label: "Translucent", icon: Layers },
                { id: "solid", label: "Solid", icon: Box },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setRenderMode(id)}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-2 py-0.5 transition-colors motion-reduce:transition-none",
                  renderMode === id
                    ? "bg-eigenia-orange text-white"
                    : "text-eigenia-muted hover:text-white"
                )}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            ))}
          </div>

          {/* Exploded-View Slider (0-100%) */}
          <div className="flex items-center gap-2 rounded-md border border-white/10 bg-eigenia-obsidian px-2.5 py-1">
            <span className="font-mono text-[10px] text-eigenia-muted">Explode</span>
            <div className="w-20">
              <Slider
                min={0}
                max={100}
                step={2}
                value={[explodePct]}
                onValueChange={([v]) => setExplodePct(v)}
                aria-label="Exploded view percentage"
              />
            </div>
            <span className="w-8 text-right font-mono text-[10px] tabular-nums text-eigenia-orange">
              {explodePct}%
            </span>
          </div>

          {/* Camera & Label Controls */}
          <div className="flex items-center gap-1">
            {(["iso", "top", "front"] as const).map((preset) => (
              <Button
                key={preset}
                size="sm"
                variant={cameraPreset === preset ? "sky" : "ghost"}
                className="h-6 px-2 font-mono text-[10px] uppercase"
                onClick={() => {
                  setCameraPreset(preset);
                  setPresetNonce((n) => n + 1);
                }}
              >
                {preset === "iso" && <Compass className="h-3 w-3" />}
                {preset}
              </Button>
            ))}
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 font-mono text-[10px]"
              onClick={() =>
                setLabelMode((m) => (m === "all" ? "selected" : m === "selected" ? "off" : "all"))
              }
              title="Toggle 3D projected labels"
            >
              {labelMode === "off" ? <Eye className="h-3 w-3" /> : <Tag className="h-3 w-3" />}
              {labelMode === "all" ? "Labels" : labelMode === "selected" ? "Selected" : "Hidden"}
            </Button>
          </div>
        </div>
      </div>

      {/* 3D WebGL Viewport + Projected 60 FPS Clickable Labels */}
      <div className="relative flex-1 overflow-hidden">
        {parts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
            <Box className="h-8 w-8 text-eigenia-muted" />
            <div className="text-xs font-semibold text-white">No 3D Hardware Modules Yet</div>
            <p className="max-w-sm font-mono text-[10px] text-eigenia-muted">
              Evaluate a project idea or adopt an AI proposal to generate an interactive 3D hardware
              assembly with color-coded wiring harnesses.
            </p>
          </div>
        ) : (
          <>
            <div ref={containerRef} className="h-full w-full cursor-grab active:cursor-grabbing" />

            {/* Projected 3D Labels Overlay */}
            <div className="pointer-events-none absolute inset-0 overflow-hidden">
              {parts.map((part) => {
                const isSelected = part.id === selectedPartId;
                return (
                  <button
                    key={part.id}
                    ref={(el) => {
                      labelElsRef.current.set(part.id, el);
                    }}
                    type="button"
                    onClick={() => onSelectPart?.(part.id)}
                    style={{ opacity: 0 }}
                    className={cn(
                      "absolute left-0 top-0 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] whitespace-nowrap shadow-md backdrop-blur-sm transition-colors motion-reduce:transition-none",
                      isSelected
                        ? "border-eigenia-orange bg-eigenia-orange text-white shadow-[0_0_12px_rgba(224,90,16,0.55)]"
                        : !part.owned
                          ? "border-eigenia-amber/70 bg-eigenia-obsidian/90 text-eigenia-amber hover:border-eigenia-amber"
                          : "border-white/20 bg-eigenia-shell/90 text-white hover:border-eigenia-sky"
                    )}
                  >
                    {part.locked && <Lock className="h-2.5 w-2.5 text-eigenia-sky" />}
                    {!part.owned && <Sparkles className="h-2.5 w-2.5 text-eigenia-amber" />}
                    <span className="font-semibold">{part.label}</span>
                    {part.metric && (
                      <span className="opacity-80">· {part.metric}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </>
        )}

        {/* Bottom Harness Legend */}
        <div className="pointer-events-none absolute bottom-2 left-2.5 flex flex-wrap items-center gap-2 rounded-md border border-white/10 bg-eigenia-shell/85 px-2.5 py-1 font-mono text-[9px] text-eigenia-ink backdrop-blur-sm">
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-3 rounded-full bg-eigenia-orange" /> 5V Power
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-3 rounded-full bg-emerald-400" /> USB
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-3 rounded-full bg-eigenia-amber" /> UART/I2C
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 border-t border-dashed border-eigenia-sky" /> Wi-Fi / BLE
          </span>
          <span className="inline-flex items-center gap-1 text-eigenia-amber">
            <span className="h-2 w-2 rounded-sm border border-eigenia-amber bg-eigenia-amber/30" />{" "}
            Ghost = AI Suggested
          </span>
        </div>
      </div>
    </div>
  );
}
