#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Automates S3 + Lambda deployment using the AWS CLI
# =============================================================================
# AWS Services used:
#   S3      — Stores and serves the static frontend (HTML/CSS/JS)
#   Lambda  — Deploys the Python metrics function as a zip archive
#
# Prerequisites:
#   1. AWS CLI installed (https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html)
#   2. AWS credentials configured: run `aws configure`
#   3. For Linux/macOS: run `chmod +x deploy.sh` then `./deploy.sh`
#      For Windows: use Git Bash or WSL to execute bash scripts
#
# Usage:
#   ./scripts/deploy.sh
#   BUCKET=my-bucket REGION=us-east-1 LAMBDA_ROLE_ARN=arn:aws:iam::... ./scripts/deploy.sh
# =============================================================================

set -euo pipefail    # Exit on error, undefined vars, or pipe failures

# ── Configuration — override with environment variables or edit here ──────────
BUCKET="${BUCKET:-cloud-metrics-dashboard-$(date +%s)}"   # Unique bucket name
REGION="${REGION:-us-east-1}"
LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-metrics-collector}"
LAMBDA_ROLE_ARN="${LAMBDA_ROLE_ARN:-}"                     # Set this before running
LAMBDA_RUNTIME="python3.12"
LAMBDA_HANDLER="metrics_collector.lambda_handler"
LAMBDA_TIMEOUT=10          # seconds (Free Tier allows up to 900s)
LAMBDA_MEMORY=128          # MB    (Free Tier: 400,000 GB-seconds/month)

# Resolve paths relative to the repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
LAMBDA_DIR="$REPO_ROOT/lambda"
BUILD_DIR="$REPO_ROOT/.build"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${GREEN}═══ $* ═══${NC}\n"; }

# ── Preflight checks ──────────────────────────────────────────────────────────
section "Preflight Checks"

if ! command -v aws &>/dev/null; then
  error "AWS CLI not found. Install from https://aws.amazon.com/cli/"
  exit 1
fi

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
if [[ -z "$AWS_ACCOUNT" ]]; then
  error "AWS credentials not configured. Run: aws configure"
  exit 1
fi

info "AWS Account:  $AWS_ACCOUNT"
info "AWS Region:   $REGION"
info "S3 Bucket:    $BUCKET"
info "Lambda Func:  $LAMBDA_FUNCTION_NAME"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Create and configure S3 bucket for static website hosting
#
# AWS S3 Static Website Hosting:
#   When enabled, S3 serves index.html for requests to the bucket URL.
#   Block Public Access must be disabled so the internet can read the files.
#   The bucket policy grants s3:GetObject to everyone ("*").
# ─────────────────────────────────────────────────────────────────────────────
section "Step 1: Setting Up S3 Static Website Hosting"

# Create the bucket (us-east-1 uses a different syntax than other regions)
if [[ "$REGION" == "us-east-1" ]]; then
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION" \
    2>/dev/null || warn "Bucket may already exist — continuing"
else
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" \
    2>/dev/null || warn "Bucket may already exist — continuing"
fi
info "S3 bucket ready: $BUCKET"

# Disable Block Public Access — required for static website hosting
# (By default AWS blocks all public access as a security measure)
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
info "Public access block removed"

# Attach a bucket policy that allows anyone to read objects (GetObject)
# This is what makes the website publicly accessible on the internet
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{
    \"Sid\": \"PublicReadGetObject\",
    \"Effect\": \"Allow\",
    \"Principal\": \"*\",
    \"Action\": \"s3:GetObject\",
    \"Resource\": \"arn:aws:s3:::${BUCKET}/*\"
  }]
}"
info "Public read bucket policy applied"

# Enable static website hosting — tells S3 which file to serve by default
aws s3api put-bucket-website --bucket "$BUCKET" --website-configuration '{
  "IndexDocument": {"Suffix": "index.html"},
  "ErrorDocument": {"Key": "index.html"}
}'
info "Static website hosting enabled"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Upload frontend files to S3
#
# `aws s3 sync` uploads only changed files (like rsync).
# --content-type flags ensure browsers interpret files correctly.
# ─────────────────────────────────────────────────────────────────────────────
section "Step 2: Uploading Frontend to S3"

