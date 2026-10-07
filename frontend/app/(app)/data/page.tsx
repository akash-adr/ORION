"use client";

import QualitySection from "@/components/data/QualitySection";
import ReconciliationSection from "@/components/data/ReconciliationSection";
import SourcesSection from "@/components/data/SourcesSection";
import ThresholdsSection from "@/components/data/ThresholdsSection";
import PageHeader from "@/components/PageHeader";

export default function DataPage() {
  return (
    <div className="grid gap-5">
      <PageHeader title="Data truth">Where each number comes from, how far to trust it, and the limits the engine works within.</PageHeader>
      <SourcesSection />
      <ReconciliationSection />
      <QualitySection />
      <ThresholdsSection />
    </div>
  );
}
