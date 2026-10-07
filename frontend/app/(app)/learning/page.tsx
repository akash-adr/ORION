"use client";

import AuditLog from "@/components/learning/AuditLog";
import LearningCharts from "@/components/learning/LearningCharts";
import LearningKpis from "@/components/learning/LearningKpis";
import OutcomesTable from "@/components/learning/OutcomesTable";
import SynapseMemory from "@/components/learning/SynapseMemory";
import PageHeader from "@/components/PageHeader";

export default function LearningPage() {
  return (
    <div className="grid gap-5">
      <PageHeader title="Learning and audit">How accurate the engine&apos;s predictions have been, what it has learned from them, and every change it has sent.</PageHeader>
      <LearningKpis />
      <LearningCharts />
      <OutcomesTable />
      <SynapseMemory />
      <AuditLog />
    </div>
  );
}
