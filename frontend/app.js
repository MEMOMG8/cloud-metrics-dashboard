/**
 * app.js — CloudMetrics Dashboard Frontend
 * =========================================
 * AWS Services used from this file:
 *   - API Gateway: the HTTPS endpoint this script calls (API_ENDPOINT below)
 *   - Lambda:      the function that handles each fetch() call
 *   - S3:          hosts this very file as a static asset
 *
 * Data flow:
 *   Browser (this JS) → HTTP GET → API Gateway URL
 *   → Lambda invoked → CloudWatch metrics fetched
 *   → JSON returned → DOM updated
 */

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURATION — Replace this with your API Gateway Invoke URL after deployment.
// You get this URL from: AWS Console → API Gateway → your API → Stages
// ─────────────────────────────────────────────────────────────────────────────
const API_ENDPOINT = "https://j3xjmbcduc.execute-api.us-east-1.amazonaws.com/prod/metrics";

const REFRESH_INTERVAL_SECONDS = 30;   // How often to poll for new metrics
const HISTORY_MAX_POINTS       = 15;   // How many readings to keep for the chart

// In-memory history arrays — stored in the browser, not in AWS
const cpuHistory = [];
const memHistory = [];
let   countdownTimer = null;
let   secondsLeft    = REFRESH_INTERVAL_SECONDS;


// ─────────────────────────────────────────────────────────────────────────────
// Data Fetching
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Calls the API Gateway endpoint and returns parsed JSON.
 * API Gateway forwards this GET request to the Lambda function.
 * Lambda returns JSON; API Gateway forwards it back here.
 */
