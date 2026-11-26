"use client";

import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  Copy,
  GitBranch,
  Info,
  Lightbulb,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface WikiMarkdownViewProps {
  markdown: string;
  onNavigateSlug?: (slug: string) => void;
}

type Block =
  | { type: "heading"; level: number; text: string; id: string }
  | { type: "paragraph"; text: string }
  | { type: "code"; lang: string; content: string }
  | { type: "mermaid"; content: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "blockquote"; alertType?: string; lines: string[] }
  | { type: "hr" };

function stripFrontmatter(md: string): string {
  const normalized = md.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) return normalized;
  const endIdx = normalized.indexOf("\n---\n", 4);
  if (endIdx === -1) return normalized;
  return normalized.slice(endIdx + 5).trimStart();
}

export function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_~[\]()]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function parseMarkdownBlocks(raw: string): Block[] {
  const clean = stripFrontmatter(raw);
  const lines = clean.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Fenced code / mermaid block
    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim().toLowerCase();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      if (lang === "mermaid") {
        blocks.push({ type: "mermaid", content: buf.join("\n").trim() });
      } else {
        blocks.push({ type: "code", lang: lang || "text", content: buf.join("\n") });
      }
      continue;
    }

    // Headings H1-H4
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const text = headingMatch[2].trim();
      blocks.push({ type: "heading", level, text, id: slugifyHeading(text) });
      i++;
      continue;
    }

    // Blockquote / GitHub Alert
    if (trimmed.startsWith(">")) {
      const qLines: string[] = [];
      let alertType: string | undefined;
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        const content = lines[i].trim().replace(/^>\s?/, "");
        const alertMatch = content.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]$/i);
        if (alertMatch && qLines.length === 0) {
          alertType = alertMatch[1].toUpperCase();
        } else {
          qLines.push(content);
        }
        i++;
      }
      blocks.push({ type: "blockquote", alertType, lines: qLines });
      continue;
    }

    // Markdown table
    if (
      trimmed.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])
    ) {
      const splitRow = (rowLine: string) =>
        rowLine
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((c) => c.trim());
      const headers = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim() !== "") {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Unordered or ordered list
    const isUl = /^[-*+]\s+/.test(trimmed);
    const isOl = /^\d+\.\s+/.test(trimmed);
    if (isUl || isOl) {
      const items: string[] = [];
      while (i < lines.length) {
        const t = lines[i].trim();
        const ulM = t.match(/^[-*+]\s+(.+)$/);
        const olM = t.match(/^\d+\.\s+(.+)$/);
        if (isUl && ulM) {
          items.push(ulM[1]);
          i++;
        } else if (isOl && olM) {
          items.push(olM[1]);
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: "list", ordered: isOl, items });
      continue;
    }

    // Paragraph (coalesce contiguous lines)
    const pLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("#") &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].trim().startsWith(">") &&
      !/^[-*+]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim())
    ) {
      pLines.push(lines[i].trim());
      i++;
    }
    blocks.push({ type: "paragraph", text: pLines.join(" ") });
  }

  return blocks;
}

