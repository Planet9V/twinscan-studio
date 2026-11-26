import { API_URL } from "./api";

export interface WikiHeading {
  level: number;
  text: string;
  id: string;
}

export interface WikiCatalogueNode {
  title: string;
  slug?: string;
  path?: string;
  description?: string;
  collapsed?: boolean;
  children?: WikiCatalogueNode[];
}

export interface WikiPageSummary {
  slug: string;
  title: string;
  description: string;
  category: string;
  audience: string;
  read_minutes: number;
  headings: Array<string | WikiHeading>;
  excerpt: string;
}

export interface WikiCatalogueResponse {
  title: string;
  version: string;
  flagship_example: string;
  catalogue: Record<string, unknown> | WikiCatalogueNode[] | null;
  pages: WikiPageSummary[];
}

export interface WikiPageDetail {
  slug: string;
  title: string;
  description: string;
  category: string;
  audience: string;
  read_minutes: number;
  headings: Array<string | WikiHeading>;
  markdown: string;
  prev_slug: string | null;
  next_slug: string | null;
}

export interface EarlyBirdRecentMaker {
  spot_number: number;
  display_name: string;
  role: string;
  hardware_stack: string;
  created_at: string;
}

export interface EarlyBirdStatus {
  campaign: string;
  total_spots: number;
  claimed_spots: number;
  remaining_spots: number;
  is_open: boolean;
  perks: string[];
  recent_makers: EarlyBirdRecentMaker[];
}

export interface EarlyBirdClaimRequest {
  name: string;
  email: string;
  role: string;
  hardware_stack: string;
  project_goal?: string;
}

export interface EarlyBirdClaimResponse {
  ok: boolean;
  spot_number: number;
  total_spots: number;
  remaining_spots: number;
  founder_code: string;
  display_name: string;
  role: string;
  hardware_stack: string;
  claimed_at: string;
}

function parseErrorDetail(status: number, bodyText: string): string {
  try {
    const parsed = JSON.parse(bodyText) as { detail?: unknown; message?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
    if (typeof parsed.message === "string" && parsed.message.trim()) {
      return parsed.message;
    }
  } catch {
    // plain text body
  }
  return bodyText.trim() || `Request failed (${status})`;
}

async function requestWikiJson<T>(
  path: string,
  init?: RequestInit,
  maxRetries = 3
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(`${API_URL}${path}`, init);
      if (!res.ok) {
        const text = await res.text();
        const detail = parseErrorDetail(res.status, text);
        const err = new Error(detail);
        if (res.status < 500 || attempt === maxRetries) {
          throw err;
        }
        lastError = err;
      } else {
        return (await res.json()) as T;
      }
    } catch (err) {
      lastError = err;
      console.error(`[wikiApi] Attempt ${attempt}/${maxRetries} failed for ${path}:`, err);
      if (attempt === maxRetries) {
        throw err;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
  }
  throw lastError instanceof Error ? lastError : new Error(`Wiki API ${path} failed`);
}

export async function getWikiCatalogue(): Promise<WikiCatalogueResponse> {
  const data = await requestWikiJson<Partial<WikiCatalogueResponse>>("/api/wiki/catalogue");
  return {
    title: data.title ?? "Eigenia TwinScan Studio Wiki",
    version: data.version ?? "2.0",
    flagship_example: data.flagship_example ?? "Hiwonder PuppyPi Pro",
    catalogue: data.catalogue ?? null,
    pages: Array.isArray(data.pages) ? data.pages : [],
  };
}

export async function getWikiPage(slug: string): Promise<WikiPageDetail> {
  const data = await requestWikiJson<Partial<WikiPageDetail>>(
    `/api/wiki/pages/${encodeURIComponent(slug)}`
  );
  return {
    slug: data.slug ?? slug,
    title: data.title ?? slug,
    description: data.description ?? "",
    category: data.category ?? "Documentation",
    audience: data.audience ?? "All Makers",
    read_minutes: Number(data.read_minutes ?? 5),
    headings: Array.isArray(data.headings) ? data.headings : [],
    markdown: data.markdown ?? "",
    prev_slug: data.prev_slug ?? null,
    next_slug: data.next_slug ?? null,
  };
}

export async function getEarlyBirdStatus(): Promise<EarlyBirdStatus> {
  const data = await requestWikiJson<Partial<EarlyBirdStatus>>("/api/early-bird/status");
  const totalSpots = Number(data.total_spots ?? 50);
  const claimedSpots = Number(data.claimed_spots ?? 0);
  return {
    campaign: data.campaign ?? "Eigenia Early Bird Maker Founders (First 50)",
    total_spots: totalSpots,
    claimed_spots: claimedSpots,
    remaining_spots: Number(data.remaining_spots ?? Math.max(0, totalSpots - claimedSpots)),
    is_open: data.is_open ?? claimedSpots < totalSpots,
    perks: Array.isArray(data.perks) ? data.perks : [],
    recent_makers: Array.isArray(data.recent_makers) ? data.recent_makers : [],
  };
}

export async function claimEarlyBirdSpot(
  payload: EarlyBirdClaimRequest
): Promise<EarlyBirdClaimResponse> {
  return requestWikiJson<EarlyBirdClaimResponse>(
    "/api/early-bird/claim",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    1
  );
}
