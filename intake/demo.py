"""One-command demo: seed the sample files into a fresh database and start the app.

    python -m intake.demo [--port 8000] [--no-serve]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
DEMO_DB = ROOT / "intake_demo.db"


def seed(db_url: str) -> list[tuple[str, str, str]]:
    from intake.pipeline import ingest
    from intake.store import make_engine, make_session_factory

    sessions = make_session_factory(make_engine(db_url))
    results = []
    with sessions() as s:
        for path in sorted(SAMPLES.iterdir()):
            r = ingest(s, path.name, path.read_bytes())
            results.append((path.name, r.status, r.message))
    return results


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-serve", action="store_true", help="seed only, do not start the web server")
    args = ap.parse_args(argv)

    if not SAMPLES.exists() or not any(SAMPLES.iterdir()):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py")], check=True)

    from intake.compare import load_rfqs

    # The sample quotes were generated relative to a fixed date; check validity against it
    # so the demo looks the same whenever it is run. Override with INTAKE_AS_OF.
    os.environ.setdefault("INTAKE_AS_OF", load_rfqs()["as_of"])

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        DEMO_DB.unlink(missing_ok=True)  # fresh local demo every run
        db_url = f"sqlite:///{DEMO_DB.as_posix()}"

    results = seed(db_url)
    width = max(len(n) for n, _, _ in results)
    for name, status, msg in results:
        print(f"  {name:<{width}}  {status:<9} {msg}")
    print(f"\nSeeded {len(results)} files (as of {os.environ['INTAKE_AS_OF']}).")

    if args.no_serve:
        return
    import socket

    with socket.socket() as probe:
        if probe.connect_ex((args.host, args.port)) == 0:
            sys.exit(f"\nPort {args.port} is already in use. Try: python -m intake.demo --port {args.port + 1}")
    import uvicorn

    from intake.web.app import create_app

    print(f"\n  Open http://{args.host}:{args.port}  (Ctrl+C to stop)\n")
    uvicorn.run(create_app(db_url), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
