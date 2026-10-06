#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# The manual path. ArgoCD is what normally deploys this: its application
# controller watches this repo's k8s/ path and syncs when the CI job rewrites
# the image tags. Running this by hand applies the same manifests directly,
# which is useful for a first install or a cluster without the Application
# registered -- but if ArgoCD is watching, it will show the app OutOfSync (or
# revert this, with self-heal on) the moment the two disagree.
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
# The migration Job is an ArgoCD hook, which means ArgoCD deletes and recreates
# it per sync. `kubectl apply` has no such lifecycle and a Job's pod template is
# immutable, so a re-run has to remove the old one first.
kubectl delete job sentra-registry-migrate -n sentra --ignore-not-found
kubectl delete job sentra-eval-migrate -n sentra --ignore-not-found
kubectl apply -k .

# 3. Wait for pods
echo "[3/5] Waiting for pods to be ready..."

echo "  Waiting for the registry database..."
kubectl wait --for=condition=ready pod -l app=sentra-registry -n sentra --timeout=120s

echo "  Waiting for the evaluation database..."
kubectl wait --for=condition=ready pod -l app=sentra-eval-db -n sentra --timeout=120s

echo "  Waiting for Qdrant..."
kubectl wait --for=condition=ready pod -l app=sentra-qdrant -n sentra --timeout=120s

echo "  Waiting for backend..."
kubectl wait --for=condition=ready pod -l app=sentra-backend -n sentra --timeout=120s

echo "  Waiting for the evaluation harness..."
kubectl wait --for=condition=ready pod -l app=sentra-eval-harness -n sentra --timeout=120s

echo "  Waiting for frontend..."
kubectl wait --for=condition=ready pod -l app=sentra-frontend -n sentra --timeout=60s

# 4. Registry schema
#
# Under ArgoCD this is a Sync hook at wave 1 and runs on its own, between the
# database (wave 0) and the backend (wave 2). `kubectl apply -k` has no hooks
# and no waves, so on this path it is applied with everything else and simply
# has to be waited for.
echo "[4/5] Waiting for the registry schema..."
if kubectl wait --for=condition=complete job/sentra-registry-migrate -n sentra --timeout=180s \
   && kubectl wait --for=condition=complete job/sentra-eval-migrate -n sentra --timeout=180s; then
  echo "  Both schemas are at head."
else
  echo "  MIGRATION FAILED. Ingestion registers every document, so it will"
  echo "  fail every file until this succeeds (#196). Logs:"
  echo "    kubectl logs -n sentra job/sentra-registry-migrate"
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
echo "Re-run the registry migration by hand:"
echo "  kubectl delete job sentra-registry-migrate -n sentra --ignore-not-found"
echo "  kubectl apply -f k8s/registry/migrate-job.yaml -n sentra"
echo ""
echo "Trigger ingestion:"
echo "  curl -X POST http://sentra.aisc.hpi.de/api/ingest"
