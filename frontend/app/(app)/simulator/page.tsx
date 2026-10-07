"use client";

import PageHeader from "@/components/PageHeader";
import CurvesGrid from "@/components/simulator/CurvesGrid";
import OptimizerPanel from "@/components/simulator/OptimizerPanel";
import WhatIf from "@/components/simulator/WhatIf";

export default function SimulatorPage() {
  return (
    <div className="grid gap-5">
      <PageHeader title="Simulator">Try a spend change before it happens, see the best plan for each objective, and read the response curves behind both.</PageHeader>
      <WhatIf />
      <OptimizerPanel />
      <CurvesGrid />
    </div>
  );
}
