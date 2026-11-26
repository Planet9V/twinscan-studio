/**
 * Cached loaders and CAD render-mode helpers for the high-resolution Hiwonder PuppyPi Pro
 * 3D CAD assets (``/models/puppypi-pro.glb`` and ``/models/puppypi-pro.stl``).
 *
 * Uses Three.js built-in ``GLTFLoader`` and a zero-dependency binary STL parser so both
 * Three.js and Babylon.js canvases can render the exact 10,022-triangle mesh with zero
 * additional npm packages.
 */

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

export const PUPPYPI_GLB_URL = "/models/puppypi-pro.glb";
export const PUPPYPI_STL_URL = "/models/puppypi-pro.stl";
export const PUPPYPI_TRIANGLE_COUNT = 10022;

export type PuppyCadRenderMode = "solid" | "translucent" | "wireframe";

export interface NormalizedStlGeometry {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint32Array;
  triangleCount: number;
  boundsMeters: { width: number; height: number; depth: number };
}

let cachedGlbTemplatePromise: Promise<THREE.Group> | null = null;
let cachedStlBufferPromise: Promise<ArrayBuffer> | null = null;

/**
 * Load and cache the raw normalized Three.js ``THREE.Group`` from ``/models/puppypi-pro.glb``.
 * The returned template is centered on X/Z, grounded at ``y = 0``, and normalized to unit
 * horizontal footprint (``max(width, depth) === 1.0``).
 */
function loadNormalizedGlbTemplate(): Promise<THREE.Group> {
  if (!cachedGlbTemplatePromise) {
    cachedGlbTemplatePromise = new Promise<THREE.Group>((resolve, reject) => {
      const loader = new GLTFLoader();
      loader.load(
        PUPPYPI_GLB_URL,
        (gltf) => {
          const root = gltf.scene || new THREE.Group();
          root.updateMatrixWorld(true);

          const rawBox = new THREE.Box3().setFromObject(root);
          const rawSize = new THREE.Vector3();
          const rawCenter = new THREE.Vector3();
          rawBox.getSize(rawSize);
          rawBox.getCenter(rawCenter);

          const maxHoriz = Math.max(rawSize.x, rawSize.z, 1e-4);
          const normScale = 1.0 / maxHoriz;

          const container = new THREE.Group();
          container.name = "PuppyPiHighResRoot";

          root.position.set(
            -rawCenter.x * normScale,
            -rawBox.min.y * normScale,
            -rawCenter.z * normScale
          );
          root.scale.setScalar(normScale);

          root.traverse((obj) => {
            if (obj instanceof THREE.Mesh) {
              if (!obj.geometry.getAttribute("normal")) {
                obj.geometry.computeVertexNormals();
              }
              obj.castShadow = true;
              obj.receiveShadow = true;
            }
          });

          container.add(root);
          resolve(container);
        },
        undefined,
        (err) => {
          cachedGlbTemplatePromise = null;
          reject(err instanceof Error ? err : new Error(String(err)));
        }
      );
    });
  }
  return cachedGlbTemplatePromise;
}

/**
 * Clone the cached high-resolution PuppyPi Pro Three.js mesh scaled to ``targetFootprintMeters``.
 * Each call returns an isolated group with freshly cloned materials so individual viewports can
 * switch ``solid`` / ``translucent`` / ``wireframe`` and dispose cleanly on unmount.
 */
export async function loadPuppyPiThreeModel(
  targetFootprintMeters = 0.42
): Promise<THREE.Group> {
  const template = await loadNormalizedGlbTemplate();
  const clone = template.clone(true);
  clone.scale.setScalar(targetFootprintMeters);

  clone.traverse((obj) => {
    if (obj instanceof THREE.Mesh) {
      obj.material = new THREE.MeshStandardMaterial({
        color: 0xcbd5e1,
        emissive: 0x3b1806,
        emissiveIntensity: 0.22,
        metalness: 0.58,
        roughness: 0.32,
      });
    }
  });
  return clone;
}

/**
 * Apply Eigenia CAD viewport shading (``solid``, ``translucent``, or ``wireframe``) to every
 * mesh inside a loaded PuppyPi Three.js model group.
 */
export function applyPuppyCadRenderMode(
  root: THREE.Object3D,
  mode: PuppyCadRenderMode,
  isLive = true
): void {
  root.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh)) return;
    const mat = obj.material;
    if (!(mat instanceof THREE.MeshStandardMaterial)) return;

    if (mode === "wireframe") {
      mat.color.setHex(0x38bdf8);
      mat.emissive.setHex(0xe05a10);
      mat.emissiveIntensity = isLive ? 0.55 : 0.35;
      mat.wireframe = true;
      mat.transparent = true;
      mat.opacity = 0.78;
      mat.metalness = 0.25;
      mat.roughness = 0.4;
      mat.side = THREE.DoubleSide;
    } else if (mode === "translucent") {
      mat.color.setHex(0x7dd3fc);
      mat.emissive.setHex(0x0c4a6e);
      mat.emissiveIntensity = 0.38;
      mat.wireframe = false;
      mat.transparent = true;
      mat.opacity = 0.44;
      mat.metalness = 0.35;
      mat.roughness = 0.25;
      mat.side = THREE.DoubleSide;
    } else {
      mat.color.setHex(0xd4dce6);
      mat.emissive.setHex(isLive ? 0x431906 : 0x1e293b);
      mat.emissiveIntensity = isLive ? 0.24 : 0.1;
      mat.wireframe = false;
      mat.transparent = false;
      mat.opacity = 1.0;
      mat.metalness = 0.58;
      mat.roughness = 0.32;
      mat.side = THREE.FrontSide;
    }
    mat.needsUpdate = true;
  });
}

