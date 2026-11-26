export interface WallSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  length_m: number;
  inlier_count: number;
}

export interface ObjectCluster {
  cluster_id: number;
  centroid_x: number;
  centroid_y: number;
  width_m: number;
  depth_m: number;
  point_count: number;
  mean_intensity: number;
  polygon: number[][];
}

export interface SpatialDarkZone {
  id: string;
  kind: "occlusion_shadow" | "unidentified_cluster";
  label: string;
  centroid_x: number;
  centroid_y: number;
  area_m2: number;
  priority_score: number;
  nbv_x: number;
  nbv_y: number;
  nbv_yaw_deg: number;
  polygon: number[][];
  recommended_action: string;
}

export interface FocusQueueItem {
  id: string;
  equipment_id?: string;
  category: "occlusion_shadow" | "unidentified_cluster" | "incomplete_asset";
  title: string;
  status: "DARK" | "INCOMPLETE" | "VERIFIED";
  priority_score: number;
  completeness_pct: number;
  target_x: number;
  target_y: number;
  nbv?: { x: number; y: number; yaw_deg: number };
  missing_fields: string[];
  recommended_action: string;
}

export interface PhysicalChangeAnomaly {
  id?: string;
  anomaly_type: string;
  centroid_x: number;
  centroid_y: number;
  area_m2: number;
  cell_count: number;
  severity: string;
}

export interface RoomMetrics {
  area_m2?: number;
  perimeter_m?: number;
  width_m?: number;
  depth_m?: number;
  wall_count?: number;
  footprint_polygon?: number[][];
}

export interface MovingObjectTrack {
  track_id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  speed_mps: number;
  heading_deg: number;
  is_moving: boolean;
  age: number;
  point_count: number;
  trail: [number, number][];
}

export interface RobotPoseTelemetry {
  x: number;
  y: number;
  roll_deg: number;
  pitch_deg: number;
  yaw_deg: number;
  battery_v?: number | null;
  live: boolean;
}

export interface LidarFrame {
  type: string;
  timestamp: number;
  scan_count: number;
  source_mode: "simulator" | "hardware" | "robot_ros2";
  rpm: number;
  point_count: number;
  baseline_active: boolean;
  rogue_injected: boolean;
  wall_height_m?: number;
  points: [number, number, number, number, number][];
  walls: WallSegment[];
  clusters: ObjectCluster[];
  dark_zones?: SpatialDarkZone[];
  moving_objects?: MovingObjectTrack[];
  poll_interval_ms?: number;
  analytics_every_n_scans?: number;
  actual_hz?: number;
  hardware_connected?: boolean;
  robot_scan_connected?: boolean;
  simulate_moving_targets?: boolean;
  robot_pose?: RobotPoseTelemetry;
  rotation_offset_deg?: number;
  cardinal_m?: {
    front: number | null;
    right: number | null;
    back: number | null;
    left: number | null;
  };
  metrics: RoomMetrics;
  anomalies: PhysicalChangeAnomaly[];
  zone_alerts: { zone_id: string; zone_name: string; hit_count: number; severity: string }[];
}

export interface BarcodeMatch {
  format: string;
  text: string;
  position: number[][];
}

export interface VisionFieldBox {
  label: string;
  value: string;
  bbox_norm: number[];
  confidence: number;
}

export interface EquipmentVisionResult {
  name: string;
  equipment_type: string;
  dexpi_class: string;
  manufacturer: string;
  model_number: string;
  part_number?: string | null;
  serial_number?: string | null;
  hardware_revision?: string | null;
  firmware_version?: string | null;
  manufacturing_date?: string | null;
  inferred_cpe_23?: string | null;
  voltage_rating?: string | null;
  current_or_power?: string | null;
  certifications: string[];
  asset_tags: string[];
  mac_addresses: string[];
  ip_or_hostname_labels: string[];
  barcodes: BarcodeMatch[];
  primary_bbox_norm: number[];
  detected_boxes: VisionFieldBox[];
  confidence: number;
  model_used: string;
  consensus_verified: boolean;
  discrepancies: string[];
  raw_notes: string;
}

export interface CompletenessInfo {
  completeness_pct: number;
  status: "DARK" | "INCOMPLETE" | "VERIFIED";
  missing_fields: string[];
  next_actions: string[];
}

export interface EnrichmentDossier {
  official_name?: string;
  dexpi_class?: string;
  inferred_cpe_23?: string;
  dimensions_m?: { width_m: number; depth_m: number; height_m: number };
  voltage_rating?: string;
  protocols?: string[];
  lifecycle_status?: string;
  datasheet_summary?: string;
  recommended_field_checks?: string[];
  citations?: string[];
  research_model_used?: string;
  enriched_at?: string;
  cyber_posture?: {
    cve_count: number;
    max_cvss: number;
    max_epss: number;
    top_cves: { cve_id: string; cvss: number; epss: number; summary: string }[];
    source: string;
  };
}

export interface EquipmentAsset {
  id: string;
  space_id: string;
  name: string;
  equipment_type: string;
  dexpi_class: string;
  manufacturer: string;
  model_number: string;
  part_number?: string | null;
  serial_number?: string | null;
  inferred_cpe_23?: string | null;
  voltage_rating?: string | null;
  current_or_power?: string | null;
  certifications: string[];
  asset_tags: string[];
  mac_addresses: string[];
  ip_or_hostname_labels: string[];
  x: number;
  y: number;
  z: number;
  yaw_deg: number;
  width_m: number;
  depth_m: number;
  height_m: number;
  confidence: number;
  model_used: string;
  image_file_id?: string | null;
  image_url?: string | null;
  embedding_model?: string;
  enrichment?: EnrichmentDossier;
  completeness?: CompletenessInfo;
  raw_notes: string;
  similarity?: number;
}

