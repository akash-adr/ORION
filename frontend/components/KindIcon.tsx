import { KIND_ICON } from "@/lib/kinds";
import { Activity } from "lucide-react";

/** The icon for an anomaly kind. */
export default function KindIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = KIND_ICON[kind] ?? Activity;
  return <Icon className={className} aria-hidden />;
}
