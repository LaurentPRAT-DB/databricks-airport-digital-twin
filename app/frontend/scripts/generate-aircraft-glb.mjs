/**
 * Generate Aircraft GLB Models
 *
 * Creates GLB files using @gltf-transform/core for Node.js compatibility.
 * Run with: node scripts/generate-aircraft-glb.mjs
 */

import { Document, NodeIO } from '@gltf-transform/core';
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = join(__dirname, '../public/models/aircraft');

// Ensure output directory exists
if (!existsSync(OUTPUT_DIR)) {
  mkdirSync(OUTPUT_DIR, { recursive: true });
}

/**
 * Create a mesh primitive with positions, normals, and indices
 */
function createCylinderVertices(radiusTop, radiusBottom, height, segments) {
  const positions = [];
  const normals = [];
  const indices = [];
  const halfHeight = height / 2;

  // Generate vertices for top and bottom caps
  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI * 2;
    const cosTheta = Math.cos(theta);
    const sinTheta = Math.sin(theta);

    // Bottom vertex
    positions.push(
      radiusBottom * cosTheta,
      -halfHeight,
      radiusBottom * sinTheta
    );
    normals.push(cosTheta, 0, sinTheta);

    // Top vertex
    positions.push(
      radiusTop * cosTheta,
      halfHeight,
      radiusTop * sinTheta
    );
    normals.push(cosTheta, 0, sinTheta);
  }

  // Generate indices for the side faces
  for (let i = 0; i < segments; i++) {
    const a = i * 2;
    const b = i * 2 + 1;
    const c = i * 2 + 2;
    const d = i * 2 + 3;

    indices.push(a, b, d);
    indices.push(a, d, c);
  }

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

/**
 * Create a box with positions, normals, and indices
 */
function createBoxVertices(width, height, depth) {
  const hw = width / 2;
  const hh = height / 2;
  const hd = depth / 2;

  // prettier-ignore
  const positions = new Float32Array([
    // Front face
    -hw, -hh,  hd,   hw, -hh,  hd,   hw,  hh,  hd,  -hw,  hh,  hd,
    // Back face
     hw, -hh, -hd,  -hw, -hh, -hd,  -hw,  hh, -hd,   hw,  hh, -hd,
    // Top face
    -hw,  hh,  hd,   hw,  hh,  hd,   hw,  hh, -hd,  -hw,  hh, -hd,
    // Bottom face
    -hw, -hh, -hd,   hw, -hh, -hd,   hw, -hh,  hd,  -hw, -hh,  hd,
    // Right face
     hw, -hh,  hd,   hw, -hh, -hd,   hw,  hh, -hd,   hw,  hh,  hd,
    // Left face
    -hw, -hh, -hd,  -hw, -hh,  hd,  -hw,  hh,  hd,  -hw,  hh, -hd,
  ]);

  // prettier-ignore
  const normals = new Float32Array([
    // Front
    0, 0, 1,  0, 0, 1,  0, 0, 1,  0, 0, 1,
    // Back
    0, 0, -1,  0, 0, -1,  0, 0, -1,  0, 0, -1,
    // Top
    0, 1, 0,  0, 1, 0,  0, 1, 0,  0, 1, 0,
    // Bottom
    0, -1, 0,  0, -1, 0,  0, -1, 0,  0, -1, 0,
    // Right
    1, 0, 0,  1, 0, 0,  1, 0, 0,  1, 0, 0,
    // Left
    -1, 0, 0,  -1, 0, 0,  -1, 0, 0,  -1, 0, 0,
  ]);

  // prettier-ignore
  const indices = new Uint16Array([
    0, 1, 2, 0, 2, 3,       // Front
    4, 5, 6, 4, 6, 7,       // Back
    8, 9, 10, 8, 10, 11,    // Top
    12, 13, 14, 12, 14, 15, // Bottom
    16, 17, 18, 16, 18, 19, // Right
    20, 21, 22, 20, 22, 23, // Left
  ]);

  return { positions, normals, indices };
}

/**
 * Create a cone with positions, normals, and indices
 */