/**
 * Dispose cloned materials created for a PuppyPi Three.js instance (preserving cached template
 * geometries so other scenes remain intact).
 */
export function disposePuppyThreeMaterials(root: THREE.Object3D): void {
  root.traverse((obj) => {
    if (obj instanceof THREE.Mesh) {
      if (Array.isArray(obj.material)) {
        obj.material.forEach((m) => m.dispose());
      } else if (obj.material) {
        obj.material.dispose();
      }
    }
  });
}

/**
 * Parse a binary STL ``ArrayBuffer`` into normalized flat-shaded arrays centered on X/Z,
 * grounded at ``y = 0``, and scaled so ``max(width, depth) === targetFootprintMeters``.
 *
 * When ``leftHandedBabylon`` is ``true``, flips Z and triangle winding so Babylon.js matches
 * the canonical Three.js orientation.
 */
export function parseBinaryStlGeometry(
  buffer: ArrayBuffer,
  targetFootprintMeters = 0.42,
  leftHandedBabylon = true
): NormalizedStlGeometry {
  if (buffer.byteLength < 84) {
    throw new Error("Invalid binary STL buffer (too short)");
  }
  const view = new DataView(buffer);
  const triCount = view.getUint32(80, true);
  const expectedBytes = 84 + triCount * 50;
  if (triCount <= 0 || buffer.byteLength < expectedBytes) {
    throw new Error(`Invalid binary STL triangle count (${triCount})`);
  }

  const rawPos = new Float32Array(triCount * 9);
  const rawNorm = new Float32Array(triCount * 9);

  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;

  let offset = 84;
  for (let t = 0; t < triCount; t++) {
    const nx = view.getFloat32(offset, true);
    const ny = view.getFloat32(offset + 4, true);
    const nz = view.getFloat32(offset + 8, true);
    offset += 12;

    const base = t * 9;
    for (let v = 0; v < 3; v++) {
      const vx = view.getFloat32(offset, true);
      const vy = view.getFloat32(offset + 4, true);
      const vz = view.getFloat32(offset + 8, true);
      offset += 12;

      const idx = base + v * 3;
      rawPos[idx] = vx;
      rawPos[idx + 1] = vy;
      rawPos[idx + 2] = vz;
      rawNorm[idx] = nx;
      rawNorm[idx + 1] = ny;
      rawNorm[idx + 2] = nz;

      if (vx < minX) minX = vx;
      if (vy < minY) minY = vy;
      if (vz < minZ) minZ = vz;
      if (vx > maxX) maxX = vx;
      if (vy > maxY) maxY = vy;
      if (vz > maxZ) maxZ = vz;
    }
    offset += 2; // attribute byte count
  }

  const sizeX = maxX - minX;
  const sizeY = maxY - minY;
  const sizeZ = maxZ - minZ;
  const cx = (minX + maxX) * 0.5;
  const cz = (minZ + maxZ) * 0.5;
  const maxHoriz = Math.max(sizeX, sizeZ, 1e-4);
  const scale = targetFootprintMeters / maxHoriz;

  const positions = new Float32Array(triCount * 9);
  const normals = new Float32Array(triCount * 9);
  const indices = new Uint32Array(triCount * 3);

  for (let t = 0; t < triCount; t++) {
    const base = t * 9;
    for (let v = 0; v < 3; v++) {
      const idx = base + v * 3;
      positions[idx] = (rawPos[idx] - cx) * scale;
      positions[idx + 1] = (rawPos[idx + 1] - minY) * scale;
      positions[idx + 2] = (rawPos[idx + 2] - cz) * scale * (leftHandedBabylon ? -1 : 1);

      normals[idx] = rawNorm[idx];
      normals[idx + 1] = rawNorm[idx + 1];
      normals[idx + 2] = rawNorm[idx + 2] * (leftHandedBabylon ? -1 : 1);
    }
    const iBase = t * 3;
    if (leftHandedBabylon) {
      indices[iBase] = iBase;
      indices[iBase + 1] = iBase + 2;
      indices[iBase + 2] = iBase + 1;
    } else {
      indices[iBase] = iBase;
      indices[iBase + 1] = iBase + 1;
      indices[iBase + 2] = iBase + 2;
    }
  }

  return {
    positions,
    normals,
    indices,
    triangleCount: triCount,
    boundsMeters: {
      width: sizeX * scale,
      height: sizeY * scale,
      depth: sizeZ * scale,
    },
  };
}

/**
 * Fetch and cache ``/models/puppypi-pro.stl`` and parse it into normalized Babylon.js arrays.
 */
export async function loadPuppyPiStlVertexArrays(
  targetFootprintMeters = 0.42,
  leftHandedBabylon = true
): Promise<NormalizedStlGeometry> {
  if (!cachedStlBufferPromise) {
    cachedStlBufferPromise = fetch(PUPPYPI_STL_URL).then((res) => {
      if (!res.ok) {
        cachedStlBufferPromise = null;
        throw new Error(`Failed loading ${PUPPYPI_STL_URL}: HTTP ${res.status}`);
      }
      return res.arrayBuffer();
    });
  }
  const buf = await cachedStlBufferPromise;
  return parseBinaryStlGeometry(buf, targetFootprintMeters, leftHandedBabylon);
}
