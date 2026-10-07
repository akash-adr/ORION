/** Bright pulses travelling along synapse segments. */
export const pulseVertex = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  uniform float uPixelRatio;
  uniform vec3  uColor;
  attribute vec3  aStart;
  attribute vec3  aEnd;
  attribute float aSeed;
  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    float t = fract(uTime * (0.25 + aSeed * 0.4) + aSeed * 13.7);
    vec3 p = mix(aStart, aEnd, t);
    float fade = sin(t * 3.14159);
    vColor = uColor * 2.2;
    vAlpha = fade;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * uPixelRatio * (1.0 / -mv.z) * (0.6 + fade * 0.6);
  }
`;

/** Particle streams flying from data-source nodes into the INGEST region. */
export const streamVertex = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  uniform float uPixelRatio;
  uniform float uActive;
  uniform vec3  uTarget;
  uniform vec3  uColor;
  attribute vec3  aStart;  // the particle's source node, updated on the CPU each frame
  attribute vec3  aJitter;
  attribute float aSeed;
  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    float t = fract(uTime * (0.28 + aSeed * 0.18) + aSeed * 7.31);
    // Each source gets one gently curved ribbon: the bend points away from the brain centre.
    vec3 mid = (aStart + uTarget) * 0.5;
    vec3 bend = normalize(vec3(aStart.xy - uTarget.xy, 0.0) + 1e-4) * 0.25;
    vec3 ctrl = mid + bend + aJitter * 0.35;
    vec3 p = mix(mix(aStart, ctrl, t), mix(ctrl, uTarget, t), t);
    p += aJitter * 0.12 * sin(t * 3.14159);
    float fade = smoothstep(0.0, 0.12, t) * (1.0 - smoothstep(0.82, 1.0, t));
    vColor = uColor * (1.2 + t * 1.6);
    vAlpha = fade * uActive;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * uPixelRatio * (1.0 / -mv.z) * (0.5 + t * 0.7);
  }
`;

export const dotFragment = /* glsl */ `
  varying vec3  vColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(vColor, smoothstep(0.5, 0.0, d) * vAlpha);
  }
`;

