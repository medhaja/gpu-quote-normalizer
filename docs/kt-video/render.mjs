// Deterministic render: composition.html + timing.json + audio/scene_XX.wav -> out/kt-video.mp4
//
//   node render.mjs                 full render, then copy deliverables into docs/kt-video/
//   node render.mjs --stills 12.5,40  write PNG stills to out/stills/ (no video)
//
// Each frame is drawn by window.renderAt(t) and captured with Playwright Chromium; PNG frames are piped
// straight into ffmpeg (no frame files on disk).
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const AUDIO = path.join(HERE, "audio");
const timing = JSON.parse(readFileSync(path.join(HERE, "timing.json"), "utf8"));
const FPS = timing.fps;
const SR = timing.sample_rate;
const MAX_BYTES = 20 * 1024 * 1024;
mkdirSync(OUT, { recursive: true });

const fmt = (s) => { const m = Math.floor(s / 60), r = Math.floor(s % 60); return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`; };

function ffmpeg(args, opts = {}) {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...args], { stdio: "inherit", ...opts });
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${args.join(" ")}`);
}
function probeDuration(file, stream) {
  const r = spawnSync("ffprobe", ["-v", "error", "-select_streams", stream, "-show_entries", "stream=duration", "-of", "csv=p=0", file], { encoding: "utf8" });
  return parseFloat(r.stdout.trim());
}

// ---------------------------------------------------------------- audio: scene WAVs + padding, sample-exact
function readWavPcm16(file) {
  const b = readFileSync(file);
  let off = 12, data = null, fmtOk = false;
  while (off < b.length) {
    const id = b.toString("ascii", off, off + 4), size = b.readUInt32LE(off + 4);
    if (id === "fmt ") fmtOk = b.readUInt16LE(off + 8) === 1 && b.readUInt16LE(off + 10) === 1 && b.readUInt32LE(off + 12) === SR && b.readUInt16LE(off + 22) === 16;
    if (id === "data") data = b.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  if (!fmtOk || !data) throw new Error(`${file}: expected 16-bit mono PCM at ${SR} Hz`);
  return data;
}
function buildNarration() {
  const parts = [];
  let samples = 0;
  for (const sc of timing.scenes) {
    const startSample = Math.round(sc.start * SR);
    if (startSample > samples) { parts.push(Buffer.alloc((startSample - samples) * 2)); samples = startSample; }
    const pcm = readWavPcm16(path.join(AUDIO, `scene_${sc.id}.wav`));
    parts.push(pcm); samples += pcm.length / 2;
  }
  const endSample = Math.round(timing.total * SR);
  if (endSample > samples) parts.push(Buffer.alloc((endSample - samples) * 2));
  const data = Buffer.concat(parts);
  const h = Buffer.alloc(44);
  h.write("RIFF", 0); h.writeUInt32LE(36 + data.length, 4); h.write("WAVE", 8); h.write("fmt ", 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(SR, 24);
  h.writeUInt32LE(SR * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(data.length, 40);
  const file = path.join(OUT, "narration.wav");
  writeFileSync(file, Buffer.concat([h, data]));
  return file;
}

// ---------------------------------------------------------------- page
async function openPage() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => { console.error("page error:", e.message); process.exitCode = 1; });
  await page.goto(pathToFileURL(path.join(HERE, "composition.html")).href + "?render=1");
  await page.evaluate(() => document.fonts.ready);
  const missing = await page.evaluate(() => window.__missingAnchors);
  if (missing.length) throw new Error(`phrases not found in timing.json words:\n  ${missing.join("\n  ")}`);
  return { browser, page };
}
const shot = async (page, t) => { await page.evaluate((s) => window.renderAt(s), t); return page.screenshot({ type: "png" }); };

async function stills(times) {
  const { browser, page } = await openPage();
  mkdirSync(path.join(OUT, "stills"), { recursive: true });
  for (const t of times) {
    const f = path.join(OUT, "stills", `t${t.toFixed(2)}.png`);
    writeFileSync(f, await shot(page, t));
    console.log(f);
  }
  await browser.close();
}

async function renderVideo(narration, crf) {
  const { browser, page } = await openPage();
  const frames = Math.round(timing.total * FPS);
  const mp4 = path.join(OUT, "kt-video.mp4");
  const ff = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y",
    "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
    "-i", narration,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", String(crf), "-preset", "veryfast", "-r", String(FPS),
    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", mp4], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error(`ffmpeg exited ${c}`)))));
  const t0 = Date.now();
  for (let i = 0; i < frames; i++) {
    const png = await shot(page, i / FPS);
    if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 300 === 0) console.log(`  frame ${i}/${frames}  (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
  }
  ff.stdin.end();
  await done;
  await browser.close();
  return mp4;
}

// ---------------------------------------------------------------- side files
function writeChapters() {
  const lines = timing.scenes.map((s) => `${fmt(s.start)} ${s.chapter}`);
  writeFileSync(path.join(OUT, "chapters.txt"), lines.join("\n") + "\n");
}
function writeVtt() {
  const srt = readFileSync(path.join(HERE, "captions.srt"), "utf8");
  copyFileSync(path.join(HERE, "captions.srt"), path.join(OUT, "captions.srt"));
  const vtt = "WEBVTT\n\n" + srt.replace(/\r/g, "").replace(/(\d\d:\d\d:\d\d),(\d\d\d)/g, "$1.$2");
  writeFileSync(path.join(OUT, "captions.vtt"), vtt);
}
async function writePoster() {
  const s1 = timing.scenes[0];
  const t = s1.start + s1.duration * 0.92;  // late in scene 1, when the whole problem slide is built
  const { browser, page } = await openPage();
  const png = path.join(OUT, "poster.png");
  writeFileSync(png, await shot(page, t));
  await browser.close();
  ffmpeg(["-i", png, "-vf", "scale=1280:-2", "-q:v", "3", path.join(OUT, "poster.jpg")]);
}

// ---------------------------------------------------------------- main
const args = process.argv.slice(2);
if (args[0] === "--stills") {
  await stills(args[1].split(",").map(Number));
} else {
  const narration = buildNarration();
  let crf = 20, mp4 = await renderVideo(narration, crf);
  while (statSync(mp4).size > MAX_BYTES && crf < 34) {
    crf += 3;
    console.log(`  ${(statSync(mp4).size / 1e6).toFixed(1)} MB > 20 MB, re-encoding at CRF ${crf}`);
    mp4 = await renderVideo(narration, crf);
  }
  writeChapters();
  writeVtt();
  await writePoster();
  const v = probeDuration(mp4, "v:0"), a = probeDuration(mp4, "a:0");
  console.log(`\n${mp4}\n  size ${(statSync(mp4).size / 1e6).toFixed(2)} MB · CRF ${crf} · video ${v.toFixed(3)}s · audio ${a.toFixed(3)}s · diff ${Math.abs(v - a).toFixed(3)}s`);
  if (Math.abs(v - a) > 0.2) { console.error("video and audio durations differ by more than 0.2 s"); process.exitCode = 1; }
  for (const [src, dst] of [["kt-video.mp4", "kt-video.mp4"], ["poster.jpg", "poster.jpg"], ["captions.vtt", "captions.vtt"], ["chapters.txt", "chapters.txt"]]) {
    copyFileSync(path.join(OUT, src), path.join(HERE, dst));
  }
  console.log("copied kt-video.mp4, poster.jpg, captions.vtt, chapters.txt into docs/kt-video/");
}
