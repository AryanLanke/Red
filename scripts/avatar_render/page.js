// Runs inside headless Edge: loads a VRM, poses it and returns PNG frames plus where the head, hands and
// elbows landed on the picture.
//
// Two ways to pose a bone (see frames.js):
// - `bones`: Euler degrees [x, y, z] in the VRM 1.0 convention (the model faces the camera, its left hand
//   is at +X). For VRM 0.0 models X and Z are flipped here, as three-vrm's own examples do.
// - `aim`: a direction in the picture's space (x to the viewer's right, y up, z toward the viewer). The
//   bone is turned so it points from its joint toward its child along that direction. Aims run after
//   `bones`, parents first, so an arm can be laid on the screen edge without working out angles.
// Faces are VRoid's own face morphs (Fcl_*), which can be mixed freely, plus three-vrm expressions.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const FOV = 20;
const SETS = {
  // Picked up: the whole body, with room for raised arms and kicking legs.
  body: { width: 800, height: 1400 },
  // Peeking over the screen edge: head, shoulders and forearms, closer up.
  peek: { width: 1000, height: 1000 },
  // Peeking around a bottom corner: the same framing (finish.py cuts the side off).
  cornerR: { width: 1000, height: 1000 },
  cornerL: { width: 1000, height: 1000 },
  // Hanging upside down from the top edge (the model is rolled 180 degrees).
  top: { width: 1000, height: 1000 },
  // Hanging from a top corner: the bottom-corner poses turned over (finish.py cuts the side and the top).
  topL: { width: 1000, height: 1000 },
  topR: { width: 1000, height: 1000 },
};

const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 50);
const light = new THREE.DirectionalLight(0xffffff, Math.PI);
light.position.set(0.6, 1.2, 2.0).normalize();
scene.add(light);
scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const lookTarget = new THREE.Object3D();
scene.add(lookTarget);

let vrm = null;
let flip = 1;
let headY = 1.4;
let morphMeshes = [];
const views = {};

const CHILD = {
  leftShoulder: 'leftUpperArm', rightShoulder: 'rightUpperArm',
  leftUpperArm: 'leftLowerArm', rightUpperArm: 'rightLowerArm',
  leftLowerArm: 'leftHand', rightLowerArm: 'rightHand',
  leftHand: 'leftMiddleProximal', rightHand: 'rightMiddleProximal',
  leftUpperLeg: 'leftLowerLeg', rightUpperLeg: 'rightLowerLeg',
  leftLowerLeg: 'leftFoot', rightLowerLeg: 'rightFoot',
  neck: 'head', spine: 'chest', chest: 'neck',
};
const AIM_ORDER = Object.keys(CHILD);
const MARKS = ['head', 'neck', 'hips', 'leftHand', 'rightHand', 'leftLowerArm', 'rightLowerArm'];

// For models without VRoid's face morphs (see renderFrame).
const FCL_TO_EXPRESSION = {
  Fcl_EYE_Close: 'blink', Fcl_EYE_Joy: 'happy', Fcl_MTH_Joy: 'happy', Fcl_BRW_Joy: 'happy',
  Fcl_ALL_Sorrow: 'sad', Fcl_BRW_Sorrow: 'sad', Fcl_MTH_Sorrow: 'sad',
  Fcl_ALL_Angry: 'angry', Fcl_BRW_Angry: 'angry', Fcl_MTH_Angry: 'angry',
  Fcl_ALL_Surprised: 'surprised', Fcl_BRW_Surprised: 'surprised',
  Fcl_BRW_Fun: 'relaxed', Fcl_ALL_Fun: 'relaxed',
  Fcl_MTH_A: 'aa', Fcl_MTH_I: 'ih', Fcl_MTH_U: 'ou', Fcl_MTH_E: 'ee', Fcl_MTH_O: 'oh',
};

function deg(v) { return (v || 0) * Math.PI / 180; }
function node(name) { return vrm.humanoid.getNormalizedBoneNode(name); }

window.loadModel = async (url) => {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm);
  vrm.scene.traverse((o) => {
    o.frustumCulled = false;
    if (o.isMesh && o.morphTargetDictionary && Object.keys(o.morphTargetDictionary).some((k) => k.startsWith('Fcl_'))) {
      morphMeshes.push(o);
    }
  });
  scene.add(vrm.scene);
  flip = vrm.meta && vrm.meta.metaVersion === '0' ? -1 : 1;

  vrm.update(0);
  vrm.scene.updateMatrixWorld(true);
  const p = new THREE.Vector3();
  node('head').getWorldPosition(p);
  headY = p.y;
  const top = headY + 0.2;               // the top of the hair, roughly

  const bodyVisible = top * 1.35;        // room for raised arms when dangling
  views.body = { centerY: top * 0.6, visible: bodyVisible };
  views.peek = { centerY: headY - 0.12, visible: 1.0 };
  views.cornerR = views.peek;
  views.cornerL = views.peek;
  views.top = { centerY: -(headY - 0.12), visible: 1.0 };      // the peek view, turned over
  views.topL = views.top;
  views.topR = views.top;
  vrm.lookAt.target = lookTarget;
  vrm.lookAt.autoUpdate = true;

  return {
    metaVersion: vrm.meta && vrm.meta.metaVersion,
    title: vrm.meta && (vrm.meta.title || vrm.meta.name),
    expressions: vrm.expressionManager.expressions.map((e) => e.expressionName),
    morphs: morphMeshes.length ? Object.keys(morphMeshes[0].morphTargetDictionary).length : 0,
    headY,
  };
};

