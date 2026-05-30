"""
metrics_collector.py - AWS Lambda Function
==========================================
AWS Service: Lambda (Serverless Compute)
Why Lambda: No servers to manage. Scales automatically from 0 to thousands of requests.
            You pay only for the compute time used (not idle time).
Free Tier:  1,000,000 requests/month + 400,000 GB-seconds of compute/month

How it works:
  API Gateway receives an HTTP request → triggers this Lambda function →
  Lambda collects metrics → returns JSON → API Gateway sends response to browser

CloudWatch Integration:
  Every print() and logging call in Lambda automatically streams to CloudWatch Logs.
  No extra code needed — AWS wires this up for free.
"""

import json
import boto3
import random
import datetime
import logging
import os

# Configure Python logger — Lambda captures all log output and sends it to
# CloudWatch Logs automatically. You can view logs in the AWS Console under
# CloudWatch > Log groups > /aws/lambda/metrics-collector
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_cloudwatch_metric(cw_client, metric_name, namespace, stat, hours=24):
    """
    Fetches a single aggregated metric from CloudWatch.

    AWS CloudWatch: The central monitoring hub for all AWS services.
    Lambda, API Gateway, S3, etc. all publish metrics to CloudWatch automatically.
    This function uses GetMetricStatistics to pull those numbers back out.

    Args:
        cw_client:   boto3 CloudWatch client (AWS SDK for Python)
        metric_name: e.g. 'Invocations', 'Errors', 'Duration'
        namespace:   groups related metrics, e.g. 'AWS/Lambda'
        stat:        aggregation type — 'Sum', 'Average', 'Maximum', 'Minimum'
        hours:       how far back to look (default 24 hours)

    Returns:
        float: the aggregated metric value, or 0.0 on error/no data
    """
    end_time = datetime.datetime.utcnow()
    start_time = end_time - datetime.timedelta(hours=hours)

    try:
        response = cw_client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[
                {
                    "Name": "FunctionName",
                    # AWS_LAMBDA_FUNCTION_NAME is injected by the Lambda runtime
                    "Value": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "metrics-collector"),
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,      # Aggregate the whole window into one data point (86400s = 24h)
            Statistics=[stat],
        )

        datapoints = response.get("Datapoints", [])
        if datapoints:
            return round(datapoints[0].get(stat, 0.0), 2)
        return 0.0

    except Exception as exc:
        # Log the error — it will appear in CloudWatch Logs so you can debug it
        logger.error("CloudWatch fetch failed for %s: %s", metric_name, exc)
        return 0.0


def generate_simulated_metrics():
    """
    Produces realistic-looking system metrics.

    In a real production system these would come from:
    - CloudWatch Agent installed on EC2 instances (CPU, memory, disk)
    - Custom metrics pushed via boto3 PutMetricData from application code
    - Third-party APM tools (Datadog, New Relic) that integrate with CloudWatch

    For this portfolio project we simulate values with time-of-day variation
    so the dashboard always shows interesting, changing data.
    """
    # Simulate higher load during business hours (UTC 13:00–21:00 = US East 9am–5pm)
    hour = datetime.datetime.utcnow().hour
    load_factor = 1.4 if 13 <= hour <= 21 else 1.0

    base_cpu = random.uniform(12, 48) * load_factor
    base_mem = random.uniform(38, 62) * load_factor

    return {
        "cpu_percent": min(round(base_cpu + random.gauss(0, 4), 1), 95.0),
        "memory_percent": min(round(base_mem + random.gauss(0, 3), 1), 92.0),
        # Disk changes slowly — tight range is intentional
        "disk_percent": round(random.uniform(44, 57), 1),
        "network_in_mbps": round(random.uniform(0.5, 30.0), 2),
        "network_out_mbps": round(random.uniform(0.1, 12.0), 2),
        "active_connections": random.randint(8, 180),
        "request_latency_ms": round(random.uniform(10, 220), 1),
    }


