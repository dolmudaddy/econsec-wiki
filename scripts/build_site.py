# -*- coding: utf-8 -*-
"""
wiki/ (Obsidian vault) → site/ (정적 웹사이트) 변환기

사용법:  python scripts/build_site.py            # site/ 생성
        python scripts/build_site.py --serve    # 생성 후 http://localhost:8000 미리보기
필요:    pip install markdown

기능: [[위키링크]]·[[경로|표시]]·[[경로#절]] 해석, > [!note] 콜아웃, 표, frontmatter 메타 칩,
      좌측 폴더 탐색, 클라이언트 검색(search.json), 역링크(백링크), 다크모드, 모바일 대응
"""
import re, json, sys, shutil, html, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
from categories import CATEGORY_NAMES

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SITE = ROOT / "site"
SKIP_DIRS = {"_templates", ".obsidian", ".trash"}
FOLDER_ORDER = ["광물별", "이슈", "정책", "연계분야", "국가", "호별", "연표"]
SITE_TITLE = "경제안보 Review 핵심광물 위키"
BUILD_DATE = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")   # KST
COUNTS_MARK = "<!-- PAGE_COUNTS -->"      # 소개.md 안의 자리표시자 → 폴더별 페이지 수 표
META_KEYS = ["category", "issue", "date", "updated", "last_issue", "minerals", "countries", "policies",
             "sectors", "relevance", "mineral_relevance", "group", "key_countries", "linked_sectors"]

# ---------- frontmatter ----------
def parse_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        k, v = line.split(":", 1)
        v = v.split("  #")[0].strip()          # 줄 끝 주석 제거
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            v = v.strip("'\"")
        meta[k.strip()] = v
    return meta, text[m.end():]

# ---------- 페이지 수집 ----------
class Page:
    def __init__(self, path):
        self.path = path
        self.rel = path.relative_to(WIKI).with_suffix("")          # 광물별/희토류(REE)
        self.key = str(self.rel).replace("\\", "/")
        self.name = path.stem
        self.folder = self.rel.parts[0] if len(self.rel.parts) > 1 else ""
        raw = path.read_text(encoding="utf-8")
        self.meta, self.body = parse_frontmatter(raw)
        h1 = re.search(r"^#\s+(.+)$", self.body, re.M)
        self.title = h1.group(1).strip() if h1 else self.name
        self.out = "index.html" if self.name == "00_Home" else self.key + ".html"
        self.links, self.backlinks = set(), set()

    @property
    def href(self):
        return "/".join(quote(p) for p in self.out.split("/"))

def collect():
    pages = []
    for p in sorted(WIKI.rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.relative_to(WIKI).parts):
            continue
        pages.append(Page(p))
    return pages

# ---------- 위키링크 ----------
WIKILINK = re.compile(r"\[\[([^\]\|#]+)(?:#([^\]\|]+))?(?:\|([^\]]+))?\]\]")

def make_resolver(pages):
    by_key = {p.key: p for p in pages}
    by_name = {}
    for p in pages:
        by_name.setdefault(p.name, p)
    def resolve(target):
        t = target.strip().rstrip("\\").replace("\\", "/")   # 표 안의 [[경로\|표시]] 이스케이프 처리
        if t.endswith(".md"):
            t = t[:-3]
        return by_key.get(t) or by_name.get(t.split("/")[-1])
    return resolve

def rel_href(frm, to_href):
    depth = frm.out.count("/")
    return "../" * depth + to_href

def convert_wikilinks(page, resolve):
    def repl(m):
        target, anchor, label = m.group(1), m.group(2), m.group(3)
        text = label or (target.split("/")[-1] + (f" › {anchor}" if anchor else ""))
        tgt = resolve(target)
        if not tgt:
            return f'<span class="broken" title="페이지 없음: {html.escape(target)}">{html.escape(text)}</span>'
        page.links.add(tgt.key)
        frag = f"#{slugify(anchor)}" if anchor else ""
        return f'<a class="wl" href="{rel_href(page, tgt.href)}{frag}">{html.escape(text)}</a>'
    return WIKILINK.sub(repl, page.body)

def slugify(s):
    s = re.sub(r"[^\w\s가-힣-]", "", s).strip().lower()
    return re.sub(r"[\s]+", "-", s)

