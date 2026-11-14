"""Build the companions' reaction sound packs: python scripts/make_sounds.py [--only en-female-1] [--list] [--check]

The packs land in RED_HOME\\sounds\\<pack id>\\ (never in git: they are build output), each with a
pack.toml that carries the licence, the source and the credit line of every clip.

Where the sounds come from (the user's order, plan.md night 2, lane sounds):
  1. Real recorded clips from Freesound.org under CC0 or CC-BY (never NonCommercial), listed in
     sounds/sources.toml: page URL, author, licence, SHA-256 of the file, and the trim points. This
     script downloads each file, checks its SHA-256 and its licence, trims it, evens out the loudness,
     cuts it under 1.4 s and writes the WAV. Run twice, it writes identical files (nothing random, no
     date in the output). Found with scripts/sound_search.py, measured with scripts/sound_measure.py.
  2. Kokoro-82M (Apache-2.0, the model Red already speaks with): only for a kind that has no licensed
     clip in that pack. The Japanese reactions are written as Kokoro phonemes by hand (no Japanese
     text phonemizer, which would need native code that Smart App Control may block); the English
     ones are short words ("hey!", "ow!").
  3. `zip` (a zipper) falls back to a sound made here from clicks and noise.
  Never: anime or game rips, paid packs, VOICEVOX, anything with an unclear licence.

Each sound is under 1.4 s and has the same loudness. Kinds are in red/sounds.py.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tomllib
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RATE = 24_000
MAX_SECONDS = 1.4                # packs promise under 1.5 s
TARGET_RMS_DB = -21.0            # every sound the same loudness
PEAK_CEILING = 0.89              # about -1 dBFS
SOURCES = ROOT / "sounds" / "sources.toml"
ALLOWED_LICENSES = {"CC0 1.0", "CC BY 4.0", "CC BY 3.0"}      # NonCommercial and the rest never ship

KINDS = ("pickup", "drop", "hover", "surprised", "laugh", "giggle", "sigh", "yawn", "hmm", "annoyed",
         "happy", "sleepy", "poke", "drag_fast", "dizzy", "pout", "sneeze", "hiccup", "climb", "zip")

# kind -> two variants: (what it is, Kokoro phonemes). ↗ rises, ʔ is the stop of っ.
JA: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "pickup":    (("きゃっ!", "kʲa↗ʔ!"), ("わっ!", "wa↗ʔ!")),
    "drop":      (("いたっ!", "itaʔ!"), ("あうっ!", "aɯʔ!")),
    "hover":     (("ん?", "ɴ↗?"), ("おっ?", "o↗ʔ?")),
    "surprised": (("えっ!?", "e↗ʔ!?"), ("えー!?", "eː↗!?")),
    "laugh":     (("あはは!", "ahahaha!"), ("ふはは!", "ɸɯhahaha!")),
    "giggle":    (("ふふっ", "ɸɯɸɯʔ"), ("えへへ", "eheheː")),
    "sigh":      (("はぁ…", "haːː…"), ("ふぅ…", "ɸɯːː…")),
    "yawn":      (("ふぁ〜", "ɸaaːː…"), ("ふあぁーん", "ɸɯaaːːɴ…")),
    "hmm":       (("うーん", "ɯːɴ…"), ("んー", "ɴːː…")),
    "annoyed":   (("もう!", "moː!"), ("むぅ…", "mɯː…")),
    "happy":     (("やった!", "jaʔta!"), ("わーい!", "waːi!")),
    "sleepy":    (("ねむ…", "nemɯ…"), ("ふぁ…", "ɸa…")),
    "poke":      (("ひゃっ!", "çʲa↗ʔ!"), ("えっ?", "e↗ʔ?")),
    "drag_fast": (("わぁー!", "waː↗ː!"), ("ひゃー!", "çʲaː↗!")),
    "dizzy":     (("ふらふら…", "ɸɯɾaɸɯɾa…"), ("めがまわる…", "meɡamawaɾɯ…")),
    "pout":      (("ふんっ!", "ɸɯɴʔ!"), ("むー!", "mɯː!")),
    "sneeze":    (("はっくしゅん!", "haʔkɯɕɯɴ!"), ("くしゅん!", "kɯɕɯɴ!")),
    "hiccup":    (("ひっく!", "çiʔkɯ!"), ("ひっく…", "çiʔkɯ…")),
    "climb":     (("よいしょ", "joiɕo"), ("んしょ…", "ɴɕo…")),
}
# English: the words a young person says. Kokoro says them when a pack has no recorded clip.
EN: dict[str, tuple[str, str]] = {
    "pickup": ("Whoa!", "Hey!"), "drop": ("Ow!", "Oof!"), "hover": ("Hm?", "Oh?"),
    "surprised": ("Eh?!", "Huh?!"), "laugh": ("Ha ha ha!", "Hee hee hee!"),
    "giggle": ("Hee hee!", "Tee hee!"), "sigh": ("Haaah.", "Phew."), "yawn": ("Haaaah-hm.", "Aaah-hmm."),
    "hmm": ("Hmm.", "Mmm?"), "annoyed": ("Ugh!", "Tsk."), "happy": ("Yay!", "Woo-hoo!"),
    "sleepy": ("Mmm, sleepy.", "So sleepy."), "poke": ("Eep!", "Eh?"), "drag_fast": ("Hey!", "Waah!"),
    "dizzy": ("Whoa, dizzy.", "Ooh, wobbly."), "pout": ("Hmph!", "Hmph."), "sneeze": ("Ah, ah, choo!", "Achoo!"),
    "hiccup": ("Hic!", "Hic."), "climb": ("Hup!", "Hnngh."),
}


@dataclass(frozen=True)
class PackSpec:
    id: str
    name: str
    gender: str
    lang: str                # ja | en
    voice: str               # Kokoro voice for the kinds with no recorded clip
    semitones: float = 0.0   # pitch shift of the fallback copy (0: as Kokoro made it)
    speed: float = 1.0
    note: str = ""


PACKS = (
    PackSpec("jp-male-1", "Japanese anime, male 1", "male", "ja", "jm_kumo", 0.0, 1.05),
    PackSpec("jp-male-2", "Japanese anime, male 2 (higher, younger)", "male", "ja", "jm_kumo", 5.0, 1.1,
             "pitched up 5 semitones"),
    PackSpec("jp-female-1", "Japanese anime, female 1 (bright)", "female", "ja", "jf_alpha", 0.0, 1.0),
    PackSpec("jp-female-2", "Japanese anime, female 2 (softer)", "female", "ja", "jf_tebukuro", 0.0, 1.05),
    PackSpec("en-female-1", "English, young woman 1 (bright)", "female", "en", "af_nova", 0.0, 1.1),
    PackSpec("en-female-2", "English, young woman 2 (soft)", "female", "en", "af_heart", 0.0, 1.05),
    PackSpec("en-male-1", "English, young man 1", "male", "en", "am_puck", 0.0, 1.1),
)


def home() -> Path:
    return Path(os.environ.get("RED_HOME", r"D:\RED"))


# --- sources.toml ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    id: str
    page: str
    url: str
    sha256: str
    author: str
    title: str
    license: str
    license_url: str

    @property
    def credit(self) -> str:
        return f'"{self.title}" by {self.author} ({self.page}), {self.license}'


@dataclass(frozen=True)
class Use:
    source: str
    pack: str
    kind: str
    start: float = 0.0
    end: float = 0.0          # 0: to the end of the clip
    gain_db: float = 0.0
    pitch: float = 0.0        # semitones, for a second pack that reuses a clip


def load_sources(path: Path = SOURCES) -> tuple[dict[str, Source], list[Use]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = {}
    for s in data.get("source", []):
        src = Source(s["id"], s["page"], s["url"], s["sha256"], s["author"], s["title"], s["license"],
                     s["license_url"])
        if src.license not in ALLOWED_LICENSES:
            raise ValueError(f"{src.id}: licence {src.license!r} is not allowed (CC0 or CC-BY only)")
        if src.id in sources:
            raise ValueError(f"{src.id}: listed twice")
        sources[src.id] = src
    uses = [Use(u["source"], u["pack"], u["kind"], float(u.get("start", 0.0)), float(u.get("end", 0.0)),
                float(u.get("gain_db", 0.0)), float(u.get("pitch", 0.0))) for u in data.get("use", [])]
    for u in uses:
        if u.source not in sources:
            raise ValueError(f"use of unknown source {u.source!r}")
        if u.kind not in KINDS:
            raise ValueError(f"unknown kind {u.kind!r}")
    return sources, uses


def fetch_source(src: Source, cache: Path) -> Path:
    """The downloaded file, checked against its SHA-256 (a changed or broken download is an error)."""
    from sound_search import fetch
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{src.id}{Path(src.url).suffix}"
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == src.sha256:
        return path
    data = fetch(src.url, binary=True)
    got = hashlib.sha256(data).hexdigest()
    if got != src.sha256:
        raise ValueError(f"{src.id}: SHA-256 {got} is not the listed {src.sha256}")
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


# --- audio -----------------------------------------------------------------------------------------

def shift_pitch(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Pitch up by resampling (the sound also gets shorter, like a younger, quicker voice)."""
    if not semitones:
        return audio
    factor = 2 ** (semitones / 12)
    n = int(audio.size / factor)
    return np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio).astype(np.float32)