def determine_health(system_metrics, lambda_metrics):
    """Derives an overall health status from key metric thresholds."""
    cpu = system_metrics["cpu_percent"]
    mem = system_metrics["memory_percent"]
    err_rate = lambda_metrics.get("error_rate_percent", 0.0)

    if cpu > 90 or mem > 95 or err_rate > 10:
        return "critical"
    if cpu > 75 or mem > 85 or err_rate > 5:
        return "warning"
    return "healthy"


def lambda_handler(event, context):
    """
    Entry point — AWS Lambda calls this function for every incoming request.

    Parameters:
        event:   dict — API Gateway passes the full HTTP request here
                         (method, path, headers, query string, body, etc.)
        context: LambdaContext object — runtime info such as function name,
                 memory limit, and how many milliseconds remain before timeout

    API Gateway → Lambda integration:
        We use "Lambda Proxy Integration", which means API Gateway forwards the
        raw HTTP request to Lambda and returns Lambda's response directly.
        Lambda must return a dict with statusCode, headers, and a string body.
    """

    logger.info(
        "Request received | method=%s | path=%s | requestId=%s",
        event.get("httpMethod"),
        event.get("path"),
        event.get("requestContext", {}).get("requestId", "local-test"),
    )

    # ── CORS Preflight ──────────────────────────────────────────────────────
    # Browsers send an OPTIONS request before the real GET to ask: "does this
    # server allow cross-origin requests from my domain?"  We must say yes,
    # otherwise the browser blocks the response before JavaScript ever sees it.
    if event.get("httpMethod") == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
            },
            "body": "",
        }

    # ── Fetch CloudWatch Metrics ────────────────────────────────────────────
    # boto3 automatically uses the Lambda execution role's IAM permissions.
    # The role needs cloudwatch:GetMetricStatistics — set this up in IAM.
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    cw_client = boto3.client("cloudwatch", region_name=aws_region)

    logger.info("Querying CloudWatch for Lambda metrics...")

    invocations = int(get_cloudwatch_metric(cw_client, "Invocations", "AWS/Lambda", "Sum"))
    errors = int(get_cloudwatch_metric(cw_client, "Errors", "AWS/Lambda", "Sum"))
    avg_duration = get_cloudwatch_metric(cw_client, "Duration", "AWS/Lambda", "Average")
    throttles = int(get_cloudwatch_metric(cw_client, "Throttles", "AWS/Lambda", "Sum"))

    error_rate = round((errors / invocations * 100), 2) if invocations > 0 else 0.0

    lambda_metrics = {
        "invocations_24h": invocations,
        "errors_24h": errors,
        "throttles_24h": throttles,
        "avg_duration_ms": avg_duration,
        "error_rate_percent": error_rate,
    }

    # ── System Metrics ──────────────────────────────────────────────────────
    system_metrics = generate_simulated_metrics()

    # ── Health Status ───────────────────────────────────────────────────────
    health_status = determine_health(system_metrics, lambda_metrics)
    logger.info(
        "Metrics ready | status=%s | cpu=%.1f%% | mem=%.1f%%",
        health_status,
        system_metrics["cpu_percent"],
        system_metrics["memory_percent"],
    )

    # ── Build Response ──────────────────────────────────────────────────────
    payload = {
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": health_status,
        "system_metrics": system_metrics,
        "lambda_metrics": lambda_metrics,
        # context gives us live runtime metadata — useful for debugging
        "metadata": {
            "function_name": context.function_name,
            "memory_limit_mb": context.memory_limit_in_mb,
            "remaining_time_ms": context.get_remaining_time_in_millis(),
            "aws_region": aws_region,
        },
    }

    # ── API Gateway Response Format ─────────────────────────────────────────
    # statusCode → HTTP status sent to the client
    # headers    → include CORS headers so the browser-hosted S3 page can read this
    # body       → must be a JSON *string*, not a dict
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",       # Allow S3 website to call this API
            "Access-Control-Allow-Headers": "Content-Type",
            "Cache-Control": "no-cache, no-store",    # Never cache live metrics
        },
        "body": json.dumps(payload),
    }
