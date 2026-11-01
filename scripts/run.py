"""Üç servisi birlikte başlatır: ölçüm API'si (8000), oyun sunucusu (8080), web arayüzü (3000).

Kullanım (depo kökünden, önce scripts/setup.py):  python scripts/run.py [--no-browser]
Ctrl+C hepsini kapatır. Servis çıktıları logs/ altına yazılır.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
API_PORT, GAME_PORT, WEB_PORT = 8000, 8080, 3000
WEB_URL = f"http://localhost:{WEB_PORT}"
API_URL = f"http://localhost:{API_PORT}"


def venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def stockfish_path() -> str | None:
    for p in sorted((ROOT / "tools" / "stockfish" / "stockfish").glob("stockfish-*")):
        if p.is_file() and p.suffix in ("", ".exe"):
            return str(p)
    return shutil.which("stockfish")


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def health() -> dict | None:
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


class Services:
    def __init__(self):
        self.procs: list[tuple[str, subprocess.Popen, Path]] = []

    def start(self, name: str, cmd: list, cwd: Path, env: dict) -> None:
        log = LOGS / f"{name}.log"
        out = open(log, "w", encoding="utf-8")
        # ayrı süreç grubu: kapatırken npm/node alt süreçleri de sonlanır
        kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, **kw)
        self.procs.append((name, p, log))

    def dead(self) -> tuple[str, Path] | None:
        for name, p, log in self.procs:
            if p.poll() is not None:
                return name, log
        return None

    def stop(self) -> None:
        for _, p, _ in self.procs:
            if p.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            else:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, p, _ in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def tail(log: Path, n: int = 15) -> str:
    try:
        return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Starts the measurement API, the game server and the web interface.")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    py, npm, node = venv_python(), shutil.which("npm"), shutil.which("node")
    if not py.exists() or not (ROOT / "apps/web/.next/BUILD_ID").exists() or not (npm and node):
        sys.exit("Run the setup first:  python scripts/setup.py")
    busy = [p for p in (API_PORT, GAME_PORT, WEB_PORT) if port_busy(p)]
    if busy:
        sys.exit(f"Port already in use: {', '.join(map(str, busy))}. Stop the previous run and try again.")

    LOGS.mkdir(exist_ok=True)
    token = secrets.token_urlsafe(32)   # API'nin /games/* uçları yalnız oyun sunucusuna açık
    base = {**os.environ, "CHESSDEX_INTERNAL_TOKEN": token}
    sf = stockfish_path()
    api_env = {**base, "PYTHONPATH": str(ROOT / "py"), "CHESSDEX_CORS": WEB_URL,
               "CHESSDEX_PUBLIC_API_URL": API_URL, "CHESSDEX_WEB_URL": WEB_URL, "CHESSDEX_LOG_FORMAT": "text"}
    if sf:
        api_env["STOCKFISH_PATH"] = sf

    svc = Services()
    try:
        svc.start("api", [py, "-m", "uvicorn", "chessdex.api.app:app", "--port", API_PORT], ROOT / "py", api_env)
        svc.start("game", [node, "--import", "tsx", "src/index.ts"], ROOT / "services/game",
                  {**base, "PORT": str(GAME_PORT), "API_URL": API_URL})
        svc.start("web", [npm, "run", "start"], ROOT / "apps/web", {**base, "NEXT_TELEMETRY_DISABLED": "1"})

        print("Starting services (loading the model can take about half a minute)...", flush=True)
        h = None
        deadline = time.time() + 180
        while time.time() < deadline:
            if (d := svc.dead()) is not None:
                sys.exit(f"The {d[0]} service stopped. Last lines of {d[1]}:\n{tail(d[1])}")
            h = h or health()
            if h and port_busy(GAME_PORT) and port_busy(WEB_PORT):
                break
            time.sleep(1)
        else:
            sys.exit("Services were not ready within 3 minutes; see logs/.")

        model = h.get("human_model", "?")
        print(f"\nReady: {WEB_URL}")
        note = "" if "maia2" in model else "  (Maia-2 missing, using a simple fallback)"
        print(f"  human-move model: {model}{note}")
        print(f"  Stockfish: {'found' if h.get('stockfish') else 'NOT FOUND (game analysis limited)'}")
        print(f"  items in bank: {h.get('bank_items')}")
        print("Press Ctrl+C to stop.", flush=True)
        if not args.no_browser:
            webbrowser.open(WEB_URL)
        while (d := svc.dead()) is None:
            time.sleep(1)
        print(f"The {d[0]} service stopped. Last lines of {d[1]}:\n{tail(d[1])}")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        svc.stop()


if __name__ == "__main__":
    main()
