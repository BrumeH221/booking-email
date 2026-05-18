#!/usr/bin/env bash
# Deploy from project root:  bash deploy/deploy_cloud_run.sh
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID env var}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-booking-email-nlp}"

# Use --source . from project root; reference Dockerfile in deploy/.
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT_ID" --region "$REGION" --platform managed \
  --no-allow-unauthenticated \
  --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 1 --timeout 300 \
  --set-env-vars RUN_MODE=cloud,DB_BACKEND=supabase,USE_LLM_API=true,USE_LOCAL_MODELS=false

echo
echo "Next steps:"
echo "  1) Create secrets in Secret Manager"
echo "  2) Bind to the service"
echo "  3) Create a Cloud Scheduler job hitting /run every 5 minutes"
