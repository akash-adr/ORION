"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import PageHeader from "@/components/PageHeader";
import CampaignsTab from "@/components/performance/CampaignsTab";
import ChannelsTab from "@/components/performance/ChannelsTab";
import ProductsTab from "@/components/performance/ProductsTab";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "channels", label: "Channels" },
  { id: "campaigns", label: "Campaigns" },
  { id: "products", label: "Products" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function Body() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "channels") as TabId;
  const channel = params.get("channel");
  const go = (next: TabId, ch?: string | null) => router.replace(`/performance?tab=${next}${ch ? `&channel=${encodeURIComponent(ch)}` : ""}`, { scroll: false });
  return (
    <>
      <div role="tablist" aria-label="Performance views" className="mb-5 inline-flex rounded-lg border border-line bg-slate p-0.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => go(t.id, t.id === "campaigns" ? channel : null)}
            onKeyDown={(e) => {
              const i = TABS.findIndex((x) => x.id === tab);
              if (e.key === "ArrowRight") go(TABS[(i + 1) % TABS.length].id);
              if (e.key === "ArrowLeft") go(TABS[(i + TABS.length - 1) % TABS.length].id);
            }}
            className={cn("rounded-md px-4 py-1.5 text-sm font-semibold transition-colors", tab === t.id ? "bg-primary text-primary-foreground" : "text-fog hover:text-bone")}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "channels" && <ChannelsTab onPick={(c) => go("campaigns", c)} />}
        {tab === "campaigns" && <CampaignsTab channel={channel} onClear={() => go("campaigns")} />}
        {tab === "products" && <ProductsTab />}
      </div>
    </>
  );
}

export default function PerformancePage() {
  return (
    <div>
      <PageHeader title="Performance">Every channel, campaign and product the engine watches, with the numbers behind each decision. Click a column to sort.</PageHeader>
      <Suspense fallback={null}>
        <Body />
      </Suspense>
    </div>
  );
}