function createConeVertices(radius, height, segments) {
  const positions = [];
  const normals = [];
  const indices = [];
  const halfHeight = height / 2;

  // Apex
  positions.push(0, halfHeight, 0);
  normals.push(0, 1, 0);

  // Base vertices
  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI * 2;
    const cosTheta = Math.cos(theta);
    const sinTheta = Math.sin(theta);

    positions.push(radius * cosTheta, -halfHeight, radius * sinTheta);

    // Normal pointing outward and slightly up
    const ny = radius / height;
    const len = Math.sqrt(cosTheta * cosTheta + ny * ny + sinTheta * sinTheta);
    normals.push(cosTheta / len, ny / len, sinTheta / len);
  }

  // Side faces
  for (let i = 1; i <= segments; i++) {
    indices.push(0, i, i + 1);
  }

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

/**
 * Add a mesh to the document
 */
function addMesh(doc, scene, name, vertices, material, buffer, translation = [0, 0, 0], rotation = [0, 0, 0, 1]) {
  const mesh = doc.createMesh(name);
  const primitive = doc.createPrimitive();

  // Create accessors with buffer
  const positionAccessor = doc.createAccessor()
    .setType('VEC3')
    .setArray(vertices.positions)
    .setBuffer(buffer);

  const normalAccessor = doc.createAccessor()
    .setType('VEC3')
    .setArray(vertices.normals)
    .setBuffer(buffer);

  const indexAccessor = doc.createAccessor()
    .setType('SCALAR')
    .setArray(vertices.indices)
    .setBuffer(buffer);

  primitive
    .setAttribute('POSITION', positionAccessor)
    .setAttribute('NORMAL', normalAccessor)
    .setIndices(indexAccessor)
    .setMaterial(material);

  mesh.addPrimitive(primitive);

  // Create node
  const node = doc.createNode(name)
    .setMesh(mesh)
    .setTranslation(translation)
    .setRotation(rotation);

  scene.addChild(node);

  return node;
}

/**
 * Create Boeing 737 model
 */
function createBoeing737(doc) {
  // Create a buffer to store all binary data
  const buffer = doc.createBuffer('buffer');

  const scene = doc.createScene('Boeing737');

  // Materials
  const bodyMat = doc.createMaterial('fuselage')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const tailMat = doc.createMaterial('tail')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const engineMat = doc.createMaterial('engine')
    .setBaseColorFactor([0.33, 0.33, 0.33, 1])
    .setMetallicFactor(0.6)
    .setRoughnessFactor(0.4);

  const windowMat = doc.createMaterial('window')
    .setBaseColorFactor([0.07, 0.07, 0.2, 1])
    .setMetallicFactor(0.8)
    .setRoughnessFactor(0.2);

  // Quaternion for 90 degree rotation around X axis
  const rotX90 = [0.7071068, 0, 0, 0.7071068];
  const rotXNeg90 = [-0.7071068, 0, 0, 0.7071068];

  // Fuselage
  addMesh(doc, scene, 'fuselage_body',
    createCylinderVertices(2, 2, 20, 16), bodyMat, buffer, [0, 0, 0], rotX90);

  // Nose cone
  addMesh(doc, scene, 'fuselage_nose',
    createConeVertices(2, 5, 16), bodyMat, buffer, [0, 0, -12.5], rotX90);

  // Tail cone
  addMesh(doc, scene, 'fuselage_tail',
    createConeVertices(2, 6, 16), bodyMat, buffer, [0, 0.5, 12], rotXNeg90);

  // Main wings
  addMesh(doc, scene, 'wing_main',
    createBoxVertices(28, 0.5, 5), bodyMat, buffer, [0, -0.5, 1]);

  // Winglets
  addMesh(doc, scene, 'winglet_right',
    createBoxVertices(0.3, 3, 2), bodyMat, buffer, [14.5, 1, 1]);
  addMesh(doc, scene, 'winglet_left',
    createBoxVertices(0.3, 3, 2), bodyMat, buffer, [-14.5, 1, 1]);

  // Horizontal stabilizer
  addMesh(doc, scene, 'stabilizer_horizontal',
    createBoxVertices(12, 0.3, 4), bodyMat, buffer, [0, 0.5, 10]);

  // Vertical stabilizer (tail fin)
  addMesh(doc, scene, 'tail_fin',
    createBoxVertices(0.4, 8, 5), tailMat, buffer, [0, 5, 9]);

  // Engines
  addMesh(doc, scene, 'engine_left',
    createCylinderVertices(1.3, 1.6, 5, 12), engineMat, buffer, [-6, -2, 0], rotX90);
  addMesh(doc, scene, 'engine_right',
    createCylinderVertices(1.3, 1.6, 5, 12), engineMat, buffer, [6, -2, 0], rotX90);

  // Cockpit window
  addMesh(doc, scene, 'cockpit_window',
    createBoxVertices(2.5, 0.1, 1.5), windowMat, buffer, [0, 1.2, -10]);

  return doc;
}

