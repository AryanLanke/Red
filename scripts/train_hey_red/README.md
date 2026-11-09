# Training a custom "Hey Red" model

Red's default "Hey Red" detector (`red/wakeword.py`) needs no training. This folder trains an openWakeWord model for the same phrase instead. It runs on Windows, uses only the Piper voices Red already pins, and downloads no datasets.

```powershell
$env:RED_HOME = "D:\RED"
pip install -r requirements-train.txt
python scripts\train_hey_red\hey_red.py all          # or: generate, train, evaluate
$env:RED_WAKEWORD = "D:\RED\models\wakeword\hey_red_v0.1.onnx"   # to try the trained model
```

## What it does

1. **Generate** (about 20 minutes on a Ryzen 7 7735HS, CPU only). The 904 speakers of `en_US-libritts_r-medium` say:
   - "Hey Red" with varied speed and prosody: 6,000 clips
   - close calls such as "Hey, Fred", "A red light" and "Hey, ready?": 6,000 clips
   - random sentences, cut into 20,000 two-second windows

   Each clip gets random gain, room echo, white, pink or brown noise, and background talk. openWakeWord's own feature models turn each clip into 16 × 96 embeddings. The result is `RED_HOME\cache\train_hey_red\features.npz`.
2. **Train** (under a minute on the CPU). This trains openWakeWord's usual small classifier head: two hidden layers of 128 with LayerNorm. The ONNX graph is written directly, with no exporter dependency, to `RED_HOME\models\wakeword\hey_red_v0.1.onnx`. The script checks that ONNX and PyTorch give the same output.
3. **Evaluate.** It compares the trained model with the built-in detector on six Piper voices that were never used for training. Each voice says "Hey Red" at three speeds, then 17 ordinary or close-call phrases, then 3.3 minutes of conversation. Results go to `RED_HOME\cache\train_hey_red\evaluation.json`.

## Result (2026-11-08)

| Detector | "Hey Red" hits | Close-call false accepts | False accepts in 3.3 min of talk | CPU during talk (one core) |
|---|---|---|---|---|
| Built-in (VAD + Whisper tiny.en) | **36/36** | **0/102** | **0** | 20.6% |
| Trained openWakeWord model | 29/36 | 10/102 ("A red light", "He read it yesterday", "Hey Rex", "The red car is fast") | 4 | **2.7%** |

The built-in detector stays the default. The trained model is much cheaper on the CPU, but it misses more and fires more.

## Why the trained model is weaker, and what it would take

openWakeWord's own models are trained on these, which this script doesn't have:
- **Real negative speech:** about 2,000 hours of pre-computed features (ACAV100M), roughly 17 GB, plus a validation set. Here the negatives are about an hour (58 minutes) of synthetic speech from a single multi-speaker voice. That's the main reason for the false accepts.
- **Real room impulse responses and background audio** (MIT RIRs, AudioSet, FMA) in place of synthetic echo and coloured noise.
- **Many more synthetic speakers and phrasings:** piper-sample-generator mixes speaker embeddings, but it depends on `piper-phonemize`, which has no Windows wheels.
- **Recordings of you** saying "Hey Red", even 20–50 clips. Nothing beats the user's own voice and microphone.

To get a model good enough to replace the default:
1. Download the ACAV100M features and use them as negatives, which needs about 20 GB of disk.
2. Add a few hours of real speech, such as LibriSpeech or Common Voice, and real noise.
3. Train for longer with openWakeWord's negative-weighting schedule.

That's a few hours of downloading and about an hour of training. A GPU helps there, but isn't needed for the small head trained here.

A cheaper middle path is a **two-stage detector**: the trained model, at a low threshold such as 0.2, decides which clips Whisper checks. That combines the trained model's low CPU use with the built-in detector's accuracy.
