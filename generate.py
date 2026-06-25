#!/usr/bin/env python3
"""
Generate an embeddable Claude Code usage widget from local transcript data.

Reads ~/.claude/projects/**/*.jsonl, computes usage stats (sessions, messages,
tokens, active days, streaks, peak hour, favorite model, daily activity heatmap,
per-model breakdown) for All / last 30d / last 7d windows, and writes a
self-contained HTML widget (data baked in) plus a stats.json.

Usage:
    python3 generate.py [--days-back N] [--out DIR]
"""
import argparse
import datetime as dt
import glob
import json
import os
from collections import Counter, defaultdict

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")

# Pretty names for known model ids.
MODEL_NAMES = {
    "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-7": "Opus 4.7",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-1-20250805": "Opus 4.1",
    "claude-opus-4-20250514": "Opus 4",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-sonnet-4-5-20250929": "Sonnet 4.5",
    "claude-sonnet-4-20250514": "Sonnet 4",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-fable-5": "Fable 5",
    "claude-3-5-haiku-20241022": "Haiku 3.5",
    "claude-3-5-sonnet-20241022": "Sonnet 3.5",
    "<synthetic>": "Synthetic",
}

# Approx token counts for fun comparison facts.
MOBY_DICK_TOKENS = 270_000  # ~206k words * ~1.3 tokens/word


def pretty_model(model_id):
    if not model_id:
        return "Unknown"
    if model_id in MODEL_NAMES:
        return MODEL_NAMES[model_id]
    # Fallback: strip date suffix, title-case.
    name = model_id.replace("claude-", "")
    return name


def iter_records():
    """Yield (timestamp, type, model, total_tokens, sessionId) for message records."""
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    typ = d.get("type")
                    if typ not in ("user", "assistant"):
                        continue
                    ts = d.get("timestamp")
                    if not ts:
                        continue
                    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                    model = msg.get("model")
                    usage = msg.get("usage") or {}
                    # Billable content tokens only (input + output). Cache
                    # creation/read tokens are excluded — they dwarf real usage
                    # (~1B vs ~15M) and the official usage card excludes them too.
                    tokens = 0
                    if isinstance(usage, dict):
                        tokens = (usage.get("input_tokens") or 0) + (
                            usage.get("output_tokens") or 0
                        )
                    yield ts, typ, model, tokens, d.get("sessionId")
        except OSError:
            continue


def parse_ts(ts):
    # ISO8601, e.g. 2026-06-25T15:28:21.213Z
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def build():
    # Per-record collection.
    records = []  # (datetime, type, model, tokens, sessionId)
    for ts, typ, model, tokens, sid in iter_records():
        t = parse_ts(ts)
        if t is None:
            continue
        # Local time for hour-of-day / day grouping.
        t = t.astimezone()
        records.append((t, typ, model, tokens, sid))

    if not records:
        raise SystemExit("No records found in ~/.claude/projects")

    records.sort(key=lambda r: r[0])
    now = dt.datetime.now().astimezone()
    today = now.date()

    def window(records, days=None):
        if days is None:
            return records
        cutoff = now - dt.timedelta(days=days)
        return [r for r in records if r[0] >= cutoff]

    def aggregate(recs):
        sessions = set()
        messages = 0
        tokens = 0
        hour_counter = Counter()
        model_counter = Counter()       # messages per model
        model_tokens = Counter()        # tokens per model
        day_counter = Counter()         # messages per local date
        day_tokens = Counter()
        for t, typ, model, tok, sid in recs:
            if sid:
                sessions.add(sid)
            messages += 1
            tokens += tok
            hour_counter[t.hour] += 1
            d = t.date()
            day_counter[d] += 1
            day_tokens[d] += tok
            if typ == "assistant" and model:
                model_counter[model] += 1
                model_tokens[model] += tok

        active_days = sorted(day_counter.keys())
        # Streaks (current = ending today or yesterday; longest = max run).
        current_streak = longest_streak = 0
        if active_days:
            day_set = set(active_days)
            # longest
            run = 0
            prev = None
            for d in active_days:
                if prev is not None and (d - prev).days == 1:
                    run += 1
                else:
                    run = 1
                longest_streak = max(longest_streak, run)
                prev = d
            # current: walk back from today
            cur = today
            if cur not in day_set:
                cur = today - dt.timedelta(days=1)
            while cur in day_set:
                current_streak += 1
                cur -= dt.timedelta(days=1)

        peak_hour = hour_counter.most_common(1)[0][0] if hour_counter else None
        fav_model = model_counter.most_common(1)[0][0] if model_counter else None

        models = []
        for mid, cnt in model_counter.most_common():
            models.append({
                "id": mid,
                "name": pretty_model(mid),
                "messages": cnt,
                "tokens": model_tokens[mid],
            })

        # Daily series for heatmap (date -> messages, tokens).
        daily = [
            {"date": d.isoformat(), "messages": day_counter[d], "tokens": day_tokens[d]}
            for d in active_days
        ]

        return {
            "sessions": len(sessions),
            "messages": messages,
            "tokens": tokens,
            "active_days": len(active_days),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "peak_hour": peak_hour,
            "favorite_model": pretty_model(fav_model) if fav_model else None,
            "models": models,
            "daily": daily,
            "moby_dick_multiple": round(tokens / MOBY_DICK_TOKENS, 1),
        }

    data = {
        "generated_at": now.isoformat(),
        "all": aggregate(records),
        "d30": aggregate(window(records, 30)),
        "d7": aggregate(window(records, 7)),
    }
    return data


