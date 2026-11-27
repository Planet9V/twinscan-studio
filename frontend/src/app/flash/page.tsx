import React from "react";
import { DeviceFlasherPanel } from "@/components/flasher/DeviceFlasherPanel";

export const metadata = {
  title: "Universal Device Flasher | Eigenia // TwinScan Studio",
  description:
    "Flash Raspberry Pi 3/4/5, Arduino, ESP32, Pi Pico, and micro:bit with headless SSH/Wi-Fi provisioning and Poka-Yoke removable-media safety.",
};

export default function FlashPage(): React.JSX.Element {
  return <DeviceFlasherPanel />;
}
