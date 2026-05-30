# CloudMetrics Dashboard

A serverless monitoring dashboard that pulls real AWS metrics and displays them in a live-updating UI. Built entirely on AWS Free Tier — Lambda handles the backend, API Gateway exposes it over HTTPS, S3 hosts the frontend, and CloudWatch is where the actual data comes from.
<img width="1089" height="892" alt="image" src="https://github.com/user-attachments/assets/5f69f513-f854-4d27-8bf7-47a32d6c53e3" />

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

- [AWS Account](https://aws.amazon.com/free/) — Free Tier is enough for this whole project
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) — run `aws configure` after installing
- Python 3.8+
- Git Bash or WSL if you're on Windows (the deploy script is bash)

---
## Setup Guide

The first three steps have to be done manually in the AWS Console — they involve IAM permissions and service linking that can't be scripted without extra setup. After that, `deploy.sh` handles everything else.

### Step 1 — Create an IAM Role for Lambda

Lambda needs permission to read from CloudWatch and write its own logs. You only do this once.

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda** → Next
3. Attach these two policies:
   - `CloudWatchReadOnlyAccess`
   - `AWSLambdaBasicExecutionRole`
4. Role name: `lambda-metrics-role` → **Create role**

---

### Step 2 — Create the Lambda Function

1. Go to **Lambda → Create function → Author from scratch**
2. Fill in:
   - Function name: `metrics-collector`
   - Runtime: **Python 3.12**
   - Execution role: **Use an existing role** → select `lambda-metrics-role`
3. Click **Create function**
4. In the **Code** tab, delete the default code and paste in everything from `lambda/metrics_collector.py`
5. Click **Deploy**

One thing worth changing right away — bump the timeout. The default is 3 seconds and CloudWatch can occasionally be slow to respond. Go to **Configuration → General configuration → Edit**, set the timeout to **10 seconds**, and save.

---

### Step 3 — Create API Gateway

1. Go to **API Gateway → Create API → REST API → Build**
2. API name: `CloudMetricsAPI` → **Create API**
3. Click **Create Resource**, name it `metrics`, click **Create resource**
4. With `/metrics` selected, click **Create Method → GET**:
   - Integration type: **Lambda Function**
   - Turn on **Lambda proxy integration** — this is important, it passes the full request object to Lambda
   - Lambda function: `metrics-collector`
   - Save → OK when it asks about permissions
5. Click **Deploy API** → New stage → Stage name: `prod` → **Deploy**
6. Copy the **Invoke URL** at the top of the page — it looks like `https://abc123.execute-api.us-east-1.amazonaws.com/prod`

Quick sanity check: paste `your-invoke-url/prod/metrics` into a browser tab. You should see raw JSON. If you do, the backend is working.

---

### Step 4 — Connect Frontend to API Gateway

Open `frontend/app.js` and update the API endpoint on line 17:

```js
// Change this:
const API_ENDPOINT = "YOUR_API_GATEWAY_URL/metrics";

// To your actual URL from Step 3:
const API_ENDPOINT = "https://abc123.execute-api.us-east-1.amazonaws.com/prod/metrics";
```

---

### Step 5 — Deploy Frontend to S3

Pick a bucket name (has to be globally unique across all of AWS — something specific works better than something generic) and run the deploy script from Git Bash:

```bash
BUCKET=your-bucket-name REGION=us-east-1 ./scripts/deploy.sh
```

The script creates the bucket, configures it for static website hosting, and uploads all the frontend files. When it finishes it prints the URL:

```
http://your-bucket-name.s3-website-us-east-1.amazonaws.com
```

If you need to re-upload `app.js` after changing it:

```bash
aws s3 cp frontend/app.js s3://your-bucket-name/app.js \
  --content-type "application/javascript; charset=utf-8" \
  --cache-control "no-cache"
```

---

### Step 6 — Generate Traffic (Optional)

The Lambda metrics panel shows real CloudWatch data, but if the function has barely been invoked the numbers will be low. The simulator script hits the API repeatedly and pushes custom metrics so the dashboard has something interesting to show:

```bash
pip install boto3

python scripts/simulate_metrics.py \
  --endpoint https://abc123.execute-api.us-east-1.amazonaws.com/prod/metrics \
  --count 30 \
  --interval 1.0 \
  --push-cloudwatch
```

Wait about a minute after running it, then refresh the dashboard — the invocation count will update.

---

### Step 7 — View CloudWatch Logs

Every time Lambda runs, it logs to CloudWatch automatically. To see the logs:

1. Go to **CloudWatch → Log groups → `/aws/lambda/metrics-collector`**
2. Open the most recent log stream
3. You'll see the structured output from the `logger.info()` calls in the function

---

## Testing

**Test Lambda before hooking up API Gateway** — go to the Lambda console, open the **Test** tab, create a test event with this payload and run it:

```json
{
  "httpMethod": "GET",
  "path": "/metrics",
  "requestContext": { "requestId": "test-001" }
}
```

You should get a green success result with a JSON body containing `system_metrics` and `lambda_metrics`.

**Test API Gateway** — once deployed, hit the endpoint directly:

```bash
curl https://YOUR_INVOKE_URL/prod/metrics | python -m json.tool
```

**Test the full stack** — open the S3 website URL and watch the numbers refresh every 30 seconds.

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
