"""Train a custom openWakeWord model for "Hey Red" on Windows, with no datasets to download.

    python scripts\\train_hey_red\\hey_red.py generate     # synthetic clips -> features
    python scripts\\train_hey_red\\hey_red.py train        # small classifier -> hey_red_v0.1.onnx
    python scripts\\train_hey_red\\hey_red.py evaluate     # compare with the built-in detector
    python scripts\\train_hey_red\\hey_red.py all          # all three

Everything is made from Piper voices that Red already pins. Training uses the
904 speakers of en_US-libritts_r-medium. The six single-speaker voices are
never used for training, so the evaluation tests voices the model hasn't heard.

Work files go to RED_HOME\\cache\\train_hey_red. The model goes to
RED_HOME\\models\\wakeword\\hey_red_v0.1.onnx, and is used with
RED_WAKEWORD=<that path>. See README.md next to this file for the limits.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from red.audio import SAMPLE_RATE, resample, to_int16  # noqa: E402
from red.config import red_home  # noqa: E402
from red.tts import PIPER_VOICES  # noqa: E402

TRAIN_VOICE = "en_US-libritts_r-medium"
TRAIN_SPEAKERS = 904
HELD_OUT_VOICES = ["en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-medium", "en_US-joe-medium",
                   "en_GB-alan-medium", "en_GB-jenny_dioco-medium"]

CLIP_SECONDS = 2.0
N_FRAMES = 16                    # openWakeWord's window: 16 embedding frames of 96 values
MODEL_NAME = "hey_red_v0.1.onnx"

POSITIVE = ["Hey Red.", "Hey, Red!", "Hey Red!", "Hey, Red.", "Hey Red?", "hey red"]

# Close calls the model must learn to reject.
ADVERSARIAL = [
    "Hey, Fred.", "Hey, Ed.", "Hey, Ted.", "Hey, Ned.", "Hey, Brad.", "Hey, bread.", "Hey, ready?",
    "Hey, read this.", "A red light.", "A red car.", "They read.", "He read it.", "Hey.", "Red.",
    "Hey there.", "Hey, Rex.", "Hey, rest.", "Hey, Reg.", "Hay bed.", "Say red.", "Play red.",
    "Hey, Rick.", "Hey, Rod.", "Hey, Rhett.", "Okay, red.", "Hey you.", "Head red.", "Hey, wait.",
    "The red one.", "I said red.", "Hey, Siri.", "Hey, Google.", "Hey, Alexa.", "Hey, Reddit.",
    "Hey, ray.", "Hey, Rob.", "Hey, right.", "Hey, run.", "Hey, red wine.", "Ready.",
]

_WORDS = ("time year people way day man thing woman life child world school state family student "
          "group country problem hand part place case week company system program question work "
          "government number night point home water room mother area money story fact month lot "
          "right study book eye job word business issue side kind head house service friend father "
          "power hour game line end member law car city community name president team minute idea "
          "kid body information back parent face others level office door health person art war "
          "history party result change morning reason research girl guy moment air teacher force "
          "education foot boy age policy music phone window computer folder file meeting dinner "
          "coffee weather train garden letter picture movie song colour colours red reading bread").split()
_SENTENCES = [
    "Can you open my downloads folder?", "Shut down the computer in two hours.", "What time is it?",
    "I'll be back in a minute.", "Did you see the game last night?", "Let's order some food.",
    "The meeting moved to three o'clock.", "Turn the music down a little.", "Where did I put my keys?",
    "I read the red book yesterday.", "She wore a red dress to the party.", "Ready when you are.",
    "He read the news this morning.", "That was a great movie.", "Could you send me the file?",
    "We should leave before the traffic gets bad.", "The weather is nice today.", "Thanks a lot.",
    "I don't know what you mean.", "Let me think about it.", "Play something relaxing.",
    "Open the browser and search for recipes.", "My phone is almost out of battery.",
    "Hey, how's it going?", "Hey, can you hear me?", "Hey there, good to see you.",
    "Red, green and blue.", "The red team won again.", "Is the bread ready yet?",
    "Fred said he would call later.", "Ed is coming over tonight.", "Ted fixed the car.",
]


def models_dir() -> Path:
    return red_home() / "models"


def work_dir() -> Path:
    return red_home() / "cache" / "train_hey_red"


# --- Synthesis and augmentation ------------------------------------------------

class Voices:
    def __init__(self):
        from piper import PiperVoice
        self._PiperVoice = PiperVoice
        self._loaded = {}

    def say(self, name: str, text: str, speaker: int | None = None, speed: float = 1.0,
            noise: float = 0.667, noise_w: float = 0.8) -> np.ndarray:
        from piper import SynthesisConfig
        if name not in self._loaded:
            PIPER_VOICES[name].ensure(models_dir() / "piper", label=name)
            self._loaded[name] = self._PiperVoice.load(models_dir() / "piper" / f"{name}.onnx")
        cfg = SynthesisConfig(speaker_id=speaker, length_scale=1.0 / speed, noise_scale=noise,
                              noise_w_scale=noise_w)
        chunks = list(self._loaded[name].synthesize(text, cfg))
        audio = np.concatenate([c.audio_float_array for c in chunks])
        audio = resample(audio, chunks[0].sample_rate)
        peak = np.max(np.abs(audio)) or 1.0
        return (audio / peak).astype(np.float32)

    def train_say(self, text: str, rng: random.Random) -> np.ndarray:
        return self.say(TRAIN_VOICE, text, speaker=rng.randrange(TRAIN_SPEAKERS),
                        speed=rng.uniform(0.75, 1.35), noise=rng.uniform(0.4, 0.9),
                        noise_w=rng.uniform(0.5, 1.0))


def _colored_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n).astype(np.float32)
    kind = rng.integers(3)
    if kind == 0:
        return white
    spec = np.fft.rfft(white)
    f = np.arange(spec.size) + 1.0
    spec = spec / (f ** (0.5 if kind == 1 else 1.0))       # pink or brown
    out = np.fft.irfft(spec, n).astype(np.float32)
    return out / (np.std(out) + 1e-9)


def augment(audio: np.ndarray, rng: np.random.Generator, babble: np.ndarray | None = None) -> np.ndarray:
    """Random gain, room echo, noise and background talk."""
    from scipy.signal import fftconvolve
    x = audio.astype(np.float32)
    if rng.random() < 0.4:                                  # a room: decaying noise burst
        rt60 = rng.uniform(0.15, 0.7)
        t = np.arange(int(rt60 * SAMPLE_RATE)) / SAMPLE_RATE
        rir = rng.standard_normal(t.size) * np.exp(-6.9 * t / rt60)
        rir[0] = 1.0
        wet = fftconvolve(x, rir)[:x.size]
        wet /= np.max(np.abs(wet)) + 1e-9
        x = 0.6 * x + 0.4 * wet.astype(np.float32)
    level = np.sqrt(np.mean(x ** 2)) + 1e-9
    if rng.random() < 0.85:
        snr = rng.uniform(3, 30)
        x = x + _colored_noise(x.size, rng) * level / (10 ** (snr / 20))
    if babble is not None and babble.size >= x.size and rng.random() < 0.3:
        start = rng.integers(0, babble.size - x.size + 1)
        b = babble[start:start + x.size]
        snr = rng.uniform(8, 20)
        x = x + b * level / ((np.sqrt(np.mean(b ** 2)) + 1e-9) * 10 ** (snr / 20))
    x = x / (np.max(np.abs(x)) + 1e-9) * rng.uniform(0.05, 0.9)
    return x.astype(np.float32)


def place_at_end(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A CLIP_SECONDS window with the phrase ending near the end, as when it's detected live."""
    n = int(CLIP_SECONDS * SAMPLE_RATE)
    out = np.zeros(n, np.float32)
    tail = int(rng.uniform(0.0, 0.3) * SAMPLE_RATE)
    audio = audio[-(n - tail):]
    out[n - tail - audio.size:n - tail] = audio
    return out


