"use client";

import React, { useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type {
  BoardId,
  MicrobitAccessorySpec,
  MicrobitAttachment,
  MicrobitLiveSensors,
  MicrobitPinSpec,
  MicrobitTrigger,
} from "@/lib/microbitApi";

export interface Microbit3DHandle {
  setView: (view: "front" | "back" | "iso" | "top") => void;
  playMotionPulse: (kind: "lift" | "tilt_left" | "tilt_right" | "shake") => void;
}

interface Microbit3DCanvasProps {
  boardId?: BoardId;
  pins: MicrobitPinSpec[];
  accessories: MicrobitAccessorySpec[];
  attachments: MicrobitAttachment[];
  selectedPinId: string | null;
  liveSensors: MicrobitLiveSensors | null;
  liveTiltEnabled: boolean;
  ledIcon: string;
  simServoAngle: number;
  simNeopixelHex: string;
  onSelectPin: (pinId: string) => void;
  onVirtualTrigger: (trigger: MicrobitTrigger) => void;
}

const LED_ICONS: Record<string, number[][]> = {
  HAPPY: [
    [0, 1, 0, 1, 0],
    [0, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [1, 0, 0, 0, 1],
    [0, 1, 1, 1, 0],
  ],
  HEART: [
    [0, 1, 0, 1, 0],
    [1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
  ],
  SURPRISED: [
    [0, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 0, 1, 0, 0],
    [0, 1, 0, 1, 0],
    [0, 0, 1, 0, 0],
  ],
  SAD: [
    [0, 1, 0, 1, 0],
    [0, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 1, 1, 1, 0],
    [1, 0, 0, 0, 1],
  ],
  CONFUSED: [
    [0, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 1, 0, 1, 0],
    [1, 0, 1, 0, 1],
    [0, 0, 0, 0, 0],
  ],
  ARROW_N: [
    [0, 0, 1, 0, 0],
    [0, 1, 1, 1, 0],
    [1, 0, 1, 0, 1],
    [0, 0, 1, 0, 0],
    [0, 0, 1, 0, 0],
  ],
  ARROW_E: [
    [0, 0, 1, 0, 0],
    [0, 0, 0, 1, 0],
    [1, 1, 1, 1, 1],
    [0, 0, 0, 1, 0],
    [0, 0, 1, 0, 0],
  ],
  ARROW_W: [
    [0, 0, 1, 0, 0],
    [0, 1, 0, 0, 0],
    [1, 1, 1, 1, 1],
    [0, 1, 0, 0, 0],
    [0, 0, 1, 0, 0],
  ],
  YES: [
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 1],
    [0, 0, 0, 1, 0],
    [1, 0, 1, 0, 0],
    [0, 1, 0, 0, 0],
  ],
  NO: [
    [1, 0, 0, 0, 1],
    [0, 1, 0, 1, 0],
    [0, 0, 1, 0, 0],
    [0, 1, 0, 1, 0],
    [1, 0, 0, 0, 1],
  ],
};

function makeAccessory3D(spec: MicrobitAccessorySpec, neopixelHex: string): {
  group: THREE.Group;
  servoHorn?: THREE.Group;
  neopixelMats?: THREE.MeshStandardMaterial[];
  clickableTrigger?: THREE.Object3D;
} {
  const g = new THREE.Group();
  const baseColor = new THREE.Color(spec.color_hex || "#38bdf8");

  if (spec.id === "hiwonder_led_matrix_8x16") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(2.6, 1.35, 0.16),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.45 })
    );
    g.add(pcb);
    const mats: THREE.MeshStandardMaterial[] = [];
    const col = new THREE.Color(neopixelHex || "#ef4444");
    for (let r = 0; r < 6; r++) {
      for (let c = 0; c < 12; c++) {
        const lit = (r === 1 && (c === 3 || c === 8)) || (r === 4 && c >= 3 && c <= 8) || (r === 3 && (c === 2 || c === 9));
        const m = new THREE.MeshStandardMaterial({
          color: lit ? col : 0x331118,
          emissive: lit ? col : 0x000000,
          emissiveIntensity: lit ? 1.2 : 0,
        });
        if (lit) mats.push(m);
        const dot = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.11, 0.06), m);
        dot.position.set(-1.08 + c * 0.195, 0.48 - r * 0.19, 0.09);
        g.add(dot);
      }
    }
    return { group: g, neopixelMats: mats };
  }

  if (spec.id === "hiwonder_ultrasonic_v56") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.9, 0.95, 0.16),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 })
    );
    g.add(pcb);
    const mats: THREE.MeshStandardMaterial[] = [];
    const ringCol = new THREE.Color(neopixelHex || "#10b981");
    for (const sx of [-0.5, 0.5]) {
      const cyl = new THREE.Mesh(
        new THREE.CylinderGeometry(0.34, 0.34, 0.42, 20),
        new THREE.MeshStandardMaterial({ color: 0xcbd5e1, metalness: 0.8, roughness: 0.2 })
      );
      cyl.rotation.x = Math.PI / 2;
      cyl.position.set(sx, 0, 0.22);
      const ringMat = new THREE.MeshStandardMaterial({
        color: ringCol,
        emissive: ringCol,
        emissiveIntensity: 1.3,
      });
      mats.push(ringMat);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.35, 0.05, 10, 24), ringMat);
      ring.position.set(sx, 0, 0.38);
      g.add(cyl, ring);
    }
    return { group: g, neopixelMats: mats };
  }

  if (spec.id === "hiwonder_temp_hum_v11") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.5, 0.9, 0.14),
      new THREE.MeshStandardMaterial({ color: 0x0369a1, roughness: 0.45 })
    );
    const chip = new THREE.Mesh(
      new THREE.BoxGeometry(0.45, 0.45, 0.14),
      new THREE.MeshStandardMaterial({ color: 0xe2e8f0, metalness: 0.7, roughness: 0.25 })
    );
    chip.position.set(0.25, 0, 0.1);
    const ph20 = new THREE.Mesh(
      new THREE.BoxGeometry(0.42, 0.28, 0.24),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 })
    );
    ph20.position.set(-0.45, 0, 0.12);
    g.add(pcb, chip, ph20);
    return { group: g };
  }

  if (spec.id === "hiwonder_touch_sensor") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.8, 0.78, 0.14),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 })
    );
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(0.32, 0.32, 0.06, 24),
      new THREE.MeshStandardMaterial({ color: 0xf59e0b, metalness: 0.85, roughness: 0.2, emissive: 0xd97706, emissiveIntensity: 0.35 })
    );
    pad.rotation.x = Math.PI / 2;
    pad.position.set(0.35, 0, 0.09);
    pad.userData = { virtualTrigger: "touch_pad" as MicrobitTrigger };
    g.add(pcb, pad);
    return { group: g, clickableTrigger: pad };
  }

  if (spec.id === "ld19_lidar") {
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.58, 0.62, 0.32, 24),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.35 })
    );
    const turret = new THREE.Mesh(
      new THREE.CylinderGeometry(0.48, 0.52, 0.28, 24),
      new THREE.MeshStandardMaterial({ color: 0x06b6d4, metalness: 0.5, roughness: 0.25 })
    );
    turret.position.y = 0.3;
    g.add(base, turret);
    return { group: g };
  }

  if (spec.id === "sg90_servo") {
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.1, 1.15, 0.55),
      new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.4, metalness: 0.15 })
    );
    const hornPivot = new THREE.Group();
    hornPivot.position.set(0, 0.62, 0.1);
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.18, 0.2, 16),
      new THREE.MeshStandardMaterial({ color: 0xe2e8f0 })
    );
    const arm = new THREE.Mesh(
      new THREE.BoxGeometry(0.95, 0.16, 0.12),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 })
    );
    arm.position.set(0.32, 0.04, 0);
    hornPivot.add(hub, arm);
    g.add(body, hornPivot);
    return { group: g, servoHorn: hornPivot };
  }

  if (spec.id === "neopixel_8") {
    const strip = new THREE.Mesh(
      new THREE.BoxGeometry(2.4, 0.35, 0.12),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 })
    );
    g.add(strip);
    const mats: THREE.MeshStandardMaterial[] = [];
    const col = new THREE.Color(neopixelHex || "#22d3ee");
    for (let i = 0; i < 8; i++) {
      const m = new THREE.MeshStandardMaterial({
        color: col,
        emissive: col,
        emissiveIntensity: 1.0,
      });
      mats.push(m);
      const led = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.18, 0.14), m);
      led.position.set(-1.05 + i * 0.3, 0, 0.04);
      g.add(led);
    }
    return { group: g, neopixelMats: mats };
  }

  if (spec.id === "oled_ssd1306") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.4, 1.1, 0.14),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 })
    );
    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(1.15, 0.68),
      new THREE.MeshStandardMaterial({ color: 0x0ea5e9, emissive: 0x0284c7, emissiveIntensity: 0.5 })
    );
    screen.position.set(0, 0.04, 0.08);
    g.add(pcb, screen);
    return { group: g };
  }

  if (spec.id === "hcsr04_ultrasonic") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.8, 0.85, 0.14),
      new THREE.MeshStandardMaterial({ color: 0x1d4ed8, roughness: 0.45 })
    );
    g.add(pcb);
    for (const sx of [-0.48, 0.48]) {
      const cyl = new THREE.Mesh(
        new THREE.CylinderGeometry(0.32, 0.32, 0.42, 20),
        new THREE.MeshStandardMaterial({ color: 0xcbd5e1, metalness: 0.75, roughness: 0.25 })
      );
      cyl.rotation.x = Math.PI / 2;
      cyl.position.set(sx, 0, 0.22);
      g.add(cyl);
    }
    return { group: g };
  }

  if (spec.id === "external_speaker") {
    const housing = new THREE.Mesh(
      new THREE.CylinderGeometry(0.65, 0.55, 0.42, 24),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.4 })
    );
    housing.rotation.x = Math.PI / 2;
    const cone = new THREE.Mesh(
      new THREE.CylinderGeometry(0.46, 0.18, 0.18, 24),
      new THREE.MeshStandardMaterial({ color: 0xec4899, roughness: 0.35 })
    );
    cone.rotation.x = Math.PI / 2;
    cone.position.z = 0.16;
    g.add(housing, cone);
    return { group: g };
  }

  const mod = new THREE.Mesh(
    new THREE.BoxGeometry(1.2, 0.9, 0.28),
    new THREE.MeshStandardMaterial({ color: baseColor, roughness: 0.45, metalness: 0.15 })
  );
  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(0.32, 16, 12),
    new THREE.MeshStandardMaterial({ color: 0xf8fafc, transparent: true, opacity: 0.85 })
  );
  dome.position.z = 0.16;
  g.add(mod, dome);
  return { group: g };
}