function renderInline(
  text: string,
  onNavigateSlug?: (slug: string) => void
): React.ReactNode[] {
  // Tokenize inline code, links, bold, and italic safely
  const tokenRegex = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyIdx = 0;

  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    keyIdx++;
    if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code
          key={`c-${keyIdx}`}
          className="rounded border border-white/10 bg-eigenia-obsidian px-1.5 py-0.5 font-mono text-[11px] text-eigenia-sky"
        >
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("[")) {
      const lm = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (lm) {
        const label = lm[1];
        const href = lm[2];
        const mdSlugMatch = href.match(/(?:\.\/)?([a-z0-9-]+)\.md(?:#.*)?$/i);
        if (mdSlugMatch && onNavigateSlug) {
          const slug = mdSlugMatch[1].toLowerCase();
          parts.push(
            <button
              key={`l-${keyIdx}`}
              type="button"
              onClick={() => onNavigateSlug(slug)}
              className="font-medium text-eigenia-orange underline decoration-eigenia-orange/50 underline-offset-2 hover:text-white"
            >
              {label}
            </button>
          );
        } else {
          parts.push(
            <a
              key={`a-${keyIdx}`}
              href={href}
              target={href.startsWith("http") ? "_blank" : undefined}
              rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
              className="font-medium text-eigenia-sky underline decoration-eigenia-sky/40 underline-offset-2 hover:text-white"
            >
              {label}
            </a>
          );
        }
      }
    } else if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(
        <strong key={`b-${keyIdx}`} className="font-semibold text-white">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(
        <em key={`i-${keyIdx}`} className="italic text-eigenia-ink">
          {token.slice(1, -1)}
        </em>
      );
    }
    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}

function summarizeMermaid(source: string): { diagramType: string; entities: string[] } {
  const firstLine =
    source
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith("%%")) ?? "diagram";
  const diagramType = firstLine.split(/\s+/)[0] || "mermaid";

  const entities = new Set<string>();
  const labelMatches = source.matchAll(/(?:\["([^"]+)"\]|\[([^\]]+)\]|participant\s+([^\n]+))/g);
  for (const m of labelMatches) {
    const val = (m[1] || m[2] || m[3] || "").replace(/^.*\s+as\s+/i, "").trim();
    if (val && val.length <= 42 && !val.startsWith("style")) {
      entities.add(val);
      if (entities.size >= 10) break;
    }
  }
  return { diagramType, entities: Array.from(entities) };
}

function MermaidPreviewCard({ source }: { source: string }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const { diagramType, entities } = useMemo(() => summarizeMermaid(source), [source]);

  const handleCopy = () => {
    void navigator.clipboard?.writeText(source);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="my-4 overflow-hidden rounded-xl border border-eigenia-sky/35 bg-gradient-to-br from-eigenia-shell via-eigenia-obsidian to-eigenia-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 bg-eigenia-shell/90 px-3.5 py-2">
        <div className="flex items-center gap-2">
          <GitBranch className="h-3.5 w-3.5 text-eigenia-orange" />
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-white">
            Architecture Diagram
          </span>
          <Badge variant="sky" className="font-mono text-[9px]">
            {diagramType}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded border border-white/15 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px] text-eigenia-muted hover:text-white"
          >
            {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy Mermaid"}
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 rounded border border-white/15 bg-eigenia-obsidian px-2 py-0.5 font-mono text-[10px] text-eigenia-sky hover:border-eigenia-sky"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? "Hide Source" : "View Source"}
          </button>
        </div>
      </div>

      {/* Visual Node Flow Summary */}
      {entities.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-3.5 py-3">
          {entities.map((ent, idx) => (
            <React.Fragment key={`${ent}-${idx}`}>
              <span className="rounded-md border border-eigenia-sky/30 bg-eigenia-surface px-2.5 py-1 font-mono text-[10px] text-white shadow-sm">
                {ent}
              </span>
              {idx < entities.length - 1 && (
                <span className="font-mono text-[10px] text-eigenia-orange">→</span>
              )}
            </React.Fragment>
          ))}
        </div>
      )}

      {expanded && (
        <pre className="max-h-72 overflow-x-auto border-t border-white/10 bg-black/50 p-3.5 font-mono text-[11px] leading-relaxed text-eigenia-ink">
          <code>{source}</code>
        </pre>
      )}
    </div>
  );
}

function CodeBlockCard({ lang, content }: { lang: string; content: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    void navigator.clipboard?.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="my-3 overflow-hidden rounded-lg border border-white/10 bg-eigenia-obsidian">
      <div className="flex items-center justify-between border-b border-white/10 bg-eigenia-shell px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase text-eigenia-muted">
          <Code2 className="h-3 w-3 text-eigenia-sky" />
          {lang}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 font-mono text-[10px] text-eigenia-muted hover:text-white"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 font-mono text-[11px] leading-relaxed text-eigenia-ink">
        <code>{content}</code>
      </pre>
    </div>
  );
}