# ---------- 콜아웃 ----------
CALLOUT = re.compile(r"^> \[!(\w+)\]\s*(.*)$", re.M)
def convert_callouts(text):
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        m = re.match(r"^> \[!(\w+)\]\s*(.*)$", lines[i])
        if m:
            kind, title = m.group(1).lower(), m.group(2).strip() or m.group(1)
            body = []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                body.append(lines[i][1:].lstrip(" "))
                i += 1
            inner = markdown.markdown("\n".join(body), extensions=["tables"])
            out.append(f'<div class="callout callout-{kind}"><div class="callout-title">{html.escape(title)}</div>{inner}</div>')
        else:
            out.append(lines[i]); i += 1
    return "\n".join(out)

# ---------- HTML 템플릿 ----------
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e4e4e4;--side:#f7f7f8;--accent:#0b57d0;--chip:#eef3ff;--code:#f3f3f3;--callout:#fff8e1;--callout-b:#f0c36d}
@media(prefers-color-scheme:dark){:root{--bg:#141517;--fg:#e6e6e6;--muted:#9a9a9a;--line:#2a2b2e;--side:#1b1c1f;--accent:#8ab4f8;--chip:#1f2a44;--code:#1f2023;--callout:#2a2413;--callout-b:#8a6d1f}}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"Segoe UI","Pretendard","Malgun Gothic","Apple SD Gothic Neo",sans-serif;background:var(--bg);color:var(--fg);line-height:1.6}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--bg)}
.top .brand{font-weight:700;white-space:nowrap}.top input{flex:1;max-width:520px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--side);color:var(--fg);font-size:14px}
.top button{display:none;background:none;border:1px solid var(--line);border-radius:6px;padding:6px 10px;color:var(--fg)}
.wrap{display:flex;min-height:calc(100vh - 50px)}
nav{width:270px;flex:none;border-right:1px solid var(--line);background:var(--side);padding:12px 8px;overflow:auto;position:sticky;top:50px;height:calc(100vh - 50px);font-size:14px}
nav details{margin-bottom:4px}nav details.sub{margin:0 0 2px 14px}nav details.sub summary{font-weight:500;font-size:13px}nav summary{cursor:pointer;font-weight:600;padding:4px 6px;list-style:none}nav summary::before{content:"▸ ";color:var(--muted)}nav details[open] summary::before{content:"▾ "}
nav ul{list-style:none;margin:0;padding:0 0 4px 14px}nav li a{display:block;padding:2px 6px;border-radius:4px;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}nav li a.cur,nav li a:hover{background:var(--chip);color:var(--accent);text-decoration:none}
main{flex:1;min-width:0;padding:24px 40px 60px;max-width:1000px}
main h1{margin-top:0}main h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:2em}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0;display:block;overflow-x:auto}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--side)}
blockquote{margin:12px 0;padding:8px 14px;border-left:4px solid var(--accent);background:var(--side)}
.callout{margin:12px 0;padding:10px 14px;border-left:4px solid var(--callout-b);background:var(--callout);border-radius:4px}.callout-title{font-weight:700;margin-bottom:4px}
code{background:var(--code);padding:1px 4px;border-radius:3px;font-size:.9em}pre{background:var(--code);padding:10px;overflow:auto}
.chips{margin:-6px 0 14px;font-size:13px;color:var(--muted)}.chip{display:inline-block;background:var(--chip);border-radius:12px;padding:1px 9px;margin:2px 4px 2px 0;color:var(--fg)}
.broken{color:#b3261e;border-bottom:1px dashed #b3261e;cursor:help}
.backlinks{margin-top:40px;padding-top:12px;border-top:1px solid var(--line);font-size:14px}.backlinks h3{margin:0 0 6px;font-size:14px;color:var(--muted)}
.crumb{font-size:13px;color:var(--muted);margin-bottom:6px}
#results{position:absolute;top:48px;left:0;right:0;margin:0 auto;max-width:720px;background:var(--bg);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.15);max-height:70vh;overflow:auto;display:none;z-index:9}
#results a{display:block;padding:8px 12px;border-bottom:1px solid var(--line);color:var(--fg)}#results a small{display:block;color:var(--muted)}#results a:hover{background:var(--side);text-decoration:none}
footer{font-size:12px;color:var(--muted);padding:20px 40px;border-top:1px solid var(--line)}
.site-footer p{margin:3px 0}.site-footer a{color:var(--muted);text-decoration:underline}.site-footer strong{font-weight:600}
@media(max-width:860px){nav{position:fixed;left:-280px;transition:left .2s;z-index:8;height:calc(100vh - 50px)}nav.open{left:0}.top button{display:block}main{padding:16px}}
"""
JS = """
const base=document.body.dataset.base;let idx=null;const q=document.getElementById('q'),res=document.getElementById('results');
document.getElementById('menu').onclick=()=>document.querySelector('nav').classList.toggle('open');
q.addEventListener('input',async()=>{const s=q.value.trim().toLowerCase();if(!s){res.style.display='none';return}
if(!idx){idx=await (await fetch(base+'search.json')).json()}
const hits=idx.map(p=>{const t=p.title.toLowerCase(),b=p.text.toLowerCase();let sc=0;if(t.includes(s))sc+=10;const n=b.split(s).length-1;sc+=Math.min(n,8);return[sc,p]}).filter(x=>x[0]>0).sort((a,b)=>b[0]-a[0]).slice(0,30);
res.innerHTML=hits.map(([sc,p])=>{const i=p.text.toLowerCase().indexOf(s);const snip=i>=0?p.text.slice(Math.max(0,i-50),i+90):p.text.slice(0,120);return `<a href="${base}${p.href}">${p.title}<small>${p.folder} — …${snip.replace(/</g,'&lt;')}…</small></a>`}).join('')||'<a>검색 결과 없음</a>';res.style.display='block'});
document.addEventListener('click',e=>{if(!res.contains(e.target)&&e.target!==q)res.style.display='none'});
"""

def build_nav(pages, cur):
    groups = {}
    for p in pages:
        if p.name == "00_Home" or not p.folder:
            continue
        groups.setdefault(p.folder, []).append(p)
    order = [f for f in FOLDER_ORDER if f in groups] + [f for f in groups if f not in FOLDER_ORDER]
    top = [f'<a href="{rel_href(cur, "index.html")}">🏠 홈</a>']
    top += [f'<a href="{rel_href(cur, p.href)}">{html.escape(p.name)}</a>' for p in pages if not p.folder and p.name != "00_Home"]
    out = [f'<div style="padding:4px 6px 10px">{" · ".join(top)}</div>']
    li = lambda p: f'<li><a href="{rel_href(cur, p.href)}"{" class=cur" if p is cur else ""}>{html.escape(p.title)}</a></li>'
    cnt = lambda n: f" <span style='color:var(--muted);font-weight:400'>({n})</span>"
    for f in order:
        items = sorted(groups[f], key=lambda p: (not p.name.startswith("_"), p.name))
        opened = " open" if f == cur.folder else ""
        if f == "이슈":   # 이슈는 frontmatter category(scripts/categories.py)별 하위 트리, 각 분류 안은 최신순
            index = [p for p in items if p.name.startswith("_")]
            cats = {}
            for p in items:
                if not p.name.startswith("_"):
                    c = p.meta.get("category")
                    cats.setdefault(c if c in CATEGORY_NAMES else "미분류", []).append(p)
            sub = []
            for c in CATEGORY_NAMES + ["미분류"]:
                ps = sorted(cats.get(c, []), key=lambda p: (str(p.meta.get("date", "")), p.name), reverse=True)
                if ps:
                    o = " open" if cur in ps else ""
                    sub.append(f"<details{o} class=sub><summary>{html.escape(c)}{cnt(len(ps))}</summary><ul>{''.join(li(p) for p in ps)}</ul></details>")
            n = len(items) - len(index)
            out.append(f"<details{opened}><summary>{html.escape(f)}{cnt(n)}</summary><ul>{''.join(li(p) for p in index)}</ul>{''.join(sub)}</details>")
            continue
        out.append(f"<details{opened}><summary>{html.escape(f)}{cnt(len(items))}</summary><ul>{''.join(li(p) for p in items)}</ul></details>")
    return "".join(out)

def chips(meta):
    parts = []
    for k in META_KEYS:
        if k in meta and meta[k]:
            v = meta[k]
            vals = v if isinstance(v, list) else [v]
            parts.append(f'<span class="chip"><b>{k}</b> {html.escape(", ".join(vals))}</span>')
    return f'<div class="chips">{"".join(parts)}</div>' if parts else ""

def render(page, pages, resolve, by_key):
    base = "../" * page.out.count("/")
    body = convert_callouts(convert_wikilinks(page, resolve))
    content = markdown.markdown(body, extensions=["tables", "fenced_code", "sane_lists", "toc"],
                                extension_configs={"toc": {"slugify": lambda v, sep: slugify(v)}})
    bl = sorted(page.backlinks)
    backlinks = ""
    if bl:
        items = "".join(f'<li><a href="{rel_href(page, by_key[k].href)}">{html.escape(by_key[k].title)}</a></li>' for k in bl)
        backlinks = f'<div class="backlinks"><h3>이 페이지를 참조하는 문서 ({len(bl)})</h3><ul>{items}</ul></div>'
    crumb = f'<div class="crumb">{html.escape(page.folder)}</div>' if page.folder else ""
    src = f'<div class="crumb">원본: wiki/{html.escape(page.key)}.md · updated {html.escape(str(page.meta.get("updated", "")))}</div>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="author" content="조성준 (Seong-Jun Cho), KIGAM">
<title>{html.escape(page.title)} · {SITE_TITLE}</title><style>{CSS}</style></head>
<body data-base="{base}"><div class="top"><button id="menu">☰</button><a class="brand" href="{base}index.html">{SITE_TITLE}</a>
<input id="q" type="search" placeholder="검색 (광물·정책·국가·키워드)…" autocomplete="off"><div id="results"></div></div>
<div class="wrap"><nav>{build_nav(pages, page)}</nav><main>{crumb}{chips(page.meta)}{content}{backlinks}{src}</main></div>
<footer class="site-footer">
  <p>출처: 외교부 경제안보외교센터 「경제안보 Review」 각 호. 본 위키의 요약·분석은 원문을 재구성한 것이며 편집자 판단은 별도 표기함. 원문 게시판: <a href="https://www.mofa.go.kr/www/brd/m_26799/list.do">mofa.go.kr</a></p>
  <p>제작: <strong>조성준</strong> (한국지질자원연구원 KIGAM 책임연구원) · Created by <strong>Dr. Seong-Jun Cho</strong>, KIGAM · <a href="{base}{quote("소개")}.html">소개 / About</a></p>
  <p>본 사이트는 개인 연구 목적의 2차 정리물로, 외교부 및 KIGAM의 공식 입장이 아닙니다. This site is an independent secondary compilation and does not represent the official views of MOFA or KIGAM.</p>
  <p>© 2026 Seong-Jun Cho · 편집물 라이선스 CC BY-NC 4.0 (외교부 원문 제외) · 최종 빌드 {BUILD_DATE}</p>
</footer>
<script>{JS}</script></body></html>"""

def counts_table(pages):
    """폴더별 페이지 수 표 (자동 생성 목차 `_*`는 제외)."""
    n = {}
    for p in pages:
        if p.folder and not p.name.startswith("_"):
            n[p.folder] = n.get(p.folder, 0) + 1
    order = [f for f in FOLDER_ORDER if f in n] + [f for f in n if f not in FOLDER_ORDER]
    rows = ["| 구분 | 페이지 수 |", "|---|---|"] + [f"| {f} | {n[f]} |" for f in order]
    return "\n".join(rows + [f"| **합계** | **{sum(n.values())}** |"])

def main():
    pages = collect()
    if not pages:
        sys.exit("wiki/ 에 페이지가 없습니다.")
    for p in pages:
        if COUNTS_MARK in p.body:
            p.body = p.body.replace(COUNTS_MARK, counts_table(pages))
    resolve = make_resolver(pages)
    by_key = {p.key: p for p in pages}
    # 1차: 링크 수집 (백링크용)
    for p in pages:
        for m in WIKILINK.finditer(p.body):
            t = resolve(m.group(1))
            if t and t is not p:
                p.links.add(t.key); t.backlinks.add(p.key)
    if SITE.exists():
        shutil.rmtree(SITE, ignore_errors=True)   # 삭제가 막힌 환경에서는 덮어쓰기로 진행
    SITE.mkdir(exist_ok=True)
    (SITE / ".nojekyll").write_text("")            # GitHub Pages가 _대시보드 같은 파일을 무시하지 않도록
    search = []
    broken = 0
    for p in pages:
        out = SITE / p.out
        out.parent.mkdir(parents=True, exist_ok=True)
        page_html = render(p, pages, resolve, by_key)
        broken += page_html.count('class="broken"')
        out.write_text(page_html, encoding="utf-8")
        plain = re.sub(r"<[^>]+>", " ", markdown.markdown(WIKILINK.sub(lambda m: m.group(3) or m.group(1), p.body), extensions=["tables"]))
        search.append({"title": p.title, "folder": p.folder, "href": p.href, "text": re.sub(r"\s+", " ", plain)[:3000]})
    (SITE / "search.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")
    if not (SITE / "index.html").exists():
        (SITE / "index.html").write_text(f'<meta http-equiv="refresh" content="0;url={pages[0].href}">', encoding="utf-8")
    print(f"site/ 생성 완료: {len(pages)}페이지, 깨진 링크 {broken}개")
    if "--serve" in sys.argv:
        import http.server, functools
        os.chdir(SITE)
        print("미리보기: http://localhost:8000  (Ctrl+C로 종료)")
        http.server.ThreadingHTTPServer(("", 8000), functools.partial(http.server.SimpleHTTPRequestHandler)).serve_forever()

if __name__ == "__main__":
    main()
