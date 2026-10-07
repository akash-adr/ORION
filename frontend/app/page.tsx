"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function Home() {
  const [status, setStatus] = useState<"loading" | "connected" | "disconnected">("loading");
  const [latency, setLatency] = useState<number | null>(null);

  useEffect(() => {
    const checkHealth = async () => {
      const startTime = performance.now();
      try {
        const response = await api.get("/health");
        if (response.status === 200 && response.data?.status === "ok") {
          setLatency(Math.round(performance.now() - startTime));
          setStatus("connected");
        } else {
          setStatus("disconnected");
        }
      } catch {
        setStatus("disconnected");
      }
    };

    checkHealth();
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center p-6 bg-background">
      <Card className="w-full max-w-md border-border bg-card/60 backdrop-blur shadow-xl">
        <CardHeader className="pb-3">
          <CardTitle className="text-xl font-semibold tracking-tight">
            D2C Advertising Intelligence Engine
          </CardTitle>
          <CardDescription className="text-xs text-muted-foreground">
            DataQuest 3.0 • Autonomous Decision Engine
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/50 border border-border">
            <span className="text-sm font-medium text-foreground">Backend Status</span>
            {status === "loading" && (
              <Badge variant="outline" className="text-muted-foreground animate-pulse">
                Checking...
              </Badge>
            )}
            {status === "connected" && (
              <div className="flex items-center gap-2">
                {latency !== null && (
                  <span className="text-xs text-muted-foreground">{latency}ms</span>
                )}
                <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
                  Connected
                </Badge>
              </div>
            )}
            {status === "disconnected" && (
              <Badge className="bg-red-500/20 text-red-400 border-red-500/30 hover:bg-red-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-red-400 mr-1.5" />
                Disconnected
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
