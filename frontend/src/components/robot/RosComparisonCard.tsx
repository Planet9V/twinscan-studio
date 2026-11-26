"use client";

import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchRosComparison,
  type RobotRecord,
  type RosComparisonPayload,
  type RosComparisonRow,
} from "@/lib/robotApi";

interface RosComparisonCardProps {
  activeRosMode: "ros1" | "ros2";
  robot: RobotRecord | null;
  onSwitchRos: (target: "ros1" | "ros2") => Promise<void>;
  switching: boolean;
  previewMode: "ros1" | "ros2" | null;
  onTogglePreview: (mode: "ros1" | "ros2" | null) => void;
}

const FALLBACK_ROWS: RosComparisonRow[] = [
  {
    dimension: "Container & OS Base",
    ros1: "puppypi — Ubuntu 20.04 LTS (Focal)",
    ros2: "puppypi_ros2 — Ubuntu 22.04 LTS (Jammy)",
    advantage: "ros2",
  },
  {
    dimension: "Middleware & Transport",
    ros1: "rosmaster XML-RPC (:11311) + TCPROS",
    ros2: "CycloneDDS (rmw_cyclonedds_cpp, ROS_DOMAIN_ID=0)",
    advantage: "ros2",
  },
  {
    dimension: "Support Status",
    ros1: "EOL (May 2025)",
    ros2: "LTS Active (through May 2027)",
    advantage: "ros2",
  },
  {
    dimension: "SLAM & Navigation",
    ros1: "gmapping / hector / move_base / TEB",
    ros2: "slam_toolbox 2.6.8 / Nav2 1.1.16 / MoveIt 2.5.5",
    advantage: "ros2",
  },
  {
    dimension: "ROSBridge Message Wiring",
    ros1: "puppy_control/{Velocity,Pose,Gait,SetServo}",
    ros2: "puppy_control_msgs/msg/{Velocity,Pose,Gait,SetServo}",
    advantage: "tie",
  },
  {
    dimension: "RRC & Services",
    ros1: "ros_robot_controller/* & puppy_control/SetRunActionName",
    ros2: "ros_robot_controller_msgs/msg/* & puppy_control_msgs/srv/SetRunActionName",
    advantage: "tie",
  },
  {
    dimension: "FPV Camera Topics",
    ros1: "/usb_cam/image_raw",
    ros2: "/image_raw (fallback /usb_cam/image_raw)",
    advantage: "tie",
  },
  {
    dimension: "Config & Mechanics Files",
    ros1: "/home/ubuntu/puppypi/.robotrc & puppy.py",
    ros2: "/home/ubuntu/ros2_ws/.typerc & puppy.py",
    advantage: "tie",
  },
];

const FALLBACK_RECOMMENDATION =
  "ROS 2 Humble (CycloneDDS) is recommended for active autonomy, Nav2/slam_toolbox mapping, and security updates through May 2027. Keep ROS 1 Noetic when running legacy Hiwonder OpenCV app demos.";

