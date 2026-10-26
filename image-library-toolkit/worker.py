"""Optional per-stage ML worker; launched with stage-specific interpreter."""
import argparse
import json
import os
from pathlib import Path

from pipeline import read_rows, write_rows, should_skip, normalize_path

def infer(stage, path, config, cache):
    models = config.get("models", {})
    settings = config.get("settings", {})
    if stage == "nudenet":
        if "engine" not in cache:
            from nudenet import NudeDetector
            cache["engine"] = NudeDetector()
        dets = cache["engine"].detect(str(path)) or []
        threshold = float(settings.get("nudenet_threshold", 0.35))
        dets = [d for d in dets if float(d.get("score", 0)) >= threshold]
        names = [str(d.get("class", "")) for d in dets]
        return json.dumps({
            "person": any("FACE" in n or "PERSON" in n for n in names),
            "sexy": any(n.endswith(("_COVERED", "_EXPOSED")) and not n.startswith(("FEET_", "ARMPITS_", "BELLY_")) for n in names),
            "nude": any(n.endswith("_EXPOSED") and n.startswith(("FEMALE_BREAST_", "FEMALE_GENITALIA_", "MALE_GENITALIA_", "BUTTOCKS_", "ANUS_")) for n in names),
            "top_classes": [d.get("class") for d in sorted(dets, key=lambda d: float(d.get("score", 0)), reverse=True)[:3]],
            "detections": dets,
        }, ensure_ascii=False)
    if stage == "yolo":
        if "engine" not in cache:
            from ultralytics import YOLO
            model_file = normalize_path(models.get("yolo", "models/yolo.pt"))
            if not model_file.is_file():
                raise FileNotFoundError(f"YOLO model not found: {model_file}")
            cache["engine"] = YOLO(str(model_file))
        result = cache["engine"].predict(source=str(path), verbose=False)[0]
        labels = []
        for box in result.boxes:
            idx = int(box.cls[0].item())
            label = str(result.names[idx])
            if label not in labels:
                labels.append(label)
        return json.dumps(labels[:12], ensure_ascii=False)
    if stage == "ocr":
        if "engine" not in cache:
            import easyocr
            cache["engine"] = easyocr.Reader(["en"], gpu=False)
        return json.dumps(cache["engine"].readtext(str(path), detail=0), ensure_ascii=False)
    if stage == "nsfw":
        import numpy as np
        from PIL import Image
        if "engine" not in cache:
            model_path = normalize_path(models.get("nsfw", "models/nsfw_mobilenet2.224x224.h5"))
            if not model_path.exists():
                raise FileNotFoundError(f"NSFW model not found: {model_path}")
            import tensorflow as tf
            if model_path.suffix.lower() == ".tflite":
                engine = tf.lite.Interpreter(model_path=str(model_path))
                engine.allocate_tensors()
                cache["input"], cache["output"] = engine.get_input_details()[0], engine.get_output_details()[0]
            else:
                import tensorflow_hub as hub
                engine = tf.keras.models.load_model(
                    str(model_path),
                    custom_objects={"KerasLayer": hub.KerasLayer},
                    compile=False,
                )
            cache["engine"] = engine
        im = Image.open(path).convert("RGB").resize((224, 224))
        x = np.asarray(im, dtype=np.float32)
        if "input" not in cache:
            from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
            x = preprocess_input(x)
        else:
            x = x / 255.0
        x = np.expand_dims(x, 0)
        engine = cache["engine"]
        if "input" in cache:
            spec = cache["input"]
            if spec["dtype"] == np.uint8:
                scale, zero = spec["quantization"]
                x = np.clip(np.round(x / scale + zero), 0, 255).astype(np.uint8)
            else:
                x = x.astype(spec["dtype"])
            engine.set_tensor(spec["index"], x)
            engine.invoke()
            y = engine.get_tensor(cache["output"]["index"])[0]
            if cache["output"]["dtype"] == np.uint8:
                scale, zero = cache["output"]["quantization"]
                y = (y.astype(np.float32) - zero) * scale
        else:
            y = engine.predict(x, verbose=0)[0]
        classes = ["drawings", "hentai", "neutral", "porn", "sexy"]
        return json.dumps(dict(zip(classes, map(float, y))), ensure_ascii=False)
    if stage == "caption":
        if "engine" not in cache:
            import torch
            from transformers import LlavaForConditionalGeneration, AutoProcessor
            model_dir = normalize_path(models.get("caption", "models/joycaption"))
            if not model_dir.exists():
                raise FileNotFoundError(f"Caption model not found: {model_dir}")
            processor = AutoProcessor.from_pretrained(str(model_dir))
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            model = LlavaForConditionalGeneration.from_pretrained(str(model_dir), torch_dtype=dtype, device_map="auto")
            model.eval()
            cache["engine"], cache["processor"] = model, processor
        import torch
        from PIL import Image
        model, processor = cache["engine"], cache["processor"]
        prompt = settings.get("caption_prompt", "Describe the image.")
        conversation = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = processor.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True)
        with Image.open(path) as source:
            image = source.convert("RGB")
            inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=int(settings.get("caption_max_tokens", 160)), do_sample=False)
        generated = ids[:, inputs["input_ids"].shape[-1]:]
        return processor.batch_decode(generated, skip_special_tokens=True)[0].strip()
    raise ValueError("Unknown stage: " + stage)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["nudenet", "yolo", "ocr", "nsfw", "caption"])
    ap.add_argument("--csv", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    config = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    csv_path = Path(args.csv).resolve()
    rows, columns = read_rows(csv_path)
    output_column = "nude" if args.stage == "nudenet" else args.stage
    if output_column not in columns:
        columns.append(output_column)
    cache, failed, processed = {}, 0, 0
    for index, row in enumerate(rows, 1):
        if should_skip(row, output_column, args.force):
            continue
        path = Path(row.get("path", ""))
        try:
            if not path.is_file():
                raise FileNotFoundError(path)
            row[output_column] = infer(args.stage, path, config, cache)
            row["other"] = row.get("other", "")
            processed += 1
            print(f"[{index}/{len(rows)}] OK: {path}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(rows)}] ERROR: {path}: {type(exc).__name__}: {exc}", flush=True)
            if args.stage == "nsfw" and "engine" not in cache:
                print("NSFW model failed to initialize; stopping instead of repeating the error for every image.", flush=True)
                break
        write_rows(csv_path, rows, columns)
    print(f"Finished {args.stage}: {processed} processed, {failed} failures", flush=True)
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
