"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  WS_URL,
  cloneSpace,
  createSpace,
  deleteSpace,
  enrichEquipmentAsset,
  fetchFocusQueue,
  fetchHealth,
  fetchLidarSnapshot,
  fetchSpaceDetail,
  fetchSpaceGraph,
  fetchSpaces,
  fetchVisionModels,
  updateSpace,
} from "@/lib/api";
import {
  fetchRobotNetwork,
  fetchRosComparison,
  listRobots,
  setRobotActiveIp,
  triggerRobotEstop,
  type RobotNetworkTelemetry,
  type RobotRecord,
  type RosComparisonPayload,
} from "@/lib/robotApi";
import type {
  EquipmentAsset,
  FocusQueueItem,
  FocusTarget,
  GraphPayload,
  LidarFrame,
  SpaceRecord,
  SpatialDarkZone,
  VisionModelOption,
} from "@/lib/types";

export function normalizeRosMode(distro?: string | null): "ros1" | "ros2" {
  const val = String(distro ?? "").toLowerCase();
  if (val.includes("humble") || val.includes("ros2") || val.includes("jazzy") || val.includes("kilted")) {
    return "ros2";
  }
  return "ros1";
}

export function formatRosDistroLabel(distro?: string | null): string {
  const raw = String(distro ?? "").trim();
  const val = raw.toLowerCase();
  if (!val || val === "unknown" || val === "none" || val === "null") {
    return "Detecting...";
  }
  if (val.includes("humble") || val.includes("ros2") || val.includes("jazzy") || val.includes("kilted")) {
    return "ROS 2 Humble";
  }
  if (val.includes("noetic") || val.includes("ros1")) {
    return "ROS 1 Noetic";
  }
  return raw;
}

export interface StudioContextValue {
  // Spaces & Spatial Twin Data
  spaces: SpaceRecord[];
  activeSpaceId: string;
  setActiveSpaceId: (id: string) => void;
  space: SpaceRecord | null;
  equipment: EquipmentAsset[];
  graph: GraphPayload | null;
  focusQueue: FocusQueueItem[];
  darkZones: SpatialDarkZone[];
  refreshSpaceData: (spaceId?: string) => Promise<void>;
  refreshSpaces: () => Promise<void>;
  createNewSpace: (payload: {
    name: string;
    facility?: string;
    description?: string;
  }) => Promise<SpaceRecord>;
  renameSpace: (
    spaceId: string,
    payload: { name?: string; facility?: string; description?: string }
  ) => Promise<SpaceRecord>;
  cloneCurrentSpace: (
    payload: { name: string; facility?: string; description?: string },
    sourceSpaceId?: string
  ) => Promise<{ space: SpaceRecord; cloned_panels: number; cloned_equipment: number }>;
  deleteSpaceById: (spaceId: string) => Promise<void>;

  // Robot Fleet State & Dual ROS 1 / ROS 2 Mode
  robots: RobotRecord[];
  activeRobotId: string | null;
  setActiveRobotId: (id: string | null) => void;
  activeRobot: RobotRecord | null;
  refreshRobots: () => Promise<void>;
  robotRosMode: "ros1" | "ros2";
  robotRosLabel: string;
  uiRosPreview: "ros1" | "ros2" | null;
  setUiRosPreview: (mode: "ros1" | "ros2" | null) => void;
  activeRosMode: "ros1" | "ros2";
  rosComparison: RosComparisonPayload | null;
  robotNetwork: RobotNetworkTelemetry | null;
  refreshRobotNetwork: () => Promise<void>;
  switchRobotActiveIp: (ip: string) => Promise<void>;

  // Shared Live LiDAR Telemetry Stream
  frame: LidarFrame | null;
  wsConnected: boolean;

  // Platform Metadata
  visionModels: VisionModelOption[];
  defaultModel: string;
  openrouterConfigured: boolean;
  dbBackend: string;
  refreshMeta: () => Promise<void>;