def random_sentence(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return rng.choice(_SENTENCES)
    words = rng.sample(_WORDS, rng.randint(3, 9))
    return " ".join(words).capitalize() + rng.choice([".", "?", "!"])


# --- Features ------------------------------------------------------------------

class Features:
    def __init__(self):
        from openwakeword.utils import AudioFeatures
        wake = models_dir() / "wakeword"
        self._f = AudioFeatures(melspec_model_path=str(wake / "melspectrogram.onnx"),
                                embedding_model_path=str(wake / "embedding_model.onnx"),
                                inference_framework="onnx")

    def __call__(self, clips: np.ndarray) -> np.ndarray:
        emb = self._f.embed_clips(to_int16(clips), batch_size=256)
        return emb[:, -N_FRAMES:, :].astype(np.float32)


def generate(n_pos: int, n_adv: int, n_neg: int, seed: int = 0) -> Path:
    from red.listener import FEATURE_MODELS
    FEATURE_MODELS.ensure(models_dir() / "wakeword", label="openWakeWord")
    out = work_dir()
    out.mkdir(parents=True, exist_ok=True)
    rnd, rng = random.Random(seed), np.random.default_rng(seed)
    voices, feats = Voices(), Features()
    t0 = time.perf_counter()

    print("Background speech...", flush=True)
    stream = np.concatenate([np.concatenate([voices.train_say(random_sentence(rnd), rnd),
                                             np.zeros(int(rnd.uniform(0.1, 0.8) * SAMPLE_RATE), np.float32)])
                             for _ in range(max(60, n_neg // 12))])
    print(f"  {stream.size / SAMPLE_RATE / 60:.1f} min of speech", flush=True)

    def batch(make, count, label):
        clips = []
        for i in range(count):
            clips.append(make())
            if (i + 1) % 500 == 0:
                print(f"  {label}: {i + 1}/{count}  ({time.perf_counter() - t0:.0f} s)", flush=True)
        return feats(np.stack(clips))

    pos = batch(lambda: augment(place_at_end(voices.train_say(rnd.choice(POSITIVE), rnd), rng), rng, stream),
                n_pos, "positives")
    adv = batch(lambda: augment(place_at_end(voices.train_say(rnd.choice(ADVERSARIAL), rnd), rng), rng, stream),
                n_adv, "close calls")
    n = int(CLIP_SECONDS * SAMPLE_RATE)

    def window():
        if rng.random() < 0.1:                               # just noise
            return augment(np.zeros(n, np.float32) + 1e-4 * rng.standard_normal(n).astype(np.float32), rng)
        start = rng.integers(0, stream.size - n)
        return augment(stream[start:start + n], rng)

    neg = batch(window, n_neg, "other speech")
    np.savez_compressed(out / "features.npz", pos=pos, adv=adv, neg=neg)
    print(f"Saved {pos.shape[0]} positive, {adv.shape[0]} close-call and {neg.shape[0]} other clips "
          f"to {out / 'features.npz'} in {time.perf_counter() - t0:.0f} s")
    return out / "features.npz"


# --- Training and ONNX export ------------------------------------------------

def train(epochs: int = 40, hidden: int = 128, seed: int = 0) -> Path:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    data = np.load(work_dir() / "features.npz")
    pos, adv, neg = data["pos"], data["adv"], data["neg"]
    x = np.concatenate([pos, adv, neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(adv) + len(neg))]).astype(np.float32)
    w = np.concatenate([np.ones(len(pos)), np.full(len(adv), 3.0), np.full(len(neg), 2.0)]).astype(np.float32)
    idx = np.random.default_rng(seed).permutation(len(x))
    split = int(0.9 * len(x))
    tr, va = idx[:split], idx[split:]

    model = nn.Sequential(
        nn.Flatten(), nn.Linear(N_FRAMES * 96, hidden), nn.LayerNorm(hidden), nn.ReLU(),
        nn.Linear(hidden, hidden), nn.LayerNorm(hidden), nn.ReLU(), nn.Linear(hidden, 1))
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    X, Y, W = (torch.from_numpy(a) for a in (x, y, w))
    loss_fn = nn.BCEWithLogitsLoss(reduction="none")
    for epoch in range(epochs):
        model.train()
        perm = torch.from_numpy(np.random.default_rng(seed + epoch).permutation(tr))
        for i in range(0, len(perm), 256):
            b = perm[i:i + 256]
            loss = (loss_fn(model(X[b]).squeeze(1), Y[b]) * W[b]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        if (epoch + 1) % 10 == 0 or epoch == 0:
            model.eval()
            with torch.no_grad():
                p = torch.sigmoid(model(X[va]).squeeze(1)).numpy()
            yv = y[va]
            print(f"  epoch {epoch + 1}: loss {loss.item():.4f}, held-back clips: "
                  f"miss {np.mean(p[yv == 1] < 0.5):.3f}, false accept {np.mean(p[yv == 0] >= 0.5):.4f}",
                  flush=True)

    path = models_dir() / "wakeword" / MODEL_NAME
    export_onnx(model, path)
    (work_dir() / "training.json").write_text(json.dumps(
        {"positives": len(pos), "close_calls": len(adv), "other": len(neg), "epochs": epochs,
         "hidden": hidden, "model": str(path)}, indent=2))
    print(f"Model saved to {path}")
    return path


def export_onnx(model, path: Path) -> None:
    """Write the MLP as a plain ONNX graph that openWakeWord can load (input [1, 16, 96] -> [1, 1])."""
    import onnx
    import onnxruntime
    import torch
    from onnx import TensorProto, helper, numpy_helper

    layers = [m for m in model if not isinstance(m, torch.nn.Flatten)]
    inits, nodes, cur, k = [], [], "flat", 0
    nodes.append(helper.make_node("Flatten", ["input"], ["flat"], axis=1))
    for m in layers:
        k += 1
        out = f"t{k}"
        if isinstance(m, torch.nn.Linear):
            inits += [numpy_helper.from_array(m.weight.detach().numpy().T.copy(), f"W{k}"),
                      numpy_helper.from_array(m.bias.detach().numpy(), f"B{k}")]
            nodes.append(helper.make_node("Gemm", [cur, f"W{k}", f"B{k}"], [out]))
        elif isinstance(m, torch.nn.LayerNorm):
            inits += [numpy_helper.from_array(m.weight.detach().numpy(), f"G{k}"),
                      numpy_helper.from_array(m.bias.detach().numpy(), f"H{k}")]
            nodes.append(helper.make_node("LayerNormalization", [cur, f"G{k}", f"H{k}"], [out],
                                          axis=-1, epsilon=m.eps))
        elif isinstance(m, torch.nn.ReLU):
            nodes.append(helper.make_node("Relu", [cur], [out]))
        cur = out
    nodes.append(helper.make_node("Sigmoid", [cur], ["output"]))
    graph = helper.make_graph(
        nodes, "hey_red",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["batch", N_FRAMES, 96])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, ["batch", 1])], inits)
    onnx_model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    onnx_model.ir_version = 8
    onnx.checker.check_model(onnx_model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(onnx_model, str(path))

    probe = np.random.default_rng(1).standard_normal((4, N_FRAMES, 96)).astype(np.float32)
    with torch.no_grad():
        want = torch.sigmoid(model(torch.from_numpy(probe))).numpy()
    got = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"]).run(
        None, {"input": probe})[0]
    assert np.allclose(want, got, atol=1e-4), "ONNX export doesn't match the trained model"


# --- Evaluation ------------------------------------------------------------------

EVAL_ORDINARY = ["I read the red book.", "He read it yesterday.", "Hey, ready to go?", "They said red.",
                 "Hey, Fred.", "Hey there.", "The red car is fast.", "Red is my favourite colour.",
                 "Hey, how are you?", "Read it again.", "A red light.", "Thank you.", "Hey, Ted!",
                 "Bread.", "Hey Rex.", "Hey, Rick.", "Hey, Ed."]


def evaluate(threshold: float = 0.5) -> dict:
    from red.listener import WakeWordDetector, make_detector

    voices = Voices()
    rng = np.random.default_rng(7)
    detectors = {"built-in (VAD + Whisper tiny.en)": make_detector(models_dir() / "wakeword", "hey_red")}
    trained = models_dir() / "wakeword" / MODEL_NAME
    if trained.exists():
        detectors["trained openWakeWord model"] = WakeWordDetector(models_dir() / "wakeword", str(trained))

    def room(s):
        return (0.003 * rng.standard_normal(int(s * SAMPLE_RATE))).astype(np.float32)

    def run(det, audio):
        det.reset()
        x = to_int16(np.concatenate([room(1.0), audio * 0.5 + room(audio.size / SAMPLE_RATE), room(1.0)]))
        t0 = time.process_time()
        best = max(det.score(x[i:i + 1280]) for i in range(0, x.size, 1280))
        return best, time.process_time() - t0

    positives = [voices.say(v, t, speed=s) for v in HELD_OUT_VOICES for s in (0.8, 1.0, 1.25)
                 for t in ("Hey Red.", "Hey, Red!")]
    ordinary = [(t, voices.say(v, t)) for v in HELD_OUT_VOICES for t in EVAL_ORDINARY]
    talk = np.concatenate([np.concatenate([voices.say(rng.choice(HELD_OUT_VOICES), s),
                                           room(rng.uniform(0.2, 0.8))])
                           for s in _SENTENCES * 3])
    results = {}
    for name, det in detectors.items():
        hits = sum(run(det, a)[0] >= threshold for a in positives)
        fa = [t for t, a in ordinary if run(det, a)[0] >= threshold]
        det.reset()
        x = to_int16(talk + room(talk.size / SAMPLE_RATE))
        t0 = time.process_time()
        scores = [det.score(x[i:i + 1280]) for i in range(0, x.size, 1280)]
        cpu = time.process_time() - t0
        fired = sum(1 for a, b in zip(scores, scores[1:]) if b >= threshold > a)
        minutes = talk.size / SAMPLE_RATE / 60
        results[name] = {
            "hits": f"{hits}/{len(positives)}",
            "false_accepts_close_calls": f"{len(fa)}/{len(ordinary)}",
            "false_accept_phrases": sorted(set(fa)),
            "talk_minutes": round(minutes, 1),
            "false_accepts_in_talk": fired,
            "cpu_percent_of_one_core_during_talk": round(100 * cpu / (minutes * 60), 1),
        }
        print(f"\n{name}:")
        for k, v in results[name].items():
            print(f"  {k}: {v}")
    (work_dir()).mkdir(parents=True, exist_ok=True)
    (work_dir() / "evaluation.json").write_text(json.dumps(results, indent=2))
    return results


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("step", choices=("generate", "train", "evaluate", "all"))
    p.add_argument("--positives", type=int, default=4000)
    p.add_argument("--close-calls", type=int, default=4000)
    p.add_argument("--other", type=int, default=12000)
    p.add_argument("--epochs", type=int, default=40)
    args = p.parse_args(argv)
    if args.step in ("generate", "all"):
        generate(args.positives, args.close_calls, args.other)
    if args.step in ("train", "all"):
        train(args.epochs)
    if args.step in ("evaluate", "all"):
        evaluate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