aws s3 cp "$FRONTEND_DIR/index.html" "s3://$BUCKET/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache"
info "Uploaded index.html"

aws s3 cp "$FRONTEND_DIR/styles.css" "s3://$BUCKET/styles.css" \
  --content-type "text/css; charset=utf-8" \
  --cache-control "max-age=3600"
info "Uploaded styles.css"

aws s3 cp "$FRONTEND_DIR/app.js" "s3://$BUCKET/app.js" \
  --content-type "application/javascript; charset=utf-8" \
  --cache-control "no-cache"
info "Uploaded app.js"

WEBSITE_URL="http://${BUCKET}.s3-website-${REGION}.amazonaws.com"
info "Frontend live at: $WEBSITE_URL"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Package Lambda function as a zip file
#
# Lambda deployment packages are zip archives uploaded to AWS.
# AWS extracts the zip and runs the handler function on each request.
# ─────────────────────────────────────────────────────────────────────────────
section "Step 3: Packaging Lambda Function"

mkdir -p "$BUILD_DIR"
LAMBDA_ZIP="$BUILD_DIR/lambda_package.zip"

# boto3 is pre-installed in the Lambda Python runtime — no need to bundle it
(cd "$LAMBDA_DIR" && zip -r "$LAMBDA_ZIP" metrics_collector.py)
info "Lambda zip created: $LAMBDA_ZIP ($(du -sh "$LAMBDA_ZIP" | cut -f1))"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Create or update the Lambda function
#
# Lambda Function:
#   - Runs metrics_collector.py in a managed Python 3.12 runtime
#   - The Execution Role grants permission to call CloudWatch APIs
#   - Lambda auto-sends all print()/logging output to CloudWatch Logs
# ─────────────────────────────────────────────────────────────────────────────
section "Step 4: Deploying Lambda Function"

FUNCTION_EXISTS=$(aws lambda get-function --function-name "$LAMBDA_FUNCTION_NAME" \
  --region "$REGION" 2>/dev/null | grep -c FunctionName || true)

if [[ "$FUNCTION_EXISTS" -gt 0 ]]; then
  # Update existing function code
  aws lambda update-function-code \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --zip-file "fileb://$LAMBDA_ZIP" \
    --region "$REGION" \
    --output text --query 'FunctionName'
  info "Lambda function code updated: $LAMBDA_FUNCTION_NAME"
else
  # Create new function — requires an IAM role ARN
  if [[ -z "$LAMBDA_ROLE_ARN" ]]; then
    warn "LAMBDA_ROLE_ARN not set — skipping Lambda create."
    warn "Set it and re-run, or create the function manually in the AWS Console."
    warn "See README.md → Manual AWS Console Steps for instructions."
  else
    aws lambda create-function \
      --function-name "$LAMBDA_FUNCTION_NAME" \
      --runtime "$LAMBDA_RUNTIME" \
      --handler "$LAMBDA_HANDLER" \
      --role "$LAMBDA_ROLE_ARN" \
      --zip-file "fileb://$LAMBDA_ZIP" \
      --timeout "$LAMBDA_TIMEOUT" \
      --memory-size "$LAMBDA_MEMORY" \
      --region "$REGION" \
      --output text --query 'FunctionName'
    info "Lambda function created: $LAMBDA_FUNCTION_NAME"
  fi
fi


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
section "Deployment Complete"

echo ""
echo "  S3 Website URL:  $WEBSITE_URL"
echo "  Lambda package:  $LAMBDA_ZIP"
echo ""
echo "  Next steps (manual — see README.md for details):"
echo "  1. Create API Gateway REST API (if not done)"
echo "  2. Add GET /metrics resource with Lambda Proxy Integration"
echo "  3. Deploy the API to a stage and copy the Invoke URL"
echo "  4. Paste the Invoke URL into frontend/app.js → API_ENDPOINT"
echo "  5. Re-run this script to re-upload app.js with the new URL"
echo ""
