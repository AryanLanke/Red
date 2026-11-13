// The sprite frames Red's companion window uses. See page.js for how `bones`, `aim`, `face` and `look` work.
//
// Two sets:
// - peek: the companion leans on the bottom edge of the screen (or a corner) with its forearms on the
//   edge, so only the upper body shows. finish.py cuts these frames at the edge line.
// - body: the whole body, used while you pick it up and carry it to another spot.
// Breathing and swaying are not frames: the window moves the picture slightly.

// --- Faces: VRoid face morphs, mixed past the stock presets so feelings read at a glance ----------------
const F = {
  neutral: {},
  blink: { Fcl_EYE_Close: 1 },
  happy: { Fcl_BRW_Joy: 1, Fcl_EYE_Joy: 1, Fcl_MTH_Joy: 1 },
  happyOpen: { Fcl_BRW_Joy: 1, Fcl_EYE_Joy: 1, Fcl_MTH_Joy: 0.5, Fcl_MTH_A: 0.6 },
  laugh: { Fcl_BRW_Fun: 1, Fcl_EYE_Joy: 1, Fcl_MTH_A: 1, Fcl_MTH_Large: 0.6 },
  // Sad, angry and surprised start from the model's own whole-face morph (Fcl_ALL_*, the balance its
  // maker chose), then push the brows and mouth further.
  sad: { Fcl_ALL_Sorrow: 1, Fcl_BRW_Sorrow: 0.5, Fcl_MTH_Down: 0.5 },
  sadTalk: { Fcl_ALL_Sorrow: 0.9, Fcl_BRW_Sorrow: 0.4, Fcl_MTH_U: 0.45 },
  cry: { Fcl_BRW_Sorrow: 1, Fcl_EYE_Close: 0.8, Fcl_MTH_Sorrow: 1, Fcl_MTH_A: 0.35 },
  angry: { Fcl_ALL_Angry: 1, Fcl_BRW_Angry: 0.5, Fcl_MTH_Down: 0.3 },
  angryTalk: { Fcl_ALL_Angry: 0.8, Fcl_BRW_Angry: 0.5, Fcl_MTH_E: 0.7 },
  surprised: { Fcl_ALL_Surprised: 1, Fcl_BRW_Surprised: 0.3, Fcl_MTH_O: 0.4 },
  shock: { Fcl_ALL_Surprised: 1, Fcl_BRW_Surprised: 0.4, Fcl_MTH_A: 0.7 },
  shy: { Fcl_BRW_Sorrow: 0.6, Fcl_EYE_Joy: 0.5, Fcl_MTH_Small: 1, Fcl_MTH_Joy: 0.3 },
  curious: { Fcl_BRW_Surprised: 0.5, Fcl_EYE_Spread: 0.3, Fcl_MTH_Small: 0.4 },
  think: { Fcl_BRW_Angry: 0.35, Fcl_BRW_Sorrow: 0.35, Fcl_EYE_Natural: 0.3, Fcl_MTH_Small: 0.7, Fcl_MTH_Down: 0.3 },
  sleep: { Fcl_EYE_Close: 1, Fcl_BRW_Fun: 0.3, Fcl_MTH_O: 0.25 },
  notice: { Fcl_BRW_Surprised: 0.8, Fcl_EYE_Surprised: 0.6, Fcl_MTH_Joy: 0.5 },
};
const talk = (face, a) => ({ ...face, Fcl_MTH_A: a });
const blinked = (face) => ({ ...face, Fcl_EYE_Close: 1, Fcl_EYE_Joy: 0, Fcl_EYE_Surprised: 0, Fcl_EYE_Spread: 0 });

// --- Peeking over the edge -------------------------------------------------------------------------
// Forearms lie on the edge and meet in front of the chest. Aims are directions in the picture.
const onEdge = {
  leftUpperArm: [0.3, -0.62, 0.72],
  leftLowerArm: [-0.78, -0.04, 0.62],
  leftHand: [-0.92, -0.12, 0.36],
  rightUpperArm: [-0.3, -0.62, 0.72],
  rightLowerArm: [0.78, -0.04, 0.62],
  rightHand: [0.92, -0.12, 0.36],
};
const leanIn = { spine: [6, 0, 0], chest: [4, 0, 0] };

