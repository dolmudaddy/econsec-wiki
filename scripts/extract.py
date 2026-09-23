# -*- coding: utf-8 -*-
"""
PDF → raw/{issue}.md 추출 (헤더·푸터·페이지번호 제거 외 원문 무수정)

사용법:
  python scripts/extract.py 26-18        # 특정 호
  python scripts/extract.py --all        # 전체 (이미 있는 raw는 건너뜀, --force 로 재생성)

출력 형식:
  # 경제안보 Review {issue} ({date})
  ## [A1] Ⅰ. 경제안보 분석 | {기사 제목}
  <!-- p.1 -->   ← 인쇄 페이지 번호 (없으면 pdf 페이지 번호 'pdf5')
  본문...
기사 경계는 페이지 상단 섹션 라벨(경제안보 분석/현안/연구동향/EWS …)과 제목 변화로 판단한다.
pymupdf 우선, 실패 시 pdftotext -layout.
"""
import sys, re, json, subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응

HERE = Path(__file__).resolve().parent.parent
PDF, RAW = HERE / "pdf", HERE / "raw"

ROMAN = r"(?:Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|I{1,3}|IV|VI?)"
SECTION_RE = re.compile(
    rf"^(?:{ROMAN}\s*\.\s*)?("
    r"경제안보\s*(?:특별\s*)?(?:분석|현안|현황|연구\s*동향|이슈|동향|정책|기고|포커스|심층분석|기획)"
    r"|EWS\s*(?:공급망)?\s*/?\s*(?:에너지)?\s*동향|공급망\s*/?\s*에너지\s*동향|공급망\s*주간\s*동향"
    r"|특별\s*기고|특집|기획|해외\s*동향|정책\s*동향)\s*$"
)
BACK_RE = re.compile(r"발간\s*목록|외교부 경제안보외교센터\(CESFA|메일링 서비스 신청")
HEADER_JUNK = re.compile(
    r"^(ISSN.*|(?:\d{4}\s*)?Vol\.\s*\d+|\s*\d{2}-\d{1,2}호,.*|\d{1,3}|Economic Security Review|경제안보\s*Review|\d{2}-E?\d{1,2}호.*|\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*\(.\)\s*)$"
)


def load_manifest():
    m = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    rows = m if isinstance(m, list) else m.get("items", m)
    return rows


