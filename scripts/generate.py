#!/usr/bin/env python3
"""Generate the activity charts of the profile README as light/dark SVGs.

Only aggregated numbers are drawn (contributions per day/month, language
share). No repository names, private or not, ever end up in the output.

Usage:
    GH_TOKEN=... python scripts/generate.py --login Adrifib --out assets
"""
import argparse
import json
import os
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape

API = "https://api.github.com/graphql"
W = 780  # width shared by every chart

THEMES = {
    "light": {
        "text": "#1f2328",
        "muted": "#656d76",
        "empty": "#ebedf0",
        "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "bar": "#30a14e",
        "track": "#eaeef2",
    },
    "dark": {
        "text": "#e6edf3",
        "muted": "#8b949e",
        "empty": "#161b22",
        "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "bar": "#26a641",
        "track": "#21262d",
    },
}
LEVEL_INDEX = {"FIRST_QUARTILE": 0, "SECOND_QUARTILE": 1, "THIRD_QUARTILE": 2, "FOURTH_QUARTILE": 3}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def gql(token, query, variables=None):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_calendar(token, login):
    q = """query($login:String!){user(login:$login){contributionsCollection{
      contributionCalendar{totalContributions weeks{contributionDays{
        date contributionCount contributionLevel weekday}}}}}}"""
    cal = gql(token, q, {"login": login})["user"]["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    return cal["weeks"], days, cal["totalContributions"]


def fetch_languages(token, login):
    """Main language of each owned, non-fork repo (counts, not bytes, so
    vendored libraries inside a repo cannot skew the chart)."""
    q = """query($login:String!){user(login:$login){repositories(
      ownerAffiliations:OWNER,isFork:false,first:100){nodes{
      primaryLanguage{name color}}}}}"""
    nodes = gql(token, q, {"login": login})["user"]["repositories"]["nodes"]
    totals, colors = defaultdict(int), {}
    for repo in nodes:
        lang = repo["primaryLanguage"]
        if lang:
            totals[lang["name"]] += 1
            colors[lang["name"]] = lang["color"] or "#8b949e"
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])), colors


def streaks(days):
    counts = [(date.fromisoformat(d["date"]), d["contributionCount"]) for d in days]
    longest = run = 0
    for _, c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    # current streak: today may still be empty, so it does not break the run
    trimmed = counts[:-1] if counts and counts[-1][1] == 0 else counts
    current = 0
    for _, c in reversed(trimmed):
        if not c:
            break
        current += 1
    return current, longest


def svg(width, height, body, t):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}" role="img">{body}</svg>\n'
    )


def text(x, y, s, t, size=11, fill="muted", anchor="start", weight="400"):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{t[fill]}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(s))}</text>'
    )


def heatmap(weeks, t):
    cell, gap, left, top = 11, 3, 32, 22
    step = cell + gap
    width = left + len(weeks) * step
    height = top + 7 * step + 34
    out = []
    last_month = None
    for wi, week in enumerate(weeks):
        first = date.fromisoformat(week["contributionDays"][0]["date"])
        if first.month != last_month and first.day <= 21:
            if last_month is not None or first.day <= 7:
                out.append(text(left + wi * step, 12, MONTHS[first.month - 1], t))
            last_month = first.month
        for d in week["contributionDays"]:
            color = t["empty"] if d["contributionLevel"] == "NONE" else t["levels"][LEVEL_INDEX[d["contributionLevel"]]]
            n = d["contributionCount"]
            out.append(
                f'<rect x="{left + wi * step}" y="{top + d["weekday"] * step}" width="{cell}" height="{cell}" '
                f'rx="2" fill="{color}"><title>{n} contribution{"s" if n != 1 else ""} on {d["date"]}</title></rect>'
            )
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(text(0, top + row * step + 9, label, t, size=10))
    # legend
    lx, ly = width - 5 * step - 62, top + 7 * step + 12
    out.append(text(lx - 6, ly + 9, "Less", t, size=10, anchor="end"))
    for i, c in enumerate([t["empty"]] + t["levels"]):
        out.append(f'<rect x="{lx + i * step}" y="{ly}" width="{cell}" height="{cell}" rx="2" fill="{c}"/>')
    out.append(text(lx + 5 * step + 4, ly + 9, "More", t, size=10))
    return svg(width, height, "".join(out), t)


