// Whole pipeline: narration (Kokoro, local) -> timing -> frames -> MP4.
//   npm run kt-video            (from docs/kt-video)
//   npm run kt-video -- --tts-only
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const py = process.platform === "win32" ? path.join(HERE, ".venv", "Scripts", "python.exe") : path.join(HERE, ".venv", "bin", "python");

function run(cmd, args) {
  console.log(`\n> ${path.basename(cmd)} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { cwd: HERE, stdio: "inherit", env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

if (!existsSync(py)) {
  console.error(`Missing ${py}. Create it first (Python 3.10-3.12):\n  uv venv .venv --python 3.12 && uv pip install --python ${py} -r requirements.txt`);
  process.exit(1);
}
run(py, ["tts.py"]);
if (!process.argv.includes("--tts-only")) run(process.execPath, ["render.mjs"]);
