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


## K3s deployment

The production-shaped deployment pins the detector to `radxa-cm5-io` and keeps Shinobi itself outside the cluster on the LAN.

### Build the ARM64 image on radxa-cm5-io

Pull the current branch first:

```bash
cd ~/PlaygroundAgent
git checkout feature/shinobi-rknn-detector
git pull
cd shinobi-rknn-person
```

If Docker is installed:

```bash
sudo docker build -t shinobi-rknn-person:local .
sudo docker save shinobi-rknn-person:local -o /tmp/shinobi-rknn-person.tar
sudo k3s ctr images import /tmp/shinobi-rknn-person.tar
```

If Podman is installed instead:

```bash
podman build -t shinobi-rknn-person:local .
podman save --format docker-archive -o /tmp/shinobi-rknn-person.tar shinobi-rknn-person:local
sudo k3s ctr images import /tmp/shinobi-rknn-person.tar
```

Verify that K3s sees it:

```bash
sudo k3s ctr images list | grep shinobi-rknn-person
```

### Create the Secret

```bash
cd ~/PlaygroundAgent/shinobi-rknn-person/k8s
cp secret.example.yaml secret.yaml
nano secret.yaml
```

Put the exact plugin key already paired with Shinobi into `SHINOBI_PLUGIN_KEY`.

The Secret file is gitignored.

### Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

Then follow logs:

```bash
kubectl -n shinobi-ai logs -f deployment/shinobi-rknn-person
```

Expected output includes the RKNN runtime/driver information, followed by:

```
[shinobi] connected to 192.168.192.162:8080
[detect] GROUP/MONITOR person x1 [0.87] 22.0 ms
```

### Why hostPath is used

This first K3s deployment deliberately reuses the already-proven host installation:

- `/usr/lib/python3/dist-packages/rknnlite`
- `/usr/lib/aarch64-linux-gnu` for `librknnrt`
- `/dev/dri` for the RK3588 RKNPU DRM device
- the already-converted `yolov8.rknn`

That minimizes variables. Once the pod is proven, those runtime files can be baked into a dedicated image and the security context narrowed.
