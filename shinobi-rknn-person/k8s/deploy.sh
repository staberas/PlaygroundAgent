#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$HERE/secret.yaml" ]; then
  echo "Missing $HERE/secret.yaml"
  echo "Copy secret.example.yaml to secret.yaml and insert the existing Shinobi plugin key."
  exit 1
fi

kubectl apply -f "$HERE/namespace.yaml"
kubectl apply -f "$HERE/configmap.yaml"
kubectl apply -f "$HERE/secret.yaml"
kubectl apply -f "$HERE/deployment.yaml"

kubectl -n shinobi-ai rollout status deployment/shinobi-rknn-person
kubectl -n shinobi-ai get pods -o wide
