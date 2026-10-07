"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { onConnectivity } from "@/lib/api";
import { makeQueryClient } from "@/lib/queries";
import { useUiStore } from "@/lib/ui-store";

/** Applies the theme to <html> and mirrors API connectivity into the UI store. */
function Sync() {
  const theme = useUiStore((s) => s.theme);
  const setOffline = useUiStore((s) => s.setOffline);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => onConnectivity((online) => setOffline(!online)), [setOffline]);
  return null;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delay={300}>
        <Sync />
        {children}
      </TooltipProvider>
    </QueryClientProvider>
  );
}
