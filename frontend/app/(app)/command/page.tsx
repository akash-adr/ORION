"use client";

import EngineMap from "@/components/command/EngineMap";
import LoopTimeline from "@/components/command/LoopTimeline";
import PnlStrip from "@/components/command/PnlStrip";
import Signals from "@/components/command/Signals";
import DecisionLedger from "@/components/ledger/DecisionLedger";
import PageHeader from "@/components/PageHeader";

export default function CommandPage() {
  return (
    <div className="grid gap-5">
      <PageHeader title="Command">What changed, what the engine recommends, and the proof one click away.</PageHeader>
      <PnlStrip />
      <div className="grid items-start gap-5 min-[1200px]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <DecisionLedger />
        <div className="grid gap-5">
          <EngineMap />
          <Signals />
        </div>
      </div>
      <LoopTimeline />
    </div>
  );
}