def finish(audio: np.ndarray, gain_db: float = 0.0) -> np.ndarray:
    """Trim, fade, cap at MAX_SECONDS, and set the same loudness for every sound."""
    from red.tts_kokoro import trim
    audio = trim(audio.astype(np.float32), top_db=45.0)
    audio = audio[: int(MAX_SECONDS * RATE)].copy()
    fade_in, fade_out = int(0.004 * RATE), int(0.04 * RATE)
    if audio.size > fade_in + fade_out:
        audio[:fade_in] *= np.linspace(0, 1, fade_in)
        audio[-fade_out:] *= np.linspace(1, 0, fade_out)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) or 1e-9
    audio = audio * (10 ** ((TARGET_RMS_DB + gain_db) / 20) / rms)
    peak = float(np.abs(audio).max())
    if peak > PEAK_CEILING:                      # a loud short pop: lower it, accepting a quieter sound
        audio = audio * (PEAK_CEILING / peak)
    return audio.astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def zipper(seed: int = 7) -> np.ndarray:
    """A short zipper made from ratcheting clicks and a little noise (our own, no licence needed):
    teeth ticking faster as the slider speeds up."""
    rng = np.random.default_rng(seed)
    n = int(0.55 * RATE)
    out = np.zeros(n, np.float32)
    t, gap = 0.0, 0.032
    while t < 0.5:
        i = int(t * RATE)
        length = int(0.004 * RATE)
        burst = rng.standard_normal(length).astype(np.float32) * np.exp(-np.linspace(0, 6, length))
        end = min(n, i + length)
        out[i:end] += burst[: end - i] * 0.7
        t += gap
        gap = max(0.012, gap * 0.93)
    # a high, thin hiss under the clicks
    hiss = np.diff(rng.standard_normal(n + 1).astype(np.float32)) * 0.04
    return out + hiss * np.hanning(n).astype(np.float32)


