"use client";

import React, { useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type {
  MicrobitAccessorySpec,
  MicrobitAttachment,
  MicrobitLiveSensors,
  MicrobitPinSpec,
} from "@/lib/microbitApi";

export interface Microbit3DHandle {
  setView: (view: "front" | "back" | "iso" | "top") => void;
}

interface Microbit3DCanvasProps {
  pins: MicrobitPinSpec[];
  accessories: MicrobitAccessorySpec[];
  attachments: MicrobitAttachment[];
  selectedPinId: string | null;
  liveSensors: MicrobitLiveSensors | null;
  liveTiltEnabled: boolean;
  onSelectPin: (pinId: string) => void;
}

// Happy face 5x5 matrix pattern
const SMILE_MATRIX = [
  [0, 1, 0, 1, 0],
  [0, 1, 0, 1, 0],
  [0, 0, 0, 0, 0],
  [1, 0, 0, 0, 1],
  [0, 1, 1, 1, 0],
];

function makeAccessory3D(spec: MicrobitAccessorySpec): THREE.Group {
  const g = new THREE.Group();
  const baseColor = new THREE.Color(spec.color_hex || "#38bdf8");

  if (spec.id === "sg90_servo") {
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.1, 1.15, 0.55),
      new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.4, metalness: 0.15 })
    );
    const horn = new THREE.Mesh(
      new THREE.BoxGeometry(0.9, 0.16, 0.12),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 })
    );
    horn.position.set(0.18, 0.65, 0.1);
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.18, 0.2, 16),
      new THREE.MeshStandardMaterial({ color: 0xe2e8f0 })
    );
    hub.position.set(0, 0.62, 0.1);
    g.add(body, horn, hub);
  } else if (spec.id === "neopixel_8") {
    const strip = new THREE.Mesh(
      new THREE.BoxGeometry(2.4, 0.35, 0.12),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 })
    );
    g.add(strip);
    const colors = [0xef4444, 0xf97316, 0xfacc15, 0x22c55e, 0x06b6d4, 0x3b82f6, 0xa855f7, 0xec4899];
    for (let i = 0; i < 8; i++) {
      const led = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.18, 0.14),
        new THREE.MeshStandardMaterial({
          color: colors[i],
          emissive: colors[i],
          emissiveIntensity: 0.85,
        })
      );
      led.position.set(-1.05 + i * 0.3, 0, 0.04);
      g.add(led);
    }
  } else if (spec.id === "oled_ssd1306") {
    const pcb = new THREE.Mesh(
      new THREE.BoxGeometry(1.4, 1.1, 0.14),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 })
    );
    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(1.15, 0.68),
      new THREE.MeshStandardMaterial({ color: 0x0ea5e9, emissive: 0x0284c7, emissiveIntensity: 0.45 })
    );
    screen.position.set(0, 0.04, 0.08);
    g.add(pcb, screen);
  } else if (spec.id === "hcsr04_ultrasonic") {
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
  } else if (spec.id === "external_speaker") {
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
  } else {
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
  }
  return g;
}

