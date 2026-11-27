"use client";

import React, { useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { API_URL } from "@/lib/api";
import type {
  CameraPose3D,
  GhostCameraHint,
  RoomObjectPose,
  RoomStudioProject,
} from "@/lib/roomStudioApi";

export interface RoomStudioViewportHandle {
  flyToPose: (pos: [number, number, number], target: [number, number, number]) => void;
  exportFullRoomGlb: () => void;
}

interface RoomStudioViewportProps {
  project: RoomStudioProject;
  ghostCameras: GhostCameraHint[];
  selectedObjectId: string | null;
  showShell: boolean;
  showObjects: boolean;
  showPhotoGhosts: boolean;
  showNbvGhosts: boolean;
  transformMode: "translate" | "rotate" | "scale";
  onSelectObject: (objectId: string | null) => void;
  onObjectTransformCommit: (objectId: string, pose: RoomObjectPose) => void;
}

function makeFrustumGhost(colorHex: number, scale = 0.28): THREE.Group {
  const g = new THREE.Group();
  const coneGeo = new THREE.ConeGeometry(scale * 0.75, scale * 1.2, 4, 1, true);
  coneGeo.rotateX(-Math.PI / 2);
  coneGeo.rotateZ(Math.PI / 4);
  const edges = new THREE.EdgesGeometry(coneGeo);
  const mat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity: 0.9 });
  const wire = new THREE.LineSegments(edges, mat);
  g.add(wire);

  const body = new THREE.Mesh(
    new THREE.BoxGeometry(scale * 0.45, scale * 0.3, scale * 0.35),
    new THREE.MeshStandardMaterial({
      color: colorHex,
      emissive: colorHex,
      emissiveIntensity: 0.35,
      roughness: 0.3,
      metalness: 0.6,
    })
  );
  body.position.set(0, 0, scale * 0.65);
  g.add(body);
  return g;
}