def issue_meta():
    """manifest.csv 기준 issue → (date, seq, title, file)"""
    import csv
    out = {}
    with open(HERE / "manifest.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["issue"]] = r
    return out


def table_md(tab):
    """병합셀 중복 제거 후 markdown 표. 레이아웃용 박스(실질 행<2 또는 행당 셀<2)는 None."""
    rows = tab.extract() or []
    clean = []
    for r in rows:
        cells, prev = [], object()
        for c in r:
            c = (c or "").replace("\n", " ").strip()
            if c and c == prev:
                continue
            cells.append(c)
            prev = c if c else prev
        if any(cells):
            clean.append(cells)
    real = [r for r in clean if sum(1 for c in r if c) >= 2]
    if len(real) < 2:
        return None
    w = max(len(r) for r in clean)
    clean = [r + [""] * (w - len(r)) for r in clean]
    md = ["| " + " | ".join(clean[0]) + " |", "|" + "---|" * w]
    md += ["| " + " | ".join(r) + " |" for r in clean[1:]]
    return "\n".join(md)


def page_lines_fitz(page):
    """표는 markdown 표로, 나머지는 블록 텍스트. y 순서대로 합친다."""
    items = []
    tboxes = []
    try:
        for t in page.find_tables().tables:
            if t.row_count >= 2 and t.col_count >= 2:
                md = table_md(t)
                if md:
                    tboxes.append(t.bbox)
                    items.append((t.bbox[1], "TABLE", md.strip()))
    except Exception:
        pass

    def inside(b):
        for tb in tboxes:
            if b[0] >= tb[0] - 2 and b[1] >= tb[1] - 2 and b[2] <= tb[2] + 2 and b[3] <= tb[3] + 2:
                return True
        return False

    for b in page.get_text("blocks", sort=True):
        if b[6] != 0 or inside(b[:4]):
            continue
        items.append((b[1], "TEXT", b[4]))
    items.sort(key=lambda x: x[0])
    lines = []
    for _, kind, txt in items:
        if kind == "TABLE":
            lines.append("")
            lines.extend(txt.split("\n"))
            lines.append("")
        else:
            lines.extend(l.rstrip() for l in txt.split("\n") if l.strip())
    return lines


def pages_pdftotext(path):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    return [[l.rstrip() for l in p.split("\n") if l.strip()] for p in out.split("\f")]


def get_pages(path):
    try:
        import fitz
        doc = fitz.open(path)
        return [page_lines_fitz(p) for p in doc], "pymupdf"
    except Exception as e:
        print(f"  [pymupdf 실패 → pdftotext] {e}")
        return pages_pdftotext(path), "pdftotext"


def analyse_head(lines, pdf_no):
    """페이지 상단에서 (섹션라벨, 제목후보, 인쇄페이지번호, 헤더 줄 수)."""
    label, title, pno, cut = None, None, None, 0
    for i, l in enumerate(lines[:7]):
        s = l.strip()
        if re.fullmatch(r"\d{1,3}", s) and pno is None:
            pno, cut = int(s), i + 1
            continue
        m = SECTION_RE.match(s)
        if m and label is None:
            label, cut = s, i + 1
            continue
        if HEADER_JUNK.match(s):
            cut = i + 1
            continue
        if label and title is None:
            title = s
        break
    return label, title, pno, cut


def norm_label(lbl):
    return re.sub(r"\s+", "", re.sub(rf"^{ROMAN}\s*\.\s*", "", lbl or ""))


def extract(issue, meta, force=False):
    rows = [r for r in meta.values() if r["issue"] == issue]
    if not rows:
        print(f"[{issue}] manifest에 없음"); return False
    r = rows[0]
    src = PDF / r["file"]
    dst = RAW / f"{issue}.md"
    if dst.exists() and not force:
        return True
    if not src.exists():
        print(f"[{issue}] PDF 없음: {src.name}"); return False
    pages, engine = get_pages(src)

    out = [f"# 경제안보 Review {issue} ({r['date']})", "",
           f"<!-- source: {r['file']} | seq={r['seq']} | engine={engine} -->",
           f"<!-- board_title: {r['title']} -->", ""]
    art_no, cur_key = 0, None
    front = True
    for idx, lines in enumerate(pages, 1):
        if not lines:
            continue
        joined = "\n".join(lines[:12])
        label, title, pno, cut = analyse_head(lines, idx)
        body = lines[cut:]
        ptag = f"p.{pno}" if pno else f"pdf{idx}"
        if (BACK_RE.search(joined) and idx > 3) or cur_key == "BACK":
            if cur_key != "BACK":
                out += ["", "## [BACK] 부록·발간목록", ""]
                cur_key = "BACK"
            out += [f"<!-- {ptag} -->"] + body + [""]
            continue
        is_toc = any(l.strip() in ("목차", "Table of Contents") for l in lines[:3])
        if front and (idx <= 3 and (is_toc or idx <= 2) and label is None or is_toc):
            if cur_key != "FRONT":
                out += ["", "## [FRONT] 표지·목차", ""]
                cur_key = "FRONT"
            out += [f"<!-- {ptag} -->"] + lines + [""]
            continue
        if label and idx <= 2 and len([l for l in lines if SECTION_RE.match(l.strip())]) >= 3:
            # 표지에 섹션라벨이 여러 개 → 표지
            if cur_key != "FRONT":
                out += ["", "## [FRONT] 표지·목차", ""]
                cur_key = "FRONT"
            out += [f"<!-- {ptag} -->"] + lines + [""]
            continue
        front = False
        key = None
        if label:
            nl = norm_label(label)
            key = (label.split(".")[0].strip() if re.match(ROMAN + r"\s*\.", label) else nl)
            # 로마숫자 없는 구형: 같은 라벨이라도 제목이 바뀌면 새 기사
            if not re.match(ROMAN + r"\s*\.", label):
                key = (nl, (title or "")[:15])
        if cur_key in (None, "FRONT", "BACK") and key is None:
            key = ("본문",)
        if key is not None and key != cur_key:
            art_no += 1
            head = label or "본문"
            t = (title or "").strip()
            # 제목이 두 줄로 나뉜 경우 다음 줄까지
            if t and len(body) > 1 and len(t) < 40 and not re.match(r"^\d\.|^요약|전문관|연구원", body[1] if body[0] == t else ""):
                nxt = body[1] if body and body[0].strip() == t else ""
                if nxt and len(nxt) < 30 and not re.search(r"전문관|연구원|요약|^\d\.", nxt):
                    t = f"{t} {nxt.strip()}"
            out += ["", f"## [A{art_no}] {head} | {t}", ""]
            cur_key = key
        out += [f"<!-- {ptag} -->"] + body + [""]
    RAW.mkdir(exist_ok=True)
    dst.write_text("\n".join(out), encoding="utf-8", errors="replace")
    print(f"[{issue}] {len(pages)}p → raw/{issue}.md  기사 {art_no}개 ({engine})")
    return True


def main():
    meta = issue_meta()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    targets = sorted(meta) if "--all" in sys.argv else args
    if not targets:
        print(__doc__); return
    for iss in targets:
        try:
            extract(iss, meta, force)
        except Exception as e:
            print(f"[{iss}] 실패: {e}")


if __name__ == "__main__":
    main()
