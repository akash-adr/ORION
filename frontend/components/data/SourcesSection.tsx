"use client";

import { BadgeCheck, CircleCheck, TriangleAlert } from "lucide-react";
import { Fragment } from "react";
import { LoadState, Panel } from "@/components/Panel";
import { dateShort, num, pct, timeShort } from "@/lib/format";
import { useSources } from "@/lib/queries";
import type { SourceRow } from "@/lib/types";

const GROUPS: { kind: SourceRow["kind"]; title: string }[] = [
  { kind: "ad_platform", title: "Ad platforms" },
  { kind: "store", title: "Store" },
  { kind: "erp", title: "Inventory" },
  { kind: "analytics", title: "Analytics" },
  { kind: "pricing", title: "Pricing" },
];

/** The real system each demo connector stands in for. The API names only its own connector id, so this mapping is UI copy. */
const STANDS_IN_FOR: Record<string, string> = {
  meta_ads: "Meta Marketing API",
  google_ads: "Google Ads API",
  amazon_ads: "Amazon Ads API",
  tiktok_ads: "TikTok Marketing API",
  programmatic: "Programmatic DSP reporting API",
  store: "Shopify Admin API",
  inventory: "ERP inventory feed",
  ga4: "GA4 Data API",
  pricing: "Catalogue and competitor price feed",
};

export default function SourcesSection() {
  const q = useSources();
  return (
    <Panel title="Sources" note="Nine connectors feed the engine. Trust is how closely a source matches the store">
      <LoadState q={q} what="the sources" height={360}>
        {(rows) => (
          <div className="overflow-x-auto">
            <table className="tbl min-w-[980px]">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Stands in for</th>
                  <th className="num">Rows</th>
                  <th>Date range</th>
                  <th>Last synced</th>
                  <th>Status</th>
                  <th className="num" title="How many more conversions the platform claims than the store recorded">Over-reporting</th>
                  <th className="num">Trust</th>
                </tr>
              </thead>
              <tbody>
                {GROUPS.map((g) => {
                  const items = rows.filter((r) => r.kind === g.kind);
                  if (!items.length) return null;
                  return (
                    <Fragment key={g.kind}>
                      <tr>
                        <td colSpan={8} className="!border-b-0 !pt-5 !pb-1 text-sm font-bold">
                          {g.title}
                        </td>
                      </tr>
                      {items.map((s) => (
                        <tr key={s.source_id}>
                          <td>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-semibold">{s.label}</span>
                              {s.verified && (
                                <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-xs font-semibold tone-gain">
                                  <BadgeCheck className="size-3" aria-hidden />
                                  Store-verified
                                </span>
                              )}
                            </div>
                            {s.status === "warn" && <div className="mt-0.5 text-sm text-fog">{s.detail}</div>}
                          </td>
                          <td className="text-fog">{STANDS_IN_FOR[s.source_id] ?? s.connector}</td>
                          <td className="num">{num(s.rows)}</td>
                          <td className="whitespace-nowrap">{dateShort(s.min_date)} to {dateShort(s.max_date, true)}</td>
                          <td className="whitespace-nowrap">{dateShort(s.last_synced)}, {timeShort(s.last_synced)}</td>
                          <td>
                            {s.status === "ok" ? (
                              <span className="inline-flex items-center gap-1 tone-gain">
                                <CircleCheck className="size-3.5" aria-hidden />
                                OK
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 font-semibold tone-risk">
                                <TriangleAlert className="size-3.5" aria-hidden />
                                Needs attention
                              </span>
                            )}
                          </td>
                          <td className="num">{s.kind !== "ad_platform" ? <span className="text-fog" title="Not applicable to this source">—</span> : (s.inflation_pct ?? 0) >= 0.005 ? <span className="font-semibold tone-risk">{pct(s.inflation_pct)}</span> : <span className="text-fog">None</span>}</td>
                          <td className="num">{s.trust_score === null ? <span className="text-fog" title="Not applicable to this source">—</span> : <span className={s.trust_score < 0.95 ? "font-semibold tone-risk" : ""}>{pct(s.trust_score)}</span>}</td>
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </Panel>
  );
}
