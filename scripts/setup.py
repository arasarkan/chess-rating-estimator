"""Kurulum: Python ortamı, Stockfish 19, Maia-2 ağırlıkları, soru bankası ve web/oyun sunucusu paketleri.

Kullanım (depo kökünden):  python scripts/setup.py [--no-maia]
Yeniden çalıştırmak güvenlidir; hazır olan adımlar atlanır. Yalnızca standart kütüphane kullanır.
"""
from __future__ import annotations

import argparse
import gzip
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
SF_DIR = ROOT / "tools" / "stockfish"
SF_RELEASE = "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/"
BANK = ROOT / "py" / "data" / "bank.jsonl"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# run.py ile aynı adresler (web arayüzü bunları derleme sırasında içine yazar)
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8080/ws"


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def run(cmd: list, **kw) -> None:
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def check_tools() -> str:
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11 or newer is required (found {platform.python_version()}).")
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not (npm and node):
        sys.exit("Node.js 20 or newer is required: https://nodejs.org/")
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    if int(ver.lstrip("v").split(".")[0]) < 20:
        sys.exit(f"Node.js 20 or newer is required (found {ver}).")
    print(f"  Python {platform.python_version()}, Node {ver}")
    return npm


def python_env(with_maia: bool) -> None:
    step("Python environment (.venv)")
    if not venv_python().exists():
        run([sys.executable, "-m", "venv", VENV])
    py = venv_python()
    run([py, "-m", "pip", "install", "-q", "-r", ROOT / "py" / "requirements.txt"])
    if not with_maia:
        return
    step("PyTorch (CPU) and Maia-2")
    torch = [py, "-m", "pip", "install", "-q", "torch"]
    if sys.platform != "darwin":  # macOS tekerlekleri zaten yalnız CPU/MPS
        torch += ["--index-url", TORCH_CPU_INDEX]
    run(torch)
    # maia2 0.11.0 eski torch/Python sürümlerine sabitlenmiş; bağımlılıkları requirements.txt'te kurulu
    run([py, "-m", "pip", "install", "-q", "--no-deps", "--ignore-requires-python", "maia2==0.11.0"])


def stockfish_asset() -> str | None:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "win32":
        return f"stockfish-windows-{'arm64' if arm else 'x86-64'}-universal.zip"
    if sys.platform == "darwin":
        return "stockfish-macos-universal.tar.gz"
    if sys.platform.startswith("linux"):
        return f"stockfish-linux-{'arm64' if arm else 'x86-64'}-universal.tar.gz"
    return None


def find_binary() -> Path | None:
    for p in sorted((SF_DIR / "stockfish").glob("stockfish-*")):
        if p.is_file() and p.suffix in ("", ".exe"):
            return p
    return None


def stockfish() -> None:
    step("Stockfish 19")
    if find_binary():
        print(f"  already present: {find_binary()}")
        return
    asset = stockfish_asset()
    if asset is None:
        print("  No prebuilt Stockfish for this platform; install it with your package manager and put it on PATH.")
        return
    dl = SF_DIR / "dl" / asset
    dl.parent.mkdir(parents=True, exist_ok=True)
    if not dl.exists():
        print(f"  downloading {SF_RELEASE}{asset}")
        urllib.request.urlretrieve(SF_RELEASE + asset, dl)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(dl) as z:
            z.extractall(SF_DIR)
    else:
        with tarfile.open(dl) as t:
            try:
                t.extractall(SF_DIR, filter="data")
            except TypeError:  # Python < 3.11.4: filter parametresi yok
                t.extractall(SF_DIR)
    binary = find_binary()
    if binary is None:
        sys.exit(f"No executable found in the Stockfish archive: {dl}")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  installed: {binary}")


def bank() -> None:
    step("Item bank")
    if BANK.exists():
        print(f"  already present: {BANK.relative_to(ROOT)}")
        return
    with gzip.open(BANK.with_suffix(".jsonl.gz"), "rb") as src, open(BANK, "wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"  unpacked: {BANK.relative_to(ROOT)}")


def maia_weights() -> None:
    step("Maia-2 weights (rapid, ~280 MB, downloaded once)")
    try:
        run([venv_python(), "-c", "from chessdex.engines.human import Maia2Model; Maia2Model(); print('  ready')"],
            cwd=ROOT / "py")
    except subprocess.CalledProcessError:
        # API bu durumda basit yedek modelle çalışır; ağırlıklar sonraki kurulumda yeniden denenir
        print("  WARNING: could not load the Maia-2 weights. Run the setup again later.")


def node_packages(npm: str) -> None:
    for d in ("services/game", "apps/web"):
        step(f"npm packages: {d}")
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / d)
    step("Building the web interface")
    env = {**os.environ, "NEXT_PUBLIC_API_URL": API_URL, "NEXT_PUBLIC_WS_URL": WS_URL, "NEXT_TELEMETRY_DISABLED": "1"}
    run([npm, "run", "build"], cwd=ROOT / "apps/web", env=env)


def main() -> None:
    ap = argparse.ArgumentParser(description="Installs everything needed to run the project locally.")
    ap.add_argument("--no-maia", action="store_true",
                    help="skip PyTorch and Maia-2 (the opponent and game analysis fall back to a simple model)")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    npm = check_tools()
    python_env(with_maia=not args.no_maia)
    stockfish()
    bank()
    if not args.no_maia:
        maia_weights()
    node_packages(npm)
    print("\nDone. Start with:  python scripts/run.py")


if __name__ == "__main__":
    main()
