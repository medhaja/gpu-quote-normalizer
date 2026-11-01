"""Narration -> per-scene WAVs, timing.json and captions.srt (all local, Kokoro TTS).

    .venv/Scripts/python.exe tts.py             # scenes whose narration changed (or has no WAV yet)
    .venv/Scripts/python.exe tts.py 03 07       # force these scenes
    .venv/Scripts/python.exe tts.py --all       # force every scene
Timing (timing.json / timing.js) and captions.srt are always rebuilt from every WAV.

Narration is read from script.md: the "> " quote block under each "## NN · Title" heading.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
SR = 24000
VOICE = "af_heart"
PAD = 0.6            # silence after each scene's narration
CLOSING_HOLD = 3.0   # the closing card stays this long after the narration ends

# Short chapter names (used for chapter labels and chapters.txt).
CHAPTERS = {
    "01": "The problem", "02": "Architecture", "03": "One row, end to end", "04": "Event log & review",
    "05": "Emails & the gap-filler", "06": "Compare & run", "07": "Gotchas & limits", "08": "Recap",
    "09": "Thank you",
}

# Spoken respellings -> written form, for captions.
CAPTION_FIXES = [
    ("python dash m intake dot demo", "python -m intake.demo"),
    ("shah two fifty-six", "SHA-256"),
    ("H one hundred", "H100"),
    ("R-F-Q ten-oh-one", "RFQ-1001"),
    ("S-X-M", "SXM"), ("R-F-Q", "RFQ"), ("L-L-M", "LLM"), ("G-P-Us", "GPUs"), ("G-P-U", "GPU"),
    ("O-R-M", "ORM"), ("C-P-U", "CPU"), ("e-val", "eval"), ("skews", "SKUs"), ("skew", "SKU"), ("okay", "ok"),
]


def load_scenes() -> list[dict]:
    text = (HERE / "script.md").read_text(encoding="utf-8")
    scenes = []
    for m in re.finditer(r"^## (\d\d) · (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        num, title, body = m.groups()
        quote = re.search(r"\*\*Narration\*\*.*?\n\n((?:> .*\n?)+)", body)
        if not quote:
            continue
        narration = " ".join(l[2:].strip() for l in quote.group(1).splitlines())
        scenes.append({"id": num, "title": title.strip(), "chapter": CHAPTERS[num], "narration": narration})
    return scenes


def synth(pipeline, scene: dict) -> None:
    chunks, words, offset = [], [], 0.0
    for result in pipeline(scene["narration"], voice=VOICE, speed=1.0):
        audio = result.audio.cpu().numpy() if hasattr(result.audio, "cpu") else np.asarray(result.audio)
        for tok in result.tokens or []:
            if tok.start_ts is None or tok.end_ts is None:
                continue
            words.append({"text": tok.text, "ws": tok.whitespace, "start": round(offset + tok.start_ts, 3),
                          "end": round(offset + tok.end_ts, 3)})
        chunks.append(audio)
        offset += len(audio) / SR
    wav = np.concatenate(chunks)
    sf.write(AUDIO / f"scene_{scene['id']}.wav", wav, SR, subtype="PCM_16")
    (AUDIO / f"scene_{scene['id']}.words.json").write_text(json.dumps(words, indent=0), encoding="utf-8")
    (AUDIO / f"scene_{scene['id']}.txt").write_text(scene["narration"], encoding="utf-8")
    print(f"  scene {scene['id']}: {len(wav) / SR:.2f}s, {len(words)} timed tokens")


def caption_text(s: str) -> str:
    for a, b in CAPTION_FIXES:
        s = re.sub(rf"\b{re.escape(a)}\b", b, s)
    return s


def cues(words: list[dict], max_words: int = 14) -> list[tuple[float, float, str]]:
    """Group tokens into caption cues, breaking at sentence ends or long clauses."""
    out, cur = [], []

    def flush():
        if cur:
            text = "".join(w["text"] + w["ws"] for w in cur).strip()
            out.append((cur[0]["start"], cur[-1]["end"], caption_text(text)))
            cur.clear()

    for i, w in enumerate(words):
        cur.append(w)
        n = sum(1 for x in cur if re.search(r"\w", x["text"]))
        nxt = words[i + 1]["text"] if i + 1 < len(words) else ""
        next_is_word = bool(re.search(r"\w", nxt))
        if (w["text"] in (".", "?", "!") or (w["text"] in (",", ":", ";") and n >= 7)
                or (n >= max_words and next_is_word)):
            flush()
    flush()
    return out


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build_timing(scenes: list[dict]) -> None:
    t, out, srt = 0.0, [], []
    for i, sc in enumerate(scenes):
        info = sf.info(str(AUDIO / f"scene_{sc['id']}.wav"))
        audio = info.frames / info.samplerate
        pad = CLOSING_HOLD if i == len(scenes) - 1 else PAD
        words = json.loads((AUDIO / f"scene_{sc['id']}.words.json").read_text(encoding="utf-8"))
        out.append({"id": sc["id"], "title": sc["title"], "chapter": sc["chapter"], "start": round(t, 3),
                    "audio": round(audio, 3), "pad": pad, "duration": round(audio + pad, 3),
                    "words": [{"w": w["text"], "s": w["start"], "e": w["end"]} for w in words]})
        for a, b, text in cues(words):
            srt.append((t + a, t + b, text))
        t += audio + pad
    timing = {"fps": 30, "sample_rate": SR, "total": round(t, 3), "scenes": out}
    (HERE / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    # Same data as a script, so composition.html also works when opened from file://.
    (HERE / "timing.js").write_text("window.TIMING = " + json.dumps(timing) + ";\n", encoding="utf-8")
    lines = []
    for n, (a, b, text) in enumerate(srt, 1):
        lines += [str(n), f"{srt_time(a)} --> {srt_time(b)}", text, ""]
    (HERE / "captions.srt").write_text("\n".join(lines), encoding="utf-8")
    print(f"timing.json: {len(out)} scenes, total {t:.2f}s; captions.srt: {len(srt)} cues")


def main(argv: list[str]) -> None:
    scenes = load_scenes()
    want = {s["id"] for s in scenes} if "--all" in argv else set(argv)
    AUDIO.mkdir(exist_ok=True)

    def stale(s: dict) -> bool:
        txt = AUDIO / f"scene_{s['id']}.txt"
        return (not (AUDIO / f"scene_{s['id']}.wav").exists() or not txt.exists()
                or txt.read_text(encoding="utf-8") != s["narration"])

    todo = [s for s in scenes if s["id"] in want or stale(s)]
    if todo:
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        for sc in todo:
            synth(pipeline, sc)
    build_timing(scenes)


if __name__ == "__main__":
    main(sys.argv[1:])
