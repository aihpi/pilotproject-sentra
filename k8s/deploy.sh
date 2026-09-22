#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Deploying Sentra to Kubernetes ==="

# 1. Create namespace
echo "[1/5] Creating namespace..."
kubectl apply -f namespace.yaml

# 2. Apply all resources via Kustomize
#
# First deploy after the Qdrant version pin: if the qdrant pod fails to start,
# its volume may hold data written by the previous 1.13.6 image, which 1.19 will
# not open. This is a prototype, so discard it and re-ingest:
#   kubectl delete pvc qdrant-storage -n sentra && ./deploy.sh
echo "[2/5] Applying Kustomize manifests..."
kubectl apply -k .

# 3. Wait for pods
echo "[3/5] Waiting for pods to be ready..."

echo "  Waiting for the registry database..."
kubectl wait --for=condition=ready pod -l app=sentra-registry -n sentra --timeout=120s

echo "  Waiting for Qdrant..."
kubectl wait --for=condition=ready pod -l app=sentra-qdrant -n sentra --timeout=120s

echo "  Waiting for backend..."
kubectl wait --for=condition=ready pod -l app=sentra-backend -n sentra --timeout=120s

echo "  Waiting for frontend..."
kubectl wait --for=condition=ready pod -l app=sentra-frontend -n sentra --timeout=60s

# 4. Registry schema
#
# Deliberately a step of its own and not part of `apply -k`: applying a schema
# is a decision, and an init container would re-run it on every pod restart.
# `create`, because the manifest uses generateName and a Job's pod template is
# immutable -- `apply` of the same name fails instead of running again.
echo "[4/5] Applying the registry schema..."
JOB=$(kubectl create -f registry/migrate-job.yaml -n sentra -o name)
echo "  ${JOB}"
if kubectl wait --for=condition=complete "${JOB}" -n sentra --timeout=120s; then
  echo "  Schema is at head."
else
  echo "  MIGRATION FAILED. Ingestion registers every document, so it will"
  echo "  fail every file until this succeeds (#196). Logs:"
  echo "    kubectl logs -n sentra ${JOB}"
  exit 1
fi

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
echo "Re-apply the registry schema after a backend upgrade:"
echo "  kubectl create -f k8s/registry/migrate-job.yaml -n sentra"
echo ""
echo "Trigger ingestion:"
echo "  curl -X POST http://sentra.aisc.hpi.de/api/ingest"
