#!/usr/bin/env python3
import argparse
import json
import queue
import signal
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import socketio
from rknnlite.api import RKNNLite


def sigmoid_softmax(x, axis):
    x = x - np.max(x, axis=axis, keepdims=True)
    exp = np.exp(x)
    return exp / np.sum(exp, axis=axis, keepdims=True)


class PersonDetector:
    def __init__(self, model_path, threshold=0.50, nms_threshold=0.45, input_size=640):
        self.threshold = float(threshold)
        self.nms_threshold = float(nms_threshold)
        self.input_size = int(input_size)
        self.rknn = RKNNLite()

        ret = self.rknn.load_rknn(str(model_path))
        if ret != 0:
            raise RuntimeError(f"load_rknn failed: {ret}")

        ret = self.rknn.init_runtime()
        if ret != 0:
            raise RuntimeError(f"init_runtime failed: {ret}")

    def close(self):
        self.rknn.release()

    def _letterbox(self, image):
        h, w = image.shape[:2]
        scale = min(self.input_size / w, self.input_size / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)

        left = (self.input_size - nw) // 2
        top = (self.input_size - nh) // 2
        canvas = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        canvas[top:top + nh, left:left + nw] = resized
        return canvas, scale, left, top

    @staticmethod
    def _dfl(position):
        n, c, h, w = position.shape
        bins = c // 4
        y = position.reshape(n, 4, bins, h, w)
        y = sigmoid_softmax(y, axis=2)
        weights = np.arange(bins, dtype=np.float32).reshape(1, 1, bins, 1, 1)
        return np.sum(y * weights, axis=2)

    def _box_process(self, position):
        grid_h, grid_w = position.shape[2:4]
        col, row = np.meshgrid(np.arange(grid_w), np.arange(grid_h))
        grid = np.concatenate(
            (
                col.reshape(1, 1, grid_h, grid_w),
                row.reshape(1, 1, grid_h, grid_w),
            ),
            axis=1,
        )
        stride = np.array(
            [self.input_size // grid_w, self.input_size // grid_h],
            dtype=np.float32,
        ).reshape(1, 2, 1, 1)

        position = self._dfl(position)
        xy1 = grid + 0.5 - position[:, 0:2, :, :]
        xy2 = grid + 0.5 + position[:, 2:4, :, :]
        return np.concatenate((xy1 * stride, xy2 * stride), axis=1)

    @staticmethod
    def _flatten(tensor):
        channels = tensor.shape[1]
        return tensor.transpose(0, 2, 3, 1).reshape(-1, channels)

    def _nms(self, boxes, scores):
        if len(boxes) == 0:
            return []

        x1, y1, x2, y2 = boxes.T
        areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        order = scores.argsort()[::-1]
        keep = []

        while order.size:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            inter = inter_w * inter_h
            union = areas[i] + areas[order[1:]] - inter
            iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)

            remaining = np.where(iou <= self.nms_threshold)[0]
            order = order[remaining + 1]

        return keep

    def _postprocess_person(self, outputs):
        # Rockchip's optimized YOLOv8 graph exposes three detection branches.
        # Each branch has box-distribution output followed by class scores
        # (and may also include score-sum outputs that are intentionally ignored).
        branches = 3
        per_branch = len(outputs) // branches
        if per_branch < 2:
            raise RuntimeError(f"Unexpected YOLOv8 output count: {len(outputs)}")

        all_boxes = []
        all_scores = []

        for branch in range(branches):
            box_tensor = outputs[per_branch * branch]
            class_tensor = outputs[per_branch * branch + 1]

            boxes = self._flatten(self._box_process(box_tensor))
            class_scores = self._flatten(class_tensor)

            # COCO class 0 == person. We intentionally ignore every other class.
            person_scores = class_scores[:, 0]
            mask = person_scores >= self.threshold
            if np.any(mask):
                all_boxes.append(boxes[mask])
                all_scores.append(person_scores[mask])

        if not all_boxes:
            return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

        boxes = np.concatenate(all_boxes)
        scores = np.concatenate(all_scores)
        keep = self._nms(boxes, scores)
        return boxes[keep], scores[keep]

    def detect_jpeg(self, jpeg_bytes):
        encoded = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("OpenCV could not decode Shinobi frame")

        original_h, original_w = frame.shape[:2]
        padded, scale, pad_x, pad_y = self._letterbox(frame)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)

        started = time.perf_counter()
        # RKNNLite requires an explicit batch dimension for this static model.
        # Input shape must be 1xHxWxC, not HxWxC.
        batched = np.expand_dims(rgb, axis=0)
        outputs = self.rknn.inference(inputs=[batched])
        inference_ms = (time.perf_counter() - started) * 1000.0
        if outputs is None:
            raise RuntimeError("RKNN inference returned no outputs")

        boxes, scores = self._postprocess_person(outputs)
        matrices = []

        for box, score in zip(boxes, scores):
            x1, y1, x2, y2 = [float(v) for v in box]

            x1 = (x1 - pad_x) / scale
            x2 = (x2 - pad_x) / scale
            y1 = (y1 - pad_y) / scale
            y2 = (y2 - pad_y) / scale

            x1 = max(0.0, min(x1, original_w - 1))
            y1 = max(0.0, min(y1, original_h - 1))
            x2 = max(0.0, min(x2, original_w))
            y2 = max(0.0, min(y2, original_h))

            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            if width < 1 or height < 1:
                continue

            matrices.append(
                {
                    "x": x1,
                    "y": y1,
                    "width": width,
                    "height": height,
                    "tag": "person",
                    "confidence": float(score),
                }
            )

        return matrices, original_w, original_h, inference_ms


