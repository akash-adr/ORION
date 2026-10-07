import { Suspense } from "react";
import PitchView from "@/components/pitch/PitchView";

export default function PitchPage() {
  return (
    <Suspense fallback={null}>
      <PitchView />
    </Suspense>
  );
}
