export const brainPointsVertex = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  uniform float uPixelRatio;
  uniform vec3  uMouse;
  uniform float uMouseStrength;
  uniform vec3  uIdleColor;
  uniform float uTint;
  uniform vec3  uRegionColor[4];
  uniform float uRegionGlow[4];
  uniform vec3  uWaveColor;
  uniform float uWaveRadius;
  uniform float uWaveStrength;
  uniform vec3  uSpotPos;
  uniform vec3  uSpotColor;
  uniform float uSpotStrength;

  attribute float aRegion;
  attribute float aRand;

  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    vec3 p = position;

    // Mouse push: dots near the cursor move outward.
    vec3 away = p - uMouse;
    float d = length(away);
    float push = smoothstep(0.55, 0.0, d) * uMouseStrength;
    p += normalize(away + 1e-4) * push * 0.22;

    // Per-dot twinkle.
    float tw = 0.78 + 0.22 * sin(uTime * 1.8 + aRand * 62.83);

    int r = int(aRegion + 0.5);
    float glow = uRegionGlow[r];
    vec3 tinted = mix(uIdleColor, uRegionColor[r], uTint);
    vec3 col = mix(tinted, uRegionColor[r], clamp(glow, 0.0, 1.0));

    // Ripple (learning) and travelling spot (anomaly -> decide).
    float wave = exp(-pow((length(p) - uWaveRadius) / 0.16, 2.0)) * uWaveStrength;
    float spot = smoothstep(0.5, 0.0, distance(p, uSpotPos)) * uSpotStrength;
    col = mix(col, uWaveColor, clamp(wave, 0.0, 1.0));
    col = mix(col, uSpotColor, clamp(spot, 0.0, 1.0));

    float energy = 0.58 + glow * 1.5 + push * 1.6 + wave * 1.8 + spot * 1.8;
    vColor = col * energy * tw;
    vAlpha = clamp(0.55 + glow * 0.45 + push * 0.5 + wave + spot, 0.0, 1.0);

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float size = uSize * (0.85 + glow * 0.5 + push * 1.2 + wave * 0.8 + spot * 0.8);
    gl_PointSize = size * uPixelRatio * (1.0 / -mv.z);
  }
`;

export const brainPointsFragment = /* glsl */ `
  varying vec3  vColor;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.05, d);
    gl_FragColor = vec4(vColor, a * vAlpha);
  }
`;

