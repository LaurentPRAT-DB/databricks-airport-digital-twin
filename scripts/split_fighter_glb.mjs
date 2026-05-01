#!/usr/bin/env node
/**
 * Split the multi-fighter GLB into individual per-fighter GLBs.
 *
 * Input:  public/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb
 * Output: public/models/aircraft/fighter-{f14,f15,f16,f18,f22,f35}.glb
 *
 * Each output contains only the nodes/meshes/accessors/bufferViews for one fighter,
 * with a minimal buffer holding just the needed geometry.
 */

import fs from 'fs';
import path from 'path';

const INPUT = 'app/frontend/public/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb';
const OUTPUT_DIR = 'app/frontend/public/models/aircraft';

const FIGHTERS = ['F-14', 'F-15', 'F-16', 'F-18', 'F-22', 'F-35'];

// Read GLB
const glbBuf = fs.readFileSync(INPUT);
const magic = glbBuf.readUInt32LE(0);
if (magic !== 0x46546C67) throw new Error('Not a GLB file');

const jsonChunkLen = glbBuf.readUInt32LE(12);
const jsonStr = glbBuf.slice(20, 20 + jsonChunkLen).toString('utf8');
const gltf = JSON.parse(jsonStr);

// Binary chunk starts after JSON chunk (header=12, jsonChunkHeader=8, jsonData, binChunkHeader=8)
const binChunkOffset = 20 + jsonChunkLen;
const binChunkLen = glbBuf.readUInt32LE(binChunkOffset);
const binData = glbBuf.slice(binChunkOffset + 8, binChunkOffset + 8 + binChunkLen);

// Find GLTF_SceneRootNode (node with >5 children)
const sceneRootIdx = gltf.nodes.findIndex(n => n.children && n.children.length > 5);
const sceneRoot = gltf.nodes[sceneRootIdx];

function getDescendants(nodeIdx) {
  const result = [nodeIdx];
  const stack = [nodeIdx];
  while (stack.length) {
    const idx = stack.pop();
    const node = gltf.nodes[idx];
    if (node.children) {
      for (const c of node.children) {
        result.push(c);
        stack.push(c);
      }
    }
  }
  return result;
}