export const RoomStudioViewport = React.forwardRef<RoomStudioViewportHandle, RoomStudioViewportProps>(
  function RoomStudioViewport(
    {
      project,
      ghostCameras,
      selectedObjectId,
      showShell,
      showObjects,
      showPhotoGhosts,
      showNbvGhosts,
      transformMode,
      onSelectObject,
      onObjectTransformCommit,
    },
    ref
  ) {
    const mountRef = useRef<HTMLDivElement | null>(null);
    const sceneRef = useRef<THREE.Scene | null>(null);
    const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
    const controlsRef = useRef<OrbitControls | null>(null);
    const transformRef = useRef<TransformControls | null>(null);
    const shellGroupRef = useRef<THREE.Group | null>(null);
    const objectsGroupRef = useRef<THREE.Group | null>(null);
    const ghostsGroupRef = useRef<THREE.Group | null>(null);
    const splatGroupRef = useRef<THREE.Group | null>(null);
    const objectNodeMapRef = useRef<Map<string, THREE.Object3D>>(new Map());
    const flyAnimRef = useRef<{
      startPos: THREE.Vector3;
      endPos: THREE.Vector3;
      startTarget: THREE.Vector3;
      endTarget: THREE.Vector3;
      t: number;
    } | null>(null);

    const onSelectRef = useRef(onSelectObject);
    onSelectRef.current = onSelectObject;
    const onCommitRef = useRef(onObjectTransformCommit);
    onCommitRef.current = onObjectTransformCommit;

    useImperativeHandle(ref, () => ({
      flyToPose: (pos, target) => {
        const cam = cameraRef.current;
        const ctrl = controlsRef.current;
        if (!cam || !ctrl) return;
        const reduced =
          typeof window !== "undefined" &&
          window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        if (reduced) {
          cam.position.set(pos[0], pos[1], pos[2]);
          ctrl.target.set(target[0], target[1], target[2]);
          ctrl.update();
          return;
        }
        flyAnimRef.current = {
          startPos: cam.position.clone(),
          endPos: new THREE.Vector3(pos[0], pos[1], pos[2]),
          startTarget: ctrl.target.clone(),
          endTarget: new THREE.Vector3(target[0], target[1], target[2]),
          t: 0,
        };
      },
      exportFullRoomGlb: () => {
        const exportGroup = new THREE.Group();
        exportGroup.name = project.name.replace(/\s+/g, "_");
        if (shellGroupRef.current) exportGroup.add(shellGroupRef.current.clone(true));
        if (objectsGroupRef.current) exportGroup.add(objectsGroupRef.current.clone(true));
        const exporter = new GLTFExporter();
        exporter.parse(
          exportGroup,
          (result) => {
            if (result instanceof ArrayBuffer) {
              const blob = new Blob([result], { type: "model/gltf-binary" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${project.name.toLowerCase().replace(/[^a-z0-9]+/g, "_")}_digital_twin.glb`;
              a.click();
              URL.revokeObjectURL(url);
            }
          },
          (err) => {
            console.error("[RoomStudioViewport] GLB export failed:", err);
          },
          { binary: true }
        );
      },
    }));

    // 1. Initialize Three.js r187 Scene, Renderer, OrbitControls, TransformControls
    useEffect(() => {
      const container = mountRef.current;
      if (!container) return;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#040711");
      scene.fog = new THREE.FogExp2("#040711", 0.045);
      sceneRef.current = scene;

      const camera = new THREE.PerspectiveCamera(
        52,
        Math.max(1, container.clientWidth) / Math.max(1, container.clientHeight),
        0.05,
        100
      );
      camera.position.set(3.8, 2.9, 4.2);
      cameraRef.current = camera;

      const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.12;
      container.innerHTML = "";
      container.appendChild(renderer.domElement);

      // Studio lighting rig
      scene.add(new THREE.AmbientLight(0xdbeafe, 0.75));
      const hemi = new THREE.HemisphereLight(0xe0f2fe, 0x0f172a, 0.65);
      scene.add(hemi);
      const dir = new THREE.DirectionalLight(0xffffff, 1.35);
      dir.position.set(3.5, 6.0, 3.0);
      dir.castShadow = true;
      dir.shadow.mapSize.set(1024, 1024);
      scene.add(dir);

      const grid = new THREE.GridHelper(16, 32, 0x1e293b, 0x0f172a);
      grid.position.y = -0.005;
      scene.add(grid);

      const shellGroup = new THREE.Group();
      const objectsGroup = new THREE.Group();
      const ghostsGroup = new THREE.Group();
      const splatGroup = new THREE.Group();
      scene.add(shellGroup, objectsGroup, ghostsGroup, splatGroup);
      shellGroupRef.current = shellGroup;
      objectsGroupRef.current = objectsGroup;
      ghostsGroupRef.current = ghostsGroup;
      splatGroupRef.current = splatGroup;

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.target.set(0, 1.0, 0);
      controlsRef.current = controls;

      const tControls = new TransformControls(camera, renderer.domElement);
      tControls.setSize(0.75);
      tControls.addEventListener("dragging-changed", (ev) => {
        controls.enabled = !ev.value;
        if (!ev.value && tControls.object) {
          const obj = tControls.object;
          const oid = obj.userData?.roomObjectId as string | undefined;
          if (oid) {
            onCommitRef.current(oid, {
              x: Number(obj.position.x.toFixed(3)),
              y: Number(obj.position.y.toFixed(3)),
              z: Number(obj.position.z.toFixed(3)),
              rx: Number(THREE.MathUtils.radToDeg(obj.rotation.x).toFixed(2)),
              ry: Number(THREE.MathUtils.radToDeg(obj.rotation.y).toFixed(2)),
              rz: Number(THREE.MathUtils.radToDeg(obj.rotation.z).toFixed(2)),
              scale: Number(obj.scale.x.toFixed(3)),
            });
          }
        }
      });
      scene.add(tControls.getHelper());
      transformRef.current = tControls;

      // Raycasting click-to-select 3D objects
      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      let downX = 0;
      let downY = 0;
      const onPointerDown = (e: PointerEvent) => {
        downX = e.clientX;
        downY = e.clientY;
      };
      const onPointerUp = (e: PointerEvent) => {
        if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return;
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(objectsGroup.children, true);
        if (hits.length > 0) {
          let cur: THREE.Object3D | null = hits[0].object;
          while (cur && !cur.userData?.roomObjectId) {
            cur = cur.parent;
          }
          if (cur?.userData?.roomObjectId) {
            onSelectRef.current(String(cur.userData.roomObjectId));
            return;
          }
        }
      };
      renderer.domElement.addEventListener("pointerdown", onPointerDown);
      renderer.domElement.addEventListener("pointerup", onPointerUp);

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
        if (flyAnimRef.current) {
          flyAnimRef.current.t = Math.min(1, flyAnimRef.current.t + dt * 2.4);
          const ease = 1 - Math.pow(1 - flyAnimRef.current.t, 3);
          camera.position.lerpVectors(flyAnimRef.current.startPos, flyAnimRef.current.endPos, ease);
          controls.target.lerpVectors(flyAnimRef.current.startTarget, flyAnimRef.current.endTarget, ease);
          if (flyAnimRef.current.t >= 1) flyAnimRef.current = null;
        }
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      return () => {
        cancelAnimationFrame(rafId);
        resizeObs.disconnect();
        renderer.domElement.removeEventListener("pointerdown", onPointerDown);
        renderer.domElement.removeEventListener("pointerup", onPointerUp);
        tControls.dispose();
        controls.dispose();
        renderer.dispose();
      };
    }, []);

    // 2. Rebuild Architectural Room Shell & Stitched Wall Textures
    useEffect(() => {
      const group = shellGroupRef.current;
      if (!group) return;
      group.clear();
      group.visible = showShell;

      const W = project.width_m || 4.6;
      const L = project.length_m || 4.2;
      const H = project.height_m || 2.6;
      const texLoader = new THREE.TextureLoader();
      texLoader.setCrossOrigin("anonymous");

      const makeWallMat = (surface: string, fallbackColor: string) => {
        const texEntry = project.wall_textures?.[surface];
        if (texEntry?.url) {
          const tex = texLoader.load(`${API_URL}${texEntry.url}`);
          tex.colorSpace = THREE.SRGBColorSpace;
          return new THREE.MeshStandardMaterial({
            map: tex,
            roughness: 0.78,
            metalness: 0.05,
            side: THREE.FrontSide,
          });
        }
        return new THREE.MeshStandardMaterial({
          color: fallbackColor,
          roughness: 0.85,
          metalness: 0.05,
          transparent: true,
          opacity: 0.92,
          side: THREE.FrontSide,
        });
      };

      // Floor
      const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(W, L),
        makeWallMat("floor", "#131c2e")
      );
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      group.add(floor);

      // North Wall (-Z, facing +Z inward)
      const north = new THREE.Mesh(new THREE.PlaneGeometry(W, H), makeWallMat("north_wall", "#182338"));
      north.position.set(0, H / 2, -L / 2);
      north.receiveShadow = true;
      group.add(north);

      // South Wall (+Z, facing -Z inward)
      const south = new THREE.Mesh(new THREE.PlaneGeometry(W, H), makeWallMat("south_wall", "#182338"));
      south.position.set(0, H / 2, L / 2);
      south.rotation.y = Math.PI;
      south.receiveShadow = true;
      group.add(south);

      // West Wall (-X, facing +X inward)
      const west = new THREE.Mesh(new THREE.PlaneGeometry(L, H), makeWallMat("west_wall", "#1b2840"));
      west.position.set(-W / 2, H / 2, 0);
      west.rotation.y = Math.PI / 2;
      west.receiveShadow = true;
      group.add(west);

      // East Wall (+X, facing -X inward)
      const east = new THREE.Mesh(new THREE.PlaneGeometry(L, H), makeWallMat("east_wall", "#1b2840"));
      east.position.set(W / 2, H / 2, 0);
      east.rotation.y = -Math.PI / 2;
      east.receiveShadow = true;
      group.add(east);

      // Clean architectural wireframe frame
      const frameBox = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, L)),
        new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.25 })
      );
      frameBox.position.set(0, H / 2, 0);
      group.add(frameBox);
    }, [project.width_m, project.length_m, project.height_m, project.wall_textures, showShell]);

    // 3. Load Optional 3DGS / PLY / GLB Room Backdrop
    useEffect(() => {
      const group = splatGroupRef.current;
      if (!group) return;
      group.clear();
      if (!project.splat_url || !showShell) return;

      const fullUrl = `${API_URL}${project.splat_url}`;
      const fmt = (project.splat_format || "").toLowerCase();
      if (fmt === "glb") {
        new GLTFLoader().load(fullUrl, (gltf) => {
          group.add(gltf.scene);
        });
      } else if (fmt === "ply") {
        new PLYLoader().load(fullUrl, (geom) => {
          const mat = new THREE.PointsMaterial({
            size: 0.025,
            vertexColors: geom.hasAttribute("color"),
            color: geom.hasAttribute("color") ? 0xffffff : 0x38bdf8,
          });
          group.add(new THREE.Points(geom, mat));
        });
      }
    }, [project.splat_url, project.splat_format, showShell]);

    // 4. Sync Compositional 3D Objects (Real GLB Meshes + Translucent Proxies)
    useEffect(() => {
      const group = objectsGroupRef.current;
      const tControls = transformRef.current;
      if (!group) return;
      if (tControls) tControls.detach();
      group.clear();
      group.visible = showObjects;
      objectNodeMapRef.current.clear();

      const gltfLoader = new GLTFLoader();
      gltfLoader.setCrossOrigin("anonymous");

      for (const obj of project.objects || []) {
        const container = new THREE.Group();
        container.name = obj.name;
        container.userData = { roomObjectId: obj.id };
        const p = obj.pose || { x: 0, y: 0.5, z: 0, rx: 0, ry: 0, rz: 0, scale: 1 };
        container.position.set(p.x, p.y, p.z);
        container.rotation.set(
          THREE.MathUtils.degToRad(p.rx || 0),
          THREE.MathUtils.degToRad(p.ry || 0),
          THREE.MathUtils.degToRad(p.rz || 0)
        );
        const sc = p.scale || 1;
        container.scale.set(sc, sc, sc);

        const [dw, dh, dd] = obj.dimensions_m || [0.35, 0.45, 0.25];
        const isSelected = obj.id === selectedObjectId;

        if (obj.mesh_url) {
          gltfLoader.load(
            `${API_URL}${obj.mesh_url}`,
            (gltf) => {
              const root = gltf.scene;
              // Normalize GLB to target physical dimensions if needed
              const box = new THREE.Box3().setFromObject(root);
              const sz = new THREE.Vector3();
              box.getSize(sz);
              const maxDim = Math.max(sz.x, sz.y, sz.z, 0.001);
              const targetMax = Math.max(dw, dh, dd, 0.15);
              const fit = targetMax / maxDim;
              root.scale.setScalar(fit);
              const center = new THREE.Vector3();
              new THREE.Box3().setFromObject(root).getCenter(center);
              root.position.sub(center);
              root.traverse((child) => {
                if ((child as THREE.Mesh).isMesh) {
                  child.castShadow = true;
                  child.receiveShadow = true;
                }
              });
              container.add(root);
            },
            undefined,
            () => {
              // Fallback proxy if GLB fails to fetch
              const fallback = new THREE.Mesh(
                new THREE.BoxGeometry(dw, dh, dd),
                new THREE.MeshStandardMaterial({ color: obj.color_hex || "#38bdf8", roughness: 0.5 })
              );
              container.add(fallback);
            }
          );
        } else {
          // Clean glassmorphic proxy volume until converted to 3D GLB
          const proxy = new THREE.Mesh(
            new THREE.BoxGeometry(dw, dh, dd),
            new THREE.MeshStandardMaterial({
              color: obj.color_hex || "#38bdf8",
              transparent: true,
              opacity: isSelected ? 0.55 : 0.35,
              roughness: 0.35,
              metalness: 0.2,
            })
          );
          proxy.castShadow = true;
          container.add(proxy);
        }

        if (isSelected) {
          const halo = new THREE.LineSegments(
            new THREE.EdgesGeometry(new THREE.BoxGeometry(dw + 0.04, dh + 0.04, dd + 0.04)),
            new THREE.LineBasicMaterial({ color: 0x22d3ee })
          );
          container.add(halo);
        }

        group.add(container);
        objectNodeMapRef.current.set(obj.id, container);
      }

      if (selectedObjectId && tControls) {
        const targetNode = objectNodeMapRef.current.get(selectedObjectId);
        if (targetNode) {
          tControls.setMode(transformMode);
          tControls.attach(targetNode);
        }
      }
    }, [project.objects, selectedObjectId, showObjects, transformMode]);

    // 5. Render Captured Photo Ghosts (Cyan) & Next-Best-View Coach Ghosts (Amber)
    useEffect(() => {
      const group = ghostsGroupRef.current;
      if (!group) return;
      group.clear();

      if (showPhotoGhosts) {
        for (const p of project.photos || []) {
          const cp: CameraPose3D = p.camera_pose || { x: 0, y: 1.35, z: 1.2, yaw_deg: 0, pitch_deg: 0 };
          const ghost = makeFrustumGhost(0x22d3ee, 0.22);
          ghost.position.set(cp.x, cp.y, cp.z);
          ghost.rotation.set(
            THREE.MathUtils.degToRad(cp.pitch_deg || 0),
            THREE.MathUtils.degToRad(cp.yaw_deg || 0),
            0
          );
          group.add(ghost);
        }
      }

      if (showNbvGhosts) {
        for (const hint of ghostCameras.slice(0, 3)) {
          const cp = hint.pose;
          const ghost = makeFrustumGhost(0xf59e0b, 0.28);
          ghost.position.set(cp.x, cp.y, cp.z);
          ghost.rotation.set(
            THREE.MathUtils.degToRad(cp.pitch_deg || 0),
            THREE.MathUtils.degToRad(cp.yaw_deg || 0),
            0
          );
          group.add(ghost);
        }
      }
    }, [project.photos, ghostCameras, showPhotoGhosts, showNbvGhosts]);

    return <div ref={mountRef} className="h-full w-full" />;
  }
);