function peek(name, { face = F.neutral, bones = {}, aim = {}, look, state = null, emotion = null } = {}) {
  return {
    name: `peek_${name}`, set: 'peek', state, emotion, face, look,
    bones: { ...leanIn, head: [0, 0, 4], ...bones },
    aim: { ...onEdge, ...aim },
  };
}

// Right hand up beside the face, the hand tipped by `tip` (waving).
const waveArm = (tip) => ({
  rightUpperArm: [-0.78, -0.15, 0.6],
  rightLowerArm: [-0.15, 0.97, 0.2],
  rightHand: [tip, 0.95, 0.15],
});
// Both hands up by the cheeks (surprise) or over the mouth (shy, laughing).
const handsUp = {
  leftUpperArm: [0.5, -0.7, 0.5], leftLowerArm: [0.15, 0.95, 0.25], leftHand: [-0.1, 0.98, 0.15],
  rightUpperArm: [-0.5, -0.7, 0.5], rightLowerArm: [-0.15, 0.95, 0.25], rightHand: [0.1, 0.98, 0.15],
};
const handsToMouth = {
  leftUpperArm: [0.22, -0.8, 0.55], leftLowerArm: [-0.42, 0.82, 0.38], leftHand: [-0.5, 0.82, 0.1],
  rightUpperArm: [-0.22, -0.8, 0.55], rightLowerArm: [0.42, 0.82, 0.38], rightHand: [0.5, 0.82, 0.1],
};
// Chin in the right hand, elbow on the edge.
const chinOnHand = {
  rightUpperArm: [-0.15, -0.8, 0.58],
  rightLowerArm: [0.4, 0.78, 0.48],
  rightHand: [0.35, 0.5, -0.8],
};
// Fists pressed on the edge (angry).
const fists = {
  leftUpperArm: [0.42, -0.7, 0.58], leftLowerArm: [-0.25, -0.2, 0.95],
  rightUpperArm: [-0.42, -0.7, 0.58], rightLowerArm: [0.25, -0.2, 0.95],
};

