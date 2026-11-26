"""Pydantic schemas for industrial nameplate, barcode, and visual grounding outputs."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BarcodeMatch(BaseModel):
    """Deterministically decoded 1D/2D industrial barcode or DataMatrix tag."""

    format: str = Field(..., description="Barcode symbology (e.g., DataMatrix, QRCode, Code128)")
    text: str = Field(..., description="Exact decoded payload text")
    position: List[List[int]] = Field(default_factory=list, description="Corner coordinates in pixels")


class VisionFieldBox(BaseModel):
    """Grounded bounding box for a detected label, tag, or hardware feature."""

    label: str
    value: str
    bbox_norm: List[float] = Field(
        default_factory=lambda: [0.0, 0.0, 1000.0, 1000.0],
        description="Normalized [ymin, xmin, ymax, xmax] box in 0-1000 scale",
    )
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class EquipmentVisionResult(BaseModel):
    """Structured cyber-physical asset metadata extracted from an equipment image."""

    name: str = Field(default="Unidentified Asset", description="Human-readable label for map placement")
    equipment_type: str = Field(default="Industrial Equipment")
    dexpi_class: str = Field(default="Equipment", description="DEXPI 2.0 / ISO 15926-4 aligned class")
    manufacturer: str = Field(default="Unknown")
    model_number: str = Field(default="Unknown")
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    hardware_revision: Optional[str] = None
    firmware_version: Optional[str] = None
    manufacturing_date: Optional[str] = None
    inferred_cpe_23: Optional[str] = Field(
        default=None,
        description="Candidate NIST CPE 2.3 string for vulnerability/EPSS linkage",
    )
    voltage_rating: Optional[str] = None
    current_or_power: Optional[str] = None
    certifications: List[str] = Field(default_factory=list)
    asset_tags: List[str] = Field(default_factory=list)
    mac_addresses: List[str] = Field(default_factory=list)
    ip_or_hostname_labels: List[str] = Field(default_factory=list)
    barcodes: List[BarcodeMatch] = Field(default_factory=list)
    primary_bbox_norm: List[float] = Field(
        default_factory=lambda: [150.0, 200.0, 850.0, 800.0],
        description="Normalized [ymin, xmin, ymax, xmax] box of primary equipment in 0-1000 scale",
    )
    detected_boxes: List[VisionFieldBox] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    model_used: str = Field(default="google/gemini-2.5-flash")
    consensus_verified: bool = Field(default=False)
    discrepancies: List[str] = Field(default_factory=list)
    raw_notes: str = Field(default="")

    def to_embedding_text(self) -> str:
        """Build a canonical semantic summary string for pgvector embedding."""
        parts = [
            f"Name: {self.name}",
            f"Type: {self.equipment_type}",
            f"DEXPI: {self.dexpi_class}",
            f"Manufacturer: {self.manufacturer}",
            f"Model: {self.model_number}",
        ]
        if self.part_number:
            parts.append(f"Part: {self.part_number}")
        if self.serial_number:
            parts.append(f"Serial: {self.serial_number}")
        if self.inferred_cpe_23:
            parts.append(f"CPE: {self.inferred_cpe_23}")
        if self.voltage_rating:
            parts.append(f"Voltage: {self.voltage_rating}")
        if self.asset_tags:
            parts.append(f"Tags: {', '.join(self.asset_tags)}")
        if self.mac_addresses:
            parts.append(f"MAC: {', '.join(self.mac_addresses)}")
        return " | ".join(parts)
