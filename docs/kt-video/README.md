# Walkthrough video

A ~3.5-minute narrated walkthrough of this codebase: the problem, the architecture, one quote row traced through the
real functions, the event log and review, the email gap-filler, the RFQ comparison, how to run the demo, and the
limitations.

| File | What it is |
|---|---|
| `kt-video.mp4` | The rendered video (1920×1080, H.264 + AAC) |
| `captions.vtt`, `chapters.txt`, `poster.jpg` | Captions, YouTube-style chapters, preview frame |
| `outline.md` | Scene plan |
| `script.md` | Narration per scene, on-screen beats, and a `file:line` source for every claim |
| `tts.py` | Narration → `audio/scene_XX.wav` (Kokoro, runs locally), `timing.json`, `timing.js`, `captions.srt` |
| `composition.html` | All scenes as one HTML page; `window.renderAt(t)` draws the exact frame for time `t` |
| `render.mjs` | Playwright Chromium screenshots every frame at 30 fps and pipes PNGs into ffmpeg |
| `build.mjs` | Runs the whole pipeline (`npm run kt-video`) |

Everything runs offline once the tools are installed. No narration or code is sent to any service.

## Rebuild

Requirements: Python 3.10–3.12, Node 18+, ffmpeg on `PATH`, and espeak-ng.

```bash
cd docs/kt-video
uv venv .venv --python 3.12          # or: python3.12 -m venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # .venv/bin/python on macOS/Linux
npm install && npx playwright install chromium
npm run kt-video                     # narration (changed scenes only) -> timing -> render -> mux
```

The first TTS run downloads the Kokoro model weights from Hugging Face. Output goes to `out/` (ignored by git), and the
deliverables are then copied into this folder.

## Edit a scene

1. **Change the words:** edit the `> ` narration block for that scene in `script.md`, and update its **Sources**.
   Spell tricky terms the way they should be spoken ("skew" for SKU, "R-F-Q", "L-L-M"); `tts.py` maps them back to
   the written form for captions (`CAPTION_FIXES`).
2. **Re-voice:** `npm run tts`. Only scenes whose narration changed are synthesized again; timing and captions are
   always rebuilt. To force a scene: `.venv/Scripts/python.exe tts.py 05`.
3. **Change the visuals:** each scene is an entry in `S["NN"]` in `composition.html`, with `html()` (static
   markup) and `draw(t, A)` (sets opacity and position from the scene-local time `t`). `A("some phrase")` returns the
   time at which that phrase is spoken, so beats stay in sync when the narration changes. If a phrase can't be found,
   rendering stops and lists it.
4. **Preview:** open `composition.html` in a browser (there's a scrub bar; it plays `out/narration.wav` if it exists),
   or `node render.mjs --stills 12.5,47` to write PNGs to `out/stills/`.
5. **Render:** `npm run render` (or `npm run kt-video` to also re-check the audio).

Rendering is deterministic: the frame depends only on `t` and `timing.json`, with no timers, CSS transitions or
randomness. If the file is larger than 20 MB, `render.mjs` re-encodes with a higher CRF.
