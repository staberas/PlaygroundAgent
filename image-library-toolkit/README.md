# Image Library Toolkit

Rebuild of the uploaded img-renamer and caption prototypes. **No model files committed.** Works on Windows and Linux.

## Architecture

A single **launcher** (`python app.py`) handles scanning, CSV editing and invoking isolated detectors. No activation/switching of environments during normal use: each optional worker has its own interpreter, configured in `config.json`.

- `scan`: walks an image directory and records filenames in a CSV.
- `nudenet`: current NudeNet detector; writes `nude` flags and scored detections.
- `yolo`: Ultralytics objects; writes `yolo` labels.
- `ocr`: EasyOCR; writes extracted text.
- `nsfw`: TensorFlow/Keras or TFLite NSFWJS model (requires local weights); five-class scores.
- `smilingwolf`: WD ViT Tagger v3 ratings and general/character image tags, in its own environment.
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

Linux: replace `py -3.11` with `python3`, and `Scripts\python.exe` with `bin/python`. Install tkinter using your distribution if missing. For the optional TensorFlow and SmilingWolf environments, inspect `requirements-optional.txt` and install/select compatible PyTorch/CUDA wheels yourself, then run `setup_envs.py --nsfw` or `--caption`.

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

### NSFW legacy KerasLayer fix

The 54-image log showed NSFW model deserialization failing with `Unknown layer: 'KerasLayer'`. The worker now registers `tensorflow_hub.KerasLayer` as a custom object. The NSFW environment is pinned to `tensorflow==2.15.1` with `tensorflow-hub==0.15.0` and `numpy<2` for its legacy HDF5 architecture. This is a compatibility attempt based on the model's TensorFlow Hub layer, not yet machine-tested. Upgrade the *existing isolated NSFW environment* with:

```powershell
.\.venv\Scripts\python.exe setup_envs.py --nsfw
.\.venv\Scripts\python.exe app.py run nsfw
```

The runner now stops after the first model-initialization error instead of logging the same error for each image.

### Marqo detector (SFW/NSFW)

Uses the official [Marqo/nsfw-image-detection-384](https://huggingface.co/Marqo/nsfw-image-detection-384) model via `timm`. The model is cached automatically in the Hugging Face cache on first use; no manual naming required. Install/download once:

```powershell
.\.venv\Scripts\python.exe setup_envs.py --marqo
.\.venv\Scripts\python.exe install_models.py --marqo
.\.venv\Scripts\python.exe app.py run marqo
.\.venv\Scripts\python.exe app.py rules
```

Outputs JSON probabilities `{"NSFW": ..., "SFW": ...}` into the new `marqo` CSV column. The review rules flag Marqo NSFW >= 0.75 as **suggestive/review**, not automatically explicit, alongside the previous NudeNet and legacy NSFW checks. For repeat scans, completed rows are skipped unless `--force` is used. Marqo's scores are not calibrated against your dataset; visually review disagreements.

## SmilingWolf (replaces caption)

The **JoyCaption** stage has been removed from the active application because the heavyweight model offloaded to RAM/disk and the chat template failed. Existing `caption` CSV data is preserved as a legacy column, but new scans use `smilingwolf`.

```powershell
.\.venv\Scripts\python.exe setup_envs.py --smilingwolf
.\.venv\Scripts\python.exe install_models.py --smilingwolf
.\.venv\Scripts\python.exe app.py run smilingwolf
.\.venv\Scripts\python.exe app.py rules
```

This uses [SmilingWolf/wd-vit-tagger-v3](https://huggingface.co/SmilingWolf/wd-vit-tagger-v3), including its official `selected_tags.csv` for reliable tag/category mapping. Category IDs 9=rating, 0=general, 4=character. Outputs `ratings`, `general_tags`, and `character_tags`. The output is cached in your scan CSV and weights in Hugging Face's local cache. SmilingWolf is Danbooru-focused; photographic classification should still use Marqo/NudeNet.

## Faster OCR

By default OCR uses CUDA GPU **only when the installed torch supports CUDA**, otherwise CPU. A normal AMD Radeon GPU on Windows does **not** enable CUDA, so CPU fallback is expected. To see the selected backend run `app.py run ocr --force`; the worker prints it at startup. OCR settings in `config.json`: `ocr_gpu` ("auto", "false", "true"), `ocr_canvas_size` (1280 by default vs EasyOCR's larger standard), `ocr_batch_size` (4), `ocr_mag_ratio` (1.0), and OCR detection thresholds. Reducing the canvas size accelerates processing of large images but may miss very small text. For NVIDIA CUDA, install CUDA-enabled PyTorch *inside* `.venvs/ocr` following [official EasyOCR installation](https://jaided.ai/easyocr/install/). Re-run OCR with `--force` to benchmark changed settings against existing entries.

## Automatic folder assignment (no file moves)

Run `python app.py assign` or click **Assign folders**. Routes each unignored image to exactly one suggested destination: `SFW/{Cosplay,General,Anime,Meme}` or `NSFW/{Cosplay,General,Anime,Meme}`. Writes `destination_folder`, `route_review`, `route_confidence` and `route_reason` into the CSV. The system **does not create folders, move files or rename them**. Double-click `destination_folder` in the table to override manually; CLI `assign --force` recalculates existing suggestions. The GUI's Assign folders button explicitly recomputes suggestions.

Routing uses available existing scores from NudeNet, legacy NSFW classifier, Marqo and WD Tagger. Explicit anatomy, strong WD explicit/questionable ratings, and agreement across models weigh more than Marqo alone. For borderline or conflicting predictions, `route_review=yes` requests inspection. Subcategory classification relies on high-confidence relevant WD tags; cosplay requires costume/photo evidence, memes require text/screenshot or meme evidence, and anime uses character/illustration signals. Remaining images default to General.

This is a **heuristic prototype**; thresholds were not statistically calibrated. `route_confidence` is a heuristic ranking, **not a probability**. Always manually review decisions before building a future file mover; even `SFW` predictions can contain mistakes. Existing CSV data and legacy columns are retained.
