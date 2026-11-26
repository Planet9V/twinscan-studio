"use client";

import React, { useMemo } from "react";
import {
  TopologyFlowCanvas,
  type TopologyEdgeSpec,
  type TopologyNodeSpec,
  type TopologyNodeStatus,
} from "@/components/ui/TopologyFlowCanvas";
import type {
  Pi5ComponentStatus,
  Pi5HardwareComponentState,
  Pi5HardwareDiagnostics,
  Pi5UsbPortInfo,
} from "@/lib/robotApi";

export interface Pi5TopologyFlowProps {
  diagnostics: Pi5HardwareDiagnostics | null;
  selectedComponentId: string | null;
  onSelectComponent: (componentId: string) => void;
  heightClassName?: string;
}

function toFlowStatus(st?: Pi5ComponentStatus | null): TopologyNodeStatus {
  if (st === "ok" || st === "warning" || st === "fault" || st === "empty") {
    return st;
  }
  return "idle";
}

function findPortForPeripheral(
  ports: Pi5UsbPortInfo[],
  keywords: string[],
  fallbackPort: string
): string {
  for (const p of ports) {
    const text = `${p.vid_pid ?? ""} ${p.product ?? ""} ${p.driver ?? ""} ${p.device_nodes.join(" ")}`.toLowerCase();
    if (keywords.some((kw) => text.includes(kw))) {
      return p.port_path;
    }
  }
  return fallbackPort;
}

function portPathToNodeId(portPath: string): string {
  switch (portPath) {
    case "1-1":
      return "usb2_port_1_1";
    case "1-2":
      return "usb2_port_1_2";
    case "3-1":
      return "usb3_port_3_1";
    case "3-2":
      return "usb3_port_3_2";
    default:
      return "usb3_port_3_1";
  }
}

