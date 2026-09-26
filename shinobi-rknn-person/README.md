# Shinobi RKNN Person Detector

Remote Shinobi object-detection plugin for Rockchip RK3588. It receives detector JPEG frames from Shinobi over Socket.IO, runs a YOLOv8n RKNN model through RKNNLite, and returns only `person` matrices to Shinobi.

The first target is a Radxa CM5 / RK3588 running Debian 12 with:

- RKNPU kernel driver working
- `rknpu2-rk3588`
- `python3-rknnlite2`
- `python3-opencv`
- a converted YOLOv8n `.rknn` model

## Layout

Shinobi remains the NVR and owns both cameras. The detector does not open RTSP streams itself.

```
Camera 1 ---\
             > Shinobi on Pi 400 -- detector JPEG --> RK3588 plugin
Camera 2 ---/                                      <-- person matrices
```

## 1. Clone and install on the RK3588

```bash
git clone https://github.com/staberas/PlaygroundAgent.git
cd PlaygroundAgent
git checkout feature/shinobi-rknn-detector
cd shinobi-rknn-person
chmod +x install.sh
./install.sh
```

The installer creates a venv with `--system-site-packages` so it can reuse the board's working Debian packages for `rknnlite` and OpenCV.

## 2. Configure the plugin

```bash
cp config.example.json config.json
nano config.json
```

Important fields:

```json
{
  "plug": "rknn-person",
  "host": "SHINOBI_LAN_IP",
  "port": 8080,
  "key": "SAME_SECRET_AS_SHINOBI",
  "model_path": "/home/stabpi3/rknn_model_zoo/examples/yolov8/model/yolov8.rknn",
  "person_threshold": 0.50
}
```

`host` is the LAN address of the Pi 400 running Shinobi, not a Kubernetes address.

## 3. Add the matching key to Shinobi

In Shinobi's main `conf.json`, add the plugin under `pluginKeys` using the same plugin ID and secret:

```json
{
  "pluginKeys": {
    "rknn-person": "SAME_SECRET_AS_SHINOBI"
  }
}
```

If `pluginKeys` already has entries, add this one without replacing them. Restart Shinobi after editing the configuration.

## 4. Local RKNNLite self-test

Before connecting to Shinobi:

```bash
.venv/bin/python plugin.py \
  --config config.json \
  --self-test ~/camera-test.jpg
```

When a person is visible, the JSON output contains a `matrices` array with `tag: "person"`, confidence, and coordinates.

## 5. Connect to Shinobi

```bash
.venv/bin/python plugin.py --config config.json
```

Expected startup:

```
[shinobi] connected to SHINOBI_IP:8080
```

When a detector frame contains a person:

```
[detect] GROUP/MONITOR person x1 [0.88] 25.1 ms
```

The plugin sends Shinobi detector triggers with:

- `f: "trigger"`
- `reason: "object"`
- `details.matrices[]`
- `tag: "person"`
- x/y/width/height
- confidence
- detector image dimensions
- the source JPEG frame

## 6. Shinobi monitor settings

Enable object detection for each desired monitor. Start with:

- 2 cameras
- 2-3 detector FPS each
- detector resolution around 640x480
- person threshold 0.50

The RK3588 test model was stable at about 25 ms per inference, so this target workload has substantial headroom.

## Design notes

- Only COCO class 0 (`person`) is returned.
- The queue is bounded; stale frames are dropped instead of building detection latency.
- The RKNN model is loaded once and remains resident.
- Preprocessing uses black letterboxing to match Rockchip's YOLOv8 model-zoo path.
- NMS is performed only for person boxes.
- The first validation is intentionally bare-metal. After a real Shinobi event works for one camera, add the second camera, then containerize the same process for K3s.
