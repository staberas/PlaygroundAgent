# Image Library Toolkit

Rebuild of the uploaded img-renamer and caption prototypes. **No model files committed.** Works on Windows and Linux.

## Architecture

A single **launcher** (`python app.py`) handles scanning, CSV editing and invoking isolated detectors. No activation/switching of environments during normal use: each optional worker has its own interpreter, configured in `config.json`.

- `scan`: walks an image directory and records filenames in a CSV.
- `nudenet`: current NudeNet detector; writes `nude` flags and scored detections.
- `yolo`: Ultralytics objects; writes `yolo` labels.
- `ocr`: EasyOCR; writes extracted text.
- `nsfw`: TensorFlow/Keras or TFLite NSFWJS model (requires local weights); five-class scores.
- `caption`: optional JoyCaption/LLaVA model in a *separate* heavy environment; writes caption text.
- `rules`: generate a JSON classification summary per image, no file moves or renames.

All worker stages skip ignored rows, retain existing data by default, save incrementally, and report failures without silently treating failed analysis as safe. `--force` recomputes a stage.

## Setup

Python 3.10+ recommended for the main app. Windows example (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-main.txt
.\.venv\Scripts\python.exe setup_envs.py --nudenet --yolo --ocr
.\.venv\Scripts\python.exe app.py
```

Linux: replace `py -3.11` with `python3`, and `Scripts\python.exe` with `bin/python`. Install tkinter using your distribution if missing. For the optional TensorFlow or JoyCaption environments, inspect `requirements-optional.txt` and install/select compatible PyTorch/CUDA wheels yourself, then run `setup_envs.py --nsfw` or `--caption`.

Edit `config.json` if the environment paths, model paths, or Python versions differ. All paths are relative to the project folder unless absolute. `setup_envs.py` creates `.venvs/<stage>/` and does **not** overwrite existing environments. The main app can run with only Python's standard library; `requirements-main.txt` is informational.

## Usage

```shell
python app.py scan "/path/to/images" --recursive
python app.py status
python app.py run nudenet
python app.py run yolo
python app.py run ocr
python app.py run nsfw
python app.py run caption
python app.py rules
python app.py gui
```

Optionally pass `--csv /path/to/imgscan.csv` before a subcommand and `--force` on `run`. `python app.py` opens the GUI. The GUI runs workers in a background thread and refreshes results on completion.

## CSV contract

`path,filename,extension,ignore,yolo,nude,nsfw,ocr,caption,new_file_name,other`. Detector outputs are JSON where applicable. `new_file_name` is a **proposal**, never applied to disk. Original scan paths and manually edited values remain stable; rescanning merges by absolute path. CSV writes use atomic replacement.

## Caveats

This is an engineering rebuild based on the two ZIPs; models were omitted from the uploads, so end-to-end inference **has not been verified** against your model weights. NudeNet flags are heuristic summaries of scored detections, not reliable human labels. Artistic/illustrated images can be misclassified. For best results, compare NSFWJS, NudeNet and captions, inspect low-confidence cases, and keep a manual review step. Do not use model results as proof of age or consent.

## Installing models and fixing existing CSVs (October 2026)

Update this folder from GitHub first. NudeNet already includes its ONNX weights in the `nudenet` pip package; its model **does not** need an additional download. Install/reinstall that environment with `python setup_envs.py --nudenet`.

For the five-category NSFW model (legacy GantMan MobileNet v2), download the verified upstream filename to the configured path:

```powershell
.\.venv\Scripts\python.exe setup_envs.py --nsfw
.\.venv\Scripts\python.exe install_models.py --nsfw --nudenet
.\.venv\Scripts\python.exe app.py run nsfw
.\.venv\Scripts\python.exe app.py run nudenet --force
.\.venv\Scripts\python.exe app.py rules
```

The installer sources NSFW weights from the original maintainer's historical S3 URL. Keep `models/nsfw_mobilenet2.224x224.h5` out of Git. This is an older Keras/HDF5 model and modern TensorFlow/Keras installations **may reject its serialization**; in that case capture the traceback so we can pin a compatible version, rather than changing model formats blindly.

**Existing CSV migration:** Older runs wrote NudeNet output under the unintended `nudenet` column while rules only read `nude`. The rules now read both, preferring `nude`. Fresh NudeNet runs write to `nude` and `--force` recomputes them. Previously exported `.rules.json` is stale until you run `app.py rules` again. In the uploaded 48-row sample, `nudenet` contains 48 populated results while `nude` and `nsfw` are entirely empty.
