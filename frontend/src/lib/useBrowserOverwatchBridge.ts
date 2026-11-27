"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ingestOverwatchFrameBlob } from "@/lib/overwatchApi";

export type BrowserResolutionPreset = "720p" | "1080p" | "4k";

export interface VideoDeviceOption {
  deviceId: string;
  label: string;
}

export interface BrowserSlotState {
  cameraId: "usb_4k" | "macbook_cam";
  deviceId: string;
  label: string;
  streaming: boolean;
  actualWidth: number;
  actualHeight: number;
  framesSent: number;
  error: string | null;
}

const PRESET_DIMS: Record<BrowserResolutionPreset, { width: number; height: number }> = {
  "720p": { width: 1280, height: 720 },
  "1080p": { width: 1920, height: 1080 },
  "4k": { width: 2560, height: 1440 },
};

function isBuiltInLabel(label: string): boolean {
  const low = label.toLowerCase();
  return low.includes("macbook") || low.includes("facetime") || low.includes("built-in") || low.includes("integrated");
}

function isExternal4kLabel(label: string): boolean {
  const low = label.toLowerCase();
  return low.includes("4k") || low.includes("usb") || low.includes("webcam") || low.includes("logitech") || low.includes("brio") || low.includes("0bda");
}

export function useBrowserOverwatchBridge() {
  const [devices, setDevices] = useState<VideoDeviceOption[]>([]);
  const [usbDeviceId, setUsbDeviceId] = useState<string>("");
  const [macDeviceId, setMacDeviceId] = useState<string>("");
  const [usbPreset, setUsbPreset] = useState<BrowserResolutionPreset>("1080p");
  const [macPreset, setMacPreset] = useState<BrowserResolutionPreset>("720p");
  const [targetFps, setTargetFps] = useState<number>(6);
  const [running, setRunning] = useState(false);
  const [autoStart, setAutoStartState] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("eigenia_overwatch_autostart") === "1";
  });
  const [bridgeError, setBridgeError] = useState<string | null>(null);

  const setAutoStart = useCallback((enabled: boolean) => {
    setAutoStartState(enabled);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("eigenia_overwatch_autostart", enabled ? "1" : "0");
    }
  }, []);
  const [slotStats, setSlotStats] = useState<Record<"usb_4k" | "macbook_cam", { w: number; h: number; sent: number; active: boolean }>>({
    usb_4k: { w: 0, h: 0, sent: 0, active: false },
    macbook_cam: { w: 0, h: 0, sent: 0, active: false },
  });
  const [liveStreams, setLiveStreams] = useState<Record<"usb_4k" | "macbook_cam", MediaStream | null>>({
    usb_4k: null,
    macbook_cam: null,
  });

  const streamsRef = useRef<Record<string, MediaStream>>({});
  const videosRef = useRef<Record<string, HTMLVideoElement>>({});
  const timersRef = useRef<Record<string, number>>({});
  const inFlightRef = useRef<Record<string, boolean>>({});

  const bindVideoElement = useCallback((slotId: "usb_4k" | "macbook_cam", el: HTMLVideoElement | null) => {
    if (el) {
      videosRef.current[slotId] = el;
      const existing = streamsRef.current[slotId];
      if (existing && el.srcObject !== existing) {
        el.srcObject = existing;
        void el.play().catch(() => {});
      }
    }
  }, []);

  const refreshDevices = useCallback(async (requestPermission = false): Promise<VideoDeviceOption[]> => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices) {
      setBridgeError("Browser camera API requires localhost or HTTPS.");
      return [];
    }
    try {
      if (requestPermission) {
        const temp = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        temp.getTracks().forEach((t) => t.stop());
      }
      const all = await navigator.mediaDevices.enumerateDevices();
      const cams = all
        .filter((d) => d.kind === "videoinput")
        .map((d, idx) => ({
          deviceId: d.deviceId,
          label: d.label || `Camera #${idx + 1}`,
        }));
      setDevices(cams);

      if (cams.length > 0) {
        const external = cams.find((c) => isExternal4kLabel(c.label) && !isBuiltInLabel(c.label));
        const builtin = cams.find((c) => isBuiltInLabel(c.label));
        const chosenUsb = external?.deviceId ?? cams.find((c) => c.deviceId !== builtin?.deviceId)?.deviceId ?? cams[0].deviceId;
        const chosenMac = builtin?.deviceId ?? cams.find((c) => c.deviceId !== chosenUsb)?.deviceId ?? "";

        setUsbDeviceId((prev) => (prev && cams.some((c) => c.deviceId === prev) ? prev : chosenUsb));
        setMacDeviceId((prev) => (prev && cams.some((c) => c.deviceId === prev) ? prev : chosenMac));
      }
      setBridgeError(null);
      return cams;
    } catch (err) {
      setBridgeError(err instanceof Error ? err.message : "Camera permission denied.");
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshDevices(false);
  }, [refreshDevices]);

  const stopSlot = useCallback((slotId: "usb_4k" | "macbook_cam") => {
    const timer = timersRef.current[slotId];
    if (timer) {
      window.clearInterval(timer);
      delete timersRef.current[slotId];
    }
    const stream = streamsRef.current[slotId];
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      delete streamsRef.current[slotId];
    }
    const vid = videosRef.current[slotId];
    if (vid) {
      vid.srcObject = null;
    }
    inFlightRef.current[slotId] = false;
    setLiveStreams((prev) => ({ ...prev, [slotId]: null }));
    setSlotStats((prev) => ({
      ...prev,
      [slotId]: { ...prev[slotId], active: false },
    }));
  }, []);

  const stopAll = useCallback(() => {
    stopSlot("usb_4k");
    stopSlot("macbook_cam");
    setRunning(false);
  }, [stopSlot]);

  useEffect(() => {
    return () => {
      stopAll();
    };
  }, [stopAll]);

  const startSlot = useCallback(
    async (
      slotId: "usb_4k" | "macbook_cam",
      deviceId: string,
      label: string,
      preset: BrowserResolutionPreset,
      fps: number,
      useMinimalConstraints = false
    ) => {
      if (!deviceId) return;
      stopSlot(slotId);
      const dims = PRESET_DIMS[preset];
      const videoConstraints: MediaTrackConstraints = useMinimalConstraints
        ? { deviceId: { exact: deviceId } }
        : {
            deviceId: { exact: deviceId },
            width: { ideal: dims.width },
            height: { ideal: dims.height },
            frameRate: { ideal: 30 },
          };

      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: videoConstraints,
        });
      } catch {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { deviceId: { exact: deviceId } },
        });
      }
      streamsRef.current[slotId] = stream;
      setLiveStreams((prev) => ({ ...prev, [slotId]: stream }));

      // Prefer the visible <video> element inside the Overwatch card so Chrome macOS
      // always decodes USB UVC MJPG frames at full resolution instead of 2x2.
      let video = videosRef.current[slotId];
      if (!video) {
        video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.autoplay = true;
        videosRef.current[slotId] = video;
      }
      video.srcObject = stream;
      await video.play().catch(() => {});

      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      const intervalMs = Math.max(120, Math.round(1000 / Math.max(1, fps)));
      const startedAt = Date.now();
      let retriedMinimal = useMinimalConstraints;

      setSlotStats((prev) => ({
        ...prev,
        [slotId]: {
          w: video.videoWidth >= 64 ? video.videoWidth : 0,
          h: video.videoHeight >= 64 ? video.videoHeight : 0,
          sent: 0,
          active: true,
        },
      }));

      timersRef.current[slotId] = window.setInterval(() => {
        const activeVid = videosRef.current[slotId];
        if (!activeVid || inFlightRef.current[slotId] || !ctx || activeVid.readyState < 2) return;
        const vw = activeVid.videoWidth;
        const vh = activeVid.videoHeight;
        // Skip macOS Chrome 2x2 warmup placeholder frames; auto-fallback to native driver format if stuck > 2.5s
        if (vw < 64 || vh < 64) {
          if (!retriedMinimal && Date.now() - startedAt > 2500) {
            retriedMinimal = true;
            void startSlot(slotId, deviceId, label, preset, fps, true).catch((err) =>
              setBridgeError(err instanceof Error ? err.message : `Camera ${label} failed to negotiate resolution.`)
            );
          }
          return;
        }
        if (canvas.width !== vw || canvas.height !== vh) {
          canvas.width = vw;
          canvas.height = vh;
        }
        ctx.drawImage(activeVid, 0, 0, vw, vh);
        inFlightRef.current[slotId] = true;
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              inFlightRef.current[slotId] = false;
              return;
            }
            void ingestOverwatchFrameBlob(slotId, label, blob, fps)
              .then(() => {
                setSlotStats((prev) => ({
                  ...prev,
                  [slotId]: { w: vw, h: vh, sent: prev[slotId].sent + 1, active: true },
                }));
              })
              .catch(() => {
                // Silent transient drop; next frame retries automatically
              })
              .finally(() => {
                inFlightRef.current[slotId] = false;
              });
          },
          "image/jpeg",
          0.86
        );
      }, intervalMs);
    },
    [stopSlot]
  );

  const startAll = useCallback(async () => {
    setBridgeError(null);
    // Always request permission if labels are blank/anonymous so Chrome reveals BOTH 4K USB + MacBook Pro cameras
    const needsUnlock =
      devices.length < 2 || devices.some((d) => !d.label || d.label.startsWith("Camera #"));
    const list = needsUnlock ? await refreshDevices(true) : devices;

    if (list.length === 0) {
      setBridgeError("No webcams detected in this browser. Check macOS Camera permission for Chrome.");
      return;
    }

    const external = list.find((c) => isExternal4kLabel(c.label) && !isBuiltInLabel(c.label));
    const builtin = list.find((c) => isBuiltInLabel(c.label));
    const effUsbId =
      !needsUnlock && usbDeviceId && list.some((c) => c.deviceId === usbDeviceId)
        ? usbDeviceId
        : external?.deviceId ?? list.find((c) => c.deviceId !== builtin?.deviceId)?.deviceId ?? list[0].deviceId;
    const effMacId =
      !needsUnlock && macDeviceId && list.some((c) => c.deviceId === macDeviceId)
        ? macDeviceId
        : builtin?.deviceId ?? list.find((c) => c.deviceId !== effUsbId)?.deviceId ?? "";

    setUsbDeviceId(effUsbId);
    setMacDeviceId(effMacId);

    const usbLabel = list.find((c) => c.deviceId === effUsbId)?.label || "4k Webcam";
    const macLabel = list.find((c) => c.deviceId === effMacId)?.label || "MacBook Pro Camera";

    try {
      await startSlot("usb_4k", effUsbId, usbLabel, usbPreset, targetFps);
      if (effMacId && effMacId !== effUsbId) {
        await new Promise((r) => window.setTimeout(r, 400));
        await startSlot("macbook_cam", effMacId, macLabel, macPreset, targetFps);
      }
      setRunning(true);
    } catch (err) {
      setBridgeError(err instanceof Error ? err.message : "Failed to start browser cameras.");
    }
  }, [devices, macDeviceId, macPreset, refreshDevices, startSlot, targetFps, usbDeviceId, usbPreset]);

  // Live-restart individual slot whenever user changes camera dropdown or resolution while running
  const selectUsbDevice = useCallback(
    (nextId: string) => {
      setUsbDeviceId(nextId);
      if (running && nextId) {
        const lbl = devices.find((c) => c.deviceId === nextId)?.label || "4k Webcam";
        void startSlot("usb_4k", nextId, lbl, usbPreset, targetFps).catch((err) =>
          setBridgeError(err instanceof Error ? err.message : "Failed to switch 4K USB camera.")
        );
      }
    },
    [devices, running, startSlot, targetFps, usbPreset]
  );

  const selectMacDevice = useCallback(
    (nextId: string) => {
      setMacDeviceId(nextId);
      if (running) {
        if (!nextId) {
          stopSlot("macbook_cam");
          return;
        }
        const lbl = devices.find((c) => c.deviceId === nextId)?.label || "MacBook Pro Camera";
        void startSlot("macbook_cam", nextId, lbl, macPreset, targetFps).catch((err) =>
          setBridgeError(err instanceof Error ? err.message : "Failed to switch MacBook camera.")
        );
      }
    },
    [devices, macPreset, running, startSlot, stopSlot, targetFps]
  );

  const selectUsbPreset = useCallback(
    (nextPreset: BrowserResolutionPreset) => {
      setUsbPreset(nextPreset);
      if (running && usbDeviceId) {
        const lbl = devices.find((c) => c.deviceId === usbDeviceId)?.label || "4k Webcam";
        void startSlot("usb_4k", usbDeviceId, lbl, nextPreset, targetFps).catch((err) =>
          setBridgeError(err instanceof Error ? err.message : "Failed to change 4K USB resolution.")
        );
      }
    },
    [devices, running, startSlot, targetFps, usbDeviceId]
  );

  const selectMacPreset = useCallback(
    (nextPreset: BrowserResolutionPreset) => {
      setMacPreset(nextPreset);
      if (running && macDeviceId) {
        const lbl = devices.find((c) => c.deviceId === macDeviceId)?.label || "MacBook Pro Camera";
        void startSlot("macbook_cam", macDeviceId, lbl, nextPreset, targetFps).catch((err) =>
          setBridgeError(err instanceof Error ? err.message : "Failed to change MacBook resolution.")
        );
      }
    },
    [devices, macDeviceId, running, startSlot, targetFps]
  );

  const swapCameras = useCallback(() => {
    const nextUsb = macDeviceId;
    const nextMac = usbDeviceId;
    setUsbDeviceId(nextUsb);
    setMacDeviceId(nextMac);
    if (running) {
      stopAll();
      window.setTimeout(() => {
        const usbLabel = devices.find((c) => c.deviceId === nextUsb)?.label || "4k Webcam";
        const macLabel = devices.find((c) => c.deviceId === nextMac)?.label || "MacBook Pro Camera";
        void (async () => {
          try {
            if (nextUsb) await startSlot("usb_4k", nextUsb, usbLabel, usbPreset, targetFps);
            if (nextMac && nextMac !== nextUsb) await startSlot("macbook_cam", nextMac, macLabel, macPreset, targetFps);
            setRunning(true);
          } catch (err) {
            setBridgeError(err instanceof Error ? err.message : "Failed to swap cameras.");
          }
        })();
      }, 120);
    }
  }, [devices, macDeviceId, macPreset, running, startSlot, stopAll, targetFps, usbDeviceId, usbPreset]);

  return {
    devices,
    usbDeviceId,
    setUsbDeviceId: selectUsbDevice,
    macDeviceId,
    setMacDeviceId: selectMacDevice,
    usbPreset,
    setUsbPreset: selectUsbPreset,
    macPreset,
    setMacPreset: selectMacPreset,
    targetFps,
    setTargetFps,
    running,
    autoStart,
    setAutoStart,
    bridgeError,
    slotStats,
    liveStreams,
    bindVideoElement,
    refreshDevices,
    startAll,
    stopAll,
    swapCameras,
  };
}
