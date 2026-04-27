#!/bin/bash
set -e

CONTROL_NODE_IP="192.168.100.21"

GPIOCHIP="gpiochip14"
GPIO_LINE="2"

SCRIPT_PATH="/usr/local/sbin/lpi3h-watchdog.sh"
SERVICE_PATH="/etc/systemd/system/lpi3h-watchdog.service"
KUBECONFIG_PATH="/root/.kube/config"

echo "[1/6] Installing required tools..."
sudo apt update
sudo apt install -y gpiod kubernetes-client

echo "[2/6] Preparing root kubeconfig..."
sudo mkdir -p /root/.kube

if [ ! -f "$HOME/.kube/config" ]; then
    echo "ERROR: $HOME/.kube/config does not exist."
    echo "Create/copy kubeconfig first, then rerun this installer."
    exit 1
fi

sudo cp "$HOME/.kube/config" "$KUBECONFIG_PATH"
sudo sed -i "s#server: https://127.0.0.1:6443#server: https://${CONTROL_NODE_IP}:6443#g" "$KUBECONFIG_PATH"
sudo sed -i "s#server: https://localhost:6443#server: https://${CONTROL_NODE_IP}:6443#g" "$KUBECONFIG_PATH"
sudo chmod 600 "$KUBECONFIG_PATH"

echo "[3/6] Testing kubectl access..."
if ! sudo KUBECONFIG="$KUBECONFIG_PATH" kubectl get --raw='/readyz' --request-timeout=10s >/dev/null 2>&1; then
    echo "ERROR: kubectl cannot reach Kubernetes API."
    echo "Check kubeconfig server points to https://${CONTROL_NODE_IP}:6443"
    sudo grep server "$KUBECONFIG_PATH" || true
    exit 1
fi

echo "[4/6] Creating watchdog script..."
sudo tee "$SCRIPT_PATH" >/dev/null <<EOF
#!/bin/bash

CHECK_INTERVAL=30
FAIL_AFTER=300
BOOT_WAIT=300
STARTUP_DELAY=600

GPIOCHIP="${GPIOCHIP}"
GPIO_LINE="${GPIO_LINE}"
KUBECONFIG_PATH="${KUBECONFIG_PATH}"

LOG_TAG="lpi3h-watchdog"

log() {
    logger -t "\$LOG_TAG" "\$1"
    echo "\$(date '+%F %T') \$1"
}

is_alive() {
    /usr/bin/kubectl \
      --kubeconfig "\$KUBECONFIG_PATH" \
      get --raw='/readyz' \
      --request-timeout=10s >/dev/null 2>&1
}

restart_lpi3h() {
    log "Kubernetes API unresponsive for 5 minutes. Power cycling LPI3H."

    /usr/bin/gpioset "\$GPIOCHIP" "\$GPIO_LINE=0"
    sleep 8
    /usr/bin/gpioset "\$GPIOCHIP" "\$GPIO_LINE=1"

    sleep 3

    /usr/bin/gpioset "\$GPIOCHIP" "\$GPIO_LINE=0"
    sleep 1
    /usr/bin/gpioset "\$GPIOCHIP" "\$GPIO_LINE=1"

    log "Power cycle sent. Waiting 5 minutes before recheck."
    sleep "\$BOOT_WAIT"
}

log "Watchdog started. Waiting 10 minutes before first check."
sleep "\$STARTUP_DELAY"

fail_seconds=0

while true; do
    if is_alive; then
        if [ "\$fail_seconds" -gt 0 ]; then
            log "Kubernetes API recovered."
        fi
        fail_seconds=0
    else
        fail_seconds=\$((fail_seconds + CHECK_INTERVAL))
        log "Kubernetes API unreachable for \${fail_seconds}s."

        if [ "\$fail_seconds" -ge "\$FAIL_AFTER" ]; then
            restart_lpi3h
            fail_seconds=0
        fi
    fi

    sleep "\$CHECK_INTERVAL"
done
EOF

sudo chmod +x "$SCRIPT_PATH"

echo "[5/6] Creating systemd service..."
sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=LPI3H Control Plane Watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${SCRIPT_PATH}
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "[6/6] Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now lpi3h-watchdog.service

echo
echo "Installed."
echo "Check status:"
echo "  sudo systemctl status lpi3h-watchdog.service"
echo
echo "Follow logs:"
echo "  journalctl -u lpi3h-watchdog.service -f"
