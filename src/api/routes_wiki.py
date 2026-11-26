"""FastAPI endpoints for the Eigenia TwinScan Documentation Wiki and Founding 50 Early Bird Makers."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["wiki-early-bird"])

DEFAULT_WIKI_DIR = Path(__file__).resolve().parents[2] / "docs" / "wiki"
_SLUG_RE = re.compile(r"^[a-z0-9\-]+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_CATEGORY_HINTS: Dict[str, Tuple[str, str]] = {
    "readme": ("Index", "All Makers & Engineers"),
    "00-": ("Introduction", "All Makers & Engineers"),
    "01-": ("Onboarding", "Principal & Senior Engineers"),
    "02-": ("Onboarding", "New Makers & Developers"),
    "03-": ("Capabilities", "Makers, Robotics & Operators"),
    "04-": ("User Guide", "Robot Operators & Makers"),
    "05-": ("Administration", "Fleet Admins & DevOps"),
    "06-": ("Developer Guide", "Full-Stack & Robotics Engineers"),
    "07-": ("Support", "Operators & Support Engineers"),
    "08-": ("Reference", "All Users & Architects"),
}


class EarlyBirdClaimRequest(BaseModel):
    """Payload to reserve one of the 50 Founding Maker Early Bird spots."""

    name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=180)
    role: str = Field(default="Maker", max_length=80)
    hardware_stack: Union[List[str], str] = Field(default_factory=list)
    project_goal: str = Field(default="", max_length=600)


def _resolve_wiki_dir(request: Request) -> Path:
    custom = getattr(request.app.state, "wiki_dir", None)
    return Path(custom) if custom is not None else DEFAULT_WIKI_DIR


def _parse_frontmatter_and_body(raw_md: str) -> Tuple[Dict[str, str], str]:
    """Parse leading YAML frontmatter key/value pairs using pure stdlib."""
    text = raw_md.lstrip("\ufeff")
    meta: Dict[str, str] = {}
    if text.startswith("---"):
        lines = text.splitlines()
        end_idx: Optional[int] = None
        for idx in range(1, min(len(lines), 40)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is not None:
            for fm_line in lines[1:end_idx]:
                if ":" in fm_line:
                    k, v = fm_line.split(":", 1)
                    key = k.strip().lower()
                    val = v.strip().strip('"').strip("'")
                    if key and val:
                        meta[key] = val
            body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
            return meta, body
    return meta, text


def _infer_category_and_audience(slug: str, meta: Dict[str, str]) -> Tuple[str, str]:
    default_cat, default_aud = ("Documentation", "Makers & Engineers")
    for prefix, pair in _CATEGORY_HINTS.items():
        if slug == prefix or slug.startswith(prefix):
            default_cat, default_aud = pair
            break
    return meta.get("category") or default_cat, meta.get("audience") or default_aud


def _extract_headings_and_excerpt(body: str) -> Tuple[List[str], str, int]:
    """Extract H1-H3 headings, a clean plain-text excerpt, and estimated reading minutes."""
    headings: List[str] = []
    excerpt_lines: List[str] = []
    in_code = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("#"):
            m = re.match(r"^(#{1,3})\s+(.+)$", line)
            if m:
                headings.append(m.group(2).strip())
            continue
        if (
            not excerpt_lines
            and line
            and not line.startswith((">", "|", "-", "*", "<!--", ":::"))
        ):
            clean = re.sub(r"[`*_]", "", line)
            clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
            excerpt_lines.append(clean)
    words = len(re.findall(r"\b\w+\b", body))
    read_minutes = max(1, int(round(words / 200.0)))
    excerpt = (excerpt_lines[0][:220] if excerpt_lines else "").strip()
    return headings[:24], excerpt, read_minutes


def _scan_wiki_pages(wiki_dir: Path) -> List[Dict[str, Any]]:
    """Scan ``docs/wiki/*.md`` and build ordered page metadata records."""
    if not wiki_dir.is_dir():
        return []
    files: List[Tuple[str, Path]] = []
    for path in sorted(wiki_dir.glob("*.md"), key=lambda p: p.name.lower()):
        slug = path.stem.lower()
        if not _SLUG_RE.fullmatch(slug):
            continue
        files.append((slug, path))

    # Order numbered pages 00-..08- first, README index first or last cleanly
    def _sort_key(item: Tuple[str, Path]) -> Tuple[int, str]:
        s = item[0]
        if s == "readme":
            return (0, s)
        if re.match(r"^\d{2}-", s):
            return (1, s)
        return (2, s)

    files.sort(key=_sort_key)
    pages: List[Dict[str, Any]] = []
    for slug, path in files:
        try:
            raw_md = path.read_text(encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"[wiki] Failed reading {path}: {exc}\n")
            continue
        meta, body = _parse_frontmatter_and_body(raw_md)
        headings, excerpt, read_minutes = _extract_headings_and_excerpt(body)
        category, audience = _infer_category_and_audience(slug, meta)
        title = meta.get("title") or (headings[0] if headings else slug.replace("-", " ").title())
        description = meta.get("description") or excerpt or f"Eigenia TwinScan documentation for {title}."
        pages.append(
            {
                "slug": slug,
                "title": title,
                "description": description,
                "category": category,
                "audience": audience,
                "read_minutes": read_minutes,
                "headings": headings,
                "excerpt": excerpt or description,
                "_path": path,
                "_raw_md": raw_md,
            }
        )
    return pages


@router.get("/wiki/catalogue")
async def get_wiki_catalogue(request: Request) -> Dict[str, Any]:
    """Return the documentation wiki hierarchy from ``docs/wiki/catalogue.json`` and page summaries."""
    wiki_dir = _resolve_wiki_dir(request)
    catalogue_data: Any = []
    cat_path = wiki_dir / "catalogue.json"
    if cat_path.is_file():
        try:
            catalogue_data = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.stderr.write(f"[wiki] Failed parsing {cat_path}: {exc}\n")
            catalogue_data = []

    raw_pages = _scan_wiki_pages(wiki_dir)
    pages = [
        {
            "slug": p["slug"],
            "title": p["title"],
            "description": p["description"],
            "category": p["category"],
            "audience": p["audience"],
            "read_minutes": p["read_minutes"],
            "headings": p["headings"],
            "excerpt": p["excerpt"],
        }
        for p in raw_pages
    ]
    return {
        "title": "Eigenia TwinScan Maker & Robotics Wiki",
        "version": "2.0.0",
        "flagship_example": "Hiwonder PuppyPi Pro (Raspberry Pi 5 8 GB + LD19 360° LiDAR + ROS 2 Humble)",
        "catalogue": catalogue_data,
        "pages": pages,
    }


@router.get("/wiki/pages/{slug}")
async def get_wiki_page(slug: str, request: Request) -> Dict[str, Any]:
    """Fetch a single wiki Markdown document by strict validated slug with prev/next navigation."""
    if not _SLUG_RE.fullmatch(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wiki page slug (allowed: lowercase letters, digits, hyphens).",
        )

    wiki_dir = _resolve_wiki_dir(request)
    raw_pages = _scan_wiki_pages(wiki_dir)
    ordered_slugs = [p["slug"] for p in raw_pages]

    found_idx: Optional[int] = None
    for idx, p in enumerate(raw_pages):
        if p["slug"] == slug:
            resolved_path = p["_path"].resolve()
            if resolved_path.parent != wiki_dir.resolve():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid wiki path.")
            found_idx = idx
            break

    if found_idx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Wiki page {slug!r} not found.")

    page = raw_pages[found_idx]
    prev_slug = ordered_slugs[found_idx - 1] if found_idx > 0 else None
    next_slug = ordered_slugs[found_idx + 1] if found_idx + 1 < len(ordered_slugs) else None

    return {
        "slug": page["slug"],
        "title": page["title"],
        "description": page["description"],
        "category": page["category"],
        "audience": page["audience"],
        "read_minutes": page["read_minutes"],
        "headings": page["headings"],
        "markdown": page["_raw_md"],
        "prev_slug": prev_slug,
        "next_slug": next_slug,
    }


@router.get("/early-bird/status")
async def get_early_bird_status(request: Request) -> Dict[str, Any]:
    """Return live 50-spot Early Bird Founding Maker availability, perks, and anonymized signups."""
    ai_store = request.app.state.robot_ai_store
    try:
        return ai_store.get_early_bird_status()
    except Exception as exc:
        sys.stderr.write(f"[early_bird] Status query failed: {exc}\n")
        raise HTTPException(status_code=500, detail="Unable to load Early Bird campaign status.") from exc


@router.post("/early-bird/claim", status_code=status.HTTP_201_CREATED)
async def claim_early_bird_spot(body: EarlyBirdClaimRequest, request: Request) -> Dict[str, Any]:
    """Claim one of the 50 Founding Maker Early Bird spots with strict email uniqueness and cap."""
    name = body.name.strip()
    email = body.email.strip().lower()
    if len(name) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name must be at least 2 characters.")
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter a valid email address.")

    ai_store = request.app.state.robot_ai_store
    try:
        return ai_store.claim_early_bird_spot(
            {
                "name": name,
                "email": email,
                "role": body.role,
                "hardware_stack": body.hardware_stack,
                "project_goal": body.project_goal,
            }
        )
    except ValueError as exc:
        code = str(exc)
        if code == "email_already_claimed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email has already claimed a Founding Maker Early Bird spot.",
            ) from exc
        if code == "early_bird_full":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="All 50 Founding Maker Early Bird spots have been claimed.",
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=code) from exc
    except Exception as exc:
        sys.stderr.write(f"[early_bird] Claim failed: {exc}\n")
        raise HTTPException(status_code=500, detail="Unable to process Early Bird reservation.") from exc
