"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { AlertOctagon, Home, RefreshCw, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function RouteError({ error, reset }: RouteErrorProps) {
  useEffect(() => {
    console.error("[Eigenia RouteError]", error);
  }, [error]);

  const stackLines = (error?.stack || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 12);

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-3xl items-center justify-center p-4">
      <Card className="w-full border-eigenia-fault/50 bg-eigenia-shell">
        <CardHeader className="border-b border-eigenia-fault/30 bg-eigenia-fault/10">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-eigenia-fault">
              <AlertOctagon className="h-4 w-4" />
              EIGENIA // CLIENT RUNTIME FAULT INTERCEPTED
            </CardTitle>
            <Badge variant="fault">
              {error?.digest ? `DIGEST ${error.digest}` : "RECOVERABLE"}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 p-5">
          <div className="rounded-md border border-eigenia-fault/40 bg-eigenia-obsidian p-3.5">
            <div className="font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
              Error Message
            </div>
            <div className="mt-1 break-words font-mono text-sm font-semibold text-white">
              {error?.message || "An unexpected client-side exception occurred."}
            </div>
          </div>

          {stackLines.length > 0 && (
            <div className="rounded-md border border-white/10 bg-eigenia-obsidian p-3.5">
              <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
                <Terminal className="h-3 w-3 text-eigenia-amber" />
                Stack Trace Summary
              </div>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-eigenia-ink">
                {stackLines.join("\n")}
              </pre>
            </div>
          )}

          <p className="text-xs text-eigenia-muted">
            If this occurred right after a container rebuild, try a hard browser refresh (Cmd+Shift+R)
            or click Retry below to re-mount this view cleanly.
          </p>

          <div className="flex flex-wrap items-center gap-2.5 pt-1">
            <Button onClick={() => reset()} variant="default">
              <RefreshCw className="h-3.5 w-3.5" />
              Retry View
            </Button>
            <Button variant="sky" asChild>
              <Link href="/">
                <Home className="h-3.5 w-3.5" />
                Mission Control
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
