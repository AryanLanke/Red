"""Try Red's voice without the rest of Red.

    python -m red.voice_demo              press Ctrl+Alt+R or say "hey Jarvis", then speak
    python -m red.voice_demo --confirm    also ask a spoken yes/no after each command
    python -m red.voice_demo --setup      only download the voice models
    python -m red.voice_demo --levels     show microphone levels for 5 seconds
    python -m red.voice_demo --say "Hi"   speak a sentence and exit
    python -m red.voice_demo --file x.wav transcribe a WAV file and exit

Red hears the command, prints the transcript and reads it back. Nothing is
routed to the LLM and no action runs.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from red.audio import Microphone, chime, record_command, resample, rms, to_float32
from red.config import load_settings
from red.listener import (DEFAULT_HOTKEY, DEFAULT_THRESHOLD, DEFAULT_WAKEWORD, Listener,
                          download_wakeword)
from red.stt import Transcriber
from red.tts import DEFAULT_VOICE, Speaker
from red.voice_confirm import spoken_ask

_OFF = {"", "0", "off", "none", "no", "false"}


@dataclass
class VoiceConfig:
    """Voice settings from RED_* variables. The integration step moves these into Settings."""

    hotkey: str | None = DEFAULT_HOTKEY
    wakeword: str | None = DEFAULT_WAKEWORD
    wakeword_threshold: float = DEFAULT_THRESHOLD
    whisper_model: str = "small"
    whisper_device: str = "auto"
    piper_voice: str = DEFAULT_VOICE

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        env = os.environ
        hotkey = env.get("RED_HOTKEY", DEFAULT_HOTKEY).strip()
        wakeword = env.get("RED_WAKEWORD", DEFAULT_WAKEWORD).strip()
        return cls(
            hotkey=None if hotkey.lower() in _OFF else hotkey,
            wakeword=None if wakeword.lower() in _OFF else wakeword,
            wakeword_threshold=float(env.get("RED_WAKEWORD_THRESHOLD", DEFAULT_THRESHOLD)),
            whisper_model=env.get("RED_WHISPER_MODEL", "small").strip() or "small",
            whisper_device=env.get("RED_WHISPER_DEVICE", "auto").strip().lower() or "auto",
            piper_voice=env.get("RED_PIPER_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE,
        )


def _is_yes(answer: str | None) -> bool:
    # Stand-in for confirm.is_yes from Track A; the integration step swaps it in.
    if answer is None:
        return False
    return answer.strip().rstrip(".!?,;: ").strip().lower() in ("y", "yes")


def _pretty_hotkey(hotkey: str) -> str:
    return "+".join(p.strip("<>").capitalize() if len(p) > 1 else p.upper() for p in hotkey.split("+"))


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit("Only 16-bit PCM WAV files are supported.")
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            frames = frames.reshape(-1, w.getnchannels())
        return resample(to_float32(frames), w.getframerate())


def _levels(seconds: float = 5.0) -> None:
    print("Microphone levels (talk, then stay quiet). Speech is usually above 0.02.")
    end = time.monotonic() + seconds
    with Microphone(block_seconds=0.1) as mic:
        while time.monotonic() < end:
            level = rms(mic.read())
            print(f"\r  {level:0.4f} {'#' * min(60, int(level * 600)):<60}", end="", flush=True)
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m red.voice_demo", description=__doc__.split("\n\n")[0])
    p.add_argument("--setup", action="store_true", help="download the voice models and exit")
    p.add_argument("--confirm", action="store_true", help="ask a spoken yes/no after each command")
    p.add_argument("--levels", action="store_true", help="show microphone levels for 5 seconds")
    p.add_argument("--say", metavar="TEXT", help="speak TEXT and exit")
    p.add_argument("--file", metavar="WAV", type=Path, help="transcribe a 16-bit WAV file and exit")
    p.add_argument("--hotkey", help=f"global shortcut (default {_pretty_hotkey(DEFAULT_HOTKEY)}, or RED_HOTKEY)")
    p.add_argument("--wakeword", help=f"pre-trained phrase or .onnx path (default {DEFAULT_WAKEWORD}, or RED_WAKEWORD)")
    p.add_argument("--no-wakeword", action="store_true", help="hotkey only")
    p.add_argument("--device", choices=("auto", "cuda", "cpu"), help="Whisper device (default auto, or RED_WHISPER_DEVICE)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="  [%(name)s] %(message)s")
    settings = load_settings()
    settings.ensure_dirs()
    cfg = VoiceConfig.from_env()
    if args.hotkey:
        cfg.hotkey = args.hotkey
    if args.wakeword:
        cfg.wakeword = args.wakeword
    if args.no_wakeword:
        cfg.wakeword = None
    if args.device:
        cfg.whisper_device = args.device

    models = settings.models_dir
    transcriber = Transcriber(models / "whisper", cfg.whisper_model, cfg.whisper_device)
    speaker = Speaker(models / "piper", cfg.piper_voice)

    if args.levels:
        _levels()
        return 0

    print(f"Voice models are in {models}")
    speaker.download()
    if args.say:
        speaker.say(args.say)
        return 0
    transcriber.download()
    if cfg.wakeword:
        download_wakeword(models / "wakeword", cfg.wakeword)
    if args.setup:
        print("Voice models are downloaded and verified.")
        return 0

    print("Loading Whisper...", end=" ", flush=True)
    t0 = time.perf_counter()
    transcriber.load()
    speaker.load()
    print(f"done in {time.perf_counter() - t0:.1f} s, on {transcriber.device} ({transcriber.compute_type}).")

    if args.file:
        t0 = time.perf_counter()
        text = transcriber.transcribe(_read_wav(args.file))
        print(f"Transcript ({time.perf_counter() - t0:.1f} s): {text!r}")
        return 0

    ask = spoken_ask(speaker, transcriber)

    def handle(source: str) -> None:
        print(f"\n[{source}] Listening... speak now.")
        chime()
        audio = record_command()
        if audio.size == 0:
            print("  (heard nothing)")
            speaker.say("I didn't hear anything.")
            return
        t0 = time.perf_counter()
        text = transcriber.transcribe(audio)
        took = time.perf_counter() - t0
        print(f"  You said: {text!r}  ({audio.size / 16000:.1f} s of audio, "
              f"transcribed in {took:.1f} s on {transcriber.device})")
        speaker.say(f"You said: {text}" if text else "Sorry, I didn't catch that.")
        if args.confirm:
            answer = ask("Do you want to confirm? [y/N]", 30.0)
            yes = _is_yes(answer)
            print(f"  Answer: {answer!r} -> {'confirmed' if yes else 'cancelled'}")
            speaker.say("Confirmed." if yes else "Cancelled.")

    listener = Listener(handle, cfg.hotkey, cfg.wakeword,
                        model_dir=models / "wakeword", threshold=cfg.wakeword_threshold)
    try:
        listener.start()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    ways = []
    if cfg.hotkey:
        ways.append(f"press {_pretty_hotkey(listener.hotkey)}")
    if cfg.wakeword:
        ways.append(f"say \"{Path(listener.wakeword).stem.replace('_', ' ').split(' v0')[0]}\"")
    if not ways:
        print("Both the hotkey and the wake word are off; nothing can trigger Red.", file=sys.stderr)
        return 2
    print(f"Ready. {' or '.join(ways).capitalize()}, then speak. Ctrl+C quits.")
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        listener.stop()
        speaker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
