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
  attribute vec3  aStart;
  attribute vec3  aJitter;
  attribute float aSeed;
  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    float t = fract(uTime * (0.28 + aSeed * 0.18) + aSeed * 7.31);
    vec3 ctrl = (aStart + uTarget) * 0.5 + vec3(0.0, 0.5, 0.0) + aJitter * 2.0;
    vec3 p = mix(mix(aStart, ctrl, t), mix(ctrl, uTarget, t), t);
    p += aJitter * 0.35 * sin(t * 3.14159);
    float fade = sin(t * 3.14159);
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

