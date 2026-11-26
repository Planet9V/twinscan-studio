"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  Box,
  Compass,
  Cpu,
  Eye,
  Grid3x3,
  Layers,
  Tag,
  Usb,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import type {
  Pi5ComponentStatus,
  Pi5HardwareComponentState,
  Pi5HardwareDiagnostics,
} from "@/lib/robotApi";
import {
  applyHardwareRenderMode,
  createCadOverlayEdges,
  getCadStatusHex,
} from "@/lib/threeCadMaterials";
import type { SceneRenderMode } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Pi5HardwareTwin3DProps {
  diagnostics: Pi5HardwareDiagnostics | null;
  selectedComponentId: string | null;
  onSelectComponent: (componentId: string) => void;
}

type LabelMode = "all" | "ports_faults" | "selected";
type CameraPreset = "iso" | "top" | "usb" | "exploded";

interface ComponentSpec {
  id: string;
  shortLabel: string;
  category: Pi5HardwareComponentState["category"];
  basePos: [number, number, number];
  explodeDelta: [number, number, number];
  anchorPos?: [number, number, number];
  baseColor: number;
  size: [number, number, number];
  shape?: "box" | "cylinder" | "lidar" | "hat";
  labelOffsetY?: number;
}

// Millimeter-proportional Raspberry Pi 5 Model B (85mm x 56mm => 8.5 x 5.6 units, 1 unit = 10mm)
// X: -4.25 (left/PCIe) -> +4.25 (right/USB+ETH), Z: -2.8 (top/GPIO) -> +2.8 (bottom/USB-C+HDMI), Y: up
const COMPONENT_SPECS: ComponentSpec[] = [
  // Core Silicon & Board
  {
    id: "bcm2712_soc",
    shortLabel: "BCM2712 SoC",
    category: "soc",
    basePos: [-1.05, 0.21, 0.15],
    explodeDelta: [0, 0, 0],
    baseColor: 0x94a3b8,
    size: [1.7, 0.24, 1.7],
    labelOffsetY: 0.35,
  },
  {
    id: "ram_lpddr4x",
    shortLabel: "8GB LPDDR4X",
    category: "soc",
    basePos: [0.45, 0.18, 0.15],
    explodeDelta: [0, 0, 0],
    baseColor: 0x1e293b,
    size: [1.05, 0.16, 1.38],
    labelOffsetY: 0.3,
  },
  {
    id: "rp1_southbridge",
    shortLabel: "RP1 I/O",
    category: "soc",
    basePos: [1.9, 0.18, 0.55],
    explodeDelta: [0, 0, 0],
    baseColor: 0x334155,
    size: [1.18, 0.16, 1.18],
    labelOffsetY: 0.3,
  },
  {
    id: "da9091_pmic",
    shortLabel: "DA9091 PMIC",
    category: "power",
    basePos: [-2.7, 0.17, 1.4],
    explodeDelta: [0, 0, 0],
    baseColor: 0x3f3f46,
    size: [0.68, 0.14, 0.68],
    labelOffsetY: 0.28,
  },
  {
    id: "wifi_bt_module",
    shortLabel: "Wi-Fi / BT",
    category: "network",
    basePos: [-3.1, 0.22, -1.35],
    explodeDelta: [0, 0, 0],
    baseColor: 0xcbd5e1,
    size: [1.3, 0.24, 1.05],
    labelOffsetY: 0.32,
  },
  // Power, Display, Storage & High-Speed Interfaces
  {
    id: "usbc_pwr",
    shortLabel: "USB-C 5V",
    category: "power",
    basePos: [-3.15, 0.26, 2.52],
    explodeDelta: [0, 0, 0],
    baseColor: 0x94a3b8,
    size: [0.9, 0.34, 0.72],
    labelOffsetY: 0.38,
  },
  {
    id: "micro_hdmi_0",
    shortLabel: "HDMI 0",
    category: "interface",
    basePos: [-1.75, 0.23, 2.56],
    explodeDelta: [0, 0, 0],
    baseColor: 0x64748b,
    size: [0.66, 0.28, 0.58],
    labelOffsetY: 0.34,
  },
  {
    id: "micro_hdmi_1",
    shortLabel: "HDMI 1",
    category: "interface",
    basePos: [-0.45, 0.23, 2.56],
    explodeDelta: [0, 0, 0],
    baseColor: 0x64748b,
    size: [0.66, 0.28, 0.58],
    labelOffsetY: 0.34,
  },
  {
    id: "pcie_ffc",
    shortLabel: "PCIe FFC",
    category: "interface",
    basePos: [-3.98, 0.23, 0.1],
    explodeDelta: [0, 0, 0],
    baseColor: 0x475569,
    size: [0.38, 0.26, 1.25],
    labelOffsetY: 0.35,
  },
  {
    id: "csi_dsi_0",
    shortLabel: "CSI/DSI 0",
    category: "interface",
    basePos: [0.65, 0.28, 1.85],
    explodeDelta: [0, 0, 0],
    baseColor: 0x334155,
    size: [0.3, 0.38, 1.3],
    labelOffsetY: 0.38,
  },
  {
    id: "csi_dsi_1",
    shortLabel: "CSI/DSI 1",
    category: "interface",
    basePos: [1.18, 0.28, 1.85],
    explodeDelta: [0, 0, 0],
    baseColor: 0x334155,
    size: [0.3, 0.38, 1.3],
    labelOffsetY: 0.38,
  },
  {
    id: "gpio_40pin",
    shortLabel: "GPIO 40-Pin",
    category: "interface",
    basePos: [-0.65, 0.36, -2.42],
    explodeDelta: [0, 0, 0],
    baseColor: 0x1e293b,
    size: [5.1, 0.54, 0.52],
    labelOffsetY: 0.45,
  },
  {
    id: "microsd_slot",
    shortLabel: "MicroSD",
    category: "storage",
    basePos: [-3.75, -0.14, 0.1],
    explodeDelta: [0, 0, 0],
    baseColor: 0x64748b,
    size: [1.2, 0.18, 1.15],
    labelOffsetY: -0.35,
  },
  // Right-Edge Ethernet + 4 USB-A Ports (Pi 5 layout: RJ45 bottom, USB3 mid, USB2 top)
  {
    id: "eth_rj45",
    shortLabel: "GbE RJ45",
    category: "network",
    basePos: [3.62, 0.78, 1.68],
    explodeDelta: [0, 0, 0],
    baseColor: 0x94a3b8,
    size: [2.05, 1.36, 1.56],
    labelOffsetY: 0.85,
  },
  {
    id: "usb3_port_3_1",
    shortLabel: "USB3 3-1",
    category: "usb",
    basePos: [3.75, 1.15, -0.05],
    explodeDelta: [0, 0, 0],
    baseColor: 0x2563eb,
    size: [1.7, 0.66, 1.34],
    labelOffsetY: 0.55,
  },
  {
    id: "usb3_port_3_2",
    shortLabel: "USB3 3-2",
    category: "usb",
    basePos: [3.75, 0.45, -0.05],
    explodeDelta: [0, 0, 0],
    baseColor: 0x1d4ed8,
    size: [1.7, 0.66, 1.34],
    labelOffsetY: -0.15,
  },
  {
    id: "usb2_port_1_1",
    shortLabel: "USB2 1-1",
    category: "usb",
    basePos: [3.75, 1.15, -1.75],
    explodeDelta: [0, 0, 0],
    baseColor: 0x334155,
    size: [1.7, 0.66, 1.34],
    labelOffsetY: 0.55,
  },
  {
    id: "usb2_port_1_2",
    shortLabel: "USB2 1-2",
    category: "usb",
    basePos: [3.75, 0.45, -1.75],
    explodeDelta: [0, 0, 0],
    baseColor: 0x1e293b,
    size: [1.7, 0.66, 1.34],
    labelOffsetY: -0.15,
  },
  // Explodable PuppyPi Stack & Peripherals
  {
    id: "rrc_hat_stm32",
    shortLabel: "RRC HAT (STM32)",
    category: "peripheral",
    basePos: [-0.25, 1.65, -0.2],
    explodeDelta: [0, 1.9, 0],
    anchorPos: [-0.65, 0.62, -2.42],
    baseColor: 0x1e293b,
    size: [7.2, 0.22, 4.7],
    shape: "hat",
    labelOffsetY: 0.42,
  },
  {
    id: "ld19_lidar_module",
    shortLabel: "LD19 LiDAR + CP2102",
    category: "peripheral",
    basePos: [0.35, 2.7, -0.3],
    explodeDelta: [0, 3.35, 0],
    anchorPos: [3.75, 0.45, -1.75],
    baseColor: 0x0f172a,
    size: [2.2, 0.72, 2.2],
    shape: "lidar",
    labelOffsetY: 0.65,
  },
  {
    id: "camera_icspring",
    shortLabel: "icSpring FPV Cam",
    category: "peripheral",
    basePos: [-4.9, 1.15, -0.35],
    explodeDelta: [-1.45, 0.95, 0],
    anchorPos: [3.75, 1.15, -1.75],
    baseColor: 0x334155,
    size: [0.85, 0.95, 1.45],
    labelOffsetY: 0.68,
  },
  {
    id: "wonderecho_pro",
    shortLabel: "WonderEcho Pro",
    category: "peripheral",
    basePos: [2.1, 2.35, 2.55],
    explodeDelta: [1.25, 1.5, 1.45],
    anchorPos: [3.75, 1.15, -0.05],
    baseColor: 0x1e293b,
    size: [1.75, 0.48, 1.35],
    labelOffsetY: 0.5,
  },
];