export function WikiMarkdownView({
  markdown,
  onNavigateSlug,
}: WikiMarkdownViewProps): React.JSX.Element {
  const blocks = useMemo(() => parseMarkdownBlocks(markdown), [markdown]);

  return (
    <article className="space-y-3 text-sm leading-relaxed text-eigenia-ink">
      {blocks.map((block, idx) => {
        if (block.type === "hr") {
          return <hr key={idx} className="my-5 border-white/10" />;
        }
        if (block.type === "heading") {
          const Tag = (`h${Math.min(4, Math.max(1, block.level))}`) as
            | "h1"
            | "h2"
            | "h3"
            | "h4";
          const cls =
            block.level === 1
              ? "mt-2 border-b border-white/10 pb-2 font-mono text-xl font-bold tracking-tight text-white"
              : block.level === 2
                ? "mt-6 border-b border-white/10 pb-1.5 font-mono text-base font-bold text-white"
                : block.level === 3
                  ? "mt-4 font-mono text-sm font-semibold text-eigenia-sky"
                  : "mt-3 font-mono text-xs font-semibold uppercase tracking-wider text-eigenia-orange";
          return (
            <Tag key={idx} id={block.id} className={cls}>
              {renderInline(block.text, onNavigateSlug)}
            </Tag>
          );
        }
        if (block.type === "paragraph") {
          return (
            <p key={idx} className="text-xs leading-6 text-eigenia-ink sm:text-[13px]">
              {renderInline(block.text, onNavigateSlug)}
            </p>
          );
        }
        if (block.type === "mermaid") {
          return <MermaidPreviewCard key={idx} source={block.content} />;
        }
        if (block.type === "code") {
          return <CodeBlockCard key={idx} lang={block.lang} content={block.content} />;
        }
        if (block.type === "list") {
          const ListTag = block.ordered ? "ol" : "ul";
          return (
            <ListTag
              key={idx}
              className={cn(
                "space-y-1.5 pl-5 text-xs leading-6 text-eigenia-ink sm:text-[13px]",
                block.ordered ? "list-decimal" : "list-disc"
              )}
            >
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item, onNavigateSlug)}</li>
              ))}
            </ListTag>
          );
        }
        if (block.type === "blockquote") {
          const isWarn = block.alertType === "WARNING" || block.alertType === "CAUTION";
          const isTip = block.alertType === "TIP";
          return (
            <div
              key={idx}
              className={cn(
                "my-3 rounded-lg border-l-4 px-3.5 py-2.5 text-xs leading-relaxed",
                isWarn
                  ? "border-eigenia-amber bg-eigenia-amber/10 text-eigenia-ink"
                  : isTip
                    ? "border-emerald-400 bg-emerald-500/10 text-eigenia-ink"
                    : "border-eigenia-sky bg-eigenia-sky/10 text-eigenia-ink"
              )}
            >
              {block.alertType && (
                <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-white">
                  {isWarn ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-eigenia-amber" />
                  ) : isTip ? (
                    <Lightbulb className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <Info className="h-3.5 w-3.5 text-eigenia-sky" />
                  )}
                  {block.alertType}
                </div>
              )}
              {block.lines.map((l, j) => (
                <p key={j}>{renderInline(l, onNavigateSlug)}</p>
              ))}
            </div>
          );
        }
        if (block.type === "table") {
          return (
            <div
              key={idx}
              className="my-4 overflow-x-auto rounded-lg border border-white/10 bg-eigenia-obsidian"
            >
              <table className="w-full border-collapse text-left text-xs">
                <thead className="border-b border-white/10 bg-eigenia-shell font-mono text-[10px] uppercase tracking-wider text-eigenia-sky">
                  <tr>
                    {block.headers.map((h, j) => (
                      <th key={j} className="px-3 py-2 font-semibold">
                        {renderInline(h, onNavigateSlug)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/10">
                  {block.rows.map((row, rIdx) => (
                    <tr key={rIdx} className="hover:bg-white/[0.03]">
                      {row.map((cell, cIdx) => (
                        <td key={cIdx} className="px-3 py-2 align-top text-eigenia-ink">
                          {renderInline(cell, onNavigateSlug)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return null;
      })}
    </article>
  );
}
