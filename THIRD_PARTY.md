# Third-party assets and their licences

Code dependencies are pinned in `requirements*.txt`. This file lists the **audio and model assets**
Red downloads or builds, with their licence and the credit they ask for. Nothing is added to Red
without a line here (plan.md section 17).

| Asset | Used for | Licence | Credit / source |
|---|---|---|---|
| Kokoro-82M (ONNX, `kokoro-v1.0.int8.onnx`, `voices-v1.0.bin`) | Red's speaking voices; the Japanese reaction sound packs | Apache-2.0 | hexgrad, https://huggingface.co/hexgrad/Kokoro-82M ; ONNX files by thewh1teagle, https://github.com/thewh1teagle/kokoro-onnx |
| Sound pack `jp-male-1` (`RED_HOME\sounds\jp-male-1`, built by `scripts/make_sounds.py`) | Companion reactions (gasps, giggles, hmm, yawn...) | Apache-2.0 (audio synthesised with Kokoro-82M voice `jm_kumo`) | Credit: Kokoro-82M (Apache-2.0). Phonemes written by hand; nothing recorded or ripped |
| Sound pack `jp-male-2` | as above | Apache-2.0 (voice `jm_kumo`, pitched up 5 semitones: a modified copy) | as above |
| Sound pack `jp-female-1` | as above | Apache-2.0 (voice `jf_alpha`) | as above |
| Sound pack `jp-female-2` | as above | Apache-2.0 (voice `jf_tebukuro`) | as above |
| Whisper models (`faster-whisper-*` conversions) | Speech to text | MIT | OpenAI Whisper; CTranslate2 conversions by Systran, https://huggingface.co/Systran |
| Silero VAD (ships inside faster-whisper) | Wake word voice activity | MIT | https://github.com/snakers4/silero-vad |
| Piper voices (`en_US-lessac-medium` and the others pinned in `red/tts.py`) | Fallback voice | Each voice's own licence, on its model card in rhasspy/piper-voices (not re-checked tonight) | https://huggingface.co/rhasspy/piper-voices |

## Looked at and not used

- **VOICEVOX** (Japanese voices): its engine is unsigned native code that Windows Smart App Control
  blocks on the development PC, and each character has its own terms (credit format,
  redistribution of the audio) that could not be confirmed from the official pages. Not shipped.
- **CC0 vocal packs (OpenGameArt, Freesound):** not used; the licence pages could not be checked.
- **Anime, games and paid voice packs:** never ripped, never used.
