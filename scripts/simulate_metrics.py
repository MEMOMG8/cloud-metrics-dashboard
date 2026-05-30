#!/usr/bin/env python3
"""
simulate_metrics.py — Traffic Simulator & Custom Metric Generator
=================================================================
Purpose:  Drive traffic to the API Gateway endpoint to generate real
          CloudWatch data (invocations, errors, duration).
          Also demonstrates pushing *custom* metrics to CloudWatch via
          the PutMetricData API.

AWS Services demonstrated:
  API Gateway — the HTTPS endpoint being called
  Lambda      — invoked on every request (invocation count goes up in CloudWatch)
  CloudWatch  — receives custom metric data via boto3 PutMetricData

Usage:
  # Basic: call the API 20 times with 2-second gaps
  python simulate_metrics.py --endpoint https://YOUR_ID.execute-api.us-east-1.amazonaws.com/prod/metrics

  # More traffic, faster
  python simulate_metrics.py --endpoint <url> --count 50 --interval 0.5

  # Also push custom CloudWatch metrics (needs AWS credentials)
  python simulate_metrics.py --endpoint <url> --push-cloudwatch
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate CloudMetrics Dashboard traffic")
    parser.add_argument(
        "--endpoint",
        required=True,
        help="API Gateway invoke URL ending in /metrics",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of requests to send (default: 20)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between requests (default: 2.0)",
    )
    parser.add_argument(
        "--push-cloudwatch",
        action="store_true",
        help="Also push custom metrics to CloudWatch via boto3 (requires AWS credentials)",
    )
    parser.add_argument(
        "--namespace",
        default="CloudMetrics/Simulation",
        help="CloudWatch metric namespace for custom metrics (default: CloudMetrics/Simulation)",
    )
    return parser.parse_args()


def call_api(endpoint: str) -> dict:
    """
    Makes an HTTP GET request to the API Gateway endpoint.

    API Gateway routes this request to the Lambda function and returns
    its JSON response. Each successful call increments the Lambda
    'Invocations' metric in CloudWatch automatically.
    """
    req = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def push_custom_metric(cw_client, namespace: str, metric_name: str, value: float, unit: str = "None"):
    """
    Publishes a custom metric to CloudWatch via PutMetricData.

    CloudWatch Custom Metrics:
      Beyond the built-in AWS service metrics (Lambda, S3, etc.),
      you can publish any application-level data you want.
      Custom metrics appear in CloudWatch dashboards and can trigger alarms.
      Free Tier: 10 custom metrics + 10 alarms included per month.

    Use cases in production:
      - Business metrics (orders/minute, active users)
      - Application health (cache hit rate, queue depth)
      - Anything not captured by default AWS instrumentation
    """
    cw_client.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
                "Timestamp": datetime.utcnow(),
            }
        ],
    )


def print_status(i: int, total: int, data: dict, elapsed_ms: float):
    """Pretty-prints the result of one API call."""
    ts    = data.get("timestamp", "?")
    status = data.get("status", "?")
    sys_m  = data.get("system_metrics", {})
    lam_m  = data.get("lambda_metrics", {})

    cpu = sys_m.get("cpu_percent", 0)
    mem = sys_m.get("memory_percent", 0)
    inv = lam_m.get("invocations_24h", 0)

    # Colour by health status
    colours = {"healthy": "\033[92m", "warning": "\033[93m", "critical": "\033[91m"}
    reset   = "\033[0m"
    col     = colours.get(status, "")

    print(
        f"  [{i:>3}/{total}]  {col}{status:<8}{reset}  "
        f"CPU {cpu:>5.1f}%  MEM {mem:>5.1f}%  "
        f"Invocations(24h): {inv:>4}  "
        f"Latency: {elapsed_ms:>6.0f}ms  "
        f"{ts}"
    )


def main():
    args = parse_args()

    # Optionally set up boto3 for custom CloudWatch metrics
    cw_client = None
    if args.push_cloudwatch:
        try:
            import boto3
            # boto3 reads credentials from ~/.aws/credentials or environment variables
            # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
            cw_client = boto3.client("cloudwatch")
            print(f"CloudWatch custom metrics → namespace '{args.namespace}'")
        except ImportError:
            print("boto3 not installed. Run: pip install boto3")
            print("Continuing without custom metric push.\n")

    print(f"\nSending {args.count} requests to: {args.endpoint}")
    print(f"Interval: {args.interval}s between requests\n")
    print(f"  {'#':>5}  {'Status':<8}  {'CPU':>9}  {'Memory':>9}  {'Invocations':>17}  {'Latency':>10}  Timestamp")
    print("  " + "─" * 90)

    success_count = 0
    error_count   = 0
    total_latency = 0.0

    for i in range(1, args.count + 1):
        t0 = time.monotonic()
        try:
            data = call_api(args.endpoint)
            elapsed_ms = (time.monotonic() - t0) * 1000
            total_latency += elapsed_ms
            success_count += 1
            print_status(i, args.count, data, elapsed_ms)

            # Push custom metrics to CloudWatch if enabled
            if cw_client:
                sys_m = data.get("system_metrics", {})
                try:
                    push_custom_metric(cw_client, args.namespace, "SimulatedCPU",
                                       sys_m.get("cpu_percent", 0), "Percent")
                    push_custom_metric(cw_client, args.namespace, "SimulatedMemory",
                                       sys_m.get("memory_percent", 0), "Percent")
                    push_custom_metric(cw_client, args.namespace, "APICallLatency",
                                       elapsed_ms, "Milliseconds")
                except Exception as exc:
                    print(f"           ⚠ CloudWatch push failed: {exc}")

        except urllib.error.HTTPError as exc:
            error_count += 1
            print(f"  [{i:>3}/{args.count}]  HTTP {exc.code} error — check your API Gateway URL and Lambda function")
        except Exception as exc:
            error_count += 1
            print(f"  [{i:>3}/{args.count}]  Error: {exc}")

        # Wait before next request (except after the last one)
        if i < args.count:
            time.sleep(args.interval + random.uniform(-0.2, 0.2))  # small jitter

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "  " + "═" * 90)
    avg_latency = total_latency / success_count if success_count else 0
    print(f"\n  Simulation complete")
    print(f"  Requests: {success_count} succeeded / {error_count} failed")
    print(f"  Avg API latency: {avg_latency:.0f} ms")

    if cw_client and success_count > 0:
        print(f"\n  Custom metrics published to CloudWatch namespace '{args.namespace}'")
        print("  View them in: AWS Console → CloudWatch → Metrics → Custom Namespaces")

    print(f"\n  Lambda invocation data will appear in CloudWatch within ~1 minute.")
    print("  View logs: AWS Console → CloudWatch → Log groups → /aws/lambda/metrics-collector\n")

    sys.exit(0 if error_count == 0 else 1)


if __name__ == "__main__":
    main()
