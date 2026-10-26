"""Download optional model weights into models/ (weights are gitignored)."""
import argparse
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = "https://s3.amazonaws.com/ir_public/nsfwjscdn/nsfw_mobilenet2.224x224.h5"

def install_nsfw():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    dest = Path(config["models"]["nsfw"]).expanduser()
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000000:
        print(f"Already present: {dest} ({dest.stat().st_size:,} bytes)")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"Downloading legacy NSFW MobileNet model: {SOURCE}")
    try:
        with urllib.request.urlopen(SOURCE, timeout=60) as response, tmp.open("wb") as output:
            shutil.copyfileobj(response, output)
        if tmp.stat().st_size < 1000000:
            raise RuntimeError("Download seems incomplete")
        with tmp.open("rb") as stream:
            if stream.read(8) != bytes.fromhex("894844460d0a1a0a"):
                raise RuntimeError("Downloaded model is not an HDF5 file")
        tmp.replace(dest)
        print(f"Installed: {dest} ({dest.stat().st_size:,} bytes)")
    finally:
        if tmp.exists():
            tmp.unlink()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nsfw", action="store_true", help="Download legacy NSFW MobileNet .h5")
    parser.add_argument("--nudenet", action="store_true", help="Confirm NudeNet bundled model is managed by the package")
    args = parser.parse_args()
    if not args.nsfw and not args.nudenet:
        parser.error("Choose --nsfw and/or --nudenet")
    if args.nudenet:
        print("NudeNet 320n.onnx is bundled within the nudenet package. Run setup_envs.py --nudenet to install it.")
    if args.nsfw:
        install_nsfw()

if __name__ == "__main__":
    main()
