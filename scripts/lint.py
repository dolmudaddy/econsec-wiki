# -*- coding: utf-8 -*-
"""
위키 린트 — 깨진 링크 · frontmatter 누락 · 미등록 광물명 · 이슈 category · 파일명 금지문자 · 광물 페이지 6축 섹션 점검.

사용법: python scripts/lint.py        (문제 0건이면 exit 0)
"""
import sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minerals import MINERAL_NAMES
from categories import CATEGORY_NAMES
from wikilib import WIKI, parse, pages, links

TYPES = {"mineral", "issue_article", "policy", "sector", "country", "issue", "timeline", "home", "dashboard", "index", "about"}
MINERAL_AXES = ["## 1. 공급 구조", "## 2. 수요 연계", "## 3. 정책·조치 타임라인", "## 4. 리스크·이벤트",
                "## 5. 한국 시사점", "## 6. 인사이트 로그"]
BAD_CHARS = re.compile(r'[\\:*?"<>|]')


def main():
    errs = []
    all_pages = pages()
    by_rel = {p.relative_to(WIKI).with_suffix("").as_posix() for p in all_pages}
    by_name = {p.stem for p in all_pages}
    for p in all_pages:
        rel = p.relative_to(WIKI).as_posix()
        if BAD_CHARS.search(p.stem):
            errs.append(f"{rel}: 파일명 금지문자")
        fm, body = parse(p)
        if fm is None:
            errs.append(f"{rel}: frontmatter 없음"); fm = {}
        elif fm.get("type") not in TYPES:
            errs.append(f"{rel}: type 누락/미정의 ({fm.get('type')})")
        for key in ("mineral", "minerals"):
            v = fm.get(key)
            for m in ([v] if isinstance(v, str) else (v or [])):
                if m and m not in MINERAL_NAMES:
                    errs.append(f"{rel}: 미등록 광물명 '{m}' ({key})")
        if fm.get("type") == "mineral":
            if p.stem != fm.get("mineral"):
                errs.append(f"{rel}: 파일명≠mineral")
            for ax in MINERAL_AXES:
                if ax not in body:
                    errs.append(f"{rel}: 섹션 누락 '{ax}'")
        if fm.get("type") == "issue_article" and fm.get("relevance") not in ("A", "B"):
            errs.append(f"{rel}: relevance는 A/B만 (C는 이슈 페이지 금지)")
        if fm.get("type") == "issue_article" and fm.get("category") not in CATEGORY_NAMES:
            errs.append(f"{rel}: category 누락/미등록 ('{fm.get('category')}') — scripts/categories.py 목록에서 1개")
        for l in links(body):
            if l not in by_rel and l not in by_name:
                errs.append(f"{rel}: 깨진 링크 [[{l}]]")
    print(f"lint: 페이지 {len(all_pages)}개 검사, 문제 {len(errs)}건")
    for e in errs:
        print("  - " + e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
