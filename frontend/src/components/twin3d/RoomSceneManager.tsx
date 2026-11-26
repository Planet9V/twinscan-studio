"use client";

import React, { useState } from "react";
import {
  Archive,
  BookmarkPlus,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Edit3,
  FolderOpen,
  Layers,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { resolveBackendAssetUrl } from "@/lib/api";
import type { SpaceRecord } from "@/lib/types";

export interface RoomSceneManagerProps {
  spaces: SpaceRecord[];
  activeSpaceId: string;
  archiving: boolean;
  onSelectSpace: (spaceId: string) => void;
  onCreateRoom: (payload: {
    name: string;
    facility?: string;
    description?: string;
  }) => Promise<void>;
  onRenameRoom: (
    spaceId: string,
    payload: { name?: string; facility?: string; description?: string }
  ) => Promise<void>;
  onCloneRoom: (
    spaceId: string,
    payload: { name: string; facility?: string; description?: string }
  ) => Promise<void>;
  onDeleteRoom: (spaceId: string) => Promise<void>;
  onArchiveSnapshot: () => void;
}

function defaultCheckpointName(baseName: string): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return `${baseName} (${hh}:${mm})`;
}

export function RoomSceneManager({
  spaces,
  activeSpaceId,
  archiving,
  onSelectSpace,
  onCreateRoom,
  onRenameRoom,
  onCloneRoom,
  onDeleteRoom,
  onArchiveSnapshot,
}: RoomSceneManagerProps) {
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [newRoomOpen, setNewRoomOpen] = useState(false);
  const [checkpointOpen, setCheckpointOpen] = useState(false);

  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomFacility, setNewRoomFacility] = useState("Main Facility");
  const [checkpointName, setCheckpointName] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editFacility, setEditFacility] = useState("");

  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const safeSpaces = Array.isArray(spaces) ? spaces : [];
  const activeSpace = safeSpaces.find((s) => s.id === activeSpaceId) ?? safeSpaces[0] ?? null;

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newRoomName.trim();
    if (!trimmed || busyKey) return;
    setBusyKey("create");
    setLocalError(null);
    try {
      await onCreateRoom({
        name: trimmed,
        facility: newRoomFacility.trim() || "Main Facility",
      });
      setNewRoomName("");
      setNewRoomOpen(false);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to create room");
    } finally {
      setBusyKey(null);
    }
  };

  const handleCheckpointSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSpace || busyKey) return;
    const trimmed = checkpointName.trim() || defaultCheckpointName(activeSpace.name);
    setBusyKey("checkpoint");
    setLocalError(null);
    try {
      await onCloneRoom(activeSpace.id, {
        name: trimmed,
        facility: activeSpace.facility,
      });
      setCheckpointName("");
      setCheckpointOpen(false);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to save room checkpoint");
    } finally {
      setBusyKey(null);
    }
  };

  const handleDuplicate = async (sp: SpaceRecord) => {
    if (busyKey) return;
    setBusyKey(`dup-${sp.id}`);
    setLocalError(null);
    try {
      await onCloneRoom(sp.id, {
        name: `${sp.name} Copy`,
        facility: sp.facility,
      });
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to duplicate room");
    } finally {
      setBusyKey(null);
    }
  };

  const handleSaveRename = async (spaceId: string) => {
    const trimmed = editName.trim();
    if (!trimmed || busyKey) return;
    setBusyKey(`rename-${spaceId}`);
    setLocalError(null);
    try {
      await onRenameRoom(spaceId, {
        name: trimmed,
        facility: editFacility.trim() || undefined,
      });
      setEditingId(null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to rename room");
    } finally {
      setBusyKey(null);
    }
  };

  const handleDelete = async (sp: SpaceRecord) => {
    if (safeSpaces.length <= 1 || busyKey) return;
    setBusyKey(`del-${sp.id}`);
    setLocalError(null);
    try {
      await onDeleteRoom(sp.id);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to delete room");
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <Card className="border-eigenia-sky/30 bg-eigenia-shell">
      <CardContent className="flex flex-col gap-2.5 px-4 py-3">
        {/* Header Strip */}
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="sky" className="font-mono text-[10px]">
              <FolderOpen className="h-3 w-3" />
              ROOMS &amp; SAVED SCENES
            </Badge>
            <span className="text-xs font-semibold text-white">
              {activeSpace?.name || "Loading Room..."}
            </span>
            {activeSpace?.facility && (
              <span className="font-mono text-[10px] text-eigenia-muted">
                · {activeSpace.facility}
              </span>
            )}
            <Badge variant="neutral" className="font-mono text-[10px] tabular-nums">
              Saved Rooms ({safeSpaces.length})
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="default"
              disabled={busyKey !== null}
              onClick={() => {
                setCheckpointOpen(false);
                setNewRoomOpen((v) => !v);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              + New Blank Room
            </Button>

            <Button
              size="sm"
              variant="sky"
              disabled={!activeSpace || busyKey !== null}
              onClick={() => {
                setNewRoomOpen(false);
                if (!checkpointOpen && activeSpace) {
                  setCheckpointName(defaultCheckpointName(activeSpace.name));
                }
                setCheckpointOpen((v) => !v);
              }}
            >
              <BookmarkPlus className="h-3.5 w-3.5" />
              Save Checkpoint
            </Button>

            <Button
              size="sm"
              variant="secondary"
              disabled={!activeSpace || archiving}
              onClick={onArchiveSnapshot}
            >
              {archiving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Archive className="h-3.5 w-3.5 text-eigenia-orange" />
              )}
              {archiving ? "Archiving..." : "Archive to PG18"}
            </Button>

            <Button
              size="sm"
              variant="outline"
              onClick={() => setGalleryOpen((v) => !v)}
              className="font-mono text-[10px]"
            >
              Manage Rooms
              {galleryOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>

        {/* Inline New Blank Room Form */}
        {newRoomOpen && (
          <form
            onSubmit={handleCreateSubmit}
            className="flex flex-wrap items-center gap-2 rounded-md border border-eigenia-orange/40 bg-eigenia-obsidian p-2.5"
          >
            <Input
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              placeholder="New Room Name (e.g. Living Room, Lab Bay 2)"
              className="h-8 min-w-[200px] flex-1 text-xs"
              autoFocus
            />
            <Input
              value={newRoomFacility}
              onChange={(e) => setNewRoomFacility(e.target.value)}
              placeholder="Floor / Facility"
              className="h-8 w-44 text-xs"
            />
            <Button
              type="submit"
              size="sm"
              disabled={!newRoomName.trim() || busyKey !== null}
            >
              {busyKey === "create" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Create Room
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setNewRoomOpen(false)}
            >
              Cancel
            </Button>
          </form>
        )}

        {/* Inline Save Checkpoint (Clone) Form */}
        {checkpointOpen && activeSpace && (
          <form
            onSubmit={handleCheckpointSubmit}
            className="flex flex-wrap items-center gap-2 rounded-md border border-eigenia-sky/40 bg-eigenia-obsidian p-2.5"
          >
            <span className="font-mono text-[10px] text-eigenia-sky">
              Clone &quot;{activeSpace.name}&quot; as:
            </span>
            <Input
              value={checkpointName}
              onChange={(e) => setCheckpointName(e.target.value)}
              placeholder="Checkpoint name..."
              className="h-8 min-w-[220px] flex-1 text-xs"
              autoFocus
            />
            <Button type="submit" size="sm" variant="sky" disabled={busyKey !== null}>
              {busyKey === "checkpoint" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <BookmarkPlus className="h-3.5 w-3.5" />
              )}
              Save Checkpoint
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setCheckpointOpen(false)}
            >
              Cancel
            </Button>
          </form>
        )}

        {localError && (
          <div className="flex items-center justify-between rounded border border-eigenia-fault/45 bg-eigenia-fault/15 px-3 py-1.5 font-mono text-[11px] text-eigenia-fault">
            <span>{localError}</span>
            <button
              type="button"
              onClick={() => setLocalError(null)}
              className="text-[10px] uppercase opacity-80 hover:opacity-100"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Expanded Saved Rooms Gallery */}
        {galleryOpen && (
          <div className="border-t border-white/10 pt-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {safeSpaces.map((sp) => {
                const isActive = sp.id === activeSpaceId;
                const isEditing = editingId === sp.id;
                const thumbSrc = resolveBackendAssetUrl(sp.thumbnail_url ?? null);
                const panelCount = sp.panel_count ?? 0;
                const wallCount = sp.wall_count ?? (Array.isArray(sp.walls) ? sp.walls.length : 0);

                return (
                  <div
                    key={sp.id}
                    className={`flex flex-col overflow-hidden rounded-lg border transition ${
                      isActive
                        ? "border-eigenia-orange bg-eigenia-orange/10 shadow-sm shadow-eigenia-orange/15"
                        : "border-white/10 bg-eigenia-obsidian hover:border-white/25"
                    }`}
                  >
                    {/* Thumbnail Preview */}
                    <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden border-b border-white/10 bg-eigenia-obsidian">
                      {thumbSrc ? (
                        <img
                          src={thumbSrc}
                          alt={sp.name}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex flex-col items-center gap-1 text-eigenia-muted">
                          <Building2 className="h-6 w-6 opacity-50" />
                          <span className="font-mono text-[9px] uppercase">Blank / No 3D Wall</span>
                        </div>
                      )}
                      <div className="absolute left-2 top-2 flex items-center gap-1">
                        {isActive && (
                          <Badge variant="default" className="font-mono text-[9px]">
                            ACTIVE
                          </Badge>
                        )}
                        <Badge variant="neutral" className="font-mono text-[9px] tabular-nums">
                          <Layers className="h-2.5 w-2.5" />
                          {panelCount} {panelCount === 1 ? "panel" : "panels"}
                        </Badge>
                        <Badge variant="sky" className="font-mono text-[9px] tabular-nums">
                          {wallCount} {wallCount === 1 ? "wall" : "walls"}
                        </Badge>
                      </div>
                    </div>

                    {/* Room Metadata & Actions */}
                    <div className="flex flex-1 flex-col justify-between gap-2.5 p-3">
                      {isEditing ? (
                        <div className="space-y-2">
                          <Input
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            placeholder="Room Name"
                            className="h-7 text-xs"
                          />
                          <Input
                            value={editFacility}
                            onChange={(e) => setEditFacility(e.target.value)}
                            placeholder="Facility / Floor"
                            className="h-7 text-xs"
                          />
                          <div className="flex items-center gap-1.5">
                            <Button
                              size="sm"
                              className="h-7 flex-1 text-[10px]"
                              disabled={!editName.trim() || busyKey !== null}
                              onClick={() => void handleSaveRename(sp.id)}
                            >
                              {busyKey === `rename-${sp.id}` ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Check className="h-3 w-3" />
                              )}
                              Save
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-[10px]"
                              onClick={() => setEditingId(null)}
                            >
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div>
                            <div className="truncate text-xs font-semibold text-white">
                              {sp.name}
                            </div>
                            <div className="mt-0.5 truncate font-mono text-[10px] text-eigenia-muted">
                              {sp.facility || "Main Facility"}
                              {typeof sp.equipment_count === "number"
                                ? ` · ${sp.equipment_count} asset(s)`
                                : ""}
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center justify-between gap-1.5 border-t border-white/10 pt-2">
                            <Button
                              size="sm"
                              variant={isActive ? "secondary" : "default"}
                              className="h-7 px-2.5 text-[10px]"
                              disabled={isActive}
                              onClick={() => onSelectSpace(sp.id)}
                            >
                              {isActive ? "Loaded" : "Load Room"}
                            </Button>

                            <div className="flex items-center gap-1">
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7"
                                title="Rename Room"
                                onClick={() => {
                                  setEditingId(sp.id);
                                  setEditName(sp.name);
                                  setEditFacility(sp.facility || "");
                                }}
                              >
                                <Edit3 className="h-3 w-3 text-eigenia-sky" />
                              </Button>

                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7"
                                title="Duplicate Room Checkpoint"
                                disabled={busyKey !== null}
                                onClick={() => void handleDuplicate(sp)}
                              >
                                {busyKey === `dup-${sp.id}` ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Copy className="h-3 w-3 text-eigenia-ink" />
                                )}
                              </Button>

                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7"
                                title={
                                  safeSpaces.length <= 1
                                    ? "Cannot delete the last remaining room"
                                    : "Delete Room"
                                }
                                disabled={safeSpaces.length <= 1 || busyKey !== null}
                                onClick={() => void handleDelete(sp)}
                              >
                                {busyKey === `del-${sp.id}` ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Trash2 className="h-3 w-3 text-eigenia-fault" />
                                )}
                              </Button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
