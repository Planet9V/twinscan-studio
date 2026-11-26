"use client";

import React from "react";
import { RobotControlPanel } from "@/components/robot/RobotControlPanel";
import { useStudio } from "@/context/StudioContext";

export default function ControlPage() {
  const { activeRobot, activeRosMode, refreshRobots } = useStudio();
  return (
    <RobotControlPanel
      robot={activeRobot}
      activeRosMode={activeRosMode}
      onRefreshRobot={() => void refreshRobots()}
    />
  );
}
