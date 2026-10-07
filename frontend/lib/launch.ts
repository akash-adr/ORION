import type { Decision } from "./types";

interface LaunchKey {
  sku_id: string;
  channel: string;
  audience: string;
}
const launchOf = (d: Decision) => (d.action as { launch?: LaunchKey }).launch;

/** The launch-test decision for an untested combination (pending or already handled), if the engine made one. */
export function findLaunchDecision(decisions: Decision[], k: LaunchKey): Decision | undefined {
  return decisions.find((d) => {
    const l = d.action.type === "launch_test" ? launchOf(d) : undefined;
    return !!l && l.sku_id === k.sku_id && l.channel === k.channel && l.audience === k.audience;
  });
}