export function Pi5TopologyFlow({
  diagnostics,
  selectedComponentId,
  onSelectComponent,
  heightClassName = "h-[520px]",
}: Pi5TopologyFlowProps) {
  const { nodes, edges } = useMemo(() => {
    const compMap = new Map<string, Pi5HardwareComponentState>();
    for (const c of diagnostics?.components ?? []) {
      compMap.set(c.component_id, c);
    }

    const ports = Array.isArray(diagnostics?.usb_ports) ? diagnostics!.usb_ports : [];
    const portMap = new Map<string, Pi5UsbPortInfo>();
    for (const p of ports) {
      portMap.set(p.port_path, p);
    }

    const getStatus = (id: string, fallback: TopologyNodeStatus = "idle"): TopologyNodeStatus => {
      const c = compMap.get(id);
      return c ? toFlowStatus(c.status) : fallback;
    };

    const getPortMetric = (portPath: string): string => {
      const p = portMap.get(portPath);
      if (!p) return "-- mA";
      const flap = p.flap_count > 0 ? ` · ${p.flap_count} flaps` : "";
      return `${p.max_power_ma} mA${flap}`;
    };

    const getPortSubtitle = (portPath: string, fallbackLabel: string): string => {
      const p = portMap.get(portPath);
      if (!p) return fallbackLabel;
      if (p.product) return p.product;
      if (p.vid_pid) return p.vid_pid;
      return "Empty port";
    };

    const builtNodes: TopologyNodeSpec[] = [
      // Column 1: Power Supply & PMIC
      {
        id: "usbc_pwr",
        label: "USB-C 5V/5A Input",
        subtitle: diagnostics?.usb_max_current_enable ? "5A PD · High Current" : "5V Supply",
        metric:
          typeof diagnostics?.ext5v_volts === "number"
            ? `${diagnostics.ext5v_volts.toFixed(3)} V`
            : "-- V",
        category: "POWER",
        status: getStatus("usbc_pwr", diagnostics ? "ok" : "idle"),
        x: 20,
        y: 120,
      },
      {
        id: "da9091_pmic",
        label: "DA9091 PMIC",
        subtitle:
          diagnostics && diagnostics.throttled_flags.length > 0
            ? `Throttled: ${diagnostics.throttled_hex}`
            : `Throttled: ${diagnostics?.throttled_hex ?? "0x0"}`,
        metric:
          typeof diagnostics?.total_pmic_watts === "number"
            ? `${diagnostics.total_pmic_watts.toFixed(2)} W`
            : "-- W",
        category: "PMIC",
        status: getStatus("da9091_pmic", diagnostics ? "ok" : "idle"),
        x: 20,
        y: 280,
      },

      // Column 2: Compute & Storage
      {
        id: "bcm2712_soc",
        label: "BCM2712 SoC",
        subtitle: diagnostics?.cpu_model || "Quad Cortex-A76",
        metric:
          typeof diagnostics?.cpu_temp_c === "number"
            ? `${diagnostics.cpu_temp_c.toFixed(1)}°C${
                diagnostics.arm_freq_mhz ? ` · ${Math.round(diagnostics.arm_freq_mhz)} MHz` : ""
              }`
            : "--°C",
        category: "SOC",
        status: getStatus("bcm2712_soc", diagnostics ? "ok" : "idle"),
        x: 270,
        y: 70,
      },
      {
        id: "ram_lpddr4x",
        label: "8GB LPDDR4X RAM",
        subtitle: "System Memory",
        metric:
          typeof diagnostics?.ram_used_mb === "number" &&
          typeof diagnostics?.ram_total_mb === "number"
            ? `${Math.round(diagnostics.ram_used_mb)} / ${Math.round(diagnostics.ram_total_mb)} MB`
            : "-- MB",
        category: "RAM",
        status: getStatus("ram_lpddr4x", diagnostics ? "ok" : "idle"),
        x: 270,
        y: 215,
      },
      {
        id: "microsd_slot",
        label: "MicroSD Storage",
        subtitle:
          typeof diagnostics?.disk_used_gb === "number" &&
          typeof diagnostics?.disk_total_gb === "number"
            ? `${diagnostics.disk_used_gb.toFixed(1)} / ${diagnostics.disk_total_gb.toFixed(1)} GB`
            : "Root Filesystem",
        metric:
          typeof diagnostics?.disk_used_pct === "number"
            ? `${Math.round(diagnostics.disk_used_pct)}% Used`
            : "--%",
        category: "STORAGE",
        status: getStatus("microsd_slot", diagnostics ? "ok" : "idle"),
        x: 270,
        y: 360,
      },

      // Column 3: I/O Bridges & Wireless
      {
        id: "wifi_bt_module",
        label: "Wi-Fi / BT Module",
        subtitle: diagnostics?.ip_address ? `wlan0 · ${diagnostics.ip_address}` : "wlan0 / BT 5.0",
        metric: compMap.get("wifi_bt_module")?.summary || "Wireless",
        category: "NETWORK",
        status: getStatus("wifi_bt_module", diagnostics ? "ok" : "idle"),
        x: 530,
        y: 20,
      },
      {
        id: "rp1_southbridge",
        label: "RP1 Southbridge",
        subtitle: "PCIe 2.0 USB / GPIO Hub",
        metric: diagnostics
          ? `USB ${diagnostics.usb_total_draw_ma}/${diagnostics.usb_budget_ma} mA`
          : "I/O Controller",
        category: "PCIe I/O",
        status: getStatus("rp1_southbridge", diagnostics ? "ok" : "idle"),
        x: 530,
        y: 185,
      },
      {
        id: "rrc_hat_stm32",
        label: "STM32 RRC HAT",
        subtitle: "/dev/rrc · Servos, IMU & Battery",
        metric: compMap.get("rrc_hat_stm32")?.summary || "UART0 / I2C",
        category: "EXPANSION",
        status: getStatus("rrc_hat_stm32", diagnostics ? "ok" : "idle"),
        x: 530,
        y: 355,
      },

      // Column 4: 4 Physical USB-A Ports
      {
        id: "usb2_port_1_1",
        label: "USB 2.0 Top (1-1)",
        subtitle: getPortSubtitle("1-1", "Black USB 2.0 Top"),
        metric: getPortMetric("1-1"),
        category: "USB 2.0",
        status: getStatus("usb2_port_1_1", toFlowStatus(portMap.get("1-1")?.status)),
        x: 800,
        y: 15,
      },
      {
        id: "usb2_port_1_2",
        label: "USB 2.0 Bottom (1-2)",
        subtitle: getPortSubtitle("1-2", "Black USB 2.0 Bottom"),
        metric: getPortMetric("1-2"),
        category: "USB 2.0",
        status: getStatus("usb2_port_1_2", toFlowStatus(portMap.get("1-2")?.status)),
        x: 800,
        y: 135,
      },
      {
        id: "usb3_port_3_1",
        label: "USB 3.0 Top (3-1)",
        subtitle: getPortSubtitle("3-1", "Blue USB 3.0 Top"),
        metric: getPortMetric("3-1"),
        category: "USB 3.0",
        status: getStatus("usb3_port_3_1", toFlowStatus(portMap.get("3-1")?.status)),
        x: 800,
        y: 255,
      },
      {
        id: "usb3_port_3_2",
        label: "USB 3.0 Bottom (3-2)",
        subtitle: getPortSubtitle("3-2", "Blue USB 3.0 Bottom"),
        metric: getPortMetric("3-2"),
        category: "USB 3.0",
        status: getStatus("usb3_port_3_2", toFlowStatus(portMap.get("3-2")?.status)),
        x: 800,
        y: 375,
      },

      // Column 5: Key ROS 2 Peripherals
      {
        id: "camera_icspring",
        label: "icSpring UVC Camera",
        subtitle: "/dev/video0 · /image_raw",
        metric: compMap.get("camera_icspring")?.summary || "UVC FPV",
        category: "VISION",
        status: getStatus("camera_icspring"),
        x: 1080,
        y: 25,
      },
      {
        id: "wonderecho_pro",
        label: "WonderEcho Pro",
        subtitle: "/dev/wonderecho · ALSA",
        metric: compMap.get("wonderecho_pro")?.summary || "Voice & Audio",
        category: "AUDIO",
        status: getStatus("wonderecho_pro"),
        x: 1080,
        y: 175,
      },
      {
        id: "ld19_lidar_module",
        label: "LD19 2D LiDAR",
        subtitle: diagnostics?.ld19_verdict?.device_path || "/dev/ldlidar · 230400",
        metric: diagnostics?.ld19_verdict?.detected ? "LIVE /scan" : "NO USB DATA",
        category: "LIDAR",
        status: getStatus(
          "ld19_lidar_module",
          diagnostics ? (diagnostics.ld19_verdict?.detected ? "ok" : "fault") : "idle"
        ),
        x: 1080,
        y: 325,
      },
    ];

    const camPortNode = portPathToNodeId(
      findPortForPeripheral(ports, ["32e6", "icspring", "camera", "uvc", "video"], "1-1")
    );
    const audioPortNode = portPathToNodeId(
      findPortForPeripheral(ports, ["1a86", "0c76", "wonderecho", "audio", "ch34"], "1-2")
    );
    const lidarPortNode = portPathToNodeId(
      findPortForPeripheral(ports, ["10c4", "cp210", "ldlidar", "ftdi"], "3-1")
    );

    const builtEdges: TopologyEdgeSpec[] = [
      {
        id: "e-pwr-pmic",
        source: "usbc_pwr",
        target: "da9091_pmic",
        label: "5V Rail",
        status: getStatus("usbc_pwr", "ok"),
        animated: true,
      },
      {
        id: "e-pmic-soc",
        source: "da9091_pmic",
        target: "bcm2712_soc",
        label: "VDD_CORE",
        status: getStatus("da9091_pmic", "ok"),
        animated: true,
      },
      {
        id: "e-pmic-ram",
        source: "da9091_pmic",
        target: "ram_lpddr4x",
        status: getStatus("da9091_pmic", "ok"),
      },
      {
        id: "e-soc-ram",
        source: "bcm2712_soc",
        target: "ram_lpddr4x",
        status: getStatus("ram_lpddr4x", "ok"),
      },
      {
        id: "e-soc-sd",
        source: "bcm2712_soc",
        target: "microsd_slot",
        label: "SDIO",
        status: getStatus("microsd_slot", "ok"),
      },
      {
        id: "e-soc-wifi",
        source: "bcm2712_soc",
        target: "wifi_bt_module",
        label: "WLAN",
        status: getStatus("wifi_bt_module", "ok"),
        animated: true,
      },
      {
        id: "e-soc-rp1",
        source: "bcm2712_soc",
        target: "rp1_southbridge",
        label: "PCIe 2.0",
        status: getStatus("rp1_southbridge", "ok"),
        animated: true,
      },
      {
        id: "e-soc-rrc",
        source: "bcm2712_soc",
        target: "rrc_hat_stm32",
        label: "UART0/I2C",
        status: getStatus("rrc_hat_stm32", "ok"),
        animated: true,
      },
      // RP1 -> 4 USB Ports
      {
        id: "e-rp1-11",
        source: "rp1_southbridge",
        target: "usb2_port_1_1",
        label: getPortMetric("1-1"),
        status: getStatus("usb2_port_1_1"),
        animated: (portMap.get("1-1")?.max_power_ma ?? 0) > 0,
      },
      {
        id: "e-rp1-12",
        source: "rp1_southbridge",
        target: "usb2_port_1_2",
        label: getPortMetric("1-2"),
        status: getStatus("usb2_port_1_2"),
        animated: (portMap.get("1-2")?.max_power_ma ?? 0) > 0,
      },
      {
        id: "e-rp1-31",
        source: "rp1_southbridge",
        target: "usb3_port_3_1",
        label: getPortMetric("3-1"),
        status: getStatus("usb3_port_3_1"),
        animated: (portMap.get("3-1")?.max_power_ma ?? 0) > 0,
      },
      {
        id: "e-rp1-32",
        source: "rp1_southbridge",
        target: "usb3_port_3_2",
        label: getPortMetric("3-2"),
        status: getStatus("usb3_port_3_2"),
        animated: (portMap.get("3-2")?.max_power_ma ?? 0) > 0,
      },
      // USB Ports -> Peripherals
      {
        id: "e-usb-cam",
        source: camPortNode,
        target: "camera_icspring",
        label: "UVC",
        status: getStatus("camera_icspring"),
        animated: getStatus("camera_icspring") === "ok",
      },
      {
        id: "e-usb-audio",
        source: audioPortNode,
        target: "wonderecho_pro",
        label: "USB Audio + UART",
        status: getStatus("wonderecho_pro"),
        animated: getStatus("wonderecho_pro") === "ok",
      },
      {
        id: "e-usb-lidar",
        source: lidarPortNode,
        target: "ld19_lidar_module",
        label: diagnostics?.ld19_verdict?.detected ? "230400 baud" : "No Data Link",
        status: getStatus(
          "ld19_lidar_module",
          diagnostics ? (diagnostics.ld19_verdict?.detected ? "ok" : "fault") : "idle"
        ),
        animated: Boolean(diagnostics?.ld19_verdict?.detected),
      },
    ];

    return { nodes: builtNodes, edges: builtEdges };
  }, [diagnostics]);

  return (
    <TopologyFlowCanvas
      nodes={nodes}
      edges={edges}
      selectedNodeId={selectedComponentId}
      onSelectNode={onSelectComponent}
      heightClassName={heightClassName}
      title="Raspberry Pi 5 Power, PCIe & USB Bus Topology (Click Any Node to Inspect)"
      legend
    />
  );
}