/**
 * Create Airbus A320 model
 */
function createAirbusA320(doc) {
  const buffer = doc.createBuffer('buffer');
  const scene = doc.createScene('AirbusA320');

  // Materials
  const bodyMat = doc.createMaterial('fuselage')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const tailMat = doc.createMaterial('tail')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const engineMat = doc.createMaterial('engine')
    .setBaseColorFactor([0.33, 0.33, 0.33, 1])
    .setMetallicFactor(0.6)
    .setRoughnessFactor(0.4);

  const windowMat = doc.createMaterial('window')
    .setBaseColorFactor([0.07, 0.07, 0.2, 1])
    .setMetallicFactor(0.8)
    .setRoughnessFactor(0.2);

  const rotX90 = [0.7071068, 0, 0, 0.7071068];
  const rotXNeg90 = [-0.7071068, 0, 0, 0.7071068];

  // Fuselage - slightly wider
  addMesh(doc, scene, 'fuselage_body',
    createCylinderVertices(2.1, 2.1, 19, 16), bodyMat, buffer, [0, 0, 0], rotX90);

  // Nose
  addMesh(doc, scene, 'fuselage_nose',
    createConeVertices(2.1, 5, 16), bodyMat, buffer, [0, 0, -12], rotX90);

  // Tail cone
  addMesh(doc, scene, 'fuselage_tail',
    createConeVertices(2.1, 7, 16), bodyMat, buffer, [0, 0.3, 12.5], rotXNeg90);

  // Main wings
  addMesh(doc, scene, 'wing_main',
    createBoxVertices(28, 0.6, 5), bodyMat, buffer, [0, -0.5, 0]);

  // Sharklets
  addMesh(doc, scene, 'sharklet_right',
    createBoxVertices(0.3, 3.5, 2.5), bodyMat, buffer, [14, 1.2, 0.5]);
  addMesh(doc, scene, 'sharklet_left',
    createBoxVertices(0.3, 3.5, 2.5), bodyMat, buffer, [-14, 1.2, 0.5]);

  // Horizontal stabilizer
  addMesh(doc, scene, 'stabilizer_horizontal',
    createBoxVertices(11, 0.3, 3.5), bodyMat, buffer, [0, 0.8, 12]);

  // Vertical stabilizer (taller for Airbus)
  addMesh(doc, scene, 'tail_fin',
    createBoxVertices(0.4, 9, 6), tailMat, buffer, [0, 5, 11]);

  // Engines (larger CFM LEAP style)
  addMesh(doc, scene, 'engine_left',
    createCylinderVertices(1.5, 1.7, 5, 12), engineMat, buffer, [-6.5, -2.2, -0.5], rotX90);
  addMesh(doc, scene, 'engine_right',
    createCylinderVertices(1.5, 1.7, 5, 12), engineMat, buffer, [6.5, -2.2, -0.5], rotX90);

  // Cockpit window
  addMesh(doc, scene, 'cockpit_window',
    createBoxVertices(2.8, 0.1, 1.4), windowMat, buffer, [0, 1.3, -10]);

  return doc;
}

/**
 * Create Generic Jet model
 */
