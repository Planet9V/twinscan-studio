"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { KnowledgeGraphPanel } from "@/components/graph/KnowledgeGraphPanel";
import { useStudio } from "@/context/StudioContext";

export default function GraphPage() {
  const router = useRouter();
  const {
    activeSpaceId,
    graph,
    setSelectedEquipmentId,
    setFocusTarget,
    handleEnrichAsset,
  } = useStudio();

  return (
    <KnowledgeGraphPanel
      spaceId={activeSpaceId}
      graph={graph}
      onSelectEquipment={(id) => setSelectedEquipmentId(id)}
      onFocusTarget={(target) => {
        setFocusTarget(target);
        if (target.equipmentId) {
          setSelectedEquipmentId(target.equipmentId);
        }
        router.push("/twin");
      }}
      onEnrich={(equipmentId) => void handleEnrichAsset(equipmentId)}
    />
  );
}
