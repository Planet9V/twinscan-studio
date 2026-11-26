"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, Download, Grid3x3, Layers, Pause, Play, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  PUPPYPI_GLB_URL,
  PUPPYPI_STL_URL,
  applyPuppyCadRenderMode,
  disposePuppyThreeMaterials,
  loadPuppyPiThreeModel,
} from "@/lib/puppyModelLoader";

type HeroRenderMode = "solid" | "translucent" | "wireframe";

interface ManagedMaterialEntry {
  mesh: THREE.Mesh;
  baseColor: number;
  emissiveColor: number;
  metalness: number;
  roughness: number;
  defaultOpacity: number;
  alwaysTransparent?: boolean;
}

export function LandingHeroTwin3D() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [renderMode, setRenderMode] = useState<HeroRenderMode>("solid");
  const [autoOrbit, setAutoOrbit] = useState(true);
  const [resetNonce, setResetNonce] = useState(0);
  const [highResLoaded, setHighResLoaded] = useState(false);

  const renderModeRef = useRef<HeroRenderMode>(renderMode);
  const autoOrbitRef = useRef<boolean>(autoOrbit);
  const controlsRef = useRef<OrbitControls | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const materialEntriesRef = useRef<ManagedMaterialEntry[]>([]);
  const edgeLinesRef = useRef<THREE.LineSegments[]>([]);
  const highResModelRef = useRef<THREE.Group | null>(null);

  renderModeRef.current = renderMode;
  autoOrbitRef.current = autoOrbit;

  // Apply Solid / Translucent / Wireframe live without recreating WebGL context
  useEffect(() => {
    const mode = renderMode;
    if (highResModelRef.current) {
      applyPuppyCadRenderMode(highResModelRef.current, mode, true);
    }
    for (const entry of materialEntriesRef.current) {
      const mat = entry.mesh.material;
      if (!(mat instanceof THREE.MeshStandardMaterial)) continue;
      if (mode === "wireframe") {
        mat.wireframe = true;
        mat.transparent = true;
        mat.opacity = entry.alwaysTransparent ? 0.28 : 0.72;
        mat.emissive.setHex(entry.emissiveColor || entry.baseColor);
        mat.emissiveIntensity = 0.55;
      } else if (mode === "translucent") {
        mat.wireframe = false;
        mat.transparent = true;
        mat.opacity = entry.alwaysTransparent ? 0.22 : 0.42;
        mat.emissive.setHex(entry.emissiveColor);
        mat.emissiveIntensity = 0.28;
      } else {
        mat.wireframe = false;
        mat.transparent = Boolean(entry.alwaysTransparent);
        mat.opacity = entry.defaultOpacity;
        mat.emissive.setHex(entry.emissiveColor);
        mat.emissiveIntensity = entry.emissiveColor ? 0.35 : 0.08;
      }
      mat.needsUpdate = true;
    }

    for (const line of edgeLinesRef.current) {
      const lmat = line.material;
      if (lmat instanceof THREE.LineBasicMaterial) {
        lmat.opacity = mode === "wireframe" ? 0.95 : mode === "translucent" ? 0.65 : 0.32;
        lmat.needsUpdate = true;
      }
    }
  }, [renderMode]);

  // Reset camera smoothly on demand
  useEffect(() => {
    if (resetNonce === 0) return;
    if (cameraRef.current && controlsRef.current) {
      cameraRef.current.position.set(3.4, 2.35, 3.65);
      controlsRef.current.target.set(0, 0.55, 0);
      controlsRef.current.update();
    }
  }, [resetNonce]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || 640;
    const height = container.clientHeight || 460;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0d10);
    scene.fog = new THREE.FogExp2(0x0b0d10, 0.068);

    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 60);
    camera.position.set(3.4, 2.35, 3.65);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.target.set(0, 0.55, 0);
    controls.minDistance = 1.8;
    controls.maxDistance = 9.0;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.autoRotate = autoOrbitRef.current;
    controls.autoRotateSpeed = 0.9;
    controlsRef.current = controls;

    // Studio Lighting (Eigenia Obsidian + Signal Orange + Telemetry Sky)
    const ambient = new THREE.AmbientLight(0xdbeafe, 0.55);
    scene.add(ambient);

    const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
    keyLight.position.set(4.5, 6.5, 4.0);
    scene.add(keyLight);

    const rimSky = new THREE.PointLight(0x38bdf8, 2.2, 14);
    rimSky.position.set(-3.5, 2.6, -2.8);
    scene.add(rimSky);

    const rimOrange = new THREE.PointLight(0xe05a10, 2.0, 12);
    rimOrange.position.set(3.2, 1.8, -2.5);
    scene.add(rimOrange);

    const geometriesToDispose: THREE.BufferGeometry[] = [];
    const materialsToDispose: THREE.Material[] = [];
    const managedEntries: ManagedMaterialEntry[] = [];
    const managedEdges: THREE.LineSegments[] = [];

    const registerMesh = (
      geo: THREE.BufferGeometry,
      opts: {
        baseColor: number;
        emissiveColor?: number;
        metalness?: number;
        roughness?: number;
        opacity?: number;
        alwaysTransparent?: boolean;
        edgeColor?: number;
      }
    ): THREE.Mesh => {
      geometriesToDispose.push(geo);
      const mat = new THREE.MeshStandardMaterial({
        color: opts.baseColor,
        emissive: opts.emissiveColor ?? 0x000000,
        emissiveIntensity: opts.emissiveColor ? 0.35 : 0.08,
        metalness: opts.metalness ?? 0.45,
        roughness: opts.roughness ?? 0.38,
        transparent: Boolean(opts.alwaysTransparent),
        opacity: opts.opacity ?? 1.0,
        side: opts.alwaysTransparent ? THREE.DoubleSide : THREE.FrontSide,
      });
      materialsToDispose.push(mat);
      const mesh = new THREE.Mesh(geo, mat);
      managedEntries.push({
        mesh,
        baseColor: opts.baseColor,
        emissiveColor: opts.emissiveColor ?? 0x000000,
        metalness: opts.metalness ?? 0.45,
        roughness: opts.roughness ?? 0.38,
        defaultOpacity: opts.opacity ?? 1.0,
        alwaysTransparent: opts.alwaysTransparent,
      });

      if (opts.edgeColor !== undefined) {
        const edgesGeo = new THREE.EdgesGeometry(geo);
        geometriesToDispose.push(edgesGeo);
        const edgeMat = new THREE.LineBasicMaterial({
          color: opts.edgeColor,
          transparent: true,
          opacity: 0.35,
        });
        materialsToDispose.push(edgeMat);
        const segs = new THREE.LineSegments(edgesGeo, edgeMat);
        mesh.add(segs);
        managedEdges.push(segs);
      }
      return mesh;
    };

    // 1. ARCHITECTURAL WIREFRAME MAKER ROOM + METRIC FLOOR GRID
    const grid = new THREE.GridHelper(9, 18, 0x38bdf8, 0x1e293b);
    grid.position.y = 0;
    const gridMats = Array.isArray(grid.material) ? grid.material : [grid.material];
    gridMats.forEach((m) => {
      m.transparent = true;
      m.opacity = 0.36;
      materialsToDispose.push(m);
    });
    geometriesToDispose.push(grid.geometry);
    scene.add(grid);

    const roomBoxGeo = new THREE.BoxGeometry(7.2, 2.9, 6.4);
    const roomEdgesGeo = new THREE.EdgesGeometry(roomBoxGeo);
    roomBoxGeo.dispose();
    geometriesToDispose.push(roomEdgesGeo);
    const roomEdgeMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.22,
    });
    materialsToDispose.push(roomEdgeMat);
    const roomWire = new THREE.LineSegments(roomEdgesGeo, roomEdgeMat);
    roomWire.position.set(0, 1.45, 0);
    scene.add(roomWire);

    // 2. GLOWING SPATIAL DARK-ZONE CUBES (NBV FRONTIERS IN ROOM CORNERS)
    const darkZoneConfigs: { pos: [number, number, number]; size: [number, number, number] }[] = [
      { pos: [-2.4, 0.42, -2.0], size: [0.85, 0.84, 0.85] },
      { pos: [2.5, 0.35, -1.7], size: [0.75, 0.7, 0.9] },
      { pos: [-2.1, 0.32, 1.9], size: [0.72, 0.64, 0.72] },
    ];
    const darkZoneMeshes: THREE.Mesh[] = [];
    for (const dz of darkZoneConfigs) {
      const dzMesh = registerMesh(new THREE.BoxGeometry(...dz.size), {
        baseColor: 0xef4444,
        emissiveColor: 0xef4444,
        opacity: 0.16,
        alwaysTransparent: true,
        edgeColor: 0xef4444,
      });
      dzMesh.position.set(...dz.pos);
      scene.add(dzMesh);
      darkZoneMeshes.push(dzMesh);
    }

    // 3. HIWONDER PUPPYPI PRO QUADRUPED DIGITAL TWIN (High-Res 10,022-Tri GLB + Procedural Fallback)
    const robotGroup = new THREE.Group();
    scene.add(robotGroup);

    const proceduralBodyGroup = new THREE.Group();
    robotGroup.add(proceduralBodyGroup);

    // Main anodized obsidian chassis (instant fallback while GLB streams)
    const bodyChassis = registerMesh(new THREE.BoxGeometry(1.12, 0.24, 0.56), {
      baseColor: 0x151922,
      metalness: 0.72,
      roughness: 0.28,
      edgeColor: 0x38bdf8,
    });
    bodyChassis.position.set(0, 0.54, 0);
    proceduralBodyGroup.add(bodyChassis);

    // Eigenia Signal-Orange anodized side trim plates
    for (const zSign of [-1, 1]) {
      const trim = registerMesh(new THREE.BoxGeometry(0.96, 0.08, 0.04), {
        baseColor: 0xe05a10,
        emissiveColor: 0xe05a10,
        metalness: 0.4,
        roughness: 0.3,
        edgeColor: 0xff8a4c,
      });
      trim.position.set(0, 0.56, zSign * 0.29);
      proceduralBodyGroup.add(trim);
    }

    // Raspberry Pi 5 8GB Top Deck PCB (dark forest green + silver BCM2712 SoC + USB blocks)
    const pi5Pcb = registerMesh(new THREE.BoxGeometry(0.62, 0.04, 0.42), {
      baseColor: 0x166534,
      metalness: 0.25,
      roughness: 0.45,
      edgeColor: 0x10b981,
    });
    pi5Pcb.position.set(-0.08, 0.69, 0);
    proceduralBodyGroup.add(pi5Pcb);

    const bcmSoc = registerMesh(new THREE.BoxGeometry(0.16, 0.03, 0.16), {
      baseColor: 0xcbd5e1,
      metalness: 0.85,
      roughness: 0.2,
      edgeColor: 0x38bdf8,
    });
    bcmSoc.position.set(-0.12, 0.725, 0);
    proceduralBodyGroup.add(bcmSoc);

    // Front FPV UVC Camera Module + Glowing Cyan Lens Ring
    const camHead = registerMesh(new THREE.BoxGeometry(0.16, 0.14, 0.24), {
      baseColor: 0x0f172a,
      metalness: 0.6,
      roughness: 0.35,
      edgeColor: 0xe05a10,
    });
    camHead.position.set(0.58, 0.62, 0);
    proceduralBodyGroup.add(camHead);

    const lensGeo = new THREE.CylinderGeometry(0.042, 0.045, 0.05, 18);
    lensGeo.rotateZ(Math.PI / 2);
    const camLens = registerMesh(lensGeo, {
      baseColor: 0x38bdf8,
      emissiveColor: 0x38bdf8,
      metalness: 0.8,
      roughness: 0.15,
    });
    camLens.position.set(0.67, 0.62, 0);
    proceduralBodyGroup.add(camLens);

    // Translucent Orange Front FPV Camera Frustum Cone (65° HFOV)
    const frustumGeo = new THREE.ConeGeometry(0.95, 2.2, 4, 1, true);
    frustumGeo.rotateZ(Math.PI / 2);
    frustumGeo.rotateX(Math.PI / 4);
    const frustumMesh = registerMesh(frustumGeo, {
      baseColor: 0xe05a10,
      emissiveColor: 0xe05a10,
      opacity: 0.11,
      alwaysTransparent: true,
      edgeColor: 0xe05a10,
    });
    frustumMesh.position.set(1.78, 0.6, 0);
    robotGroup.add(frustumMesh);

    // Articulated 4 Quadruped Legs (fallback while GLB streams)
    const legSpecs: { x: number; z: number; phase: number }[] = [
      { x: 0.38, z: 0.31, phase: 0 },
      { x: 0.38, z: -0.31, phase: Math.PI },
      { x: -0.38, z: 0.31, phase: Math.PI },
      { x: -0.38, z: -0.31, phase: 0 },
    ];
    const legGroups: { group: THREE.Group; phase: number }[] = [];
    for (const ls of legSpecs) {
      const legRoot = new THREE.Group();
      legRoot.position.set(ls.x, 0.48, ls.z);

      const hip = registerMesh(new THREE.CylinderGeometry(0.06, 0.06, 0.08, 16), {
        baseColor: 0xe05a10,
        metalness: 0.5,
        roughness: 0.35,
      });
      hip.rotation.x = Math.PI / 2;
      legRoot.add(hip);

      const thigh = registerMesh(new THREE.BoxGeometry(0.075, 0.28, 0.06), {
        baseColor: 0x1e293b,
        metalness: 0.65,
        roughness: 0.3,
        edgeColor: 0x38bdf8,
      });
      thigh.position.set(-0.04, -0.14, 0);
      thigh.rotation.z = -0.22;
      legRoot.add(thigh);

      const shin = registerMesh(new THREE.BoxGeometry(0.06, 0.28, 0.055), {
        baseColor: 0xe05a10,
        metalness: 0.45,
        roughness: 0.35,
        edgeColor: 0xffa46b,
      });
      shin.position.set(0.02, -0.35, 0);
      shin.rotation.z = 0.24;
      legRoot.add(shin);

      const foot = registerMesh(new THREE.SphereGeometry(0.045, 12, 12), {
        baseColor: 0x09090b,
        roughness: 0.85,
      });
      foot.position.set(0.06, -0.47, 0);
      legRoot.add(foot);

      proceduralBodyGroup.add(legRoot);
      legGroups.push({ group: legRoot, phase: ls.phase });
    }

    // Load High-Resolution 10,022-Triangle PuppyPi Pro GLB asynchronously
    let disposed = false;
    void loadPuppyPiThreeModel(1.38)
      .then((highResGroup) => {
        if (disposed) {
          disposePuppyThreeMaterials(highResGroup);
          return;
        }
        applyPuppyCadRenderMode(highResGroup, renderModeRef.current, true);
        highResGroup.position.set(0, 0.02, 0);
        robotGroup.add(highResGroup);
        highResModelRef.current = highResGroup;
        proceduralBodyGroup.visible = false;
        turretBase.position.set(0.1, 1.06, 0);
        turretRotor.position.set(0.1, 1.15, 0);
        frustumMesh.position.set(1.75, 0.72, 0);
        setHighResLoaded(true);
      })
      .catch(() => {
        // Keep clean procedural PuppyPi fallback on offline error
      });

    // 4. SPINNING ROOF LD19 360° LIDAR TURRET + ANIMATED LASER SWEEP RAYS
    const turretBase = registerMesh(new THREE.CylinderGeometry(0.18, 0.2, 0.08, 24), {
      baseColor: 0x0f172a,
      metalness: 0.7,
      roughness: 0.25,
      edgeColor: 0x38bdf8,
    });
    turretBase.position.set(0.16, 0.74, 0);
    robotGroup.add(turretBase);

    const turretRotor = new THREE.Group();
    turretRotor.position.set(0.16, 0.84, 0);
    robotGroup.add(turretRotor);

    const rotorCap = registerMesh(new THREE.CylinderGeometry(0.15, 0.16, 0.11, 24), {
      baseColor: 0x1e293b,
      emissiveColor: 0x10b981,
      metalness: 0.75,
      roughness: 0.2,
      edgeColor: 0x10b981,
    });
    turretRotor.add(rotorCap);

    // Animated fan of green & signal-orange LiDAR rays spinning with turret
    const rayCount = 24;
    const rayPositions = new Float32Array(rayCount * 2 * 3);
    const rayColors = new Float32Array(rayCount * 2 * 3);
    const cEmerald = new THREE.Color(0x10b981);
    const cOrange = new THREE.Color(0xe05a10);
    for (let i = 0; i < rayCount; i++) {
      const ang = (i / rayCount) * Math.PI * 2;
      const dist = 2.4 + Math.sin(i * 1.7) * 0.45;
      const idx = i * 6;
      rayPositions[idx] = 0;
      rayPositions[idx + 1] = 0;
      rayPositions[idx + 2] = 0;
      rayPositions[idx + 3] = Math.cos(ang) * dist;
      rayPositions[idx + 4] = -0.32;
      rayPositions[idx + 5] = Math.sin(ang) * dist;
      const col = i % 4 === 0 ? cOrange : cEmerald;
      rayColors[idx] = col.r;
      rayColors[idx + 1] = col.g;
      rayColors[idx + 2] = col.b;
      rayColors[idx + 3] = col.r;
      rayColors[idx + 4] = col.g;
      rayColors[idx + 5] = col.b;
    }
    const rayGeo = new THREE.BufferGeometry();
    rayGeo.setAttribute("position", new THREE.BufferAttribute(rayPositions, 3));
    rayGeo.setAttribute("color", new THREE.BufferAttribute(rayColors, 3));
    geometriesToDispose.push(rayGeo);
    const rayMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
    });
    materialsToDispose.push(rayMat);
    const rayLines = new THREE.LineSegments(rayGeo, rayMat);
    turretRotor.add(rayLines);

    // 5. LIVE FLOOR 360° LIDAR POINT CLOUD RING
    const cloudCount = 240;
    const cloudPos = new Float32Array(cloudCount * 3);
    const cloudCol = new Float32Array(cloudCount * 3);
    const cSky = new THREE.Color(0x38bdf8);
    for (let i = 0; i < cloudCount; i++) {
      const theta = (i / cloudCount) * Math.PI * 2;
      const radius = 2.65 + Math.cos(theta * 4) * 0.35 + Math.sin(theta * 3) * 0.18;
      cloudPos[i * 3] = Math.cos(theta) * radius;
      cloudPos[i * 3 + 1] = 0.08 + (i % 5) * 0.03;
      cloudPos[i * 3 + 2] = Math.sin(theta) * radius;
      const col = i % 9 === 0 ? cOrange : i % 3 === 0 ? cEmerald : cSky;
      cloudCol[i * 3] = col.r;
      cloudCol[i * 3 + 1] = col.g;
      cloudCol[i * 3 + 2] = col.b;
    }
    const cloudGeo = new THREE.BufferGeometry();
    cloudGeo.setAttribute("position", new THREE.BufferAttribute(cloudPos, 3));
    cloudGeo.setAttribute("color", new THREE.BufferAttribute(cloudCol, 3));
    geometriesToDispose.push(cloudGeo);
    const cloudMat = new THREE.PointsMaterial({
      size: 0.075,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
    });
    materialsToDispose.push(cloudMat);
    const pointCloud = new THREE.Points(cloudGeo, cloudMat);
    scene.add(pointCloud);

    materialEntriesRef.current = managedEntries;
    edgeLinesRef.current = managedEdges;

    // Animation loop
    let animId = 0;
    const clock = new THREE.Clock();
    const animate = () => {
      animId = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();

      // Spin LD19 turret ~7 Hz scaled smoothly for cinema visibility
      turretRotor.rotation.y = t * 3.4;

      // Subtle breathing stance + articulated leg micro-sway
      robotGroup.position.y = Math.sin(t * 2.1) * 0.022;
      for (const lg of legGroups) {
        lg.group.rotation.z = Math.sin(t * 2.1 + lg.phase) * 0.035;
      }

      // Pulse dark-zone NBV cubes gently
      darkZoneMeshes.forEach((dz, idx) => {
        const pulse = 1 + Math.sin(t * 2.4 + idx * 1.4) * 0.04;
        dz.scale.set(pulse, 1, pulse);
      });

      controls.autoRotate = autoOrbitRef.current;
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    const resizeObserver = new ResizeObserver(() => {
      if (!container) return;
      const w = container.clientWidth || 640;
      const h = container.clientHeight || 460;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    resizeObserver.observe(container);

    return () => {
      disposed = true;
      cancelAnimationFrame(animId);
      resizeObserver.disconnect();
      controls.dispose();
      if (highResModelRef.current) {
        disposePuppyThreeMaterials(highResModelRef.current);
        highResModelRef.current = null;
      }
      geometriesToDispose.forEach((g) => g.dispose());
      materialsToDispose.forEach((m) => m.dispose());
      renderer.dispose();
      materialEntriesRef.current = [];
      edgeLinesRef.current = [];
    };
  }, []);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-eigenia-orange/35 bg-eigenia-obsidian shadow-[0_24px_80px_rgba(0,0,0,0.65)]">
      {/* Top Floating HUD */}
      <div className="pointer-events-none absolute left-3.5 right-3.5 top-3.5 z-10 flex flex-wrap items-center justify-between gap-2">
        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5">
          <Badge variant="default" className="font-mono text-[10px] shadow-sm">
            LIVE WEBGL 3D TWIN
          </Badge>
          <Badge
            variant="sky"
            className="border-emerald-500/40 bg-emerald-500/15 font-mono text-[10px] text-emerald-400"
          >
            LD19 360° · 6.9 Hz
          </Badge>
          <Badge variant="neutral" className="hidden font-mono text-[10px] sm:inline-flex">
            {highResLoaded ? "PuppyPi Pro · 10k-Tri CAD" : "PuppyPi Pro · Pi 5 8GB"}
          </Badge>
        </div>

        {/* Interactive Solid / Translucent / Wireframe + Orbit + CAD Download Controls */}
        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5">
          <div className="inline-flex items-center rounded-md border border-white/15 bg-eigenia-shell/90 p-0.5 backdrop-blur-md">
            {(
              [
                { id: "solid", label: "Solid", Icon: Box },
                { id: "translucent", label: "Translucent", Icon: Layers },
                { id: "wireframe", label: "Wireframe", Icon: Grid3x3 },
              ] as const
            ).map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setRenderMode(id)}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 font-mono text-[10px] font-medium transition motion-reduce:transition-none ${
                  renderMode === id
                    ? "bg-eigenia-orange text-white shadow-sm"
                    : "text-eigenia-muted hover:text-white"
                }`}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            ))}
          </div>

          <Button
            size="sm"
            variant="secondary"
            asChild
            className="h-7 bg-eigenia-shell/90 px-2 font-mono text-[10px] backdrop-blur-md"
            title="Download High-Res PuppyPi Pro GLB Model"
          >
            <a href={PUPPYPI_GLB_URL} download="puppypi-pro.glb">
              <Download className="h-3 w-3 text-eigenia-orange" />
              GLB
            </a>
          </Button>
          <Button
            size="sm"
            variant="secondary"
            asChild
            className="hidden h-7 bg-eigenia-shell/90 px-2 font-mono text-[10px] backdrop-blur-md sm:inline-flex"
            title="Download High-Res PuppyPi Pro STL Mesh"
          >
            <a href={PUPPYPI_STL_URL} download="puppypi-pro.stl">
              <Download className="h-3 w-3 text-eigenia-sky" />
              STL
            </a>
          </Button>

          <Button
            size="icon"
            variant="secondary"
            className="h-7 w-7 bg-eigenia-shell/90 backdrop-blur-md"
            title={autoOrbit ? "Pause Auto-Orbit" : "Resume Auto-Orbit"}
            onClick={() => setAutoOrbit((v) => !v)}
          >
            {autoOrbit ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </Button>
          <Button
            size="icon"
            variant="secondary"
            className="h-7 w-7 bg-eigenia-shell/90 backdrop-blur-md"
            title="Reset Camera View"
            onClick={() => setResetNonce((n) => n + 1)}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Three.js Canvas Mount */}
      <div
        ref={containerRef}
        className="h-[420px] w-full cursor-grab active:cursor-grabbing sm:h-[470px]"
      />

      {/* Bottom Interactive Telemetry Caption */}
      <div className="pointer-events-none absolute bottom-3 left-3.5 right-3.5 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-shell/85 px-3 py-1.5 font-mono text-[10px] text-eigenia-ink backdrop-blur-md">
        <span className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> LD19 Sweep
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-eigenia-orange" /> 65° FPV Frustum
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-eigenia-fault" /> Dark-Zone Frontiers
          </span>
        </span>
        <span className="text-eigenia-muted">Drag to Orbit · Scroll to Zoom</span>
      </div>
    </div>
  );
}
