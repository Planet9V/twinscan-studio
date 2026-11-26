"use client";

import React from "react";
import { RobotCatalogPanel } from "@/components/robot/RobotCatalogPanel";
import { useStudio } from "@/context/StudioContext";

export default function CatalogPage() {
  const {
    robots,
    activeRobotId,
    setActiveRobotId,
    refreshRobots,
    robotNetwork,
    refreshRobotNetwork,
    switchRobotActiveIp,
  } = useStudio();

  return (
    <RobotCatalogPanel
      robots={robots}
      activeRobotId={activeRobotId}
      onSelectRobot={setActiveRobotId}
      onRobotsChanged={() => void refreshRobots()}
      robotNetwork={robotNetwork}
      onRefreshNetwork={refreshRobotNetwork}
      onSwitchActiveIp={switchRobotActiveIp}
    />
  );
}
