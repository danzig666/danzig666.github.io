#!/usr/bin/env python3
"""Build QGIS/index.html: a catalogue of the public QGIS plugins in this account.

A repository counts as a QGIS plugin when it has a metadata.txt with a [general]
section that names the plugin and its qgisMinimumVersion (the file every QGIS
plugin ships). Forks are listed too, marked with the repository they fork.

Standard library only. Set GITHUB_TOKEN to avoid the low anonymous rate limit.

    python scripts/build_qgis_page.py            # writes QGIS/index.html and QGIS/plugins.json
"""

import configparser
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OWNER = os.environ.get("PAGE_OWNER", "danzig666")
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "QGIS"
# Repositories to leave out even though they contain a plugin.
EXCLUDE = {s.strip().lower() for s in os.environ.get("EXCLUDE_REPOS", "").split(",") if s.strip()}
SKIP_DIRS = re.compile(r"(^|/)(tests?|testdata|test_data|examples?|docs?|build|dist|\.github)/", re.I)

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch(url, accept="application/vnd.github+json", raw=False):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "qgis-plugin-page-builder"})
    if TOKEN and url.startswith(API):
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            link = resp.headers.get("Link", "")
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):  # missing, or empty repository
            return None, ""
        raise
    return (body if raw else json.loads(body)), link


def api_pages(url):
    while url:
        data, link = fetch(url)
        yield from data or []
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None


def parse_metadata(text):
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str  # keys are camelCase
    try:
        cp.read_string(text)
    except configparser.Error:
        return None
    if not cp.has_section("general"):
        return None
    g = {k: v.strip() for k, v in cp.items("general")}
    if not g.get("name") or not g.get("qgisMinimumVersion"):
        return None
    return g


def find_plugin(repo):
    """Return (metadata dict, folder inside repo) for the shallowest plugin metadata.txt."""
    branch = repo["default_branch"]
    try:
        tree, _ = fetch(f"{API}/repos/{repo['full_name']}/git/trees/{urllib.parse.quote(branch)}?recursive=1")
    except urllib.error.HTTPError as e:
        if e.code in (403, 451) and e.headers.get("X-RateLimit-Remaining") != "0":
            print(f"  skipped {repo['full_name']}: HTTP {e.code}", file=sys.stderr)
            return None, None
        raise
    if not tree:
        return None, None
    paths = [
        t["path"] for t in tree.get("tree", [])
        if t["type"] == "blob" and t["path"].split("/")[-1] == "metadata.txt" and not SKIP_DIRS.search(t["path"])
    ]
    for path in sorted(paths, key=lambda p: (p.count("/"), p)):
        raw, _ = fetch(f"https://raw.githubusercontent.com/{repo['full_name']}/{branch}/{urllib.parse.quote(path)}", raw=True)
        if raw is None:
            continue
        meta = parse_metadata(raw.decode("utf-8-sig", errors="replace"))
        if meta:
            return meta, path.rpartition("/")[0]
    return None, None


def truthy(v):
    return str(v).strip().lower() in ("true", "yes", "1")


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def collect():
    plugins = []
    for repo in api_pages(f"{API}/users/{OWNER}/repos?per_page=100&type=owner&sort=pushed"):
        if repo["private"] or repo["archived"] or repo.get("disabled") or repo["name"].lower() in EXCLUDE:
            continue
        if repo["name"].lower() == f"{OWNER}.github.io".lower():
            continue
        meta, folder = find_plugin(repo)
        if not meta:
            continue
        name = repo["full_name"]
        print(f"  plugin: {name} -> {meta['name']}", file=sys.stderr)

        fork = None
        if repo["fork"]:
            full, _ = fetch(f"{API}/repos/{name}")
            parent = (full or {}).get("parent")
            if parent:
                cmp_, _ = fetch(
                    f"{API}/repos/{parent['full_name']}/compare/"
                    f"{urllib.parse.quote(parent['default_branch'])}...{OWNER}:{urllib.parse.quote(repo['default_branch'])}"
                )
                fork = {
                    "parent": parent["full_name"],
                    "parent_url": parent["html_url"],
                    "ahead": (cmp_ or {}).get("ahead_by"),
                }
            else:
                fork = {"parent": None, "parent_url": None, "ahead": None}

        release, _ = fetch(f"{API}/repos/{name}/releases/latest")
        download = None
        if release:
            zips = [a for a in release.get("assets", []) if a["name"].lower().endswith(".zip")]
            download = {
                "tag": release["tag_name"],
                "url": zips[0]["browser_download_url"] if zips else release["html_url"],
                "is_zip": bool(zips),
            }

        icon = meta.get("icon")
        icon_url = None
        if icon and not icon.startswith((":", "/")) and ".." not in icon:
            rel = f"{folder}/{icon}" if folder else icon
            icon_url = f"https://raw.githubusercontent.com/{name}/{repo['default_branch']}/{urllib.parse.quote(rel)}"

        qmax = meta.get("qgisMaximumVersion", "")
        qgis4 = truthy(meta.get("supportsQt6", "")) or version_tuple(qmax) >= (4,)

        tags = [t.strip() for t in re.split(r"[,;]", meta.get("tags", "")) if t.strip()]
        plugins.append({
            "repo": repo["name"],
            "repo_url": repo["html_url"],
            "name": meta["name"],
            "version": meta.get("version", ""),
            "description": meta.get("description") or repo.get("description") or "",
            "about": meta.get("about", ""),
            "tags": tags[:8],
            "qgis_min": meta.get("qgisMinimumVersion", ""),
            "qgis_max": qmax,
            "qgis4": qgis4,
            "experimental": truthy(meta.get("experimental", "")),
            "homepage": meta.get("homepage", ""),
            "icon": icon_url,
            "stars": repo["stargazers_count"],
            "pushed": repo["pushed_at"][:10],
            "pushed_at": repo["pushed_at"],
            "fork": fork,
            "release": download,
        })
    # Most recently updated first, own plugins and forks mixed.
    plugins.sort(key=lambda p: p["pushed_at"], reverse=True)
    return plugins


