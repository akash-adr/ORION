/** Read a CSS colour token (e.g. "--loss") from the document; WebGL cannot use var(). */
export function readToken(name: string, scope?: Element | null, fallback = "#8b97b0"): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(scope ?? document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