  // Selection, Focus, Enrichment & Safety
  selectedEquipmentId: string | null;
  setSelectedEquipmentId: (id: string | null) => void;
  focusTarget: FocusTarget | null;
  setFocusTarget: (target: FocusTarget | null) => void;
  enrichingId: string | null;
  handleEnrichAsset: (equipmentId: string) => Promise<void>;
  handleGlobalEstop: () => Promise<void>;
  estopActive: boolean;
}

const StudioContext = createContext<StudioContextValue | null>(null);

export function StudioProvider({ children }: { children: React.ReactNode }) {
  const [spaces, setSpaces] = useState<SpaceRecord[]>([]);
  const [activeSpaceId, setActiveSpaceIdState] = useState<string>("");
  const [space, setSpace] = useState<SpaceRecord | null>(null);
  const [equipment, setEquipment] = useState<EquipmentAsset[]>([]);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [focusQueue, setFocusQueue] = useState<FocusQueueItem[]>([]);
  const [darkZones, setDarkZones] = useState<SpatialDarkZone[]>([]);

  const [robots, setRobots] = useState<RobotRecord[]>([]);
  const [activeRobotId, setActiveRobotId] = useState<string | null>(null);
  const [uiRosPreview, setUiRosPreview] = useState<"ros1" | "ros2" | null>(null);
  const [rosComparison, setRosComparison] = useState<RosComparisonPayload | null>(null);
  const [robotNetwork, setRobotNetwork] = useState<RobotNetworkTelemetry | null>(null);

  const [frame, setFrame] = useState<LidarFrame | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  const [visionModels, setVisionModels] = useState<VisionModelOption[]>([]);
  const [defaultModel, setDefaultModel] = useState("google/gemini-2.5-flash");
  const [openrouterConfigured, setOpenrouterConfigured] = useState(false);
  const [dbBackend, setDbBackend] = useState("Connecting...");

  const [selectedEquipmentId, setSelectedEquipmentId] = useState<string | null>(null);
  const [focusTarget, setFocusTarget] = useState<FocusTarget | null>(null);
  const [enrichingId, setEnrichingId] = useState<string | null>(null);
  const [estopActive, setEstopActive] = useState(false);

  const activeSpaceIdRef = useRef<string>("");
  activeSpaceIdRef.current = activeSpaceId;
  const activeRobotIdRef = useRef<string | null>(null);
  activeRobotIdRef.current = activeRobotId;
  const activeRobotDistroRef = useRef<string | null>(null);

  const refreshSpaceData = useCallback(async (spaceId?: string) => {
    const sid = spaceId || activeSpaceIdRef.current;
    if (!sid) return;
    try {
      const [detail, g, fq] = await Promise.all([
        fetchSpaceDetail(sid),
        fetchSpaceGraph(sid),
        fetchFocusQueue(sid).catch(() => null),
      ]);
      setSpace(detail?.space ?? null);
      setEquipment(Array.isArray(detail?.equipment) ? detail.equipment : []);
      setGraph(g ?? null);
      if (fq) {
        setFocusQueue(Array.isArray(fq.focus_queue) ? fq.focus_queue : []);
        setDarkZones(Array.isArray(fq.dark_zones) ? fq.dark_zones : []);
      }
    } catch (err) {
      console.error("[StudioContext] Failed to refresh space data:", err);
    }
  }, []);

  const refreshSpaces = useCallback(async () => {
    try {
      const resp = await fetchSpaces();
      const list = resp.spaces ?? [];
      setSpaces(list);
      const currentValid = list.some((s) => s.id === activeSpaceIdRef.current);
      const nextId = currentValid
        ? activeSpaceIdRef.current
        : resp.active_space_id || list[0]?.id || "";
      if (nextId) {
        setActiveSpaceIdState(nextId);
        activeSpaceIdRef.current = nextId;
        await refreshSpaceData(nextId);
      }
    } catch (err) {
      console.error("[StudioContext] Failed to fetch spaces:", err);
    }
  }, [refreshSpaceData]);

  const setActiveSpaceId = useCallback(
    (id: string) => {
      setActiveSpaceIdState(id);
      activeSpaceIdRef.current = id;
      setSelectedEquipmentId(null);
      setFocusTarget(null);
      void refreshSpaceData(id);
    },
    [refreshSpaceData]
  );

  const createNewSpace = useCallback(
    async (payload: { name: string; facility?: string; description?: string }) => {
      const created = await createSpace(payload);
      setActiveSpaceIdState(created.id);
      activeSpaceIdRef.current = created.id;
      setSelectedEquipmentId(null);
      setFocusTarget(null);
      const listResp = await fetchSpaces().catch(() => null);
      if (listResp?.spaces) {
        setSpaces(listResp.spaces);
      } else {
        setSpaces((prev) => [created, ...prev.filter((s) => s.id !== created.id)]);
      }
      await refreshSpaceData(created.id);
      return created;
    },
    [refreshSpaceData]
  );

  const renameSpace = useCallback(
    async (
      spaceId: string,
      payload: { name?: string; facility?: string; description?: string }
    ) => {
      const updated = await updateSpace(spaceId, payload);
      setSpaces((prev) => prev.map((s) => (s.id === spaceId ? { ...s, ...updated } : s)));
      if (activeSpaceIdRef.current === spaceId) {
        setSpace((prev) => (prev ? { ...prev, ...updated } : updated));
      }
      return updated;
    },
    []
  );

  const cloneCurrentSpace = useCallback(
    async (
      payload: { name: string; facility?: string; description?: string },
      sourceSpaceId?: string
    ) => {
      const targetId = sourceSpaceId || activeSpaceIdRef.current;
      if (!targetId) {
        throw new Error("No active room selected to clone");
      }
      const res = await cloneSpace(targetId, payload);
      setActiveSpaceIdState(res.space.id);
      activeSpaceIdRef.current = res.space.id;
      setSelectedEquipmentId(null);
      setFocusTarget(null);
      const listResp = await fetchSpaces().catch(() => null);
      if (listResp?.spaces) {
        setSpaces(listResp.spaces);
      } else {
        setSpaces((prev) => [res.space, ...prev.filter((s) => s.id !== res.space.id)]);
      }
      await refreshSpaceData(res.space.id);
      return res;
    },
    [refreshSpaceData]
  );

  const deleteSpaceById = useCallback(
    async (spaceId: string) => {
      const res = await deleteSpace(spaceId);
      const listResp = await fetchSpaces().catch(() => null);
      const nextList = listResp?.spaces ?? [];
      setSpaces(nextList);
      const nextActive =
        res.active_space_id ||
        listResp?.active_space_id ||
        nextList[0]?.id ||
        "";
      setActiveSpaceIdState(nextActive);
      activeSpaceIdRef.current = nextActive;
      setSelectedEquipmentId(null);
      setFocusTarget(null);
      if (nextActive) {
        await refreshSpaceData(nextActive);
      }
    },
    [refreshSpaceData]
  );

  const refreshRobots = useCallback(async () => {
    try {
      const resp = await listRobots();
      const list = resp.robots ?? [];
      setRobots(list);
      setActiveRobotId((prev) => {
        if (prev && list.some((r) => r.id === prev)) return prev;
        const preferred = list.find((r) => r.status === "online") ?? list[0];
        return preferred ? preferred.id : null;
      });
    } catch (err) {
      console.error("[StudioContext] Failed to fetch robots:", err);
    }
  }, []);

  const refreshRobotNetwork = useCallback(async () => {
    const rid = activeRobotIdRef.current;
    if (!rid) {
      setRobotNetwork(null);
      return;
    }
    try {
      const net = await fetchRobotNetwork(rid);
      if (activeRobotIdRef.current === rid) {
        setRobotNetwork(net);
        if (
          net.active_ros_distro &&
          net.active_ros_distro !== activeRobotDistroRef.current
        ) {
          void refreshRobots();
        }
      }
    } catch (err) {
      console.error("[StudioContext] Failed to fetch robot network:", err);
    }
  }, [refreshRobots]);

  const switchRobotActiveIp = useCallback(
    async (ip: string) => {
      const rid = activeRobotIdRef.current;
      if (!rid || !ip.trim()) return;
      try {
        await setRobotActiveIp(rid, ip.trim());
        await refreshRobots();
        await refreshRobotNetwork();
      } catch (err) {
        console.error("[StudioContext] Failed to switch active robot IP:", err);
        throw err;
      }
    },
    [refreshRobots, refreshRobotNetwork]
  );

  const refreshMeta = useCallback(async () => {
    try {
      const [health, visionResp, rosComp] = await Promise.all([
        fetchHealth().catch(() => ({ database_backend: "Offline" })),
        fetchVisionModels().catch(() => null),
        fetchRosComparison().catch(() => null),
      ]);
      setDbBackend(String(health.database_backend || "Unknown"));
      if (visionResp) {
        setVisionModels(visionResp.models ?? []);
        setDefaultModel(visionResp.default_model || "google/gemini-2.5-flash");
        setOpenrouterConfigured(Boolean(visionResp.openrouter_configured));
      }
      if (rosComp) {
        setRosComparison(rosComp);
      }
    } catch (err) {
      console.error("[StudioContext] Failed to refresh metadata:", err);
    }
  }, []);

  // Initial bootstrap
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        await Promise.all([
          refreshMeta(),
          refreshSpaces(),
          refreshRobots(),
          fetchLidarSnapshot()
            .then((snap) => {
              if (active) setFrame(snap);
            })
            .catch(() => null),
        ]);
      } catch (err) {
        console.error("[StudioContext] Bootstrap error:", err);
      }
    })();
    return () => {
      active = false;
    };
  }, [refreshMeta, refreshSpaces, refreshRobots]);

  const activeRobot = useMemo(
    () => robots.find((r) => r.id === activeRobotId) ?? null,
    [robots, activeRobotId]
  );

  activeRobotDistroRef.current = activeRobot?.active_ros_distro ?? null;

  const detectedRosDistro = activeRobot?.active_ros_distro ?? robotNetwork?.active_ros_distro ?? null;

  const robotRosMode = useMemo<"ros1" | "ros2">(
    () => normalizeRosMode(detectedRosDistro),
    [detectedRosDistro]
  );

  const robotRosLabel = useMemo(
    () => formatRosDistroLabel(detectedRosDistro),
    [detectedRosDistro]
  );

  const activeRosMode: "ros1" | "ros2" = uiRosPreview ?? robotRosMode;

  // Hydrate cached network telemetry immediately & refresh live via SSH when active robot changes
  useEffect(() => {
    if (!activeRobotId) {
      setRobotNetwork(null);
      return;
    }
    const cachedNet = activeRobot?.capabilities?.network as RobotNetworkTelemetry | undefined;
    if (cachedNet && typeof cachedNet === "object") {
      setRobotNetwork({
        ...cachedNet,
        robot_id: activeRobotId,
        active_ip: activeRobot?.ip_address ?? cachedNet.active_ip ?? null,
        wifi: cachedNet.wifi ?? null,
        ethernet: Array.isArray(cachedNet.ethernet) ? cachedNet.ethernet : [],
        interfaces: Array.isArray(cachedNet.interfaces) ? cachedNet.interfaces : [],
      });
    }
    void refreshRobotNetwork();
  }, [activeRobotId, activeRobot?.ip_address, activeRobot?.capabilities?.network, refreshRobotNetwork]);

  // Single shared live WebSocket subscription for 10 Hz LD19 telemetry
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      try {
        ws = new WebSocket(`${WS_URL}/api/lidar/stream`);
        ws.onopen = () => {
          if (!disposed) setWsConnected(true);
        };
        ws.onclose = () => {
          if (!disposed) {
            setWsConnected(false);
            timer = setTimeout(connect, 2000);
          }
        };
        ws.onerror = () => {
          ws?.close();
        };
        ws.onmessage = (evt) => {
          try {
            const parsed = JSON.parse(evt.data) as LidarFrame;
            if (parsed.type === "lidar_frame") {
              setFrame(parsed);
              if (parsed.dark_zones && parsed.dark_zones.length > 0) {
                setDarkZones(parsed.dark_zones);
              }
            }
          } catch {
            // ignore malformed frame
          }
        };
      } catch (err) {
        console.error("[StudioContext] LiDAR WebSocket error:", err);
        if (!disposed) {
          timer = setTimeout(connect, 2500);
        }
      }
    };

    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const handleEnrichAsset = useCallback(
    async (equipmentId: string) => {
      setEnrichingId(equipmentId);
      try {
        await enrichEquipmentAsset(equipmentId, true);
        await refreshSpaceData();
      } catch (err) {
        console.error("[StudioContext] Enrichment failed:", err);
      } finally {
        setEnrichingId(null);
      }
    },
    [refreshSpaceData]
  );

  const handleGlobalEstop = useCallback(async () => {
    setEstopActive(true);
    try {
      const targetIds = activeRobotId ? [activeRobotId] : robots.map((r) => r.id);
      if (targetIds.length > 0) {
        await Promise.allSettled(targetIds.map((id) => triggerRobotEstop(id)));
      }
    } catch (err) {
      console.error("[StudioContext] Global E-STOP failed:", err);
    } finally {
      setTimeout(() => setEstopActive(false), 1800);
    }
  }, [activeRobotId, robots]);

  const value = useMemo<StudioContextValue>(
    () => ({
      spaces,
      activeSpaceId,
      setActiveSpaceId,
      space,
      equipment,
      graph,
      focusQueue,
      darkZones,
      refreshSpaceData,
      refreshSpaces,
      createNewSpace,
      renameSpace,
      cloneCurrentSpace,
      deleteSpaceById,
      robots,
      activeRobotId,
      setActiveRobotId,
      activeRobot,
      refreshRobots,
      robotRosMode,
      robotRosLabel,
      uiRosPreview,
      setUiRosPreview,
      activeRosMode,
      rosComparison,
      robotNetwork,
      refreshRobotNetwork,
      switchRobotActiveIp,
      frame,
      wsConnected,
      visionModels,
      defaultModel,
      openrouterConfigured,
      dbBackend,
      refreshMeta,
      selectedEquipmentId,
      setSelectedEquipmentId,
      focusTarget,
      setFocusTarget,
      enrichingId,
      handleEnrichAsset,
      handleGlobalEstop,
      estopActive,
    }),
    [
      spaces,
      activeSpaceId,
      setActiveSpaceId,
      space,
      equipment,
      graph,
      focusQueue,
      darkZones,
      refreshSpaceData,
      refreshSpaces,
      createNewSpace,
      renameSpace,
      cloneCurrentSpace,
      deleteSpaceById,
      robots,
      activeRobotId,
      activeRobot,
      refreshRobots,
      robotRosMode,
      robotRosLabel,
      uiRosPreview,
      activeRosMode,
      rosComparison,
      robotNetwork,
      refreshRobotNetwork,
      switchRobotActiveIp,
      frame,
      wsConnected,
      visionModels,
      defaultModel,
      openrouterConfigured,
      dbBackend,
      refreshMeta,
      selectedEquipmentId,
      focusTarget,
      enrichingId,
      handleEnrichAsset,
      handleGlobalEstop,
      estopActive,
    ]
  );

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) {
    throw new Error("useStudio must be used within a StudioProvider");
  }
  return ctx;
}
