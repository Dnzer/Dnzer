#!/usr/bin/env python3
from __future__ import annotations
import base64, json, os, time, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
USERNAME = os.environ.get("GITHUB_USERNAME", "").strip()
if not USERNAME:
    raise SystemExit("GITHUB_USERNAME is required")

HEADERS = {"Accept":"application/vnd.github+json", "X-GitHub-Api-Version":"2026-03-10", "User-Agent":"github-tech-stack-stats"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

INTERESTING_FILES = {"package.json","requirements.txt","pyproject.toml","Pipfile","composer.json","Gemfile","go.mod","Cargo.toml","Dockerfile","docker-compose.yml","docker-compose.yaml","compose.yml","compose.yaml","vercel.json","vite.config.js","vite.config.ts","next.config.js","next.config.mjs","astro.config.mjs","angular.json","tailwind.config.js","tailwind.config.ts"}

RULES = [
("Frameworks","React",["react","react-dom"]),("Frameworks","Next.js",["next"]),("Frameworks","Vue",["vue"]),("Frameworks","Nuxt",["nuxt"]),("Frameworks","Angular",["@angular/core","angular.json"]),("Frameworks","Svelte",["svelte"]),("Frameworks","Astro",["astro","astro.config"]),("Frameworks","Express",["express"]),("Frameworks","Django",["django"]),("Frameworks","Flask",["flask"]),("Frameworks","FastAPI",["fastapi"]),("Frameworks","Laravel",["laravel"]),("Runtime","Node.js",["node"]),("Runtime","Bun",["bun"]),("Runtime","Deno",["deno"]),("Styling","Tailwind CSS",["tailwindcss","tailwind.config"]),("Build Tools","Vite",["vite","vite.config"]),("Build Tools","Webpack",["webpack"]),("Build Tools","Babel",["babel"]),("Automation","n8n",["n8n"]),("AI","OpenAI",["openai"]),("AI","Ollama",["ollama"]),("AI","LangChain",["langchain"]),("AI","YOLO",["yolo","ultralytics"]),("Databases","PostgreSQL",["postgresql","postgres","psycopg","pg"]),("Databases","MySQL",["mysql","mysql2"]),("Databases","MongoDB",["mongodb","mongoose"]),("Databases","SQLite",["sqlite"]),("Databases","Redis",["redis"]),("DevOps","Docker",["dockerfile","docker-compose","compose.yaml","compose.yml"]),("DevOps","GitHub Actions",[".github/workflows"]),("DevOps","Vercel",["vercel.json"]),("Cloud","AWS",["boto3","aws-sdk","amazonaws"]),("Cloud","Google Cloud",["google-cloud"]),("Cloud","Azure",["azure"]),("Testing","Jest",["jest"]),("Testing","Pytest",["pytest"]),
]

def get(path, params=None):
    url = API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code in (403,429):
                time.sleep(5*(attempt+1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3: raise
            time.sleep(2**attempt)
    return None

def list_repos():
    repos=[]; page=1
    if TOKEN:
        while True:
            batch=get("/user/repos", {"per_page":100,"page":page,"affiliation":"owner"})
            if not batch: break
            repos.extend(batch)
            if len(batch)<100: break
            page+=1
    else:
        while True:
            batch=get(f"/users/{urllib.parse.quote(USERNAME)}/repos", {"per_page":100,"page":page,"type":"owner"})
            if not batch: break
            repos.extend(batch)
            if len(batch)<100: break
            page+=1
    return [r for r in repos if not r.get("fork") and not r.get("archived")]

def file_text(repo, path):
    d=get(f"/repos/{USERNAME}/{repo['name']}/contents/{urllib.parse.quote(path,safe='/')}")
    if not d or d.get("type")!="file": return ""
    try: return base64.b64decode(d.get("content","")).decode("utf-8","ignore")
    except Exception: return ""

def analyze(repo):
    langs=get(f"/repos/{USERNAME}/{repo['name']}/languages") or {}
    branch=repo.get("default_branch") or "main"
    tree=get(f"/repos/{USERNAME}/{repo['name']}/git/trees/{urllib.parse.quote(branch,safe='')}",{"recursive":"1"}) or {}
    paths=[x.get("path","") for x in tree.get("tree",[]) if x.get("type")=="blob"]
    found=defaultdict(set)
    if any(p.startswith(".github/workflows/") for p in paths): found["DevOps"].add("GitHub Actions")
    if any(PurePosixPath(p).name.lower()=="dockerfile" for p in paths): found["DevOps"].add("Docker")
    if any(PurePosixPath(p).name.lower() in {"docker-compose.yml","docker-compose.yaml","compose.yml","compose.yaml"} for p in paths): found["DevOps"].add("Docker")
    interesting=[p for p in paths if PurePosixPath(p).name.lower() in {x.lower() for x in INTERESTING_FILES}]
    text="\n".join(file_text(repo,p) for p in interesting[:20])
    low=text.lower()
    for cat,name,terms in RULES:
        if any(t.lower() in low for t in terms): found[cat].add(name)
    return langs, found

def pct(counter):
    total=sum(counter.values())
    return {k:round(v*100/total,2) for k,v in counter.most_common()} if total else {}

def esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"','&quot;')

def svg(username, languages, tech, repos, stamp):
    rows=[]; y=155
    for name,p in list(languages.items())[:8]:
        bar=max(2,int(400*p/100)); rows.append(f'<text x="55" y="{y}" class="label">{esc(name)}</text><rect x="190" y="{y-17}" width="400" height="18" rx="9" class="track"/><rect x="190" y="{y-17}" width="{bar}" height="18" rx="9" class="bar"/><text x="610" y="{y}" class="pct">{p:.1f}%</text>'); y+=38
    items=[]; y=155
    for cat,vals in tech.items():
        for name,count in list(vals.items())[:4]:
            items.append(f'<text x="690" y="{y}" class="cat">{esc(cat)}</text><text x="790" y="{y}" class="tech">{esc(name)}</text><text x="845" y="{y+18}" class="count">{count}</text>'); y+=43
            if y>570: break
        if y>570: break
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="650" viewBox="0 0 900 650"><rect width="900" height="650" rx="24" fill="#0d1117"/><rect x="1" y="1" width="898" height="648" rx="24" fill="none" stroke="#30363d"/><text x="55" y="55" class="title">GitHub Tech Stack</text><text x="55" y="88" class="subtitle">@{esc(username)} · {repos} repositories analyzed</text><line x1="55" y1="112" x2="845" y2="112" stroke="#30363d"/><text x="55" y="135" class="section">LANGUAGES</text>{''.join(rows)}<line x1="665" y1="135" x2="665" y2="590" stroke="#30363d"/><text x="690" y="135" class="section">STACK</text>{''.join(items)}<text x="55" y="620" class="footer">Updated {esc(stamp)} · Generated by GitHub Actions</text><style>.title{{fill:#f0f6fc;font:700 30px sans-serif}}.subtitle{{fill:#8b949e;font:400 16px sans-serif}}.section{{fill:#58a6ff;font:700 13px sans-serif;letter-spacing:2px}}.label{{fill:#c9d1d9;font:500 14px sans-serif}}.pct{{fill:#8b949e;font:600 13px sans-serif}}.track{{fill:#21262d}}.bar{{fill:#58a6ff}}.cat{{fill:#8b949e;font:400 10px sans-serif}}.tech{{fill:#c9d1d9;font:600 12px sans-serif}}.count{{fill:#6e7681;font:400 10px sans-serif}}.footer{{fill:#6e7681;font:400 11px sans-serif}}</style></svg>'''

def main():
    repos=list_repos(); lang=Counter(); tech=defaultdict(Counter); details=[]
    for i,r in enumerate(repos,1):
        try: langs,found=analyze(r)
        except Exception as e: print(f"[WARN] {r['name']}: {e}"); continue
        lang.update(langs)
        for cat,names in found.items():
            for n in names: tech[cat][n]+=1
        details.append({"name":r["name"],"private":bool(r.get("private")),"html_url":r.get("html_url"),"languages":langs})
        print(f"[{i}/{len(repos)}] {r['name']}")
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out={"username":USERNAME,"repositories_analyzed":len(details),"generated_at":stamp,"languages":dict(lang.most_common()),"language_percentages":pct(lang),"technologies":{c:dict(v.most_common()) for c,v in sorted(tech.items())},"repositories":details}
    Path("data").mkdir(exist_ok=True); Path("assets").mkdir(exist_ok=True)
    Path("data/tech-stack.json").write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding="utf-8")
    Path("assets/tech-stack.svg").write_text(svg(USERNAME,out["language_percentages"],out["technologies"],len(details),stamp),encoding="utf-8")
    print(f"Generated stats for {len(details)} repositories.")

if __name__=="__main__": main()