def fmt_int(n):
    return f"{n:,}"


def render_html(data):
    blob = json.dumps(data, separators=(",", ":"))
    return HTML_TEMPLATE.replace("__DATA__", blob)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Code Usage</title>
<style>
  :root {
    --bg: #1a1a1a;
    --card: #262626;
    --card-2: #2f2f2f;
    --text: #f5f5f5;
    --muted: #8f8f8f;
    --accent: #6b8fd6;
    --grid-empty: #333333;
    --radius: 14px;
    --font: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: transparent; font-family: var(--font); }
  .ccw {
    width: 100%; max-width: 640px; margin: 0 auto;
    background: var(--bg); color: var(--text);
    border-radius: var(--radius); padding: 18px;
    border: 1px solid #303030;
  }
  .ccw-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
  .ccw-tabs, .ccw-ranges { display: flex; gap: 4px; }
  .ccw-btn {
    background: transparent; border: none; color: var(--muted);
    font: inherit; font-size: 14px; font-weight: 600;
    padding: 7px 13px; border-radius: 9px; cursor: pointer;
  }
  .ccw-btn.active { background: var(--card-2); color: var(--text); }
  .ccw-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
  .ccw-stat { background: var(--card); border-radius: 10px; padding: 13px 14px; }
  .ccw-stat .label { color: var(--muted); font-size: 13px; font-weight: 500; margin-bottom: 6px; }
  .ccw-stat .value { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
  .ccw-heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 1fr); gap: 4px; margin-bottom: 12px; }
  .ccw-cell { width: 100%; aspect-ratio: 1; border-radius: 4px; background: var(--grid-empty); }
  .ccw-foot { color: var(--muted); font-size: 14px; }
  .ccw-models { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
  .ccw-model-row { background: var(--card); border-radius: 10px; padding: 12px 14px; }
  .ccw-model-head { display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 8px; }
  .ccw-model-head .nm { font-weight: 700; }
  .ccw-model-head .ct { color: var(--muted); }
  .ccw-bar { height: 7px; border-radius: 4px; background: var(--card-2); overflow: hidden; }
  .ccw-bar > div { height: 100%; background: var(--accent); border-radius: 4px; }
  .hidden { display: none; }
  @media (max-width: 520px) {
    .ccw-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
<div class="ccw" id="ccw">
  <div class="ccw-top">
    <div class="ccw-tabs" id="ccw-tabs">
      <button class="ccw-btn active" data-view="overview">Overview</button>
      <button class="ccw-btn" data-view="models">Models</button>
    </div>
    <div class="ccw-ranges" id="ccw-ranges">
      <button class="ccw-btn active" data-range="all">All</button>
      <button class="ccw-btn" data-range="d30">30d</button>
      <button class="ccw-btn" data-range="d7">7d</button>
    </div>
  </div>
  <div id="ccw-overview">
    <div class="ccw-grid" id="ccw-stats"></div>
    <div class="ccw-heat" id="ccw-heat"></div>
    <div class="ccw-foot" id="ccw-foot"></div>
  </div>
  <div id="ccw-models-view" class="hidden">
    <div class="ccw-models" id="ccw-models"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
let RANGE = "all", VIEW = "overview";

function fmtInt(n){ return n.toLocaleString("en-US"); }
function fmtTokens(n){
  if (n >= 1e9) return (n/1e9).toFixed(1)+"B";
  if (n >= 1e6) return (n/1e6).toFixed(1)+"M";
  if (n >= 1e3) return (n/1e3).toFixed(1)+"K";
  return ""+n;
}
function fmtHour(h){
  if (h === null || h === undefined) return "—";
  const ap = h < 12 ? "AM" : "PM";
  let hh = h % 12; if (hh === 0) hh = 12;
  return hh + " " + ap;
}

function renderStats(d){
  const cells = [
    ["Sessions", fmtInt(d.sessions)],
    ["Messages", fmtInt(d.messages)],
    ["Total tokens", fmtTokens(d.tokens)],
    ["Active days", fmtInt(d.active_days)],
    ["Current streak", d.current_streak + "d"],
    ["Longest streak", d.longest_streak + "d"],
    ["Peak hour", fmtHour(d.peak_hour)],
    ["Favorite model", d.favorite_model || "—"],
  ];
  document.getElementById("ccw-stats").innerHTML = cells.map(
    ([l,v]) => `<div class="ccw-stat"><div class="label">${l}</div><div class="value">${v}</div></div>`
  ).join("");
}

function renderHeat(d){
  // Build a contiguous day grid ending today, 7 rows (weeks as columns).
  const byDate = {};
  let max = 1;
  d.daily.forEach(x => { byDate[x.date] = x.messages; if (x.messages > max) max = x.messages; });
  const WEEKS = RANGE === "d7" ? 2 : (RANGE === "d30" ? 6 : 22);
  const today = new Date();
  const cells = [];
  const totalDays = WEEKS * 7;
  // Align so the last column ends on this week.
  const start = new Date(today);
  start.setDate(today.getDate() - (totalDays - 1));
  for (let i = 0; i < totalDays; i++){
    const dt = new Date(start);
    dt.setDate(start.getDate() + i);
    const key = dt.toISOString().slice(0,10);
    const v = byDate[key] || 0;
    const intensity = v === 0 ? 0 : 0.25 + 0.75 * Math.min(1, v / max);
    cells.push(intensity);
  }
  document.getElementById("ccw-heat").innerHTML = cells.map(intensity => {
    if (intensity === 0) return `<div class="ccw-cell"></div>`;
    return `<div class="ccw-cell" style="background: rgba(107,143,214,${intensity.toFixed(2)})"></div>`;
  }).join("");
}

function renderFoot(d){
  const mult = d.moby_dick_multiple;
  document.getElementById("ccw-foot").textContent =
    `You've used ~${mult}× more tokens than Moby-Dick.`;
}

function renderModels(d){
  const maxTok = Math.max(1, ...d.models.map(m => m.tokens));
  document.getElementById("ccw-models").innerHTML = d.models.map(m => {
    const pct = (100 * m.tokens / maxTok).toFixed(1);
    return `<div class="ccw-model-row">
      <div class="ccw-model-head">
        <span class="nm">${m.name}</span>
        <span class="ct">${fmtInt(m.messages)} msgs · ${fmtTokens(m.tokens)} tok</span>
      </div>
      <div class="ccw-bar"><div style="width:${pct}%"></div></div>
    </div>`;
  }).join("") || `<div class="ccw-foot">No model data in this range.</div>`;
}

function render(){
  const d = DATA[RANGE];
  document.getElementById("ccw-overview").classList.toggle("hidden", VIEW !== "overview");
  document.getElementById("ccw-models-view").classList.toggle("hidden", VIEW !== "models");
  if (VIEW === "overview"){ renderStats(d); renderHeat(d); renderFoot(d); }
  else { renderModels(d); }
}

document.getElementById("ccw-tabs").addEventListener("click", e => {
  const b = e.target.closest("[data-view]"); if (!b) return;
  VIEW = b.dataset.view;
  document.querySelectorAll("#ccw-tabs .ccw-btn").forEach(x => x.classList.toggle("active", x === b));
  render();
});
document.getElementById("ccw-ranges").addEventListener("click", e => {
  const b = e.target.closest("[data-range]"); if (!b) return;
  RANGE = b.dataset.range;
  document.querySelectorAll("#ccw-ranges .ccw-btn").forEach(x => x.classList.toggle("active", x === b));
  render();
});
render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    data = build()

    html = render_html(data)
    out_json = os.path.join(args.out, "stats.json")
    # index.html so GitHub Pages serves it at the site root; widget.html kept
    # as the documented iframe-embed target. Both identical.
    for name in ("index.html", "widget.html"):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            fh.write(html)
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    a = data["all"]
    print("Wrote index.html, widget.html,", out_json)
    print(f"  sessions={fmt_int(a['sessions'])} messages={fmt_int(a['messages'])} "
          f"tokens={a['tokens']:,} active_days={a['active_days']}")
    print(f"  current_streak={a['current_streak']}d longest_streak={a['longest_streak']}d "
          f"peak_hour={a['peak_hour']} fav={a['favorite_model']}")


if __name__ == "__main__":
    main()
