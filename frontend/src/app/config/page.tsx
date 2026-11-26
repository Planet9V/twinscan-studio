"use client";

import React, { useEffect, useState } from "react";
import { Bot, Database, RefreshCw, Sparkles } from "lucide-react";
import { AdminConfigPanel } from "@/components/admin/AdminConfigPanel";
import { RobotRemoteConfigPanel } from "@/components/robot/RobotRemoteConfigPanel";
import { Button } from "@/components/ui/button";
import { SegmentedTabs } from "@/components/ui/SegmentedTabs";
import { WorkspaceHeader } from "@/components/ui/WorkspaceHeader";
import { useStudio } from "@/context/StudioContext";

type ConfigTabId = "ai" | "robot" | "databases";

function normalizeConfigTab(raw: string | null): ConfigTabId {
  if (raw === "ai" || raw === "models" || raw === "openrouter") return "ai";
  if (raw === "databases" || raw === "storage" || raw === "platform-admin") return "databases";
  if (raw === "robot" || raw === "robot-config" || raw === "ros") return "robot";
  return "ai";
}

export default function ConfigPage() {
  const {
    activeRobot,
    refreshRobots,
    activeRosMode,
    robotNetwork,
    refreshRobotNetwork,
    switchRobotActiveIp,
    uiRosPreview,
    setUiRosPreview,
    spaces,
    activeSpaceId,
    setActiveSpaceId,
    refreshSpaces,
    refreshMeta,
  } = useStudio();

  const [activeTab, setActiveTab] = useState<ConfigTabId>("ai");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get("tab");
    if (tabParam) {
      setActiveTab(normalizeConfigTab(tabParam));
    }
  }, []);

  const handleTabChange = (next: string) => {
    const valid = normalizeConfigTab(next);
    setActiveTab(valid);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", valid);
      window.history.replaceState({}, "", url.toString());
    }
  };

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
      <WorkspaceHeader
        badge="PLATFORM & ROBOT CONFIG"
        title="AI Models, Robot OS & Sovereign Storage"
        subtitle="Fernet-encrypted OpenRouter keys, live ROS 1 / ROS 2 switching, Wi-Fi/SSH hardening, PostgreSQL 18 blobs, and Neo4j sync."
        statusTone={activeRobot?.status === "online" ? "ok" : "idle"}
        statusLabel={
          activeRobot
            ? `${activeRobot.name} · ${activeRosMode === "ros2" ? "ROS 2 HUMBLE" : "ROS 1 NOETIC"}`
            : "PLATFORM READY"
        }
        metrics={[
          {
            label: "Active ROS",
            value: activeRosMode === "ros2" ? "ROS 2" : "ROS 1",
            tone: activeRosMode === "ros2" ? "orange" : "sky",
          },
          {
            label: "Robot IP",
            value: activeRobot?.ip_address || "Unbound",
            tone: activeRobot?.status === "online" ? "emerald" : "default",
          },
          {
            label: "Saved Rooms",
            value: spaces.length,
            tone: "sky",
          },
        ]}
        actions={
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              void refreshRobots();
              void refreshSpaces();
              void refreshMeta();
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Sync All
          </Button>
        }
      />

      <SegmentedTabs
        value={activeTab}
        onValueChange={handleTabChange}
        tabs={[
          {
            id: "ai",
            label: "AI & OpenRouter Models",
            icon: <Sparkles className="h-3.5 w-3.5" />,
          },
          {
            id: "robot",
            label: "Robot OS, Wi-Fi & ROS 1/2",
            icon: <Bot className="h-3.5 w-3.5" />,
            alertTone: activeRobot?.status === "online" ? "ok" : null,
          },
          {
            id: "databases",
            label: "Databases & Storage",
            icon: <Database className="h-3.5 w-3.5" />,
            count: spaces.length,
          },
        ]}
      />

      {activeTab === "ai" && (
        <AdminConfigPanel
          section="ai"
          spaces={spaces}
          activeSpaceId={activeSpaceId}
          onSelectSpace={setActiveSpaceId}
          onSpacesChanged={() => void refreshSpaces()}
          onSettingsChanged={() => void refreshMeta()}
        />
      )}

      {activeTab === "robot" && (
        <RobotRemoteConfigPanel
          robot={activeRobot}
          onUpdated={() => void refreshRobots()}
          activeRosMode={activeRosMode}
          robotNetwork={robotNetwork}
          onRefreshNetwork={refreshRobotNetwork}
          onSwitchActiveIp={switchRobotActiveIp}
          previewMode={uiRosPreview}
          onTogglePreview={setUiRosPreview}
        />
      )}

      {activeTab === "databases" && (
        <AdminConfigPanel
          section="databases"
          spaces={spaces}
          activeSpaceId={activeSpaceId}
          onSelectSpace={setActiveSpaceId}
          onSpacesChanged={() => void refreshSpaces()}
          onSettingsChanged={() => void refreshMeta()}
        />
      )}
    </div>
  );
}