class ShinobiRKNNPlugin:
    def __init__(self, config):
        self.config = config
        self.detector = PersonDetector(
            config["model_path"],
            threshold=config.get("person_threshold", 0.50),
            nms_threshold=config.get("nms_threshold", 0.45),
            input_size=config.get("input_size", 640),
        )
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_delay=3,
            logger=False,
            engineio_logger=False,
        )
        self.frame_chunks = {}
        self.jobs = queue.Queue(maxsize=int(config.get("queue_size", 4)))
        self.running = True
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._register_socket_handlers()

    @property
    def plug(self):
        return self.config.get("plug", "rknn-person")

    def _register_socket_handlers(self):
        @self.sio.event
        def connect():
            print(f"[shinobi] connected to {self.config['host']}:{self.config['port']}")
            self.sio.emit(
                "ocv",
                {
                    "f": "init",
                    "plug": self.plug,
                    "notice": self.config.get("notice", "RK3588 RKNN YOLOv8 person detector"),
                    "type": "detector",
                    "connectionType": "websocket",
                    "pluginKey": self.config["key"],
                },
            )

        @self.sio.event
        def disconnect():
            print("[shinobi] disconnected")

        @self.sio.on("f")
        def on_plugin_event(data):
            try:
                self._handle_plugin_event(data)
            except Exception as exc:
                print(f"[shinobi] event error: {exc}")

    def _enqueue(self, frame, metadata):
        job = (bytes(frame), metadata)
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            # Detector frames are time-sensitive. Drop the oldest instead of
            # allowing latency to grow behind real time.
            try:
                self.jobs.get_nowait()
                self.jobs.task_done()
            except queue.Empty:
                pass
            try:
                self.jobs.put_nowait(job)
            except queue.Full:
                pass

    def _handle_plugin_event(self, data):
        event_type = data.get("f")

        if event_type == "frameFromRam":
            frame = data.get("buffer")
            if frame:
                self._enqueue(frame, data)
            return

        if event_type != "frame":
            return

        chunk = data.get("frame")
        if chunk is None:
            return

        if isinstance(chunk, list):
            chunk = bytes(chunk)
        elif not isinstance(chunk, (bytes, bytearray)):
            chunk = bytes(chunk)

        key = f"{data.get('id', '')}{data.get('ke', '')}"
        chunks = self.frame_chunks.setdefault(key, [])
        chunks.append(chunk)

        # Shinobi may split a JPEG over multiple socket messages.
        if len(chunk) >= 2 and chunk[-2:] == b"\xff\xd9":
            frame = b"".join(chunks)
            self.frame_chunks.pop(key, None)
            self._enqueue(frame, data)

    def _worker_loop(self):
        while self.running:
            try:
                frame, data = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                matrices, width, height, inference_ms = self.detector.detect_jpeg(frame)
                if matrices:
                    payload = {
                        "f": "trigger",
                        "id": data.get("id"),
                        "ke": data.get("ke"),
                        "details": {
                            "plug": self.plug,
                            "name": "rk3588-yolov8-person",
                            "reason": "object",
                            "matrices": matrices,
                            "imgWidth": width,
                            "imgHeight": height,
                            "time": round(inference_ms, 2),
                        },
                    }
                    if self.config.get("return_frame", True):
                        payload["frame"] = frame

                    self.sio.emit(
                        "ocv",
                        {
                            **payload,
                            "pluginKey": self.config["key"],
                            "plug": self.plug,
                        },
                    )

                    summary = ", ".join(f"{m['confidence']:.2f}" for m in matrices)
                    print(
                        f"[detect] {data.get('ke')}/{data.get('id')} "
                        f"person x{len(matrices)} [{summary}] {inference_ms:.1f} ms"
                    )
            except Exception as exc:
                print(f"[detect] error: {exc}")
            finally:
                self.jobs.task_done()

    def run(self):
        self.worker.start()
        scheme = "https" if self.config.get("https", False) else "http"
        url = f"{scheme}://{self.config['host']}:{self.config['port']}"
        self.sio.connect(url, transports=["websocket"])
        self.sio.wait()

    def close(self):
        self.running = False
        try:
            self.sio.disconnect()
        except Exception:
            pass
        self.detector.close()


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    required = ("host", "port", "key", "model_path")
    missing = [name for name in required if not config.get(name)]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")

    config["model_path"] = str(Path(config["model_path"]).expanduser().resolve())
    if not Path(config["model_path"]).is_file():
        raise FileNotFoundError(config["model_path"])
    return config


def main():
    parser = argparse.ArgumentParser(description="Shinobi RK3588 RKNN person detector")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--self-test", help="Run one JPEG through RKNN and exit")
    args = parser.parse_args()

    config = load_config(args.config)
    plugin = ShinobiRKNNPlugin(config)

    if args.self_test:
        jpeg = Path(args.self_test).read_bytes()
        matrices, width, height, ms = plugin.detector.detect_jpeg(jpeg)
        print(json.dumps({
            "width": width,
            "height": height,
            "inference_ms": round(ms, 2),
            "matrices": matrices,
        }, indent=2))
        plugin.close()
        return

    def stop(_sig, _frame):
        plugin.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    plugin.run()


if __name__ == "__main__":
    main()
