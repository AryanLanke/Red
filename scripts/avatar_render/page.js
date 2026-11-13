// Runs inside headless Edge: loads a VRM, poses it and returns PNG frames.
// Bone angles in frames.js are degrees in the VRM 1.0 convention (the model faces the camera, its left
// hand is at +X). For VRM 0.0 models the X and Z angles are flipped here, as three-vrm's own examples do.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const W = 800;
const H = 1400;
const FOV = 20;

const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(FOV, W / H, 0.1, 50);
const light = new THREE.DirectionalLight(0xffffff, Math.PI);
light.position.set(0.6, 1.2, 2.0).normalize();
scene.add(light);
scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const lookTarget = new THREE.Object3D();
scene.add(lookTarget);

let vrm = null;
let flip = 1;
let headY = 1.4;

function deg(v) { return (v || 0) * Math.PI / 180; }

window.loadModel = async (url) => {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm);
  vrm.scene.traverse((o) => { o.frustumCulled = false; });
  scene.add(vrm.scene);
  flip = vrm.meta && vrm.meta.metaVersion === '0' ? -1 : 1;

  vrm.update(0);
  const head = vrm.humanoid.getNormalizedBoneNode('head');
  const p = new THREE.Vector3();
  head.getWorldPosition(p);
  headY = p.y;
  const top = headY + 0.2;               // the top of the hair, roughly
  const visible = top * 1.35;            // room for raised arms and the drag pose
  const centerY = top * 0.6;
  const dist = (visible / 2) / Math.tan(deg(FOV / 2));
  camera.position.set(0, centerY, dist);
  camera.lookAt(0, centerY, 0);
  vrm.lookAt.target = lookTarget;
  vrm.lookAt.autoUpdate = true;

  return {
    metaVersion: vrm.meta && vrm.meta.metaVersion,
    title: vrm.meta && (vrm.meta.title || vrm.meta.name),
    expressions: vrm.expressionManager.expressions.map((e) => e.expressionName),
    headY,
  };
};

window.renderFrame = (frame) => {
  vrm.humanoid.resetNormalizedPose();
  for (const [bone, angles] of Object.entries(frame.bones || {})) {
    const node = vrm.humanoid.getNormalizedBoneNode(bone);
    if (!node) continue;
    const [x, y, z] = angles;
    node.rotation.set(deg(x) * flip, deg(y), deg(z) * flip);
  }
  const hips = vrm.humanoid.getNormalizedBoneNode('hips');
  if (frame.lift) hips.position.y += frame.lift;

  const em = vrm.expressionManager;
  for (const e of em.expressions) em.setValue(e.expressionName, 0);
  for (const [name, value] of Object.entries(frame.face || {})) em.setValue(name, value);

  // Eyes: at the viewer unless the frame says otherwise (x, y in metres from the camera's aim point).
  const look = frame.look || [0, 0];
  lookTarget.position.set(camera.position.x + look[0], camera.position.y + look[1], camera.position.z);

  // Let hair and clothes settle under gravity in this pose.
  if (vrm.springBoneManager) vrm.springBoneManager.reset();
  for (let i = 0; i < 150; i++) vrm.update(1 / 60);

  renderer.render(scene, camera);
  return renderer.domElement.toDataURL('image/png');
};

window.rendererReady = true;
