// The sprite frames Red's companion window uses. Bone angles are degrees [x, y, z] in the VRM 1.0
// convention: positive x bends a bone forward/down, an upper arm's z lowers (left, negative) or
// raises it; see page.js. Face values are three-vrm expression names (VRM 0.0 presets are mapped:
// joy -> happy, sorrow -> sad, fun -> relaxed, a/i/u/e/o -> aa/ih/ou/ee/oh).
// Breathing and swaying are not frames: the window does them by moving the picture slightly.

const relaxed = {
  leftUpperArm: [0, 0, -72],
  rightUpperArm: [0, 0, 72],
  leftLowerArm: [0, -12, 0],
  rightLowerArm: [0, 12, 0],
  leftHand: [0, 0, -5],
  rightHand: [0, 0, 5],
  spine: [2, 0, 0],
  head: [0, 0, 3],
};

const listening = {
  ...relaxed,
  spine: [8, 0, 0],
  chest: [3, 0, 0],
  head: [4, 0, 8],
};

const thinking = {
  ...relaxed,
  rightUpperArm: [-40, 0, 70],
  rightLowerArm: [0, 130, 0],
  rightHand: [0, 0, 20],
  head: [-10, 0, -6],
};

const sleeping = {
  ...relaxed,
  leftUpperArm: [0, 0, -78],
  rightUpperArm: [0, 0, 78],
  spine: [6, 0, 0],
  neck: [10, 0, 0],
  head: [16, 0, 8],
};

// The hand swings out and in around a raised forearm; past about -100 the hand goes behind the head.
function waving(forearm, hand) {
  return {
    ...relaxed,
    rightUpperArm: [0, 0, -20],
    rightLowerArm: [0, 0, forearm],
    rightHand: [0, 0, hand],
    head: [0, 0, -5],
  };
}

function dangling(legSwing) {
  return {
    leftUpperArm: [0, 0, 55],
    rightUpperArm: [0, 0, -55],
    leftLowerArm: [0, 0, 25],
    rightLowerArm: [0, 0, -25],
    leftUpperLeg: [-legSwing, 0, 0],
    leftLowerLeg: [legSwing + 15, 0, 0],
    rightUpperLeg: [legSwing, 0, 0],
    rightLowerLeg: [15, 0, 0],
    head: [-4, 0, 0],
  };
}

export const FRAMES = [
  { name: 'idle', state: 'idle', bones: relaxed, face: {} },
  { name: 'idle_blink', state: 'idle', bones: relaxed, face: { blink: 1 } },
  { name: 'talk_1', state: 'speaking', bones: relaxed, face: { aa: 0.35 } },
  { name: 'talk_2', state: 'speaking', bones: relaxed, face: { aa: 0.8 } },
  { name: 'talk_3', state: 'speaking', bones: relaxed, face: { oh: 0.7 } },
  { name: 'happy', emotion: 'happy', bones: relaxed, face: { happy: 1 } },
  { name: 'happy_talk_1', emotion: 'happy', bones: relaxed, face: { happy: 1, aa: 0.4 } },
  { name: 'happy_talk_2', emotion: 'happy', bones: relaxed, face: { happy: 1, aa: 0.8 } },
  { name: 'laugh', emotion: 'laugh', bones: { ...relaxed, head: [-8, 0, 4] }, face: { happy: 1, aa: 0.6 } },
  { name: 'sad', emotion: 'sad', bones: { ...relaxed, head: [8, 0, 4] }, face: { sad: 1 } },
  { name: 'sad_talk', emotion: 'sad', bones: { ...relaxed, head: [8, 0, 4] }, face: { sad: 1, aa: 0.4 } },
  { name: 'angry', emotion: 'angry', bones: relaxed, face: { angry: 1 } },
  { name: 'angry_talk', emotion: 'angry', bones: relaxed, face: { angry: 1, aa: 0.5 } },
  { name: 'surprised', emotion: 'surprised', bones: relaxed, face: { Surprised: 1, oh: 0.4 } },
  { name: 'shy', emotion: 'shy', bones: { ...relaxed, head: [6, 0, 10] }, face: { relaxed: 1 }, look: [-0.4, -0.3] },
  { name: 'listen', state: 'listening', bones: listening, face: {} },
  { name: 'listen_blink', state: 'listening', bones: listening, face: { blink: 1 } },
  { name: 'think', state: 'thinking', bones: thinking, face: {}, look: [0.3, 0.8] },
  { name: 'think_blink', state: 'thinking', bones: thinking, face: { blink: 1 }, look: [0.3, 0.8] },
  { name: 'wave_1', state: 'greeting', bones: waving(-55, 30), face: { happy: 1 } },
  { name: 'wave_2', state: 'greeting', bones: waving(-80, 0), face: { happy: 1, aa: 0.3 } },
  { name: 'wave_3', state: 'greeting', bones: waving(-100, -35), face: { happy: 1 } },
  { name: 'drag_1', state: 'dragged', bones: dangling(20), face: { Surprised: 1, oh: 0.6 } },
  { name: 'drag_2', state: 'dragged', bones: dangling(-15), face: { Surprised: 1, oh: 0.4 } },
  { name: 'sleep', state: 'sleeping', bones: sleeping, face: { blink: 1 } },
];