export function RosComparisonCard({
  activeRosMode,
  robot,
  onSwitchRos,
  switching,
  previewMode,
  onTogglePreview,
}: RosComparisonCardProps) {
  const [payload, setPayload] = useState<RosComparisonPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRosComparison()
      .then((data) => {
        if (!cancelled && data) setPayload(data);
      })
      .catch(() => {
        // Fallback rows keep comparison card instant even if backend is offline
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows: RosComparisonRow[] =
    (Array.isArray(payload?.comparison_rows) && payload.comparison_rows.length > 0
      ? payload.comparison_rows
      : Array.isArray(payload?.rows) && payload.rows.length > 0
        ? payload.rows
        : FALLBACK_ROWS);

  const recommendation =
    typeof payload?.recommendation === "string"
      ? payload.recommendation
      : typeof payload?.summary === "string"
        ? payload.summary
        : FALLBACK_RECOMMENDATION;

  const isRos2Active = activeRosMode === "ros2";
  const isPreviewingRos2 = previewMode === "ros2";

  return (
    <Card
      className={
        isRos2Active
          ? "border-eigenia-orange/60 bg-eigenia-surface shadow-md shadow-eigenia-orange/10"
          : "border-white/10 bg-eigenia-surface"
      }
    >
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <ArrowRightLeft className="h-4 w-4 text-eigenia-orange" />
            ROS 1 Noetic vs. ROS 2 Humble — Dual-Mode Comparison
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={isRos2Active ? "default" : "sky"}>
              Active UI Mode: {isRos2Active ? "ROS 2 HUMBLE (DDS)" : "ROS 1 NOETIC"}
            </Badge>
            {previewMode && (
              <Badge variant="amber">
                Theme Preview: {previewMode.toUpperCase()}
              </Badge>
            )}
          </div>
        </div>

        {/* 1-Click Mode Activation & Theme Preview Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={!isRos2Active && !previewMode ? "sky" : "secondary"}
            disabled={!robot || switching}
            onClick={() => void onSwitchRos("ros1")}
          >
            {switching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            Activate ROS 1 on Robot
          </Button>
          <Button
            size="sm"
            variant="default"
            disabled={!robot || switching}
            onClick={() => void onSwitchRos("ros2")}
          >
            {switching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Activate ROS 2 on Robot (Orange Mode)
          </Button>
          <Button
            size="sm"
            variant={isPreviewingRos2 ? "default" : "outline"}
            onClick={() => onTogglePreview(isPreviewingRos2 ? null : "ros2")}
          >
            {isPreviewingRos2 ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
            {isPreviewingRos2 ? "Exit ROS 2 Theme Preview" : "Preview ROS 2 Theme"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Side-by-Side Comparison Matrix */}
        <div className="overflow-x-auto rounded-md border border-white/10">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/10 bg-eigenia-obsidian font-mono text-[10px] uppercase">
              <tr>
                <th className="px-3 py-2.5 text-eigenia-muted">Dimension</th>
                <th
                  className={`px-3 py-2.5 ${
                    !isRos2Active
                      ? "bg-eigenia-sky/15 text-eigenia-sky"
                      : "text-eigenia-sky"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span>ROS 1 Noetic</span>
                    <Badge variant="fault" className="px-1.5 py-0 text-[9px]">
                      EOL May 2025
                    </Badge>
                  </div>
                </th>
                <th
                  className={`px-3 py-2.5 ${
                    isRos2Active
                      ? "bg-eigenia-orange/20 text-eigenia-orange"
                      : "text-eigenia-orange"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span>ROS 2 Humble</span>
                    <Badge variant="default" className="px-1.5 py-0 text-[9px]">
                      LTS May 2027
                    </Badge>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {rows.map((row) => (
                <tr key={row.dimension} className="hover:bg-white/[0.02]">
                  <td className="px-3 py-2 font-medium text-white">{row.dimension}</td>
                  <td
                    className={`px-3 py-2 font-mono text-[11px] ${
                      !isRos2Active ? "bg-eigenia-sky/5 text-white" : "text-eigenia-muted"
                    }`}
                  >
                    {row.ros1}
                  </td>
                  <td
                    className={`px-3 py-2 font-mono text-[11px] ${
                      isRos2Active ? "bg-eigenia-orange/10 text-white" : "text-eigenia-ink"
                    }`}
                  >
                    {row.ros2}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Lifecycle Recommendation */}
        <div
          className={`flex items-start gap-2.5 rounded-md border p-3 text-xs ${
            isRos2Active
              ? "border-eigenia-orange/45 bg-eigenia-orange/10 text-eigenia-ink"
              : "border-eigenia-amber/35 bg-eigenia-amber/10 text-eigenia-amber"
          }`}
        >
          {isRos2Active ? (
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-eigenia-orange" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-eigenia-amber" />
          )}
          <div className="leading-relaxed">{recommendation}</div>
        </div>
      </CardContent>
    </Card>
  );
}
