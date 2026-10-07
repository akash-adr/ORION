"use client";

import { Lock } from "lucide-react";
import { Panel } from "@/components/Panel";

const Swatch = ({ children }: { children: React.ReactNode }) => (
  <svg width="26" height="20" viewBox="0 0 26 20" aria-hidden className="shrink-0">
    {children}
  </svg>
);

/** What every visual encoding on the brain means, in plain words. */
export default function Legend() {
  const rows: { sw: React.ReactNode; title: string; text: string }[] = [
    { sw: <Swatch><circle cx="6" cy="10" r="4" fill="var(--gain)" /><circle cx="14" cy="10" r="4" fill="var(--risk)" /><circle cx="22" cy="10" r="4" fill="var(--loss)" /></Swatch>, title: "Colour is health", text: "Green earns more than it costs, amber is weak, red is losing money." },
    { sw: <Swatch><circle cx="8" cy="10" r="3" fill="var(--fog)" /><circle cx="19" cy="10" r="7" fill="var(--fog)" /></Swatch>, title: "Size is spend", text: "A bigger dot spends more each day." },
    { sw: <Swatch><rect x="9" y="6" width="8" height="8" rx="1.5" transform="rotate(45 13 10)" fill="var(--fog)" /></Swatch>, title: "Diamonds are products", text: "Circles are campaigns; diamonds are the products they promote." },
    { sw: <Swatch><circle cx="13" cy="10" r="4" fill="var(--fog)" /><circle cx="13" cy="10" r="8" fill="none" stroke="var(--gain)" strokeDasharray="2 3" /></Swatch>, title: "Dashed outer ring: room to scale", text: "The next rupee here still earns more than a rupee." },
    { sw: <Swatch><circle cx="13" cy="10" r="6" fill="var(--fog)" /><circle cx="13" cy="10" r="3" fill="none" stroke="var(--ink)" /></Swatch>, title: "Dark inner ring: past saturation", text: "More spend here loses money; the engine plans to cut." },
    { sw: <Swatch><circle cx="13" cy="12" r="4" fill="var(--fog)" /><rect x="9" y="0.5" width="8" height="8" rx="2" fill="var(--ink)" stroke="var(--risk)" /></Swatch>, title: "Lock: stock guard", text: "The product is nearly out of stock, so spend cannot rise." },
    { sw: <Swatch><circle cx="13" cy="10" r="4" fill="var(--loss)" /><circle cx="13" cy="10" r="8" fill="none" stroke="var(--loss)" opacity="0.5" /></Swatch>, title: "Pulsing ring: alert", text: "The engine found a signal here, in the alert's colour." },
    { sw: <Swatch><circle cx="13" cy="10" r="4" fill="var(--fog)" /><circle cx="13" cy="10" r="8.5" fill="none" stroke="var(--risk)" strokeDasharray="1.5 2.5" /></Swatch>, title: "Dotted amber ring: low trust", text: "Meta and Google report more conversions than the store saw; a wider ring means less trust." },
    { sw: <Swatch><circle cx="13" cy="10" r="6" fill="none" stroke="var(--synapse)" strokeDasharray="2 3" /></Swatch>, title: "Dashed circle: untested idea", text: "A combination the engine has not run. Solid with a Test label once a test is running." },
    { sw: <Swatch><rect x="9" y="6" width="8" height="8" rx="2" fill="var(--slate)" stroke="var(--fog)" strokeWidth="1.5" /></Swatch>, title: "Square: data source", text: "Amber with an over-reporting figure when a platform over-claims; Store-verified once fixed." },
    { sw: <Swatch><line x1="2" y1="14" x2="24" y2="6" stroke="var(--synapse)" strokeWidth="1" opacity="0.4" /><line x1="2" y1="16" x2="24" y2="12" stroke="var(--synapse)" strokeWidth="3" opacity="0.8" /></Swatch>, title: "Line thickness: memory", text: "A thicker line means decisions on that campaign delivered what they predicted." },
    { sw: <Swatch><circle cx="5" cy="10" r="3" fill="var(--loss)" /><circle cx="13" cy="10" r="3" fill="var(--gain)" /><circle cx="21" cy="10" r="3" fill="var(--risk)" /></Swatch>, title: "Travelling dots: events", text: "Red for a loss, green for a gain, amber for a risk or block. Blue-green for system steps." },
    { sw: <Swatch><circle cx="4" cy="10" r="3" fill="var(--region-ingest)" /><circle cx="11" cy="10" r="3" fill="var(--region-diagnose)" /><circle cx="18" cy="10" r="3" fill="var(--region-decide)" /><circle cx="24" cy="10" r="2.5" fill="var(--region-learn)" /></Swatch>, title: "Regions", text: "Ingest (back), Diagnose (top), Decide (front), Learn (centre): the stage the engine is in." },
  ];
  return (
    <Panel title="How to read the map">
      <ul className="grid gap-3">
        {rows.map((r) => (
          <li key={r.title} className="grid grid-cols-[26px_minmax(0,1fr)] items-start gap-3">
            <span className="mt-0.5 rounded bg-ink p-0.5 dark-capsule">{r.sw}</span>
            <span className="text-sm">
              <span className="font-semibold">{r.title}.</span> <span className="text-fog">{r.text}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-fog">
        <Lock className="size-3" aria-hidden />
        Every mark comes from live engine data; none is decoration.
      </p>
    </Panel>
  );
}
