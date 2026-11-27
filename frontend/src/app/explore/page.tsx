"use client";

import React from "react";
import { Compass, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AutonomousExplorerPanel } from "@/components/robot/AutonomousExplorerPanel";
import { useStudio } from "@/context/StudioContext";

export default function ExplorePage(): React.JSX.Element {
  const { activeRobot, activeRosMode, robotRosLabel } = useStudio();
  const isRos2 = activeRosMode === "ros2";

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
      <Card
        className={
          isRos2
            ? "border-cyan-500/50 bg-eigenia-shell/95 shadow-[0_0_20px_rgba(34,211,238,0.12)]"
            : "border-white/10 bg-eigenia-shell"
        }
      >
        <CardContent className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-cyan-500/50 bg-cyan-500/15">
              <Compass className="h-4 w-4 text-cyan-400" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-mono text-sm font-bold tracking-wider text-white">
                  AUTONOMOUS EXPLORE &amp; 3D ROOM MAPPING
                </h1>
                <Badge variant={isRos2 ? "default" : "sky"}>
                  <Zap className="h-3 w-3" />
                  {isRos2 ? "ROS 2 HUMBLE" : robotRosLabel}
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-eigenia-muted">
                Zero waypoints required — PuppyPi autonomously seeks unmapped dark zones, captures
                multi-angle 3D room scans, tags objects into Spatial Memory, and auto-returns home on low battery.
              </p>
            </div>
          </div>
          {activeRobot && (
            <Badge variant="neutral">
              {activeRobot.name} · {activeRobot.ip_address}
            </Badge>
          )}
        </CardContent>
      </Card>

      <AutonomousExplorerPanel robot={activeRobot} />
    </div>
  );
}
