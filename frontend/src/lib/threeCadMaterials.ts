import * as THREE from "three";
import type { Pi5ComponentStatus } from "@/lib/robotApi";
import type { SceneRenderMode } from "@/lib/types";

export const CAD_STATUS_COLORS = {
  ok: 0x10b981,
  warning: 0xf59e0b,
  fault: 0xef4444,
  empty: 0x475569,
  selected: 0xe05a10,
  wireCyan: 0x38bdf8,
} as const;

export function getCadStatusHex(status: Pi5ComponentStatus, isSelected = false): number {
  if (isSelected) return CAD_STATUS_COLORS.selected;
  switch (status) {
    case "ok":
      return CAD_STATUS_COLORS.ok;
    case "warning":
      return CAD_STATUS_COLORS.warning;
    case "fault":
      return CAD_STATUS_COLORS.fault;
    case "empty":
    default:
      return CAD_STATUS_COLORS.empty;
  }
}

export function createCadOverlayEdges(
  geometry: THREE.BufferGeometry,
  colorHex: number,
  opacity = 0.85
): THREE.LineSegments {
  const edgesGeo = new THREE.EdgesGeometry(geometry, 20);
  const edgesMat = new THREE.LineBasicMaterial({
    color: colorHex,
    transparent: true,
    opacity,
  });
  return new THREE.LineSegments(edgesGeo, edgesMat);
}

export function applyHardwareRenderMode(
  mesh: THREE.Mesh,
  edges: THREE.LineSegments | null,
  mode: SceneRenderMode,
  baseColorHex: number,
  statusColorHex: number,
  isSelected: boolean
): void {
  const mat = mesh.material as THREE.MeshStandardMaterial;
  const edgeMat = edges ? (edges.material as THREE.LineBasicMaterial) : null;
  const activeAccent = isSelected ? CAD_STATUS_COLORS.selected : statusColorHex;

  if (mode === "wireframe") {
    mat.color.setHex(isSelected ? CAD_STATUS_COLORS.selected : baseColorHex);
    mat.emissive.setHex(activeAccent);
    mat.emissiveIntensity = isSelected ? 0.55 : 0.2;
    mat.transparent = true;
    mat.opacity = isSelected ? 0.34 : 0.16;
    mat.depthWrite = false;
    mat.roughness = 0.6;
    mat.metalness = 0.2;
    mat.wireframe = false;
    mat.needsUpdate = true;

    if (edgeMat) {
      edgeMat.color.setHex(activeAccent);
      edgeMat.opacity = isSelected ? 1.0 : 0.92;
      edgeMat.needsUpdate = true;
    }
  } else if (mode === "translucent") {
    mat.color.setHex(baseColorHex);
    mat.emissive.setHex(activeAccent);
    mat.emissiveIntensity = isSelected ? 0.48 : 0.18;
    mat.transparent = true;
    mat.opacity = isSelected ? 0.72 : 0.44;
    mat.depthWrite = false;
    mat.roughness = 0.45;
    mat.metalness = 0.25;
    mat.wireframe = false;
    mat.needsUpdate = true;

    if (edgeMat) {
      edgeMat.color.setHex(activeAccent);
      edgeMat.opacity = isSelected ? 0.98 : 0.68;
      edgeMat.needsUpdate = true;
    }
  } else {
    // "solid" studio shaded
    mat.color.setHex(baseColorHex);
    mat.emissive.setHex(activeAccent);
    mat.emissiveIntensity = isSelected ? 0.45 : 0.12;
    mat.transparent = false;
    mat.opacity = 1.0;
    mat.depthWrite = true;
    mat.roughness = 0.42;
    mat.metalness = 0.35;
    mat.wireframe = false;
    mat.needsUpdate = true;

    if (edgeMat) {
      edgeMat.color.setHex(activeAccent);
      edgeMat.opacity = isSelected ? 0.98 : 0.36;
      edgeMat.needsUpdate = true;
    }
  }
}