export interface SpaceRecord {
  id: string;
  name: string;
  facility: string;
  description: string;
  walls: WallSegment[];
  zones: { id: string; name: string; polygon: number[][]; threshold: number }[];
  metrics: RoomMetrics;
  created_at?: string;
  updated_at?: string;
  panel_count?: number;
  equipment_count?: number;
  wall_count?: number;
  thumbnail_url?: string | null;
}

export interface GraphPayload {
  nodes: { id: string; label: string; node_type: string; meta: Record<string, unknown> }[];
  edges: { id: string; source: string; target: string; label: string }[];
  stats: {
    node_count: number;
    edge_count: number;
    equipment_count: number;
    dark_zone_count?: number;
    anomaly_count: number;
  };
  neo4j: { status: string; uri: string; error?: string };
}

export interface OpenRouterPricing {
  prompt_per_1m_usd: number;
  completion_per_1m_usd: number;
  image_per_1k_usd?: number | null;
  blended_per_1m_usd: number;
  is_free: boolean;
  cost_tier: string;
}

export interface OpenRouterModelInfo {
  id: string;
  label: string;
  name?: string;
  provider?: string;
  tier: string;
  description?: string;
  context_length?: number;
  input_modalities?: string[];
  output_modalities?: string[];
  categories?: string[];
  model_type?: string;
  pricing?: OpenRouterPricing;
  recommended_for?: string[];
}

export type VisionModelOption = OpenRouterModelInfo;

export interface OpenRouterCatalogResponse {
  source: string;
  count: number;
  fetched_at?: string;
  category_counts?: Record<string, number>;
  models: OpenRouterModelInfo[];
}

export interface OpenRouterKeyTestResult {
  ok: boolean;
  status: string;
  http_status?: number | null;
  latency_ms: number;
  key_source: string;
  label?: string | null;
  is_free_tier?: boolean;
  usage_usd?: number | null;
  limit_usd?: number | null;
  limit_remaining_usd?: number | null;
  total_credits_usd?: number | null;
  error?: string | null;
}

export interface AdminSettingItem {
  key: string;
  value: string;
  is_secret: boolean;
  is_set: boolean;
  persisted: boolean;
  category: string;
  description: string;
  updated_at?: string | null;
}

export interface StoredFileRecord {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  deduplicated?: boolean;
  category: string;
  space_id?: string | null;
  equipment_id?: string | null;
  url: string;
  created_at: string;
}

export interface StorageStats {
  file_count: number;
  unique_blob_count: number;
  logical_bytes: number;
  physical_bytes: number;
  dedup_savings_bytes: number;
}

export interface FocusTarget {
  x: number;
  y: number;
  label: string;
  equipmentId?: string;
}

export type SceneRenderMode = "solid" | "translucent" | "wireframe";
export type SceneResolution = "low" | "medium" | "high";
export type SceneQualityPreset = "fast" | "balanced" | "studio_ultra";

export interface SceneEnhanceOptions {
  quality_preset?: SceneQualityPreset;
  burst_frames?: number;
  clahe_sharpen?: boolean;
  upscale_2x?: boolean;
  flip_tta?: boolean;
  guided_depth?: boolean;
  normal_map?: boolean;
  taubin_smooth?: boolean;
}

export interface SceneQualityMetrics {
  preset: SceneQualityPreset;
  passes_applied: string[];
  frames_stacked: number;
  lidar_sweeps_stacked: number;
  sharpness_before: number;
  sharpness_after: number;
  sharpness_gain_pct: number;
  contrast_before: number;
  contrast_after: number;
  texture_width: number;
  texture_height: number;
  has_normal_map: boolean;
  lidar_residual_rmse_m: number | null;
  processing_ms: number;
}

export interface ScenePanelPose {
  x: number;
  y: number;
  z: number;
  yaw_deg: number;
  pitch_deg: number;
  roll_deg: number;
}

export interface ScenePanelMesh {
  grid_w: number;
  grid_h: number;
  hfov_deg: number;
  vfov_deg: number;
  positions: number[];
  normals: number[];
  uvs: number[];
  indices: number[];
}

export interface ScenePanelRecord {
  id: string;
  space_id: string;
  robot_id: string | null;
  label: string;
  stage: "single_wall" | "pano_360" | "room_map";
  pose: ScenePanelPose;
  lidar_calibrated: boolean;
  lidar_ray_count: number;
  depth_source: "lidar_depth_anything" | "depth_anything" | "lidar_only" | "geometric_relief";
  mean_distance_m: number;
  min_distance_m: number;
  max_distance_m: number;
  vertex_count: number;
  triangle_count: number;
  texture_file_id: string | null;
  texture_url: string | null;
  normal_map_file_id?: string | null;
  normal_map_url?: string | null;
  quality_metrics?: SceneQualityMetrics | null;
  glb_file_id: string | null;
  glb_url: string | null;
  mesh: ScenePanelMesh;
  created_at: string;
}
