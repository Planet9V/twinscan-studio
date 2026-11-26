"use client";

import React from "react";
import { ScanFace, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AiVisionStudioPanel } from "@/components/robot/AiVisionStudioPanel";
import { useStudio } from "@/context/StudioContext";

export default function VisionPage() {
  const { activeRobot, activeRosMode, robotRosLabel } = useStudio();
  const isRos2 = activeRosMode === "ros2";

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
      <Card
        className={
          isRos2
            ? "border-eigenia-orange/60 bg-eigenia-shell/95 shadow-[0_0_20px_rgba(224,90,16,0.16)]"
            : "border-white/10 bg-eigenia-shell"
        }
      >
        <CardContent className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-eigenia-sky/50 bg-eigenia-sky/15">
              <ScanFace className="h-4 w-4 text-eigenia-sky" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-mono text-sm font-bold tracking-wider text-white">
                  AI VISION &amp; PEOPLE RECOGNITION STUDIO
                </h1>
                <Badge variant={isRos2 ? "default" : "sky"}>
                  <Zap className="h-3 w-3" />
                  {isRos2 ? "ROS 2 HUMBLE" : robotRosLabel}
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-eigenia-muted">
                YuNet + SFace + pgvector face recognition, YOLO11n animals &amp; objects, click-to-track following,
                Line Follow v2 eyedropper, AprilTag, and OpenRouter Deep Identify.
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

      <AiVisionStudioPanel robot={activeRobot} activeRosMode={activeRosMode} />
    </div>
  );
}