export const Microbit3DCanvas = React.forwardRef<Microbit3DHandle, Microbit3DCanvasProps>(
  function Microbit3DCanvas(
    { pins, accessories, attachments, selectedPinId, liveSensors, liveTiltEnabled, onSelectPin },
    ref
  ) {
    const mountRef = useRef<HTMLDivElement | null>(null);
    const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
    const controlsRef = useRef<OrbitControls | null>(null);
    const boardGroupRef = useRef<THREE.Group | null>(null);
    const pinMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());
    const attachmentsGroupRef = useRef<THREE.Group | null>(null);
    const onSelectPinRef = useRef(onSelectPin);
    onSelectPinRef.current = onSelectPin;

    const targetRotRef = useRef<{ rx: number; rz: number }>({ rx: 0, rz: 0 });

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
    }));

    // Update live board tilt target from real micro:bit accelerometer
    useEffect(() => {
      if (!liveTiltEnabled || !liveSensors) {
        targetRotRef.current = { rx: 0, rz: 0 };
        return;
      }
      const ax = Math.max(-1024, Math.min(1024, liveSensors.ax || 0)) / 1024;
      const ay = Math.max(-1024, Math.min(1024, liveSensors.ay || 0)) / 1024;
      targetRotRef.current = {
        rx: ay * 0.75,
        rz: -ax * 0.75,
      };
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

      // BBC micro:bit v2.2 PCB Group (1 unit = 10mm => 5.2 x 4.2 x 0.16)
      const board = new THREE.Group();
      boardGroupRef.current = board;
      scene.add(board);

      const pcb = new THREE.Mesh(
        new THREE.BoxGeometry(5.2, 4.2, 0.16),
        new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.42, metalness: 0.25 })
      );
      board.add(pcb);

      // Subtle cyan PCB trace border
      const pcbEdge = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(5.22, 4.22, 0.17)),
        new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.35 })
      );
      board.add(pcbEdge);

      // FRONT: 5x5 Red LED Matrix
      for (let r = 0; r < 5; r++) {
        for (let c = 0; c < 5; c++) {
          const lit = SMILE_MATRIX[r][c] === 1;
          const led = new THREE.Mesh(
            new THREE.BoxGeometry(0.14, 0.26, 0.06),
            new THREE.MeshStandardMaterial({
              color: lit ? 0xff2a3c : 0x331118,
              emissive: lit ? 0xff1e32 : 0x000000,
              emissiveIntensity: lit ? 1.4 : 0,
            })
          );
          led.position.set((c - 2) * 0.42, (2 - r) * 0.42 + 0.15, 0.1);
          board.add(led);
        }
      }

      // FRONT: Button A (left) & Button B (right)
      for (const bx of [-1.85, 1.85]) {
        const housing = new THREE.Mesh(
          new THREE.BoxGeometry(0.62, 0.62, 0.12),
          new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.4 })
        );
        housing.position.set(bx, 0.15, 0.12);
        const cap = new THREE.Mesh(
          new THREE.CylinderGeometry(0.2, 0.2, 0.14, 16),
          new THREE.MeshStandardMaterial({ color: 0x020617, roughness: 0.3 })
        );
        cap.rotation.x = Math.PI / 2;
        cap.position.set(bx, 0.15, 0.18);
        board.add(housing, cap);
      }

      // FRONT: Gold Capacitive Touch Logo (top center)
      const logo = new THREE.Mesh(
        new THREE.BoxGeometry(1.1, 0.52, 0.05),
        new THREE.MeshStandardMaterial({ color: 0xf59e0b, metalness: 0.85, roughness: 0.22 })
      );
      logo.position.set(0, 1.55, 0.09);
      board.add(logo);

      // FRONT: MEMS Mic Indicator LED (top right)
      const micLed = new THREE.Mesh(
        new THREE.SphereGeometry(0.08, 12, 12),
        new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0xef4444, emissiveIntensity: 0.9 })
      );
      micLed.position.set(1.25, 1.55, 0.11);
      board.add(micLed);

      // BACK: nRF52833 MCU, 9mm Piezo Speaker, USB Micro-B, JST Battery
      const mcu = new THREE.Mesh(
        new THREE.BoxGeometry(0.75, 0.75, 0.09),
        new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.4 })
      );
      mcu.position.set(-1.1, 0.2, -0.11);
      board.add(mcu);

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
      board.add(speakerBox, speakerCone);

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
      board.add(usbPort, jstPort);

      // EDGE CONNECTOR PINS (Clickable Gold Pads along bottom y = -1.78)
      pinMeshesRef.current.clear();
      const ringPins = [
        { id: "P0", x: -1.75 },
        { id: "P1", x: -0.875 },
        { id: "P2", x: 0.0 },
        { id: "3V", x: 0.875 },
        { id: "GND", x: 1.75 },
      ];
      for (const rp of ringPins) {
        const pad = new THREE.Mesh(
          new THREE.BoxGeometry(0.54, 0.68, 0.19),
          new THREE.MeshStandardMaterial({ color: 0xeab308, metalness: 0.85, roughness: 0.22 })
        );
        pad.position.set(rp.x, -1.78, 0);
        pad.userData = { pinId: rp.id };
        board.add(pad);
        pinMeshesRef.current.set(rp.id, pad);
      }
      // Small edge pins (P8, P12, P13, P19, P20)
      const smallPins = [
        { id: "P8", x: -1.3 },
        { id: "P12", x: -0.42 },
        { id: "P13", x: 0.42 },
        { id: "P19", x: 1.28 },
        { id: "P20", x: 1.48 },
      ];
      for (const sp of smallPins) {
        const pad = new THREE.Mesh(
          new THREE.BoxGeometry(0.14, 0.52, 0.19),
          new THREE.MeshStandardMaterial({ color: 0xd97706, metalness: 0.85, roughness: 0.25 })
        );
        pad.position.set(sp.x, -1.84, 0);
        pad.userData = { pinId: sp.id };
        board.add(pad);
        pinMeshesRef.current.set(sp.id, pad);
      }

      // Attachments & 3D Jumper Wires Group
      const attGroup = new THREE.Group();
      attachmentsGroupRef.current = attGroup;
      scene.add(attGroup);

      // Raycaster for clicking gold edge pins
      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      const onClick = (e: MouseEvent) => {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(Array.from(pinMeshesRef.current.values()), false);
        if (hits.length > 0 && hits[0].object.userData?.pinId) {
          onSelectPinRef.current(String(hits[0].object.userData.pinId));
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
      const animate = () => {
        rafId = requestAnimationFrame(animate);
        board.rotation.x += (targetRotRef.current.rx - board.rotation.x) * 0.12;
        board.rotation.z += (targetRotRef.current.rz - board.rotation.z) * 0.12;
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
    }, []);

    // 2. Highlight Selected Pin in 3D
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

    // 3. Render Attached 3D Accessories + Curved Color-Coded Jumper Wires
    useEffect(() => {
      const group = attachmentsGroupRef.current;
      if (!group) return;
      group.clear();

      const accById = new Map(accessories.map((a) => [a.id, a]));
      const pinXById = new Map(pins.map((p) => [p.id, p.x_mm / 10]));

      attachments.forEach((att, idx) => {
        const spec = accById.get(att.accessory_id);
        if (!spec) return;

        // Arrange accessories cleanly in an arc below/beside the micro:bit
        const spread = Math.max(1, attachments.length - 1);
        const xPos = attachments.length === 1 ? 0 : -2.6 + (idx / spread) * 5.2;
        const yPos = -3.05;
        const zPos = 1.65 + (idx % 2) * 0.55;

        const mod3d = makeAccessory3D(spec);
        mod3d.position.set(xPos, yPos, zPos);
        group.add(mod3d);

        // Draw curved 3D jumper wires from each micro:bit edge pin to the accessory
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
    }, [attachments, accessories, pins]);

    return <div ref={mountRef} className="h-full w-full" />;
  }
);
