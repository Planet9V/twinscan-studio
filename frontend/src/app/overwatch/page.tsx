import React from "react";
import { OverwatchCockpit } from "@/components/overwatch/OverwatchCockpit";

export const metadata = {
  title: "Overwatch Tactical Cockpit | Eigenia // TwinScan Studio",
  description:
    "Multi-camera C4ISR overwatch with frustum overlap heatmaps, N-ray GDOP triangulation, 4-point floor homography, and ROI super-resolution.",
};

export default function OverwatchPage(): React.JSX.Element {
  return <OverwatchCockpit />;
}
