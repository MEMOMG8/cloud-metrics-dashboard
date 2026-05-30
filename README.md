# CloudMetrics Dashboard

A serverless cloud monitoring dashboard built with AWS Free Tier services. Demonstrates core cloud engineering concepts: serverless compute, object storage, API management, and observability.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AWS Cloud (Free Tier)                         │
│                                                                       │
│  ┌─────────────────┐        ┌──────────────┐        ┌─────────────┐ │
│  │   S3 Bucket     │        │ API Gateway  │        │   Lambda    │ │
│  │ (Static Site)   │        │  REST API    │───────>│  Function   │ │
│  │                 │        │  GET /metrics│        │ Python 3.12 │ │
│  │  index.html  ───┼──load──│              │        └──────┬──────┘ │
│  │  styles.css     │  JS    └──────────────┘               │        │
│  │  app.js         │               ^                       │ boto3  │
│  └─────────────────┘               │                       v        │
│                              HTTP GET                ┌─────────────┐ │
│                                    │                │  CloudWatch │ │
│                             ┌──────┴──────┐         │             │ │
│                             │   Browser   │         │ • Logs      │ │
│                             │  (User's PC)│         │ • Metrics   │ │
│                             └─────────────┘         │ • Alarms    │ │
│                                                      └─────────────┘ │
└───────────────────────────────────────────────────────────────────────┘

Data flow:
  1. Browser loads HTML/CSS/JS from S3 static website URL
  2. JavaScript calls API Gateway endpoint every 30 seconds
  3. API Gateway triggers Lambda function (Python)
  4. Lambda reads real metrics from CloudWatch (invocations, errors, duration)
  5. Lambda returns JSON → API Gateway → Browser → DOM updated
  6. Lambda logs automatically stream to CloudWatch Logs
```

## Tech Stack

| Service | Role | Free Tier |
|---|---|---|
| **S3** | Hosts static frontend | 5 GB storage, 20K GET requests/month |
| **API Gateway** | HTTPS endpoint for the browser to call | 1M API calls/month for 12 months |
| **Lambda** | Serverless Python function — collects metrics | 1M requests + 400K GB-seconds/month |
| **CloudWatch** | Logs Lambda output; stores service metrics | 5 GB logs, 10 metrics, 3 dashboards/month |

---

## Project Structure

```
cloud-metrics-dashboard/
├── README.md
├── lambda/
│   └── metrics_collector.py     # Lambda function — metrics collection + API response
├── frontend/
│   ├── index.html               # Dashboard UI (served from S3)
│   ├── styles.css               # Dark-theme dashboard styles
│   └── app.js                   # Fetches metrics, updates DOM, draws chart
└── scripts/
    ├── deploy.sh                # Automates S3 upload + Lambda packaging (AWS CLI)
    └── simulate_metrics.py      # Sends traffic to API Gateway to generate CloudWatch data
```

---

## Prerequisites

- [AWS Account](https://aws.amazon.com/free/) (Free Tier is sufficient)
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) — configured with `aws configure`
- Python 3.8+ (for the simulation script)
- Git Bash or WSL (Windows) to run deploy.sh

---

## Setup Guide

### Step 1 — Create an IAM Role for Lambda

Lambda needs permission to read CloudWatch metrics. Do this once in the AWS Console.

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda** → Next
3. Attach these policies:
   - `CloudWatchReadOnlyAccess` (read metrics from CloudWatch)
   - `AWSLambdaBasicExecutionRole` (write logs to CloudWatch Logs)
4. Role name: `lambda-metrics-role` → **Create role**
5. Copy the **Role ARN** — you'll need it in Step 3.

---

### Step 2 — Create the Lambda Function

1. Go to **Lambda → Create function**
2. Select **Author from scratch**
3. Settings:
   - Function name: `metrics-collector`
   - Runtime: **Python 3.12**
   - Execution role: **Use an existing role** → select `lambda-metrics-role`
4. Click **Create function**
5. In the **Code** tab, replace the default code with the contents of `lambda/metrics_collector.py`
6. Click **Deploy**

**Increase the timeout** (the default 3s may be too short when CloudWatch is slow):
- Configuration tab → General configuration → Edit → Timeout: **10 seconds** → Save

---

### Step 3 — Create API Gateway

1. Go to **API Gateway → Create API → REST API → Build**
2. API name: `CloudMetricsAPI` → **Create API**
3. In the API, click **Actions → Create Resource**
   - Resource name: `metrics` → **Create resource**
4. With `/metrics` selected: **Actions → Create Method → GET → ✓**
   - Integration type: **Lambda Function**
   - Lambda proxy integration: **✓ enabled** (sends full request to Lambda)
   - Lambda function: `metrics-collector`
   - Click **Save** → **OK** to grant permission
5. **Actions → Deploy API**
   - Deployment stage: **[New Stage]** → Stage name: `prod` → **Deploy**
6. Copy the **Invoke URL** shown at the top (looks like `https://abc123.execute-api.us-east-1.amazonaws.com/prod`)

---

### Step 4 — Connect Frontend to API Gateway

Open `frontend/app.js` and update line 17:

```js
// Before:
const API_ENDPOINT = "YOUR_API_GATEWAY_URL/metrics";

// After (use your actual Invoke URL from Step 3):
const API_ENDPOINT = "https://abc123.execute-api.us-east-1.amazonaws.com/prod/metrics";
```

---

### Step 5 — Deploy Frontend to S3

Run the deployment script (Git Bash or WSL on Windows):

```bash
# First time — creates bucket and uploads all files
BUCKET=my-cloudmetrics-dashboard-2025 REGION=us-east-1 ./scripts/deploy.sh

# After editing app.js — re-upload just the changed file
aws s3 cp frontend/app.js s3://YOUR_BUCKET_NAME/app.js \
  --content-type "application/javascript; charset=utf-8" \
  --cache-control "no-cache"
```

The script prints your website URL when done:
```
http://my-cloudmetrics-dashboard-2025.s3-website-us-east-1.amazonaws.com
```

Open that URL in a browser to see the live dashboard.

---

### Step 6 — Generate Traffic (Optional)

Run the simulator to populate CloudWatch with real Lambda invocation data:

```bash
# Install requests (only needed for --push-cloudwatch flag; base script uses stdlib)
pip install boto3

# Send 30 requests, 1 per second, and push custom CloudWatch metrics
python scripts/simulate_metrics.py \
  --endpoint https://abc123.execute-api.us-east-1.amazonaws.com/prod/metrics \
  --count 30 \
  --interval 1.0 \
  --push-cloudwatch
```

After running the simulator, wait ~1 minute and refresh the dashboard — the Lambda invocation count in the bottom panel will update.

---

### Step 7 — View CloudWatch Logs

Every Lambda invocation writes logs automatically. To view them:

1. **CloudWatch → Log groups → `/aws/lambda/metrics-collector`**
2. Click the most recent log stream
3. You'll see structured log entries from `logger.info()` calls in the function

---

## Manual AWS Console Steps (Cannot Be Automated Here)

These require the AWS Console because they involve IAM trust relationships or first-time resource creation:

| # | Step | Why It's Manual |
|---|---|---|
| 1 | Create IAM role for Lambda | IAM trust policies require console confirmation |
| 2 | Create Lambda function | First-time create requires linking the IAM role |
| 3 | Create API Gateway + resource | Service-to-service permissions need console approval |
| 4 | Deploy API to a stage | Generates the Invoke URL you paste into app.js |
| 5 | (Optional) Enable CloudWatch Alarms | Set thresholds for email alerts on high error rate |

Everything else (S3 bucket, file uploads, Lambda code updates) is handled by `deploy.sh`.

---

## Testing the Setup

**Test Lambda directly** (before wiring up API Gateway):

In the Lambda Console → Test tab, create a test event with this JSON:

```json
{
  "httpMethod": "GET",
  "path": "/metrics",
  "requestContext": { "requestId": "test-001" }
}
```

Expected: Status 200, JSON body with `system_metrics` and `lambda_metrics` keys.

**Test API Gateway**:

```bash
curl https://YOUR_INVOKE_URL/prod/metrics | python -m json.tool
```

**Test the full stack**: Open the S3 website URL in a browser and confirm numbers update every 30 seconds.

---

## Cost Estimate (Free Tier)

| Service | Free Tier | Estimated Monthly Usage | Cost |
|---|---|---|---|
| S3 | 5 GB storage, 20K GETs | ~1 MB storage, ~5K requests | **$0.00** |
| API Gateway | 1M calls/month (12 months) | ~50K calls | **$0.00** |
| Lambda | 1M requests + 400K GB-s/month | ~50K requests, ~1K GB-s | **$0.00** |
| CloudWatch | 5 GB logs/month | ~10 MB logs | **$0.00** |
| **Total** | | | **$0.00** |

---

## Resume Bullet Points

Copy these directly onto your resume under a "Projects" section:

```
• Built a serverless AWS monitoring dashboard using Lambda (Python), API Gateway,
  S3 static hosting, and CloudWatch — deployed entirely within the AWS Free Tier.

• Designed and implemented a RESTful API with AWS API Gateway + Lambda proxy
  integration, including CORS handling and structured JSON responses consumed
  by a vanilla JS frontend hosted on S3.

• Integrated AWS CloudWatch to capture Lambda invocation metrics, error rates,
  and execution duration; surfaced real-time observability data on a live web dashboard
  with 30-second auto-refresh.

• Authored an end-to-end AWS CLI deployment script (deploy.sh) automating S3 bucket
  provisioning, public access policies, static website hosting configuration,
  and Lambda function packaging — reducing manual setup to 4 console steps.
```

---

## Architecture Decisions (Interview Talking Points)

**Why Lambda over EC2?**
No idle cost. EC2 would run 24/7 even with zero traffic. Lambda charges only per invocation — perfect for a dashboard that gets polled every 30 seconds.

**Why S3 for the frontend?**
Zero server maintenance. S3 static website hosting serves files from AWS's global infrastructure without managing Nginx, certificates, or uptime. Same approach used by companies like Netflix for static assets.

**Why API Gateway?**
It handles authentication, rate limiting, TLS termination, and CORS — things I'd have to build myself with a custom server. It also provides a stable URL even if the Lambda function is redeployed or renamed.

**Why CloudWatch?**
It's the native AWS observability layer — already integrated with every AWS service. Using it avoids installing third-party agents and keeps the stack entirely within AWS's managed ecosystem.
