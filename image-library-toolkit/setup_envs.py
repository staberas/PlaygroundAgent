"""Create isolated optional stage environments (no activation required)."""
import argparse
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = {
    "nudenet": ["nudenet>=3.4,<4", "onnxruntime", "pillow"],
    "yolo": ["ultralytics", "pillow"],
    "ocr": ["easyocr"],
    "nsfw": ["tensorflow==2.15.1", "tensorflow-hub==0.15.0", "numpy<2", "setuptools==80.9.0", "pillow"],
    "marqo": ["torch", "torchvision", "timm", "huggingface_hub", "pillow"],
    "caption": ["torch", "transformers==4.51.0", "accelerate", "sentencepiece", "pillow"],
}

def main():
    parser = argparse.ArgumentParser()
    for stage in PACKAGES:
        parser.add_argument("--" + stage, action="store_true")
    parser.add_argument("--python", default=sys.executable, help="Python executable to bootstrap environments (default: current)")
    args = parser.parse_args()
    stages = [s for s in PACKAGES if getattr(args, s)]
    if not stages:
        parser.error("Choose at least one stage flag; e.g. --nudenet")
    for stage in stages:
        folder = ROOT / ".venvs" / stage
        if not folder.exists():
            subprocess.run([args.python, "-m", "venv", str(folder)], check=True)
        exe = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(exe), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(exe), "-m", "pip", "install", *PACKAGES[stage]], check=True)
        print(f"{stage}: {exe}")

if __name__ == "__main__":
    main()