const PEEK = [
  peek('idle', { state: 'idle' }),
  peek('idle_blink', { state: 'idle', face: F.blink }),
  peek('talk_1', { state: 'speaking', face: talk(F.neutral, 0.4) }),
  peek('talk_2', { state: 'speaking', face: talk(F.neutral, 0.85) }),
  peek('talk_3', { state: 'speaking', face: { Fcl_MTH_O: 0.8 } }),
  peek('notice', { state: 'notice', face: F.notice, bones: { spine: [-2, 0, 0], head: [-6, 0, 0] } }),
  peek('listen', { state: 'listening', face: F.curious, bones: { spine: [12, 0, 0], chest: [6, 0, 0], head: [4, 0, 14] } }),
  peek('listen_blink', { state: 'listening', face: blinked(F.curious), bones: { spine: [12, 0, 0], chest: [6, 0, 0], head: [4, 0, 14] } }),
  peek('think', { state: 'thinking', face: F.think, aim: chinOnHand, bones: { head: [2, 0, -10] }, look: [0.6, 0.9] }),
  peek('think_blink', { state: 'thinking', face: blinked(F.think), aim: chinOnHand, bones: { head: [2, 0, -10] }, look: [0.6, 0.9] }),
  peek('happy', { emotion: 'happy', face: F.happy, bones: { head: [-4, 0, 10] } }),
  peek('happy_talk_1', { emotion: 'happy', face: talk(F.happy, 0.45), bones: { head: [-4, 0, 10] } }),
  peek('happy_talk_2', { emotion: 'happy', face: F.happyOpen, bones: { head: [-4, 0, 10] } }),
  peek('laugh', { emotion: 'laugh', face: F.laugh, bones: { spine: [-4, 0, 0], head: [-16, 0, 8] }, aim: handsToMouth }),
  peek('laugh_2', { emotion: 'laugh', face: F.laugh, bones: { spine: [-2, 0, 0], head: [-10, 0, -6] } }),
  // Slumped shoulders, not a dropped head: the face has to stay visible under the fringe.
  peek('sad', { emotion: 'sad', face: F.sad, bones: { spine: [10, 0, 0], chest: [4, 0, 0], head: [3, 0, 12], leftShoulder: [0, 0, -8], rightShoulder: [0, 0, 8] }, look: [0, -0.6] }),
  peek('sad_talk', { emotion: 'sad', face: F.sadTalk, bones: { spine: [10, 0, 0], chest: [4, 0, 0], head: [1, 0, 12], leftShoulder: [0, 0, -8], rightShoulder: [0, 0, 8] }, look: [0, -0.3] }),
  peek('cry', { emotion: 'sad', face: F.cry, bones: { spine: [12, 0, 0], head: [6, 0, -8] }, aim: handsToMouth }),
  peek('angry', { emotion: 'angry', face: F.angry, aim: fists, bones: { spine: [14, 0, 0], chest: [4, 0, 0], head: [-2, 0, 0], leftShoulder: [0, 0, 12], rightShoulder: [0, 0, -12] } }),
  peek('angry_talk', { emotion: 'angry', face: F.angryTalk, aim: fists, bones: { spine: [14, 0, 0], chest: [4, 0, 0], head: [-4, 0, 0], leftShoulder: [0, 0, 12], rightShoulder: [0, 0, -12] } }),
  peek('surprised', { emotion: 'surprised', face: F.shock, aim: handsUp, bones: { spine: [-8, 0, 0], head: [-8, 0, 0] } }),
  peek('shy', { emotion: 'shy', face: F.shy, aim: handsToMouth, bones: { head: [10, 0, 16] }, look: [-0.8, -0.5] }),
  peek('wave_1', { state: 'greeting', face: F.happyOpen, aim: waveArm(-0.45), bones: { head: [-4, 0, 8] } }),
  peek('wave_2', { state: 'greeting', face: F.happy, aim: waveArm(0.0), bones: { head: [-4, 0, 8] } }),
  peek('wave_3', { state: 'greeting', face: F.happyOpen, aim: waveArm(0.45), bones: { head: [-4, 0, 8] } }),
  peek('sleep', { state: 'sleeping', face: F.sleep, bones: { spine: [22, 0, 0], chest: [10, 0, 0], neck: [14, 0, 0], head: [26, 0, 14] } }),
];

// --- Picked up and carried ---------------------------------------------------------------------------
function dangle(name, { face, arms, legs, head = [-4, 0, 0], emotion = null }) {
  return {
    name: `body_${name}`, set: 'body', state: 'dragged', emotion, face,
    bones: { ...legs, head },
    aim: arms,
  };
}
const flail = (l, r) => ({
  leftUpperArm: l[0], leftLowerArm: l[1],
  rightUpperArm: r[0], rightLowerArm: r[1],
});
// Legs seen from the front: a forward swing barely shows, so they also splay out and the knees bend.
const kick = (a, b, spread = 8) => ({
  leftUpperLeg: [-a, 0, spread], leftLowerLeg: [Math.max(a, 0) + 35, 0, 0],
  rightUpperLeg: [-b, 0, -spread], rightLowerLeg: [Math.max(b, 0) + 35, 0, 0],
});