async function fetchMetrics() {
  const response = await fetch(API_ENDPOINT, {
    method: "GET",
    headers: { "Accept": "application/json" },
    // no-store prevents the browser from caching live metric responses
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API Gateway returned HTTP ${response.status}`);
  }

  return response.json();
}


// ─────────────────────────────────────────────────────────────────────────────
// DOM Helpers
// ─────────────────────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

/** Animates a numeric DOM element from its current text value to `target`. */
function animateNumber(element, target, decimals = 1) {
  const start  = parseFloat(element.textContent) || 0;
  const delta  = target - start;
  const frames = 20;
  let   frame  = 0;

  const tick = () => {
    frame++;
    const progress = frame / frames;
    const eased    = 1 - Math.pow(1 - progress, 3);   // ease-out cubic
    element.textContent = (start + delta * eased).toFixed(decimals);
    if (frame < frames) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/**
 * Updates a metric card's progress bar and colour.
 * Thresholds: >75% = warning (yellow), >90% = critical (red)
 */
function updateProgressBar(fillEl, value) {
  fillEl.style.width = `${Math.min(value, 100)}%`;
  fillEl.classList.remove("warn", "crit");
  if (value > 90) fillEl.classList.add("crit");
  else if (value > 75) fillEl.classList.add("warn");
}


// ─────────────────────────────────────────────────────────────────────────────
// Dashboard Update
// ─────────────────────────────────────────────────────────────────────────────

/** Pushes a value into a fixed-size history ring buffer. */
function pushHistory(arr, value) {
  arr.push(value);
  if (arr.length > HISTORY_MAX_POINTS) arr.shift();
}

/** Applies fresh API data to every part of the dashboard. */
function updateDashboard(data) {
  const sys = data.system_metrics;
  const lam = data.lambda_metrics;
  const meta = data.metadata || {};

  // ── Status badge ───────────────────────────────────────────────────────────
  const badge = $("status-badge");
  badge.className = `status-badge ${data.status}`;
  $("status-text").textContent = data.status.toUpperCase();

  // ── CPU Card ───────────────────────────────────────────────────────────────
  animateNumber($("cpu-value"), sys.cpu_percent);
  updateProgressBar($("cpu-bar"), sys.cpu_percent);
  $("cpu-sub").textContent = `${sys.active_connections} active connections`;

  // ── Memory Card ───────────────────────────────────────────────────────────
  animateNumber($("mem-value"), sys.memory_percent);
  updateProgressBar($("mem-bar"), sys.memory_percent);

  // ── Disk Card ─────────────────────────────────────────────────────────────
  animateNumber($("disk-value"), sys.disk_percent);
  updateProgressBar($("disk-bar"), sys.disk_percent);

  // ── Network Card ──────────────────────────────────────────────────────────
  $("net-in").textContent  = sys.network_in_mbps.toFixed(1);
  $("net-out").textContent = sys.network_out_mbps.toFixed(1);
  $("latency-val").textContent = `${sys.request_latency_ms} ms avg latency`;

  // ── Lambda Stats ──────────────────────────────────────────────────────────
  $("lam-invocations").textContent = lam.invocations_24h.toLocaleString();
  $("lam-errors").textContent      = lam.errors_24h;
  $("lam-duration").textContent    = `${lam.avg_duration_ms.toFixed(0)}ms`;
  $("lam-throttles").textContent   = lam.throttles_24h;

  // Colour-code error rate
  const errEl = $("lam-errrate");
  errEl.textContent = `${lam.error_rate_percent.toFixed(1)}%`;
  errEl.className = "lambda-stat-val";
  if (lam.error_rate_percent > 10)     errEl.classList.add("crit");
  else if (lam.error_rate_percent > 5) errEl.classList.add("warn");
  else                                  errEl.classList.add("good");

  // ── Footer metadata ────────────────────────────────────────────────────────
  $("meta-region").textContent   = meta.aws_region || "—";
  $("meta-memory").textContent   = meta.memory_limit_mb ? `${meta.memory_limit_mb} MB` : "—";
  $("meta-remaining").textContent = meta.remaining_time_ms
    ? `${meta.remaining_time_ms} ms`
    : "—";
  $("meta-timestamp").textContent = new Date(data.timestamp).toLocaleTimeString();

  // ── History chart ──────────────────────────────────────────────────────────
  pushHistory(cpuHistory, sys.cpu_percent);
  pushHistory(memHistory, sys.memory_percent);
  drawChart();
}


// ─────────────────────────────────────────────────────────────────────────────
// Canvas Chart
// Draws a simple dual-line chart showing CPU and Memory history.
// Uses the native Canvas 2D API — no external chart library needed.
// ─────────────────────────────────────────────────────────────────────────────

function drawChart() {
  const canvas = $("history-chart");
  if (!canvas) return;

  // Match canvas pixel dimensions to its CSS size (important for retina screens)
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width  = rect.width  * dpr;
  canvas.height = rect.height * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const PAD = { top: 10, right: 10, bottom: 20, left: 32 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top  - PAD.bottom;

  ctx.clearRect(0, 0, W, H);

  // Background grid lines at 25%, 50%, 75%, 100%
  ctx.strokeStyle = "#21273a";
  ctx.lineWidth   = 1;
  [25, 50, 75, 100].forEach(pct => {
    const y = PAD.top + plotH - (pct / 100) * plotH;
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(PAD.left + plotW, y);
    ctx.stroke();

    // Y-axis labels
    ctx.fillStyle   = "#4a5568";
    ctx.font        = "10px 'Segoe UI', sans-serif";
    ctx.textAlign   = "right";
    ctx.fillText(`${pct}`, PAD.left - 6, y + 3.5);
  });

  if (cpuHistory.length < 2) return;   // Need at least 2 points to draw a line

  const points = cpuHistory.length;
  const xStep  = plotW / (HISTORY_MAX_POINTS - 1);

  // Helper: converts a data index + value → canvas coordinates
  const toX = i   => PAD.left + i * xStep;
  const toY = val => PAD.top  + plotH - (val / 100) * plotH;

  /**
   * Draws one smooth line with an area fill beneath it.
   * Uses quadratic Bezier curves for smooth interpolation.
   */
  function drawLine(history, color, fillColor) {
    ctx.beginPath();
    // Start point
    ctx.moveTo(toX(0), toY(history[0]));

    for (let i = 1; i < history.length; i++) {
      const cpx = (toX(i - 1) + toX(i)) / 2;
      ctx.quadraticCurveTo(toX(i - 1), toY(history[i - 1]), cpx, (toY(history[i-1]) + toY(history[i])) / 2);
    }
    ctx.lineTo(toX(history.length - 1), toY(history[history.length - 1]));

    ctx.strokeStyle = color;
    ctx.lineWidth   = 2;
    ctx.stroke();

    // Filled area under the line
    ctx.lineTo(toX(history.length - 1), PAD.top + plotH);
    ctx.lineTo(toX(0), PAD.top + plotH);
    ctx.closePath();

    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + plotH);
    grad.addColorStop(0, fillColor);
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.fill();
  }

  drawLine(memHistory, "#3fb950", "rgba(63,185,80,0.18)");  // Memory (green)
  drawLine(cpuHistory, "#00d4ff", "rgba(0,212,255,0.18)");  // CPU (cyan)

  // Draw data points as small circles
  [
    { history: cpuHistory, color: "#00d4ff" },
    { history: memHistory, color: "#3fb950" },
  ].forEach(({ history, color }) => {
    history.forEach((val, i) => {
      ctx.beginPath();
      ctx.arc(toX(i), toY(val), 3, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    });
  });
}


// ─────────────────────────────────────────────────────────────────────────────
// Refresh Loop
// ─────────────────────────────────────────────────────────────────────────────

function showError(message) {
  const el = $("error-banner");
  el.textContent = `Error: ${message}. Check the browser console and confirm your API_ENDPOINT is set correctly.`;
  el.classList.add("visible");
}

function hideError() {
  $("error-banner").classList.remove("visible");
}

/** Fetches fresh data from Lambda via API Gateway and updates the UI. */
async function refresh() {
  try {
    const data = await fetchMetrics();
    hideError();
    updateDashboard(data);
  } catch (err) {
    console.error("Metrics fetch failed:", err);
    showError(err.message);
  }
}

/** Counts down the timer and fires refresh() when it hits zero. */
function startCountdown() {
  clearInterval(countdownTimer);
  secondsLeft = REFRESH_INTERVAL_SECONDS;

  countdownTimer = setInterval(() => {
    secondsLeft--;
    $("countdown").textContent = `${secondsLeft}s`;

    if (secondsLeft <= 0) {
      secondsLeft = REFRESH_INTERVAL_SECONDS;
      $("countdown").textContent = "…";
      refresh();
    }
  }, 1000);
}


// ─────────────────────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Warn clearly if the developer forgot to set the endpoint
  if (API_ENDPOINT.startsWith("YOUR_API")) {
    showError(
      "API_ENDPOINT not configured — open app.js and replace YOUR_API_GATEWAY_URL with your API Gateway Invoke URL"
    );
    return;
  }

  // Initial load, then kick off the auto-refresh loop
  refresh();
  startCountdown();

  // Redraw chart when the window is resized (canvas needs explicit redraw)
  window.addEventListener("resize", drawChart);
});