function useView(set) {
  const size = SETS[set];
  const view = views[set];
  renderer.setSize(size.width, size.height);
  camera.aspect = size.width / size.height;
  camera.position.set(0, view.centerY, (view.visible / 2) / Math.tan(deg(FOV / 2)));
  camera.lookAt(0, view.centerY, 0);
  camera.updateProjectionMatrix();
  return { ...size, pxPerMetre: size.height / view.visible };
}

const _a = new THREE.Vector3();
const _b = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _qp = new THREE.Quaternion();

function aimBone(name, dir) {
  const bone = node(name);
  const child = node(CHILD[name]);
  if (!bone || !child) return;
  bone.quaternion.identity();
  vrm.scene.updateMatrixWorld(true);
  bone.getWorldPosition(_a);
  child.getWorldPosition(_b);
  const current = _b.sub(_a).normalize();
  const wanted = new THREE.Vector3(...dir).normalize();
  _q.setFromUnitVectors(current, wanted);                  // turn in world space
  bone.parent.getWorldQuaternion(_qp);
  bone.quaternion.copy(_qp.clone().invert().multiply(_q).multiply(_qp));
}

function project(name, size) {
  const n = node(name);
  if (!n) return null;
  n.getWorldPosition(_a);
  _a.project(camera);
  return [Math.round((_a.x + 1) / 2 * size.width), Math.round((1 - _a.y) / 2 * size.height)];
}

window.renderFrame = (frame) => {
  const size = useView(frame.set || 'body');
  vrm.scene.rotation.z = frame.flip ? Math.PI : 0;       // upside down (rolled about the camera's axis)
  vrm.scene.updateMatrixWorld(true);
  vrm.humanoid.resetNormalizedPose();
  for (const [bone, angles] of Object.entries(frame.bones || {})) {
    const n = node(bone);
    if (!n) continue;
    const [x, y, z] = angles;
    n.rotation.set(deg(x) * flip, deg(y), deg(z) * flip);
  }
  const aims = frame.aim || {};
  for (const bone of AIM_ORDER) if (aims[bone]) aimBone(bone, aims[bone]);

  const em = vrm.expressionManager;
  for (const e of em.expressions) em.setValue(e.expressionName, 0);
  for (const [name, value] of Object.entries(frame.expr || {})) em.setValue(name, value);

  // Eyes: at the viewer unless the frame says otherwise (x, y in metres from the camera).
  const look = frame.look || [0, 0];
  lookTarget.position.set(camera.position.x + look[0], camera.position.y + look[1], camera.position.z);

  // Let hair and clothes settle under gravity in this pose.
  if (vrm.springBoneManager) vrm.springBoneManager.reset();
  for (let i = 0; i < 150; i++) vrm.update(1 / 60);

  // Models not made in VRoid have no Fcl_* morphs: their faces come from the standard VRM expressions.
  if (!morphMeshes.length) {
    const wanted = {};
    for (const [name, value] of Object.entries(frame.face || {})) {
      const expr = FCL_TO_EXPRESSION[name];
      if (expr) wanted[expr] = Math.max(wanted[expr] || 0, value);
    }
    for (const [name, value] of Object.entries(wanted)) {
      if (em.getExpression(name)) em.setValue(name, value);
      else if (name === 'surprised' && em.getExpression('Surprised')) em.setValue('Surprised', value);
    }
    vrm.update(0);
  }

  // Face morphs go on after the expression manager has written its own weights. Every morph is cleared
  // first: the manager only resets the morphs its presets use, so others (Fcl_EYE_Joy...) would carry
  // over from the frame before and close the eyes of the next one.
  for (const mesh of morphMeshes) {
    mesh.morphTargetInfluences.fill(0);
    for (const [name, value] of Object.entries(frame.face || {})) {
      const i = mesh.morphTargetDictionary[name];
      if (i !== undefined) mesh.morphTargetInfluences[i] = value;
    }
  }

  vrm.scene.updateMatrixWorld(true);
  renderer.render(scene, camera);
  const marks = {};
  for (const m of MARKS) marks[m] = project(m, size);
  return { png: renderer.domElement.toDataURL('image/png'), marks, size };
};

window.rendererReady = true;