def resample_to(audio: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate == RATE:
        return audio
    n = int(audio.size * RATE / src_rate)
    return np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio).astype(np.float32)


def cut(src_path: Path, use: Use) -> np.ndarray:
    from sound_measure import decode
    audio = decode(src_path, RATE)
    a = int(use.start * RATE)
    b = int(use.end * RATE) if use.end else audio.size
    return shift_pitch(audio[a:b], use.pitch)


# --- the packs -------------------------------------------------------------------------------------

def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pack_toml(spec: PackSpec, clips: list[dict], sources: dict[str, Source]) -> str:
    used = sorted({sources[c["source"]].license for c in clips if c.get("source")})
    has_kokoro = any(c["origin"] == "kokoro" for c in clips)
    has_made = any(c["origin"] == "made" for c in clips)
    parts = []
    if used:
        parts.append("recorded clips from Freesound.org under " + " and ".join(used)
                     + " (the credit of each clip is below)")
    if has_kokoro:
        extra = f", {spec.note}" if spec.note else ""
        parts.append(f"Kokoro-82M by hexgrad, Apache-2.0, voice {spec.voice}{extra}, for the kinds with no recorded clip")
    if has_made:
        parts.append("a zipper sound made for Red (no third-party material)")
    lines = [
        f"name = {_toml_str(spec.name)}", f'gender = "{spec.gender}"',
        f'style = "{"anime-ja" if spec.lang == "ja" else "young-en"}"', f'lang = "{spec.lang}"',
        "license = " + _toml_str("; ".join(parts) + "."),
        "source = " + _toml_str("sounds/sources.toml in the Red repository; scripts/make_sounds.py builds this pack"),
        f'voice = "{spec.voice}"',
        "kinds = [" + ", ".join(f'"{k}"' for k in KINDS if any(c["kind"] == k for c in clips)) + "]",
        "",
    ]
    for c in clips:
        lines.append("[[clip]]")
        lines.append(f'file = "{c["file"]}"')
        lines.append(f'kind = "{c["kind"]}"')
        lines.append(f'origin = "{c["origin"]}"')
        if c.get("source"):
            s = sources[c["source"]]
            lines += [f"page = {_toml_str(s.page)}", f"author = {_toml_str(s.author)}",
                      f'license = "{s.license}"', f"license_url = {_toml_str(s.license_url)}",
                      f"credit = {_toml_str(s.credit)}"]
        elif c["origin"] == "kokoro":
            lines.append('license = "Apache-2.0"')
            lines.append('credit = "Kokoro-82M by hexgrad (Apache-2.0)"')
        else:
            lines.append('license = "made for Red"')
        lines.append("")
    return "\n".join(lines)