def esc(s):
    return html.escape(s or "", quote=True)


def card(p):
    badges = []
    if p["fork"]:
        parent = p["fork"]["parent"]
        ahead = p["fork"]["ahead"]
        txt = f"Fork of {esc(parent)}" if parent else "Fork"
        if ahead:
            txt += f" · {ahead} commit{'s' if ahead != 1 else ''} ahead"
        link = p["fork"]["parent_url"]
        badges.append(f'<a class="badge fork" href="{esc(link)}">{txt}</a>' if link else f'<span class="badge fork">{txt}</span>')
    qrange = f"QGIS {esc(p['qgis_min'])}" + (f"–{esc(p['qgis_max'])}" if p["qgis_max"] else "+")
    badges.append(f'<span class="badge">{qrange}</span>')
    if p["qgis4"]:
        badges.append('<span class="badge ok">QGIS 4 / Qt6</span>')
    if p["experimental"]:
        badges.append('<span class="badge warn">Experimental</span>')

    icon = (f'<img class="icon" src="{esc(p["icon"])}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{{className:\'icon ph\'}}))">'
            if p["icon"] else '<div class="icon ph"></div>')

    links = [f'<a href="{esc(p["repo_url"])}">Source</a>']
    if p["release"]:
        label = "Download zip" if p["release"]["is_zip"] else "Latest release"
        links.insert(0, f'<a class="primary" href="{esc(p["release"]["url"])}">{label} <span class="muted">{esc(p["release"]["tag"])}</span></a>')
    hp = p["homepage"].rstrip("/")
    if hp and hp != p["repo_url"].rstrip("/") and hp.startswith("http"):
        links.append(f'<a href="{esc(p["homepage"])}">Homepage</a>')
    links.append(f'<a href="{esc(p["repo_url"])}/issues">Issues</a>')

    about = ""
    if p["about"] and p["about"].strip() != p["description"].strip():
        paras = "".join(f"<p>{esc(x)}</p>" for x in re.split(r"\n\s*\n", p["about"]) if x.strip())
        about = f'<details><summary>More</summary>{paras}</details>'

    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in p["tags"])
    search = " ".join([p["name"], p["repo"], p["description"], p["about"], " ".join(p["tags"])]).lower()
    version = f'<span class="ver">v{esc(p["version"])}</span>' if p["version"] else ""
    return f"""
<article class="card" data-search="{esc(search)}" data-fork="{'1' if p['fork'] else '0'}" data-q4="{'1' if p['qgis4'] else '0'}">
  <header>{icon}<div><h2><a href="{esc(p['repo_url'])}">{esc(p['name'])}</a> {version}</h2>
  <div class="badges">{''.join(badges)}</div></div></header>
  <p class="desc">{esc(p['description'])}</p>
  {about}
  <div class="tags">{tags}</div>
  <footer><div class="links">{''.join(links)}</div><span class="muted small">Updated {esc(p['pushed'])}</span></footer>
</article>"""


def render(plugins):
    own = sum(1 for p in plugins if not p["fork"])
    forks = len(plugins) - own
    cards = "".join(card(p) for p in plugins)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QGIS Plugins</title>