const BODY = [
  dangle('drag_1', { face: F.shock,
    arms: flail([[0.75, 0.62, 0.2], [0.35, 0.93, 0.1]], [[-0.75, 0.62, 0.2], [-0.35, 0.93, 0.1]]),
    legs: kick(30, -5, 14) }),
  dangle('drag_2', { face: F.surprised,
    arms: flail([[0.92, 0.3, 0.25], [0.6, 0.78, 0.2]], [[-0.6, 0.78, 0.2], [-0.2, 0.97, 0.1]]),
    legs: kick(-5, 35, 4) }),
  dangle('drag_3', { face: F.shock,
    arms: flail([[0.6, 0.78, 0.2], [0.2, 0.97, 0.1]], [[-0.92, 0.3, 0.25], [-0.6, 0.78, 0.2]]),
    legs: kick(40, 10, 18), head: [-6, 0, 8] }),
  dangle('drag_fun', { face: F.laugh, emotion: 'happy',
    arms: flail([[0.97, 0.05, 0.2], [0.95, 0.2, 0.2]], [[-0.97, 0.05, 0.2], [-0.95, 0.2, 0.2]]),
    legs: kick(45, 45, 20), head: [-10, 0, 0] }),
  dangle('drop', { face: F.happy, emotion: 'happy',
    arms: flail([[0.55, -0.8, 0.2], [0.65, -0.6, 0.45]], [[-0.55, -0.8, 0.2], [-0.65, -0.6, 0.45]]),
    legs: kick(5, 5, 6), head: [4, 0, 6] }),
];

// --- Peeking around a bottom corner -------------------------------------------------------------------
// cornerR: the companion is behind the bottom-right corner. It leans in from the right, its body turned
// toward the middle of the screen, the left hand gripping the right edge beside its face and the right
// arm doing what the peek frame's right arm does (resting on the bottom edge, waving, chin in hand...).
// finish.py cuts these at the bottom edge and at the gripping hand. cornerL is the mirror image, posed
// (not flipped), so hair clips and logos stay on the right side.
// Elbow out and down behind the edge, forearm up, the hand at cheek height with the fingers pointing
// into the screen: from the front only the fingers show, curled round the edge.
const grip = {
  leftUpperArm: [0.45, -0.6, 0.66],
  leftLowerArm: [-0.2, 0.9, 0.38],
  leftHand: [-0.88, 0.15, 0.45],
};
const cornerLean = { hips: [0, -18, 0], spine: [6, 0, 14], chest: [2, 0, 8] };

function corner(frame) {
  const bones = { ...frame.bones, ...cornerLean };
  const head = frame.bones.head || [0, 0, 0];
  bones.head = [head[0], head[1], head[2] - 6];
  const aim = { ...frame.aim, ...grip };
  return { ...frame, name: frame.name.replace(/^peek_/, 'cornerR_'), set: 'cornerR', bones, aim };
}

// Mirror a pose across the body's middle: left <-> right, and turns about y and z change sign.
function swapSide(name) {
  if (name.startsWith('left')) return 'right' + name.slice(4);
  if (name.startsWith('right')) return 'left' + name.slice(5);
  return name;
}
function mirror(frame, set) {
  const bones = {};
  for (const [k, [x, y, z]] of Object.entries(frame.bones || {})) bones[swapSide(k)] = [x, -y, -z];
  const aim = {};
  for (const [k, [x, y, z]] of Object.entries(frame.aim || {})) aim[swapSide(k)] = [-x, y, z];
  const look = frame.look ? [-frame.look[0], frame.look[1]] : undefined;
  return { ...frame, name: frame.name.replace(/^cornerR_/, `${set}_`), set, bones, aim, look };
}

const CORNER_R = PEEK.map(corner);
const CORNER_L = CORNER_R.map((f) => mirror(f, 'cornerL'));

// --- Hanging upside down from the top edge ----------------------------------------------------------
// The edge pose turned over: the whole model is rolled 180 degrees in the picture (`flip`), so its
// forearms rest along the top edge and its head hangs below them. Hair and clothes settle under the
// real gravity, so they fall past the head. Directions in the picture turn with it.
function top(frame) {
  const aim = {};
  for (const [k, [x, y, z]] of Object.entries(frame.aim || {})) aim[k] = [-x, -y, z];
  const look = frame.look ? [-frame.look[0], -frame.look[1]] : undefined;
  return { ...frame, name: frame.name.replace(/^peek_/, 'top_'), set: 'top', flip: true, aim, look };
}
const TOP = PEEK.map(top);

export const FRAMES = [...PEEK, ...CORNER_R, ...CORNER_L, ...TOP, ...BODY];