def kokoro_fallback(engine, spec: PackSpec, kind: str, n: int) -> np.ndarray:
    if spec.lang == "ja":
        audio = engine.create_phonemes(JA[kind][n][1], spec.voice, spec.speed)
    else:
        audio = engine.create(EN[kind][n], spec.voice, spec.speed)
    return shift_pitch(audio, spec.semitones)


def build(specs=PACKS, out: Path | None = None, engine=None, *, sources_path: Path = SOURCES,
          cache: Path | None = None, fetcher=fetch_source) -> dict[str, list[Path]]:
    sources, uses = load_sources(sources_path)
    out = out or home() / "sounds"
    cache = cache or home() / "cache" / "sounds-src"
    made: dict[str, list[Path]] = {}
    for spec in specs:
        folder = out / spec.id
        clips: list[dict] = []
        files: list[Path] = []
        counts: dict[str, int] = {}
        for use in (u for u in uses if u.pack == spec.id):
            counts[use.kind] = counts.get(use.kind, 0) + 1
            name = f"{use.kind}_{counts[use.kind]}.wav"
            audio = finish(cut(fetcher(sources[use.source], cache), use), use.gain_db)
            write_wav(folder / name, audio)
            files.append(folder / name)
            clips.append({"file": name, "kind": use.kind, "origin": "freesound", "source": use.source})
        for kind in KINDS:
            if counts.get(kind):
                continue
            if kind == "zip":
                variants = [("zip_1.wav", finish(zipper(7))), ("zip_2.wav", finish(zipper(11)))]
                origin = "made"
            else:
                if engine is None:
                    from red.tts_kokoro import KokoroEngine, MODEL_FILE, VOICES_FILE
                    k = home() / "models" / "kokoro"
                    engine = KokoroEngine(k / MODEL_FILE, k / VOICES_FILE)
                variants = [(f"{kind}_{n + 1}.wav", finish(kokoro_fallback(engine, spec, kind, n)))
                            for n in range(2)]
                origin = "kokoro"
            for name, audio in variants:
                write_wav(folder / name, audio)
                files.append(folder / name)
                clips.append({"file": name, "kind": kind, "origin": origin})
        # a stale file from an older build must not stay in the pack
        keep = {p.name for p in files}
        for old in folder.glob("*.wav"):
            if old.name not in keep:
                old.unlink()
        clips.sort(key=lambda c: (KINDS.index(c["kind"]), c["file"]))
        (folder / "pack.toml").write_text(pack_toml(spec, clips, sources), encoding="utf-8")
        made[spec.id] = files
        real = sum(1 for c in clips if c["origin"] == "freesound")
        print(f"{spec.id}: {len(files)} sounds ({real} recorded) in {folder}")
    return made


def credits_markdown(sources: dict[str, Source], uses: list[Use]) -> str:
    """The CC-BY credit lines for THIRD_PARTY.md (one per source that a pack uses)."""
    used = {u.source for u in uses}
    lines = []
    for sid in sorted(used):
        s = sources[sid]
        packs = ", ".join(sorted({u.pack for u in uses if u.source == sid}))
        lines.append(f"- {s.credit}. License: {s.license_url}. In: {packs}.")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", help="pack ids to build")
    p.add_argument("--list", action="store_true")
    p.add_argument("--credits", action="store_true", help="print the credit lines for THIRD_PARTY.md")
    args = p.parse_args()
    if args.list:
        for spec in PACKS:
            print(f"{spec.id}: {spec.name} ({spec.voice})")
        return
    if args.credits:
        sources, uses = load_sources()
        print(credits_markdown(sources, uses))
        return
    build([s for s in PACKS if not args.only or s.id in args.only])


if __name__ == "__main__":
    main()