for (const prefix of FIGHTERS) {
  // Find top-level children of sceneRoot matching this prefix
  const topChildIndices = sceneRoot.children.filter(
    ci => gltf.nodes[ci].name && gltf.nodes[ci].name.startsWith(prefix)
  );

  // Collect all descendant node indices
  const allNodeIndices = new Set();
  for (const ci of topChildIndices) {
    for (const di of getDescendants(ci)) allNodeIndices.add(di);
  }

  // Collect mesh indices
  const meshIndices = new Set();
  for (const ni of allNodeIndices) {
    if (gltf.nodes[ni].mesh !== undefined) meshIndices.add(gltf.nodes[ni].mesh);
  }

  // Collect accessor indices from meshes
  const accessorIndices = new Set();
  for (const mi of meshIndices) {
    const mesh = gltf.meshes[mi];
    for (const prim of mesh.primitives) {
      if (prim.indices !== undefined) accessorIndices.add(prim.indices);
      for (const ai of Object.values(prim.attributes)) accessorIndices.add(ai);
    }
  }

  // Collect bufferView indices from accessors
  const bvIndices = new Set();
  for (const ai of accessorIndices) {
    bvIndices.add(gltf.accessors[ai].bufferView);
  }

  // Build new buffer: pack only the byte ranges we need
  // Map old bufferView -> { newBvIndex, newByteOffset }
  const bvMap = new Map();
  const chunks = [];
  let newOffset = 0;
  let newBvIdx = 0;

  // For each accessor, we need its byte range within the bufferView
  // Since accessors can reference subranges of a bufferView, we need to
  // extract per-accessor ranges
  const accMap = new Map(); // old accessor idx -> new accessor idx
  const newAccessors = [];
  const newBufferViews = [];
  const newMeshes = [];
  const meshMap = new Map(); // old mesh idx -> new mesh idx

  // Strategy: for each accessor, extract its exact data from the source buffer
  let newAccIdx = 0;
  for (const ai of [...accessorIndices].sort((a, b) => a - b)) {
    const acc = gltf.accessors[ai];
    const bv = gltf.bufferViews[acc.bufferView];

    // Component sizes
    const compSizes = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 };
    const typeCounts = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT2: 4, MAT3: 9, MAT4: 16 };
    const compSize = compSizes[acc.componentType] || 4;
    const typeCount = typeCounts[acc.type] || 1;
    const elementSize = compSize * typeCount;
    const stride = bv.byteStride || elementSize;

    // Source byte range in the binary buffer
    const srcStart = (bv.byteOffset || 0) + (acc.byteOffset || 0);
    const dataLen = acc.count * stride;

    // Copy this data
    const chunk = Buffer.alloc(dataLen);
    binData.copy(chunk, 0, srcStart, srcStart + dataLen);

    // Align to 4 bytes
    const padding = (4 - (dataLen % 4)) % 4;
    const paddedChunk = padding > 0 ? Buffer.concat([chunk, Buffer.alloc(padding)]) : chunk;

    // New bufferView for this accessor
    const newBv = {
      buffer: 0,
      byteOffset: newOffset,
      byteLength: dataLen,
    };
    if (bv.byteStride) newBv.byteStride = bv.byteStride;
    if (bv.target) newBv.target = bv.target;

    const bvIdx = newBufferViews.length;
    newBufferViews.push(newBv);
    chunks.push(paddedChunk);
    newOffset += paddedChunk.length;

    // New accessor
    const newAcc = {
      bufferView: bvIdx,
      byteOffset: 0,
      componentType: acc.componentType,
      count: acc.count,
      type: acc.type,
    };
    if (acc.min) newAcc.min = acc.min;
    if (acc.max) newAcc.max = acc.max;
    if (acc.normalized) newAcc.normalized = acc.normalized;

    newAccessors.push(newAcc);
    accMap.set(ai, newAccIdx);
    newAccIdx++;
  }

  // Build new meshes
  for (const mi of [...meshIndices].sort((a, b) => a - b)) {
    const mesh = gltf.meshes[mi];
    const newPrims = mesh.primitives.map(prim => {
      const newPrim = {};
      if (prim.indices !== undefined) newPrim.indices = accMap.get(prim.indices);
      newPrim.attributes = {};
      for (const [attr, ai] of Object.entries(prim.attributes)) {
        newPrim.attributes[attr] = accMap.get(ai);
      }
      if (prim.material !== undefined) newPrim.material = 0; // single material
      if (prim.mode !== undefined) newPrim.mode = prim.mode;
      return newPrim;
    });
    meshMap.set(mi, newMeshes.length);
    newMeshes.push({ primitives: newPrims, name: mesh.name });
  }

  // Build new node tree: scene -> group -> [fighter parts]
  const newNodes = [];
  const childNodeIndices = [];

  for (const ci of topChildIndices) {
    const descendants = getDescendants(ci);
    const localNodeMap = new Map(); // old node idx -> new node idx

    for (const di of descendants) {
      const oldNode = gltf.nodes[di];
      const newNode = { name: oldNode.name };
      if (oldNode.mesh !== undefined) newNode.mesh = meshMap.get(oldNode.mesh);
      if (oldNode.translation) newNode.translation = oldNode.translation;
      if (oldNode.rotation) newNode.rotation = oldNode.rotation;
      if (oldNode.scale) newNode.scale = oldNode.scale;
      if (oldNode.matrix) newNode.matrix = oldNode.matrix;
      localNodeMap.set(di, newNodes.length);
      newNodes.push(newNode);
    }

    // Wire up children
    for (const di of descendants) {
      const oldNode = gltf.nodes[di];
      if (oldNode.children && oldNode.children.length) {
        const newIdx = localNodeMap.get(di);
        newNodes[newIdx].children = oldNode.children
          .filter(c => localNodeMap.has(c))
          .map(c => localNodeMap.get(c));
      }
    }

    childNodeIndices.push(localNodeMap.get(ci));
  }

  // Scene root node
  const rootIdx = newNodes.length;
  newNodes.push({ name: prefix + '_root', children: childNodeIndices });

  // Combine buffer
  const newBuffer = Buffer.concat(chunks);

  // Build minimal GLTF
  const newGltf = {
    asset: { version: '2.0', generator: 'split_fighter_glb' },
    scene: 0,
    scenes: [{ nodes: [rootIdx] }],
    nodes: newNodes,
    meshes: newMeshes,
    accessors: newAccessors,
    bufferViews: newBufferViews,
    buffers: [{ byteLength: newBuffer.length }],
    materials: gltf.materials ? [gltf.materials[0]] : [],
  };

  // Write GLB
  const jsonBuf = Buffer.from(JSON.stringify(newGltf));
  // Pad JSON to 4-byte alignment
  const jsonPad = (4 - (jsonBuf.length % 4)) % 4;
  const paddedJson = jsonPad > 0 ? Buffer.concat([jsonBuf, Buffer.alloc(jsonPad, 0x20)]) : jsonBuf;
  // Pad binary to 4-byte alignment
  const binPad = (4 - (newBuffer.length % 4)) % 4;
  const paddedBin = binPad > 0 ? Buffer.concat([newBuffer, Buffer.alloc(binPad)]) : newBuffer;

  const totalLen = 12 + 8 + paddedJson.length + 8 + paddedBin.length;
  const header = Buffer.alloc(12);
  header.writeUInt32LE(0x46546C67, 0); // magic
  header.writeUInt32LE(2, 4);          // version
  header.writeUInt32LE(totalLen, 8);   // total length

  const jsonChunkHeader = Buffer.alloc(8);
  jsonChunkHeader.writeUInt32LE(paddedJson.length, 0);
  jsonChunkHeader.writeUInt32LE(0x4E4F534A, 4); // JSON

  const binChunkHeader = Buffer.alloc(8);
  binChunkHeader.writeUInt32LE(paddedBin.length, 0);
  binChunkHeader.writeUInt32LE(0x004E4942, 4); // BIN

  const outBuf = Buffer.concat([header, jsonChunkHeader, paddedJson, binChunkHeader, paddedBin]);
  const slug = prefix.toLowerCase().replace('-', '');
  const outPath = path.join(OUTPUT_DIR, `fighter-${slug}.glb`);
  fs.writeFileSync(outPath, outBuf);

  console.log(`${prefix} -> ${outPath} (${(outBuf.length/1024).toFixed(0)} KB)`);
}

console.log('\nDone! Individual fighter GLBs created.');
