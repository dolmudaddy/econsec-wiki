# -*- coding: utf-8 -*-
"""
wiki/광물별/_대시보드.md 재생성 — 광물 페이지 frontmatter + 이슈/호별 페이지 frontmatter 집계.

열: 광물 | 최근 언급 호 | 최근 3개월 언급 횟수 | 최신 정책 이벤트 | 현재 판단(첫 줄)
'최근 3개월'은 manifest 최신 발간일 기준 92일.
"""
import sys, re, csv
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minerals import MINERALS, GROUP_ORDER
from wikilib import ROOT, WIKI, parse


def latest_date():
    with open(ROOT / "manifest.csv", encoding="utf-8-sig") as f:
        return max(date.fromisoformat(r["date"]) for r in csv.DictReader(f))


def mentions():
    """광물 → [(date, issue)] : 이슈 기사 페이지 기준."""
    out = {}
    for p in (WIKI / "이슈").glob("*.md"):
        fm, _ = parse(p)
        if not fm or not fm.get("date"):
            continue
        for m in fm.get("minerals") or []:
            out.setdefault(m, []).append((date.fromisoformat(fm["date"]), fm.get("issue", "")))
    return out


def judgement(body):
    m = re.search(r"^> \*\*현재 판단[^*]*\*\*[ \t]*(.*)$", body, re.M)
    if not m:
        return ""
    first = m.group(1).strip()
    if not first:  # 다음 인용 줄
        nxt = re.search(r"^> \*\*현재 판단.*\n> (.+)$", body, re.M)
        first = nxt.group(1).strip() if nxt else ""
    first = first.replace("|", "／").replace("**", "")
    return first if len(first) <= 120 else first[:119] + "…"


def latest_event(body):
    sec = re.search(r"## 3\. 정책·조치 타임라인(.*?)(?=\n## )", body, re.S)
    if not sec:
        return ""
    rows = [r for r in sec.group(1).split("\n") if r.startswith("|") and not re.match(r"^\|\s*(날짜|-)", r)]
    rows = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    rows = [r for r in rows if len(r) >= 3 and re.match(r"\d{4}", r[0])]
    if not rows:
        return ""
    r = max(rows, key=lambda r: r[0])
    return f"{r[0]} {r[1]} — {r[2]}".replace("|", "／")[:90]


def main():
    ref = latest_date()
    since = ref - timedelta(days=92)
    ment = mentions()
    rows_by_group = {g: [] for g in GROUP_ORDER}
    for name, (group, _) in MINERALS.items():
        p = WIKI / "광물별" / f"{name}.md"
        ms = sorted(ment.get(name, []), reverse=True)
        recent = sum(1 for d, _ in ms if d >= since)
        if p.exists():
            fm, body = parse(p)
            last = fm.get("last_issue") or (ms[0][1] if ms else "")
            row = (f"[[광물별/{name}\\|{name}]]", f"[[호별/{last}\\|{last}]]" if last else "—",
                   str(recent), latest_event(body) or "—", judgement(body) or "—")
        else:
            row = (f"{name} (페이지 미생성)", ms[0][1] if ms else "—", str(recent), "—", "—")
        rows_by_group[group].append(row)

    out = ["---", "type: dashboard", f"updated: {date.today().isoformat()}", "tags: [dashboard]", "---",
           "# 핵심광물 대시보드", "",
           f"> 자동 생성: `python scripts/build_dashboard.py` · 기준일 {ref.isoformat()} (최신 발간일) · "
           f"최근 3개월 = {since.isoformat()} 이후 이슈 기사 수", ""]
    for g in GROUP_ORDER:
        out += [f"## {g}", "", "| 광물 | 최근 언급 호 | 최근 3개월 언급 | 최신 정책 이벤트 | 현재 판단(첫 줄) |",
                "|---|---|---|---|---|"]
        out += ["| " + " | ".join(r) + " |" for r in rows_by_group[g]]
        out.append("")
    (WIKI / "광물별" / "_대시보드.md").write_text("\n".join(out), encoding="utf-8")
    print(f"_대시보드.md 생성 ({len(MINERALS)}개 광물, 기준일 {ref})")


if __name__ == "__main__":
    main()