<meta name="description" content="QGIS plugins by {esc(OWNER)}: {own} plugins and {forks} forks.">
<style>
:root {{
  --bg:#f6f7f9; --surface:#fff; --text:#1b2530; --muted:#5d6b78; --line:#dde2e8;
  --accent:#2e7d32; --accent-soft:#e6f2e7; --link:#1565c0;
  --fork:#7b4fb0; --fork-soft:#f1eafa; --warn:#9a5b00; --warn-soft:#fdf1dc;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#11161b; --surface:#1a2129; --text:#e3e8ed; --muted:#97a3ae; --line:#2b3540;
    --accent:#7cc47f; --accent-soft:#1f3322; --link:#7db4f0;
    --fork:#c3a2ec; --fork-soft:#2c2338; --warn:#f0b357; --warn-soft:#3a2c14;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#11161b; --surface:#1a2129; --text:#e3e8ed; --muted:#97a3ae; --line:#2b3540;
  --accent:#7cc47f; --accent-soft:#1f3322; --link:#7db4f0;
  --fork:#c3a2ec; --fork-soft:#2c2338; --warn:#f0b357; --warn-soft:#3a2c14;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
a {{ color:var(--link); text-decoration:none; }} a:hover {{ text-decoration:underline; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:40px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:30px; letter-spacing:-.01em; }}
.lead {{ margin:0 0 24px; color:var(--muted); }}
.bar {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:20px; }}
.bar input {{ flex:1 1 260px; min-width:0; padding:9px 12px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:var(--text); font:inherit; }}
.chip {{ padding:7px 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--text); font:inherit; font-size:14px; cursor:pointer; }}
.chip[aria-pressed="true"] {{ background:var(--accent-soft); border-color:var(--accent); color:var(--accent); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }}
@media (max-width:420px) {{ .grid {{ grid-template-columns:1fr; }} }}
.card {{ display:flex; flex-direction:column; gap:10px; padding:18px; background:var(--surface); border:1px solid var(--line); border-radius:12px; }}
.card[hidden] {{ display:none; }}
.card header {{ display:flex; gap:12px; align-items:flex-start; }}
.icon {{ width:40px; height:40px; flex:none; border-radius:8px; object-fit:contain; }}
.icon.ph {{ background:var(--accent-soft); }}
h2 {{ margin:0; font-size:17px; line-height:1.3; }} h2 a {{ color:var(--text); }}
.ver {{ font-size:13px; font-weight:400; color:var(--muted); }}
.badges, .tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }}
.badge {{ font-size:12px; padding:2px 8px; border-radius:999px; background:var(--bg); border:1px solid var(--line); color:var(--muted); }}
.badge.ok {{ background:var(--accent-soft); border-color:transparent; color:var(--accent); }}
.badge.fork {{ background:var(--fork-soft); border-color:transparent; color:var(--fork); }}
.badge.warn {{ background:var(--warn-soft); border-color:transparent; color:var(--warn); }}
.desc {{ margin:0; }}
details {{ color:var(--muted); font-size:14px; }} details summary {{ cursor:pointer; color:var(--link); }}
details p {{ margin:8px 0 0; white-space:pre-line; }}
.tag {{ font-size:12px; color:var(--muted); }} .tag::before {{ content:"#"; }}
.card footer {{ margin-top:auto; display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; align-items:center; padding-top:10px; border-top:1px solid var(--line); }}
.links {{ display:flex; flex-wrap:wrap; gap:14px; font-size:14px; }}
.links .primary {{ font-weight:600; }}
.muted {{ color:var(--muted); font-weight:400; }} .small {{ font-size:12px; }}
.empty {{ display:none; color:var(--muted); padding:24px 0; }}
.foot {{ margin-top:32px; color:var(--muted); font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>QGIS Plugins</h1>
  <p class="lead">{own} plugins and {forks} forks by <a href="https://github.com/{esc(OWNER)}">{esc(OWNER)}</a>. Install a downloaded zip in QGIS with <em>Plugins › Manage and Install Plugins › Install from ZIP</em>.</p>
  <div class="bar" role="search">
    <input id="q" type="search" placeholder="Search plugins…" aria-label="Search plugins">
    <button class="chip" data-f="all" aria-pressed="true">All</button>
    <button class="chip" data-f="own" aria-pressed="false">Own</button>
    <button class="chip" data-f="fork" aria-pressed="false">Forks</button>
    <button class="chip" data-f="q4" aria-pressed="false">QGIS 4 ready</button>
  </div>
  <div class="grid" id="grid">{cards}
  </div>
  <p class="empty" id="empty">No plugins match.</p>
  <p class="foot">This page is rebuilt automatically from each repository's <code>metadata.txt</code>.</p>
</div>
<script>
(function () {{
  var q = document.getElementById("q"), cards = [].slice.call(document.querySelectorAll(".card")),
      chips = [].slice.call(document.querySelectorAll(".chip")), empty = document.getElementById("empty"), f = "all";
  function apply() {{
    var t = q.value.trim().toLowerCase(), n = 0;
    cards.forEach(function (c) {{
      var ok = (!t || c.dataset.search.indexOf(t) >= 0) &&
        (f === "all" || (f === "own" && c.dataset.fork === "0") || (f === "fork" && c.dataset.fork === "1") || (f === "q4" && c.dataset.q4 === "1"));
      c.hidden = !ok; if (ok) n++;
    }});
    empty.style.display = n ? "none" : "block";
  }}
  q.addEventListener("input", apply);
  chips.forEach(function (b) {{ b.addEventListener("click", function () {{
    f = b.dataset.f; chips.forEach(function (x) {{ x.setAttribute("aria-pressed", String(x === b)); }}); apply();
  }}); }});
}})();
</script>
</body>
</html>
"""


def main():
    print(f"Scanning public repositories of {OWNER}…", file=sys.stderr)
    plugins = collect()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "plugins.json").write_text(json.dumps(plugins, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (OUT_DIR / "index.html").write_text(render(plugins), encoding="utf-8", newline="\n")
    print(f"Wrote {len(plugins)} plugins to {OUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
