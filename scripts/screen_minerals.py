# -*- coding: utf-8 -*-
"""
핵심광물 스크리닝 — raw/{issue}.md 를 기사([A n]) 단위로 나눠 §3 광물명·동의어 히트 수를 센다.

사용법:
  python scripts/screen_minerals.py 26-18     # 콘솔 출력
  python scripts/screen_minerals.py --all     # 전 호 → screening.csv

등급 후보(최종 등급은 Claude가 원문을 읽고 판단):
  A 후보: 제목에 광물 키워드가 있거나, 광물 히트 합계 ≥ 25
  B 후보: 히트 합계 ≥ 5
  C 후보: 그 외
EWS(공급망 동향) 섹션은 광물 키워드가 들어간 헤드라인 줄을 따로 뽑아 보여준다.
"""
import sys, re, csv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minerals import MINERALS

HERE = Path(__file__).resolve().parent.parent
RAW = HERE / "raw"
SKIP_ISSUES = re.compile(r"합본|-E\d")          # 통합본·영문판은 스크리닝 제외(§6-7)

PATTERNS = {}
# 대문자 약어는 대소문자 구분 (REE, LEU, PGM, MSP, GaN …), 일반 영문은 대소문자 무시
for name, (_, syns) in MINERALS.items():
    parts = []
    for s in syns:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-]*", s):
            flag = "" if (s.isupper() or re.search(r"[A-Z].*[A-Z]", s)) else "(?i:"
            pat = r"(?<![A-Za-z])" + re.escape(s) + (r"s?" if s[-1].islower() else "") + r"(?![A-Za-z])"
            parts.append(pat if not flag else flag + pat + ")")
        else:
            parts.append(re.escape(s))
    PATTERNS[name] = re.compile("|".join(parts))

CORE = "핵심광물(총론)"
STEEL = "철강(232조 관련 시 한정)"


def split_articles(text):
    arts = []
    cur = None
    for line in text.split("\n"):
        m = re.match(r"^## \[(A\d+|FRONT|BACK)\] ?(.*)$", line)
        if m:
            cur = {"id": m.group(1), "head": m.group(2).strip(), "lines": []}
            arts.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    return [a for a in arts if a["id"].startswith("A")]


def pages_of(lines):
    ps = [m.group(1) for l in lines for m in [re.match(r"<!-- (p\.\d+|pdf\d+) -->", l)] if m]
    return f"{ps[0]}–{ps[-1]}" if ps else ""


def count(text):
    return Counter({n: len(p.findall(text)) for n, p in PATTERNS.items() if p.search(text)})


def grade(title_hits, hits):
    core_total = sum(v for k, v in hits.items() if k != STEEL)
    if title_hits or core_total >= 25:
        return "A"
    if core_total >= 5:
        return "B"
    return "C"


def screen(issue, verbose=True):
    p = RAW / f"{issue}.md"
    if not p.exists():
        print(f"[{issue}] raw 없음 — extract 먼저"); return []
    rows = []
    for a in split_articles(p.read_text(encoding="utf-8")):
        body = "\n".join(a["lines"])
        hits = count(body)
        head = a["head"]
        title = head.split("|", 1)[-1].strip()
        th = count(title)
        is_ews = bool(re.search(r"EWS|공급망\s*주간|공급망/에너지", head))
        g = grade(sum(th.values()) if not is_ews else 0, hits)
        ews_lines = []
        if is_ews or re.search(r"\[[^\]]*(광물|희토|리튬|흑연|니켈|코발트|구리|갈륨|우라늄)", body):
            for l in a["lines"]:
                if len(l) < 300 and any(PATTERNS[n].search(l) for n in PATTERNS) and (
                        l.startswith("|") or l.startswith("美") or l.startswith("中") or l.startswith("**[") or re.match(r"^[^\s]{1,6},", l)):
                    ews_lines.append(l.strip()[:200])
        rows.append({
            "issue": issue, "art": a["id"], "section": head.split("|")[0].strip(), "title": title,
            "pages": pages_of(a["lines"]), "total": sum(hits.values()), "grade_cand": g,
            "hits": "; ".join(f"{k}:{v}" for k, v in hits.most_common()),
            "ews_mineral_lines": len(ews_lines),
        })
        if verbose:
            print(f"[{issue} {a['id']}] {g} | {head[:70]} | {rows[-1]['pages']} | 합계 {rows[-1]['total']}")
            if hits:
                print("    " + rows[-1]["hits"])
            for l in ews_lines[:15]:
                print("    · " + l)
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        issues = sorted(p.stem for p in RAW.glob("*.md") if not SKIP_ISSUES.search(p.stem))
        allrows = []
        for i in issues:
            allrows += screen(i, verbose=False)
        with open(HERE / "screening.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(allrows[0].keys()))
            w.writeheader(); w.writerows(allrows)
        c = Counter(r["grade_cand"] for r in allrows)
        print(f"screening.csv: {len(issues)}호 {len(allrows)}기사 | A후보 {c['A']} / B후보 {c['B']} / C후보 {c['C']}")
    elif args:
        for i in args:
            screen(i)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
