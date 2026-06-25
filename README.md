# Claude Code Usage Widget

A self-contained, embeddable widget showing your real Claude Code usage, built
from your local transcript data in `~/.claude/projects/**/*.jsonl`. No network
calls, no API keys - everything is computed locally and baked into one HTML file.

## Files
- `generate.py` - parser + widget generator. Re-run anytime to refresh.
- `widget.html` - the standalone widget (data baked in). This is what you embed.
- `stats.json` - the raw computed stats, if you want to render your own UI.

## Regenerate
```bash
python3 generate.py          # writes widget.html + stats.json next to the script
python3 generate.py --out /some/dir
```
Takes <1s over ~570 transcript files.

## Embed it on a website

**Option A - iframe (simplest, fully isolated):**
```html
<iframe src="widget.html" width="660" height="440" frameborder="0"
        style="border:none;background:transparent"></iframe>
```
Host `widget.html` anywhere static (GitHub Pages, S3, Netlify, etc.).

**Option B - inline:** copy the `<style>` block and the `<div class="ccw">…</div>`
plus the `<script>` from `widget.html` directly into your page. The widget is
namespaced under `.ccw` / `ccw-*` classes to avoid clashing with your styles.

## What's shown
- **Overview tab:** sessions, messages, total tokens, active days, current /
  longest streak, peak hour, favorite model, plus a contribution-style activity
  heatmap and a fun token comparison.
- **Models tab:** per-model message + token breakdown.
- **All / 30d / 7d** range toggles, all precomputed.

## Metric definitions (so the numbers are honest)
- **Messages** = `user` + `assistant` turn records. (Anthropic's official usage
  card counts content blocks / tool turns separately, so its message and token
  totals run ~20% higher - same underlying data, different counting rule.)
- **Total tokens** = `input_tokens + output_tokens` summed across assistant
  turns. **Cache creation/read tokens are excluded** - including them inflates
  the total ~70x (~1B vs ~15M) and is not what the usage card reports.
- **Sessions** = distinct `sessionId`.
- **Active days / streaks / peak hour** = derived from message timestamps in
  your local timezone.
- **Favorite model** = model with the most assistant turns.