export const Microbit3DCanvas = React.forwardRef<Microbit3DHandle, Microbit3DCanvasProps>(
  function Microbit3DCanvas(
    {
      boardId = "microbit_v2",
      pins,
      accessories,
      attachments,
      selectedPinId,
      liveSensors,
      liveTiltEnabled,
      ledIcon,
      simServoAngle,
      simNeopixelHex,
      onSelectPin,
      onVirtualTrigger,
    },
    ref
  ) {
    const mountRef = useRef<HTMLDivElement | null>(null);
    const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
    const controlsRef = useRef<OrbitControls | null>(null);
    const boardGroupRef = useRef<THREE.Group | null>(null);
    const ledMeshesRef = useRef<THREE.Mesh[][]>([]);
    const pinMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());
    const interactiveMeshesRef = useRef<THREE.Object3D[]>([]);
    const attachmentsGroupRef = useRef<THREE.Group | null>(null);
    const servoHornsRef = useRef<THREE.Group[]>([]);
    const neopixelMatsRef = useRef<THREE.MeshStandardMaterial[]>([]);

    const onSelectPinRef = useRef(onSelectPin);
    onSelectPinRef.current = onSelectPin;
    const onVirtualTriggerRef = useRef(onVirtualTrigger);
    onVirtualTriggerRef.current = onVirtualTrigger;

    const targetRotRef = useRef<{ rx: number; rz: number }>({ rx: 0, rz: 0 });
    const targetServoRadRef = useRef<number>(0);
    const motionPulseRef = useRef<{ kind: string; t: number } | null>(null);

    useImperativeHandle(ref, () => ({
      setView: (view) => {
        const cam = cameraRef.current;
        const ctrl = controlsRef.current;
        if (!cam || !ctrl) return;
        if (view === "front") cam.position.set(0, 0.2, 7.6);
        else if (view === "back") cam.position.set(0, 0.2, -7.6);
        else if (view === "top") cam.position.set(0, 7.8, 1.5);
        else cam.position.set(4.2, 3.4, 6.8);
        ctrl.target.set(0, -0.3, 0);
        ctrl.update();
      },
      playMotionPulse: (kind) => {
        motionPulseRef.current = { kind, t: 0 };
      },
    }));

    useEffect(() => {
      targetServoRadRef.current = THREE.MathUtils.degToRad((simServoAngle - 90) * 1.0);
    }, [simServoAngle]);

    useEffect(() => {
      const col = new THREE.Color(simNeopixelHex || "#22d3ee");
      neopixelMatsRef.current.forEach((m) => {
        m.color.copy(col);
        m.emissive.copy(col);
      });
    }, [simNeopixelHex]);

    // Update 5x5 LED matrix dynamically
    useEffect(() => {
      const pat = LED_ICONS[ledIcon?.toUpperCase()] || LED_ICONS.HAPPY;
      const grid = ledMeshesRef.current;
      for (let r = 0; r < grid.length; r++) {
        for (let c = 0; c < grid[r].length; c++) {
          const lit = pat[r]?.[c] === 1;
          const mat = grid[r][c].material as THREE.MeshStandardMaterial;
          mat.color.setHex(lit ? 0xff2a3c : 0x331118);
          mat.emissive.setHex(lit ? 0xff1e32 : 0x000000);
          mat.emissiveIntensity = lit ? 1.5 : 0;
        }
      }
    }, [ledIcon]);

    useEffect(() => {
      if (!liveTiltEnabled || !liveSensors) {
        targetRotRef.current = { rx: 0, rz: 0 };
        return;
      }
      const ax = Math.max(-1024, Math.min(1024, liveSensors.ax || 0)) / 1024;
      const ay = Math.max(-1024, Math.min(1024, liveSensors.ay || 0)) / 1024;
      targetRotRef.current = { rx: ay * 0.75, rz: -ax * 0.75 };
    }, [liveSensors, liveTiltEnabled]);

    // 1. Build Three.js r187 micro:bit v2.2 PCB Scene
    useEffect(() => {
      const container = mountRef.current;
      if (!container) return;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#050914");

      const camera = new THREE.PerspectiveCamera(
        46,
        Math.max(1, container.clientWidth) / Math.max(1, container.clientHeight),
        0.1,
        100
      );
      camera.position.set(3.8, 2.8, 6.8);
      cameraRef.current = camera;

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      container.innerHTML = "";
      container.appendChild(renderer.domElement);

      scene.add(new THREE.AmbientLight(0xdbeafe, 0.9));
      const key = new THREE.DirectionalLight(0xffffff, 1.4);
      key.position.set(5, 8, 7);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0x38bdf8, 0.7);
      fill.position.set(-5, -4, -6);
      scene.add(fill);

      const grid = new THREE.GridHelper(18, 24, 0x1e293b, 0x0f172a);
      grid.position.y = -3.4;
      scene.add(grid);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.target.set(0, -0.3, 0);
      controlsRef.current = controls;

      const board = new THREE.Group();
      boardGroupRef.current = board;
      scene.add(board);

      interactiveMeshesRef.current = [];
      pinMeshesRef.current.clear();
      ledMeshesRef.current = [];

      if (boardId === "rpi5_16gb") {
        // Raspberry Pi 5 16GB PCB (emerald green + 40-pin GPIO + USB 3.0 + Ethernet + BCM2712 heatsink)
        const pcb = new THREE.Mesh(
          new THREE.BoxGeometry(6.2, 4.1, 0.18),
          new THREE.MeshStandardMaterial({ color: 0x065f46, roughness: 0.42, metalness: 0.2 })
        );
        board.add(pcb);
        const cpu = new THREE.Mesh(
          new THREE.BoxGeometry(1.4, 1.4, 0.35),
          new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.85, roughness: 0.25 })
        );
        cpu.position.set(-0.3, 0.1, 0.24);
        const eth = new THREE.Mesh(
          new THREE.BoxGeometry(1.15, 0.95, 0.85),
          new THREE.MeshStandardMaterial({ color: 0xcbd5e1, metalness: 0.85, roughness: 0.2 })
        );
        eth.position.set(2.55, -1.1, 0.5);
        const usb1 = new THREE.Mesh(
          new THREE.BoxGeometry(1.0, 0.82, 0.82),
          new THREE.MeshStandardMaterial({ color: 0x2563eb, metalness: 0.4, roughness: 0.3 })
        );
        usb1.position.set(2.55, 0.2, 0.48);
        const usb2 = usb1.clone();
        usb2.position.set(2.55, 1.25, 0.48);
        board.add(cpu, eth, usb1, usb2);

        // 40-pin GPIO header along bottom edge for clean jumper routing
        const header = new THREE.Mesh(
          new THREE.BoxGeometry(4.4, 0.48, 0.35),
          new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.5 })
        );
        header.position.set(-0.4, -1.78, 0.22);
        board.add(header);
      } else if (boardId === "puppypi_pro") {
        // PuppyPi Pro Quadruped Proof-of-Concept + LD19 LiDAR Turret + WonderEcho AI Box
        const chassis = new THREE.Mesh(
          new THREE.BoxGeometry(4.6, 1.4, 2.4),
          new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.38, metalness: 0.35 })
        );
        board.add(chassis);
        const topDeck = new THREE.Mesh(
          new THREE.BoxGeometry(4.4, 0.14, 2.2),
          new THREE.MeshStandardMaterial({ color: 0x0284c7, roughness: 0.35, metalness: 0.4 })
        );
        topDeck.position.y = 0.75;
        const lidarTurret = new THREE.Mesh(
          new THREE.CylinderGeometry(0.62, 0.68, 0.48, 24),
          new THREE.MeshStandardMaterial({ color: 0x06b6d4, metalness: 0.6, roughness: 0.25 })
        );
        lidarTurret.position.set(0.8, 1.12, 0);
        const aiBox = new THREE.Mesh(
          new THREE.BoxGeometry(1.2, 0.48, 0.9),
          new THREE.MeshStandardMaterial({ color: 0x7c3aed, roughness: 0.35 })
        );
        aiBox.position.set(-1.1, 1.06, 0);
        board.add(topDeck, lidarTurret, aiBox);
        // 4 legs
        for (const [lx, lz] of [[-1.6, 1.05], [1.6, 1.05], [-1.6, -1.05], [1.6, -1.05]]) {
          const leg = new THREE.Mesh(
            new THREE.BoxGeometry(0.32, 1.5, 0.26),
            new THREE.MeshStandardMaterial({ color: 0x334155, metalness: 0.5, roughness: 0.35 })
          );
          leg.position.set(lx, -1.1, lz);
          board.add(leg);
        }
      } else {
        // Default: BBC micro:bit v2.2 PCB
        const pcb = new THREE.Mesh(
          new THREE.BoxGeometry(5.2, 4.2, 0.16),
          new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.42, metalness: 0.25 })
        );
        board.add(pcb);
        board.add(
          new THREE.LineSegments(
            new THREE.EdgesGeometry(new THREE.BoxGeometry(5.22, 4.22, 0.17)),
            new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.35 })
          )
        );

        const ledGrid: THREE.Mesh[][] = [];
        for (let r = 0; r < 5; r++) {
          const row: THREE.Mesh[] = [];
          for (let c = 0; c < 5; c++) {
            const lit = LED_ICONS.HAPPY[r][c] === 1;
            const led = new THREE.Mesh(
              new THREE.BoxGeometry(0.14, 0.26, 0.06),
              new THREE.MeshStandardMaterial({
                color: lit ? 0xff2a3c : 0x331118,
                emissive: lit ? 0xff1e32 : 0x000000,
                emissiveIntensity: lit ? 1.5 : 0,
              })
            );
            led.position.set((c - 2) * 0.42, (2 - r) * 0.42 + 0.15, 0.1);
            board.add(led);
            row.push(led);
          }
          ledGrid.push(row);
        }
        ledMeshesRef.current = ledGrid;

        const btns: Array<{ x: number; trigger: MicrobitTrigger }> = [
          { x: -1.85, trigger: "button_a" },
          { x: 1.85, trigger: "button_b" },
        ];
        for (const b of btns) {
          const housing = new THREE.Mesh(
            new THREE.BoxGeometry(0.66, 0.66, 0.12),
            new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.4 })
          );
          housing.position.set(b.x, 0.15, 0.12);
          housing.userData = { virtualTrigger: b.trigger };
          const cap = new THREE.Mesh(
            new THREE.CylinderGeometry(0.22, 0.22, 0.16, 16),
            new THREE.MeshStandardMaterial({ color: 0x020617, roughness: 0.3 })
          );
          cap.rotation.x = Math.PI / 2;
          cap.position.set(b.x, 0.15, 0.19);
          cap.userData = { virtualTrigger: b.trigger };
          board.add(housing, cap);
          interactiveMeshesRef.current.push(housing, cap);
        }

        const logo = new THREE.Mesh(
          new THREE.BoxGeometry(1.15, 0.54, 0.06),
          new THREE.MeshStandardMaterial({ color: 0xf59e0b, metalness: 0.85, roughness: 0.22 })
        );
        logo.position.set(0, 1.55, 0.09);
        logo.userData = { virtualTrigger: "logo_touch" as MicrobitTrigger };
        board.add(logo);
        interactiveMeshesRef.current.push(logo);

        const micLed = new THREE.Mesh(
          new THREE.SphereGeometry(0.08, 12, 12),
          new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0xef4444, emissiveIntensity: 0.9 })
        );
        micLed.position.set(1.25, 1.55, 0.11);
        const mcu = new THREE.Mesh(
          new THREE.BoxGeometry(0.75, 0.75, 0.09),
          new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.4 })
        );
        mcu.position.set(-1.1, 0.2, -0.11);
        const speakerBox = new THREE.Mesh(
          new THREE.BoxGeometry(0.95, 0.95, 0.24),
          new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.35 })
        );
        speakerBox.position.set(0.35, 0.15, -0.18);
        const speakerCone = new THREE.Mesh(
          new THREE.CylinderGeometry(0.32, 0.32, 0.05, 20),
          new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.8, roughness: 0.2 })
        );
        speakerCone.rotation.x = Math.PI / 2;
        speakerCone.position.set(0.35, 0.15, -0.31);
        const usbPort = new THREE.Mesh(
          new THREE.BoxGeometry(0.75, 0.48, 0.28),
          new THREE.MeshStandardMaterial({ color: 0xcbd5e1, metalness: 0.85, roughness: 0.2 })
        );
        usbPort.position.set(0, 1.92, -0.2);
        const jstPort = new THREE.Mesh(
          new THREE.BoxGeometry(0.68, 0.56, 0.42),
          new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 })
        );
        jstPort.position.set(1.55, 1.78, -0.26);
        board.add(micLed, mcu, speakerBox, speakerCone, usbPort, jstPort);
      }

      // Dynamic Clickable Pin Pads for whichever board is active
      for (const p of pins) {
        const isBig = p.pad_type === "ring" || boardId !== "microbit_v2";
        const pad = new THREE.Mesh(
          new THREE.BoxGeometry(isBig ? 0.36 : 0.14, isBig ? 0.52 : 0.44, 0.22),
          new THREE.MeshStandardMaterial({
            color: p.pad_type === "power" ? 0xef4444 : p.pad_type === "ground" ? 0x475569 : 0xeab308,
            metalness: 0.8,
            roughness: 0.25,
          })
        );
        pad.position.set((p.x_mm || 0) / 10, -1.78, boardId === "rpi5_16gb" ? 0.24 : 0);
        pad.userData = { pinId: p.id };
        board.add(pad);
        pinMeshesRef.current.set(p.id, pad);
        interactiveMeshesRef.current.push(pad);
      }

      const attGroup = new THREE.Group();
      attachmentsGroupRef.current = attGroup;
      scene.add(attGroup);

      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      const onClick = (e: MouseEvent) => {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(interactiveMeshesRef.current, false);
        if (hits.length > 0) {
          const ud = hits[0].object.userData;
          if (ud?.virtualTrigger) {
            onVirtualTriggerRef.current(ud.virtualTrigger as MicrobitTrigger);
          } else if (ud?.pinId) {
            onSelectPinRef.current(String(ud.pinId));
          }
        }
      };
      renderer.domElement.addEventListener("click", onClick);

      const resizeObs = new ResizeObserver(() => {
        if (!container) return;
        const w = Math.max(1, container.clientWidth);
        const h = Math.max(1, container.clientHeight);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      });
      resizeObs.observe(container);

      let rafId = 0;
      const clock = new THREE.Clock();
      const animate = () => {
        rafId = requestAnimationFrame(animate);
        const dt = Math.min(0.05, clock.getDelta());

        let pulseY = 0;
        let pulseRz = 0;
        if (motionPulseRef.current) {
          motionPulseRef.current.t += dt;
          const t = motionPulseRef.current.t;
          if (t > 0.9) {
            motionPulseRef.current = null;
          } else if (motionPulseRef.current.kind === "lift") {
            pulseY = Math.sin((t / 0.9) * Math.PI) * 1.15;
          } else if (motionPulseRef.current.kind === "shake") {
            pulseRz = Math.sin(t * 36) * 0.28 * (1 - t / 0.9);
          } else if (motionPulseRef.current.kind === "tilt_left") {
            pulseRz = Math.sin((t / 0.9) * Math.PI) * 0.55;
          } else if (motionPulseRef.current.kind === "tilt_right") {
            pulseRz = -Math.sin((t / 0.9) * Math.PI) * 0.55;
          }
        }

        board.position.y += (pulseY - board.position.y) * 0.22;
        board.rotation.x += (targetRotRef.current.rx - board.rotation.x) * 0.14;
        board.rotation.z += (targetRotRef.current.rz + pulseRz - board.rotation.z) * 0.18;

        for (const horn of servoHornsRef.current) {
          horn.rotation.y += (targetServoRadRef.current - horn.rotation.y) * 0.16;
        }

        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      return () => {
        cancelAnimationFrame(rafId);
        resizeObs.disconnect();
        renderer.domElement.removeEventListener("click", onClick);
        controls.dispose();
        renderer.dispose();
      };
    }, [boardId, pins]);

    useEffect(() => {
      pinMeshesRef.current.forEach((mesh, pid) => {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        if (pid === selectedPinId) {
          mat.emissive.setHex(0x22d3ee);
          mat.emissiveIntensity = 0.85;
        } else {
          mat.emissive.setHex(0x000000);
          mat.emissiveIntensity = 0;
        }
      });
    }, [selectedPinId]);

    useEffect(() => {
      const group = attachmentsGroupRef.current;
      if (!group) return;
      group.clear();
      servoHornsRef.current = [];
      neopixelMatsRef.current = [];

      const accById = new Map(accessories.map((a) => [a.id, a]));
      const pinXById = new Map(pins.map((p) => [p.id, p.x_mm / 10]));

      attachments.forEach((att, idx) => {
        const spec = accById.get(att.accessory_id);
        if (!spec) return;
        const spread = Math.max(1, attachments.length - 1);
        const xPos = attachments.length === 1 ? 0 : -2.6 + (idx / spread) * 5.2;
        const yPos = -3.05;
        const zPos = 1.65 + (idx % 2) * 0.55;

        const built = makeAccessory3D(spec, simNeopixelHex);
        built.group.position.set(xPos, yPos, zPos);
        group.add(built.group);
        if (built.servoHorn) servoHornsRef.current.push(built.servoHorn);
        if (built.neopixelMats) neopixelMatsRef.current.push(...built.neopixelMats);
        if (built.clickableTrigger) interactiveMeshesRef.current.push(built.clickableTrigger);

        spec.wires.forEach((wire, wIdx) => {
          const targetPinId =
            wire.to_role === "signal"
              ? att.pin
              : wire.to_role === "secondary"
                ? att.secondary_pin || spec.secondary_pin || "P2"
                : wire.to_role;
          const startX = pinXById.get(targetPinId) ?? 0;
          const start = new THREE.Vector3(startX, -2.05, 0.06);
          const end = new THREE.Vector3(xPos + (wIdx - 1) * 0.22, yPos + 0.45, zPos);
          const mid1 = new THREE.Vector3(startX, -2.65, 0.55 + wIdx * 0.12);
          const mid2 = new THREE.Vector3(end.x, -2.55, zPos * 0.72);
          const curve = new THREE.CatmullRomCurve3([start, mid1, mid2, end]);
          const tube = new THREE.Mesh(
            new THREE.TubeGeometry(curve, 24, 0.042, 8, false),
            new THREE.MeshStandardMaterial({ color: wire.color, roughness: 0.4 })
          );
          group.add(tube);
        });
      });
    }, [attachments, accessories, pins]); // eslint-disable-line react-hooks/exhaustive-deps

    return <div ref={mountRef} className="h-full w-full" />;
  }
);
