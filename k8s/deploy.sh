#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Deploying Sentra to Kubernetes ==="

# 1. Create namespace
echo "[1/5] Creating namespace..."
kubectl apply -f namespace.yaml

# 2. Apply secrets (if present)
if [ -f "secrets/secret.yaml" ]; then
  echo "[2/5] Applying secrets..."
  kubectl apply -f secrets/secret.yaml
else
  echo "[2/5] No secrets/secret.yaml found — skipping"
  echo "  Create it: cp secrets/example-secret.yaml secrets/secret.yaml"
  echo "  Then edit secrets/secret.yaml with your AI Hub API key"
fi

# 3. Apply all resources via Kustomize
echo "[3/5] Applying Kustomize manifests..."
kubectl apply -k .

# 4. Wait for pods
echo "[4/5] Waiting for pods to be ready..."

echo "  Waiting for Qdrant..."
kubectl wait --for=condition=ready pod -l app=sentra-qdrant -n sentra --timeout=120s

echo "  Waiting for backend..."
kubectl wait --for=condition=ready pod -l app=sentra-backend -n sentra --timeout=120s

echo "  Waiting for frontend..."
kubectl wait --for=condition=ready pod -l app=sentra-frontend -n sentra --timeout=60s

# 5. Status
echo "[5/5] Checking status..."
kubectl get pods -n sentra

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Verify:"
echo "  kubectl get pods -n sentra"
echo "  kubectl logs -f -n sentra -l app=sentra-backend"
echo ""
echo "Port-forward to test locally:"
echo "  kubectl port-forward -n sentra svc/sentra-frontend 3000:80"
echo "  Open http://localhost:3000"
echo ""
echo "Upload documents to the PVC:"
echo "  kubectl cp ./documents/ sentra/<backend-pod>:/data/Ausarbeitungen/"
echo ""
echo "Trigger ingestion:"
echo "  curl -X POST http://sentra.aisc.hpi.de/api/ingest"
