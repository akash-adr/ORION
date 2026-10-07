// Extracts each particle's centre from public/models/brain.glb into public/models/brain-points.bin
// (Float32 xyz, world space). Run: node scripts/extract-brain-points.mjs
import fs from "fs";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const buf = fs.readFileSync("public/models/brain.glb");
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const gltf = await new Promise((res, rej) => new GLTFLoader().parse(ab, "", res, rej));
gltf.scene.updateMatrixWorld(true);

const out = [];
const v = new THREE.Vector3();
gltf.scene.traverse((o) => {
  if (!o.isMesh || !o.geometry.index) return;
  const pos = o.geometry.attributes.position;
  const idx = o.geometry.index.array;
  const parent = new Int32Array(pos.count).map((_, i) => i);
  const find = (x) => { while (parent[x] !== x) x = parent[x] = parent[parent[x]]; return x; };
  for (let i = 0; i < idx.length; i += 3) {
    const a = find(idx[i]);
    parent[find(idx[i + 1])] = a;
    parent[find(idx[i + 2])] = a;
  }
  const acc = new Map();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
    const r = find(i);
    const e = acc.get(r) ?? { x: 0, y: 0, z: 0, n: 0 };
    e.x += v.x; e.y += v.y; e.z += v.z; e.n++;
    acc.set(r, e);
  }
  for (const e of acc.values()) out.push(e.x / e.n, e.y / e.n, e.z / e.n);
});

fs.writeFileSync("public/models/brain-points.bin", Buffer.from(new Float32Array(out).buffer));
console.log(`wrote ${out.length / 3} points`);
