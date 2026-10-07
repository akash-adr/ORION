/** Read a CSS colour token (e.g. "--loss") from the document; WebGL cannot use var(). */
export function readToken(name: string, scope?: Element | null, fallback = "#8b97b0"): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(scope ?? document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

let webglProbe: boolean | null = null;

/** Is WebGL available? Probed once (each probe makes a context) and the probe context is released straight away. */
export function webglAvailable(): boolean {
  if (webglProbe !== null) return webglProbe;
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    webglProbe = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    webglProbe = false;
  }
  return webglProbe;
}

export const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