function createGenericJet(doc) {
  const buffer = doc.createBuffer('buffer');
  const scene = doc.createScene('GenericJet');

  // Materials
  const bodyMat = doc.createMaterial('fuselage')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const tailMat = doc.createMaterial('tail')
    .setBaseColorFactor([1, 1, 1, 1])
    .setMetallicFactor(0.3)
    .setRoughnessFactor(0.7);

  const engineMat = doc.createMaterial('engine')
    .setBaseColorFactor([0.33, 0.33, 0.33, 1])
    .setMetallicFactor(0.6)
    .setRoughnessFactor(0.4);

  const windowMat = doc.createMaterial('window')
    .setBaseColorFactor([0.07, 0.07, 0.2, 1])
    .setMetallicFactor(0.8)
    .setRoughnessFactor(0.2);

  const rotX90 = [0.7071068, 0, 0, 0.7071068];
  const rotXNeg90 = [-0.7071068, 0, 0, 0.7071068];

  // Fuselage
  addMesh(doc, scene, 'fuselage_body',
    createCylinderVertices(2, 2, 18, 12), bodyMat, buffer, [0, 0, 0], rotX90);

  // Nose
  addMesh(doc, scene, 'fuselage_nose',
    createConeVertices(2, 4, 12), bodyMat, buffer, [0, 0, -11], rotX90);

  // Tail cone
  addMesh(doc, scene, 'fuselage_tail',
    createConeVertices(2, 5, 12), bodyMat, buffer, [0, 0.5, 11.5], rotXNeg90);

  // Wings
  addMesh(doc, scene, 'wing_main',
    createBoxVertices(28, 0.5, 5), bodyMat, buffer, [0, -0.5, 1]);

  // Winglets
  addMesh(doc, scene, 'winglet_right',
    createBoxVertices(0.3, 3, 2), bodyMat, buffer, [14.5, 1, 1]);
  addMesh(doc, scene, 'winglet_left',
    createBoxVertices(0.3, 3, 2), bodyMat, buffer, [-14.5, 1, 1]);

  // Horizontal stabilizer
  addMesh(doc, scene, 'stabilizer_horizontal',
    createBoxVertices(10, 0.3, 3), bodyMat, buffer, [0, 0.5, 10]);

  // Vertical stabilizer
  addMesh(doc, scene, 'tail_fin',
    createBoxVertices(0.3, 7, 4), tailMat, buffer, [0, 4, 9]);

  // Engines
  addMesh(doc, scene, 'engine_left',
    createCylinderVertices(1.2, 1.5, 4, 8), engineMat, buffer, [-6, -2, 0], rotX90);
  addMesh(doc, scene, 'engine_right',
    createCylinderVertices(1.2, 1.5, 4, 8), engineMat, buffer, [6, -2, 0], rotX90);

  // Cockpit window
  addMesh(doc, scene, 'cockpit_window',
    createBoxVertices(2.5, 0.1, 1.5), windowMat, buffer, [0, 1, -8]);

  return doc;
}

/**
 * Main function
 */
async function main() {
  console.log('Generating aircraft GLB models...\n');

  const io = new NodeIO();

  try {
    // Boeing 737
    const doc737 = new Document();
    createBoeing737(doc737);
    const glb737 = await io.writeBinary(doc737);
    writeFileSync(join(OUTPUT_DIR, 'boeing-737.glb'), glb737);
    console.log('Created: boeing-737.glb');

    // Airbus A320
    const docA320 = new Document();
    createAirbusA320(docA320);
    const glbA320 = await io.writeBinary(docA320);
    writeFileSync(join(OUTPUT_DIR, 'airbus-a320.glb'), glbA320);
    console.log('Created: airbus-a320.glb');

    // Generic Jet
    const docGeneric = new Document();
    createGenericJet(docGeneric);
    const glbGeneric = await io.writeBinary(docGeneric);
    writeFileSync(join(OUTPUT_DIR, 'generic-jet.glb'), glbGeneric);
    console.log('Created: generic-jet.glb');

    console.log(`\nAll models generated in: ${OUTPUT_DIR}`);
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  }
}

main();
