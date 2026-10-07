import NeuralView from "@/components/neural/NeuralView";
import PageHeader from "@/components/PageHeader";

export default function NeuralPage() {
  return (
    <div>
      <PageHeader title="Neural view">The engine as a live map. Every dot is a campaign, product or data source, and every pulse is a real event. Click anything for the reasoning behind it.</PageHeader>
      <NeuralView />
    </div>
  );
}