interface MeshBundle {
  spec: ComponentSpec;
  group: THREE.Group;
  meshes: THREE.Mesh[];
  edges: THREE.LineSegments[];
  guideLine?: THREE.Line;
}

function getStatusPillClasses(status: Pi5ComponentStatus, isSelected: boolean): string {
  if (isSelected) {
    return "border-eigenia-orange bg-eigenia-orange/90 text-white shadow-[0_0_12px_rgba(224,90,16,0.6)]";
  }
  switch (status) {
    case "ok":
      return "border-emerald-400/70 bg-eigenia-obsidian/90 text-emerald-300 hover:border-emerald-300";
    case "warning":
      return "border-eigenia-amber/80 bg-eigenia-obsidian/90 text-eigenia-amber hover:border-eigenia-amber";
    case "fault":
      return "border-eigenia-fault/85 bg-eigenia-obsidian/95 text-eigenia-fault hover:border-eigenia-fault";
    case "empty":
    default:
      return "border-slate-500/60 bg-eigenia-obsidian/85 text-slate-300 hover:border-slate-300";
  }
}

export function Pi5HardwareTwin3D({
  diagnostics,
  selectedComponentId,
  onSelectComponent,
}: Pi5HardwareTwin3DProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const labelRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const bundlesRef = useRef<Map<string, MeshBundle>>(new Map());
  const pcbMeshRef = useRef<THREE.Mesh | null>(null);
  const pcbEdgesRef = useRef<THREE.LineSegments | null>(null);
  const flyTargetRef = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  const explodeRef = useRef<number>(0.25);
  const onSelectRef = useRef(onSelectComponent);
  onSelectRef.current = onSelectComponent;

  const [webglError, setWebglError] = useState<string | null>(null);
  const [renderMode, setRenderMode] = useState<SceneRenderMode>("wireframe");
  const [explodePct, setExplodePct] = useState<number>(25);
  const [labelMode, setLabelMode] = useState<LabelMode>("ports_faults");
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("iso");

  explodeRef.current = explodePct / 100;

  // Map live diagnostic state by canonical component_id
  const statusMap = useMemo(() => {
    const map = new Map<string, Pi5HardwareComponentState>();
    for (const c of diagnostics?.components ?? []) {
      map.set(c.component_id, c);
    }
    return map;
  }, [diagnostics]);

  // Determine which 3D callout labels should be visible
  const visibleLabelIds = useMemo(() => {
    const set = new Set<string>();
    for (const spec of COMPONENT_SPECS) {
      const st = statusMap.get(spec.id)?.status ?? "empty";
      const isSelected = spec.id === selectedComponentId;
      if (labelMode === "all") {
        set.add(spec.id);
      } else if (labelMode === "selected") {
        if (isSelected) set.add(spec.id);
      } else {
        // "ports_faults"
        if (
          isSelected ||
          st === "fault" ||
          st === "warning" ||
          spec.category === "usb" ||
          spec.category === "peripheral" ||
          spec.id === "bcm2712_soc" ||
          spec.id === "da9091_pmic"
        ) {
          set.add(spec.id);
        }
      }
    }
    return set;
  }, [labelMode, selectedComponentId, statusMap]);

  const visibleLabelIdsRef = useRef<Set<string>>(visibleLabelIds);
  visibleLabelIdsRef.current = visibleLabelIds;

  // Initialize Three.js Scene + All 22 Millimeter-Proportional Pi 5 & PuppyPi Meshes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer | null = null;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    } catch (err) {
      console.error("[Pi5HardwareTwin3D] WebGL initialization failed:", err);
      setWebglError("WebGL 3D context could not be initialized for the Raspberry Pi 5 Twin.");
      return;
    }

    setWebglError(null);
    const width = Math.max(container.clientWidth, 320);
    const height = Math.max(container.clientHeight, 360);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.setClearColor(0x0b0d10, 1);
    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0b0d10");

    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 120);
    camera.position.set(8.2, 7.6, 8.8);
    cameraRef.current = camera;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 3.2;
    controls.maxDistance = 26;
    controls.target.set(0.2, 1.1, 0);
    controls.update();
    controlsRef.current = controls;

    // Cancel camera fly-to when user manually drags
    const stopFly = () => {
      flyTargetRef.current = null;
    };
    controls.addEventListener("start", stopFly);

    // Studio CAD lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const keyLight = new THREE.DirectionalLight(0xf8fafc, 1.25);
    keyLight.position.set(8, 14, 10);
    scene.add(keyLight);
    const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.65);
    rimLight.position.set(-10, 8, -8);
    scene.add(rimLight);
    const warmLight = new THREE.PointLight(0xe05a10, 0.7, 22);
    warmLight.position.set(4, 5, 4);
    scene.add(warmLight);

    // CAD baseplate grid
    const grid = new THREE.GridHelper(18, 36, 0x263143, 0x161c26);
    grid.position.y = -0.35;
    scene.add(grid);

    // Raspberry Pi 5 Model B PCB Substrate (85mm x 56mm => 8.5 x 0.16 x 5.6)
    const pcbGeo = new THREE.BoxGeometry(8.5, 0.16, 5.6);
    const pcbMat = new THREE.MeshStandardMaterial({
      color: 0x0f5132,
      roughness: 0.55,
      metalness: 0.15,
    });
    const pcbMesh = new THREE.Mesh(pcbGeo, pcbMat);
    pcbMesh.position.set(0, 0, 0);
    const pcbEdges = createCadOverlayEdges(pcbGeo, 0x38bdf8, 0.55);
    pcbMesh.add(pcbEdges);
    scene.add(pcbMesh);
    pcbMeshRef.current = pcbMesh;
    pcbEdgesRef.current = pcbEdges;

    // 4 Corner M2.5 mounting holes
    const holeGeo = new THREE.CylinderGeometry(0.14, 0.14, 0.2, 12);
    const holeMat = new THREE.MeshStandardMaterial({ color: 0xeab308, metalness: 0.8, roughness: 0.25 });
    [
      [-3.9, 0.01, -2.45],
      [1.9, 0.01, -2.45],
      [-3.9, 0.01, 2.45],
      [1.9, 0.01, 2.45],
    ].forEach(([hx, hy, hz]) => {
      const h = new THREE.Mesh(holeGeo, holeMat);
      h.position.set(hx, hy, hz);
      scene.add(h);
    });

    // Build all 22 canonical interactive components
    const bundles = new Map<string, MeshBundle>();
    const pickables: THREE.Mesh[] = [];

    for (const spec of COMPONENT_SPECS) {
      const grp = new THREE.Group();
      grp.position.set(...spec.basePos);
      const meshes: THREE.Mesh[] = [];
      const edgesList: THREE.LineSegments[] = [];

      const addPart = (
        geo: THREE.BufferGeometry,
        offset: [number, number, number] = [0, 0, 0],
        colorHex = spec.baseColor
      ) => {
        const mat = new THREE.MeshStandardMaterial({ color: colorHex });
        const m = new THREE.Mesh(geo, mat);
        m.position.set(...offset);
        m.userData = { componentId: spec.id };
        const ed = createCadOverlayEdges(geo, 0x38bdf8, 0.85);
        m.add(ed);
        grp.add(m);
        meshes.push(m);
        edgesList.push(ed);
        pickables.push(m);
      };

      if (spec.shape === "lidar") {
        // LD19 360° ToF LiDAR Base + Spinning Optical Turret + CP2102 USB-UART Converter PCB
        addPart(new THREE.BoxGeometry(1.9, 0.22, 1.9), [0, -0.15, 0], 0x1e293b);
        addPart(new THREE.CylinderGeometry(0.86, 0.92, 0.56, 24), [0, 0.24, 0], 0x0f172a);
        addPart(new THREE.CylinderGeometry(0.68, 0.68, 0.16, 24), [0, 0.56, 0], 0x334155);
        // CP2102 USB-to-UART converter mini PCB beside turret
        addPart(new THREE.BoxGeometry(0.85, 0.14, 0.48), [1.55, -0.12, -0.65], 0x065f46);
      } else if (spec.shape === "hat") {
        // Hiwonder RRC Expansion HAT PCB + STM32 MCU + Servo Pin Bank
        addPart(new THREE.BoxGeometry(...spec.size), [0, 0, 0], 0x1e293b);
        addPart(new THREE.BoxGeometry(0.95, 0.18, 0.95), [-1.2, 0.18, 0.25], 0x334155);
        addPart(new THREE.BoxGeometry(3.8, 0.26, 0.65), [0.8, 0.22, -1.55], 0x475569);
      } else {
        addPart(new THREE.BoxGeometry(...spec.size));
        if (spec.id === "camera_icspring") {
          // Camera lens barrel facing -X
          const lensGeo = new THREE.CylinderGeometry(0.32, 0.36, 0.42, 18);
          lensGeo.rotateZ(Math.PI / 2);
          addPart(lensGeo, [-0.52, 0, 0], 0x0f172a);
        }
      }

      scene.add(grp);

      // Exploded dashed guide line for stack/peripheral components
      let guideLine: THREE.Line | undefined;
      if (spec.anchorPos) {
        const lineGeo = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(...spec.anchorPos),
          new THREE.Vector3(...spec.basePos),
        ]);
        const lineMat = new THREE.LineDashedMaterial({
          color: 0xe05a10,
          dashSize: 0.22,
          gapSize: 0.14,
          transparent: true,
          opacity: 0.65,
        });
        guideLine = new THREE.Line(lineGeo, lineMat);
        guideLine.computeLineDistances();
        scene.add(guideLine);
      }

      bundles.set(spec.id, { spec, group: grp, meshes, edges: edgesList, guideLine });
    }
    bundlesRef.current = bundles;

    // Raycaster click selection
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let downPos = { x: 0, y: 0 };
    const handlePointerDown = (e: PointerEvent) => {
      downPos = { x: e.clientX, y: e.clientY };
    };
    const handlePointerUp = (e: PointerEvent) => {
      if (!renderer) return;
      if (Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 6) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(pickables, false);
      const compId = hits[0]?.object?.userData?.componentId as string | undefined;
      if (compId) {
        onSelectRef.current(compId);
      }
    };
    renderer.domElement.addEventListener("pointerdown", handlePointerDown);
    renderer.domElement.addEventListener("pointerup", handlePointerUp);

    // Resize observer
    const handleResize = () => {
      if (!container || !renderer) return;
      const w = Math.max(container.clientWidth, 320);
      const h = Math.max(container.clientHeight, 360);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const resizeObs = new ResizeObserver(handleResize);
    resizeObs.observe(container);

    // 60 FPS Animation + Explode Interpolation + Projected 3D Callout Labels
    const projVec = new THREE.Vector3();
    let rafId = 0;

    const animate = () => {
      rafId = window.requestAnimationFrame(animate);

      // Smooth camera fly-to
      if (flyTargetRef.current) {
        camera.position.lerp(flyTargetRef.current.pos, 0.11);
        controls.target.lerp(flyTargetRef.current.target, 0.12);
        if (
          camera.position.distanceTo(flyTargetRef.current.pos) < 0.05 &&
          controls.target.distanceTo(flyTargetRef.current.target) < 0.05
        ) {
          flyTargetRef.current = null;
        }
      }

      // Smooth explode offset + guide line update
      const factor = explodeRef.current;
      const cw = container.clientWidth || width;
      const ch = container.clientHeight || height;

      bundles.forEach((bundle, id) => {
        const { spec, group, guideLine } = bundle;
        const tx = spec.basePos[0] + spec.explodeDelta[0] * factor;
        const ty = spec.basePos[1] + spec.explodeDelta[1] * factor;
        const tz = spec.basePos[2] + spec.explodeDelta[2] * factor;
        group.position.x += (tx - group.position.x) * 0.18;
        group.position.y += (ty - group.position.y) * 0.18;
        group.position.z += (tz - group.position.z) * 0.18;

        if (guideLine && spec.anchorPos) {
          const posAttr = guideLine.geometry.getAttribute("position") as THREE.BufferAttribute;
          posAttr.setXYZ(0, spec.anchorPos[0], spec.anchorPos[1], spec.anchorPos[2]);
          posAttr.setXYZ(1, group.position.x, group.position.y, group.position.z);
          posAttr.needsUpdate = true;
          guideLine.computeLineDistances();
          guideLine.visible = factor > 0.02;
        }

        // Update projected DOM callout pill position directly (zero React re-renders)
        const el = labelRefs.current[id];
        if (!el) return;
        if (!visibleLabelIdsRef.current.has(id)) {
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          return;
        }

        projVec.set(
          group.position.x,
          group.position.y + (spec.labelOffsetY ?? 0.35),
          group.position.z
        );
        projVec.project(camera);

        if (projVec.z > 1) {
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          return;
        }

        const rawX = (projVec.x * 0.5 + 0.5) * cw;
        const rawY = (-projVec.y * 0.5 + 0.5) * ch;
        const clampedX = Math.max(52, Math.min(cw - 52, rawX));
        const clampedY = Math.max(20, Math.min(ch - 20, rawY));
        el.style.transform = `translate3d(${clampedX.toFixed(1)}px, ${clampedY.toFixed(1)}px, 0) translate(-50%, -50%)`;
        el.style.opacity = "1";
        el.style.pointerEvents = "auto";
      });

      controls.update();
      renderer?.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(rafId);
      resizeObs.disconnect();
      controls.removeEventListener("start", stopFly);
      renderer?.domElement.removeEventListener("pointerdown", handlePointerDown);
      renderer?.domElement.removeEventListener("pointerup", handlePointerUp);
      controls.dispose();
      bundles.forEach((b) => {
        b.meshes.forEach((m) => {
          m.geometry.dispose();
          (m.material as THREE.Material).dispose();
        });
        b.edges.forEach((ed) => {
          ed.geometry.dispose();
          (ed.material as THREE.Material).dispose();
        });
        if (b.guideLine) {
          b.guideLine.geometry.dispose();
          (b.guideLine.material as THREE.Material).dispose();
        }
      });
      pcbGeo.dispose();
      pcbMat.dispose();
      pcbEdges.geometry.dispose();
      (pcbEdges.material as THREE.Material).dispose();
      holeGeo.dispose();
      holeMat.dispose();
      grid.dispose();
      renderer?.dispose();
      bundlesRef.current.clear();
      pcbMeshRef.current = null;
      pcbEdgesRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, []);

  // Update CAD render mode + live diagnostic status colors + selection highlight
  useEffect(() => {
    if (pcbMeshRef.current && pcbEdgesRef.current) {
      applyHardwareRenderMode(
        pcbMeshRef.current,
        pcbEdgesRef.current,
        renderMode,
        0x0f5132,
        0x38bdf8,
        false
      );
    }

    bundlesRef.current.forEach((bundle, id) => {
      const liveState = statusMap.get(id);
      const status: Pi5ComponentStatus = liveState?.status ?? "empty";
      const isSelected = id === selectedComponentId;
      const statusHex = getCadStatusHex(status, isSelected);
      bundle.meshes.forEach((m, idx) => {
        applyHardwareRenderMode(
          m,
          bundle.edges[idx] ?? null,
          renderMode,
          bundle.spec.baseColor,
          statusHex,
          isSelected
        );
      });
    });
  }, [renderMode, statusMap, selectedComponentId]);

  // Apply Camera Presets
  useEffect(() => {
    if (!cameraRef.current || !controlsRef.current) return;
    if (cameraPreset === "top") {
      flyTargetRef.current = {
        pos: new THREE.Vector3(0, 12.5, 0.05),
        target: new THREE.Vector3(0, 0.4, 0),
      };
    } else if (cameraPreset === "usb") {
      flyTargetRef.current = {
        pos: new THREE.Vector3(10.2, 3.1, -0.4),
        target: new THREE.Vector3(3.4, 0.9, -0.4),
      };
    } else if (cameraPreset === "exploded") {
      setExplodePct(85);
      flyTargetRef.current = {
        pos: new THREE.Vector3(9.6, 8.8, 10.4),
        target: new THREE.Vector3(0, 2.3, 0),
      };
    } else {
      flyTargetRef.current = {
        pos: new THREE.Vector3(8.2, 7.6, 8.8),
        target: new THREE.Vector3(0.2, 1.1, 0),
      };
    }
  }, [cameraPreset]);

  // Auto-fly camera smoothly to newly selected component (BOM -> 3D cross-probing!)
  useEffect(() => {
    if (!selectedComponentId) return;
    const bundle = bundlesRef.current.get(selectedComponentId);
    if (!bundle) return;
    const factor = explodeRef.current;
    const { spec } = bundle;
    const tx = spec.basePos[0] + spec.explodeDelta[0] * factor;
    const ty = spec.basePos[1] + spec.explodeDelta[1] * factor;
    const tz = spec.basePos[2] + spec.explodeDelta[2] * factor;

    const target = new THREE.Vector3(tx, ty, tz);
    const offset =
      spec.category === "usb"
        ? new THREE.Vector3(4.2, 2.1, -1.2)
        : spec.id === "microsd_slot"
        ? new THREE.Vector3(-4.0, -2.0, 2.8)
        : new THREE.Vector3(3.6, 3.2, 4.2);

    flyTargetRef.current = {
      pos: target.clone().add(offset),
      target,
    };
  }, [selectedComponentId]);

  const faultCount = useMemo(
    () => (diagnostics?.components ?? []).filter((c) => c.status === "fault").length,
    [diagnostics]
  );
  const warnCount = useMemo(
    () => (diagnostics?.components ?? []).filter((c) => c.status === "warning").length,
    [diagnostics]
  );

  return (
    <div className="relative flex h-[540px] w-full flex-col overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
      {/* Top Toolbar: Render Mode, Camera Presets, Label Filter & Explode Slider */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="default">
            <Cpu className="h-3 w-3" /> 3D PI 5 + PUPPYPI BOM TWIN
          </Badge>

          {/* 3 Render Mode Buttons */}
          <div className="inline-flex items-center rounded border border-white/10 bg-eigenia-obsidian p-0.5">
            {(
              [
                { id: "wireframe", label: "Wireframe", icon: Grid3x3 },
                { id: "translucent", label: "Translucent", icon: Layers },
                { id: "solid", label: "Solid", icon: Box },
              ] as const
            ).map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setRenderMode(m.id)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-[10px] font-medium transition-colors",
                    renderMode === m.id
                      ? "bg-eigenia-orange text-white"
                      : "text-eigenia-muted hover:text-white"
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {m.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Camera Presets */}
        <div className="flex flex-wrap items-center gap-1">
          <Button
            size="sm"
            variant={cameraPreset === "iso" ? "sky" : "secondary"}
            onClick={() => setCameraPreset("iso")}
          >
            Iso
          </Button>
          <Button
            size="sm"
            variant={cameraPreset === "top" ? "sky" : "secondary"}
            onClick={() => setCameraPreset("top")}
          >
            <Compass className="h-3 w-3" /> Top PCB
          </Button>
          <Button
            size="sm"
            variant={cameraPreset === "usb" ? "sky" : "secondary"}
            onClick={() => setCameraPreset("usb")}
          >
            <Usb className="h-3 w-3" /> USB Ports
          </Button>
          <Button
            size="sm"
            variant={cameraPreset === "exploded" ? "sky" : "secondary"}
            onClick={() => setCameraPreset("exploded")}
          >
            <Eye className="h-3 w-3" /> Exploded
          </Button>
        </div>
      </div>

      {/* Sub-bar: Exploded-View Slider + Label Filter Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-eigenia-obsidian/90 px-3 py-1.5">
        <div className="flex min-w-[210px] flex-1 items-center gap-2.5">
          <span className="whitespace-nowrap font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
            Explode Stack: <strong className="text-white">{explodePct}%</strong>
          </span>
          <Slider
            min={0}
            max={100}
            step={5}
            value={[explodePct]}
            onValueChange={([v]) => setExplodePct(v)}
            className="max-w-[180px]"
          />
        </div>

        <div className="flex items-center gap-1.5">
          <Tag className="h-3 w-3 text-eigenia-sky" />
          {(
            [
              { id: "all", label: "All Labels" },
              { id: "ports_faults", label: "Ports & Faults" },
              { id: "selected", label: "Selected" },
            ] as const
          ).map((lm) => (
            <button
              key={lm.id}
              type="button"
              onClick={() => setLabelMode(lm.id)}
              className={cn(
                "rounded border px-2 py-0.5 font-mono text-[10px] transition-colors",
                labelMode === lm.id
                  ? "border-eigenia-sky bg-eigenia-sky/15 text-eigenia-sky"
                  : "border-white/10 bg-eigenia-surface text-eigenia-muted hover:text-white"
              )}
            >
              {lm.label}
            </button>
          ))}
        </div>
      </div>

      {/* Interactive 3D Viewport + 60 FPS Projected Tailwind Callout Labels */}
      <div className="relative flex-1 overflow-hidden">
        {webglError ? (
          <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-eigenia-amber">
            {webglError}
          </div>
        ) : (
          <div ref={containerRef} className="h-full w-full" />
        )}

        {/* Projected 3D Callout Overlay Layer */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          {COMPONENT_SPECS.map((spec) => {
            const live = statusMap.get(spec.id);
            const status: Pi5ComponentStatus = live?.status ?? "empty";
            const isSelected = spec.id === selectedComponentId;
            const pulseDot = status === "fault" || status === "warning";

            return (
              <button
                key={spec.id}
                ref={(el) => {
                  labelRefs.current[spec.id] = el;
                }}
                type="button"
                onClick={() => onSelectComponent(spec.id)}
                style={{ opacity: 0, pointerEvents: "none" }}
                className={cn(
                  "absolute left-0 top-0 inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[10px] font-medium backdrop-blur-sm transition-colors",
                  getStatusPillClasses(status, isSelected)
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    isSelected
                      ? "bg-white"
                      : status === "ok"
                      ? "bg-emerald-400"
                      : status === "warning"
                      ? "bg-eigenia-amber"
                      : status === "fault"
                      ? "bg-eigenia-fault"
                      : "bg-slate-400",
                    pulseDot && "animate-pulse"
                  )}
                />
                <span>{spec.shortLabel}</span>
              </button>
            );
          })}
        </div>

        {/* Bottom Legend Strip */}
        <div className="pointer-events-none absolute bottom-2.5 left-3 flex flex-wrap gap-1.5">
          <Badge variant="sky">22 Components</Badge>
          {faultCount > 0 && <Badge variant="fault">{faultCount} Fault</Badge>}
          {warnCount > 0 && <Badge variant="amber">{warnCount} Warning</Badge>}
          <Badge variant="neutral">Click any 3D chip/port to inspect</Badge>
        </div>
      </div>
    </div>
  );
}

export default Pi5HardwareTwin3D;