def monthly(days, t):
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(12):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    totals = defaultdict(int)
    for d in days:
        dt = date.fromisoformat(d["date"])
        totals[(dt.year, dt.month)] += d["contributionCount"]
    values = [totals[k] for k in keys]
    peak = max(values) or 1
    height, base, top = 190, 160, 24
    slot = (W - 20) / 12
    out = []
    for i, (k, v) in enumerate(zip(keys, values)):
        h = (base - top) * v / peak
        x = 10 + i * slot + slot * 0.2
        bw = slot * 0.6
        out.append(f'<rect x="{x:.1f}" y="{top}" width="{bw:.1f}" height="{base - top}" rx="4" fill="{t["track"]}"/>')
        if v:
            out.append(
                f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" fill="{t["bar"]}">'
                f"<title>{MONTHS[k[1] - 1]} {k[0]}: {v}</title></rect>"
            )
        out.append(text(x + bw / 2, base - h - 6 if v else base - 6, v, t, size=11, fill="text", anchor="middle", weight="600"))
        label = MONTHS[k[1] - 1] + (f" '{str(k[0])[2:]}" if k[1] == 1 or i == 0 else "")
        out.append(text(x + bw / 2, base + 18, label, t, size=11, anchor="middle"))
    return svg(W, height, "".join(out), t)


def languages(langs, colors, t, top_n=10):
    total = sum(s for _, s in langs) or 1
    shown = langs[:top_n]
    rest = sum(s for _, s in langs[top_n:])
    if rest:
        shown = shown + [("Other", rest)]
        colors = {**colors, "Other": t["muted"]}
    bar_h, y0 = 12, 6
    out = [f'<clipPath id="r"><rect x="0" y="{y0}" width="{W}" height="{bar_h}" rx="6"/></clipPath><g clip-path="url(#r)">']
    x = 0.0
    for name, size in shown:
        w = W * size / total
        out.append(f'<rect x="{x:.2f}" y="{y0}" width="{w + 0.5:.2f}" height="{bar_h}" fill="{colors[name]}"/>')
        x += w
    out.append("</g>")
    col_w = W / 3
    for i, (name, size) in enumerate(shown):
        cx, cy = (i % 3) * col_w, 46 + (i // 3) * 26
        out.append(f'<circle cx="{cx + 6:.1f}" cy="{cy - 4}" r="5" fill="{colors[name]}"/>')
        out.append(text(cx + 18, cy, name, t, size=13, fill="text", weight="600"))
        out.append(text(cx + 18 + 8 * len(name) + 8, cy, f"{size} repo{'s' if size != 1 else ''}", t, size=13))
    rows = (len(shown) + 2) // 3
    return svg(W, 46 + rows * 26, "".join(out), t)


def stats(total, current, longest, active_days, t):
    items = [
        (total, "contributions in the last year"),
        (active_days, "active days"),
        (current, "day current streak"),
        (longest, "day longest streak"),
    ]
    col = W / len(items)
    out = []
    for i, (value, label) in enumerate(items):
        cx = col * i + col / 2
        out.append(text(cx, 38, value, t, size=34, fill="text", anchor="middle", weight="700"))
        out.append(text(cx, 62, label, t, size=12, anchor="middle"))
        if i:
            out.append(f'<line x1="{col * i:.1f}" y1="14" x2="{col * i:.1f}" y2="68" stroke="{t["track"]}" stroke-width="1.5"/>')
    return svg(W, 80, "".join(out), t)


def write(out_dir, name, builder, *args):
    for mode, t in THEMES.items():
        with open(os.path.join(out_dir, f"{name}-{mode}.svg"), "w", encoding="utf-8") as f:
            f.write(builder(*args, t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", required=True)
    ap.add_argument("--out", default="assets")
    ap.add_argument(
        "--languages", choices=["always", "never"], default="always",
        help="'never' keeps the existing language chart (e.g. when the token cannot see private repos)",
    )
    args = ap.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ["GITHUB_TOKEN"]
    os.makedirs(args.out, exist_ok=True)

    weeks, days, total = fetch_calendar(token, args.login)
    current, longest = streaks(days)
    active = sum(1 for d in days if d["contributionCount"])
    write(args.out, "stats", stats, total, current, longest, active)
    write(args.out, "heatmap", heatmap, weeks)
    write(args.out, "monthly", monthly, days)
    if args.languages == "always":
        langs, colors = fetch_languages(token, args.login)
        write(args.out, "languages", lambda *a: languages(langs, colors, a[-1]))
    print(f"{datetime.now(timezone.utc):%Y-%m-%d} total={total} active={active} streak={current}/{longest}")


if __name__ == "__main__":
    main()
