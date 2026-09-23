# -*- coding: utf-8 -*-
"""
외교부 경제안보 Review PDF 일괄 다운로드
사용법:  python download_econsec.py
  - 같은 폴더의 manifest.json 을 읽어 pdf/ 폴더에 97개 PDF를 내려받습니다.
  - 이미 받은 파일은 건너뜁니다(재실행 안전).
  - 결과 목록은 manifest.csv 로 저장됩니다.
"""
import json, re, csv, time, sys, os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE = "https://www.mofa.go.kr/www/brd/m_26799/down.do?brd_id=100863&seq={seq}&data_tp=A&file_seq={fs}"
HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdf"
PDF_DIR.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.mofa.go.kr/www/brd/m_26799/list.do"}


def issue_id(no, title, date):
    """게시글 제목 → 호수 식별자 (예: 26-18, 26-E2, 2025-합본, 22-3)"""
    t = title.replace(" ", "")
    if "통합본" in t:
        m = re.search(r"(20\d{2})년", t) or re.search(r"(\d{2})-1호", t)
        y = m.group(1) if m else date[:4]
        y = y if len(y) == 4 else "20" + y
        tag = "합본E" if ("영문" in t or "Economic" in title) else "합본"
        return f"{y}-{tag}"
    m = re.search(r"영문(\d{2})-(\d{1,2})호", t)
    if m:
        return f"{m.group(1)}-E{int(m.group(2)):02d}"
    m = re.search(r"(\d{2})-(\d{1,2})호", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"리뷰(\d{1,2})호", t)
    if m:
        return f"{date[2:4]}-{int(m.group(1)):02d}"
    return f"no{no:03d}"


def fetch(url, retries=3):
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=120) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
                if data[:4] != b"%PDF":
                    raise ValueError(f"PDF 아님 (Content-Type={ctype}, {len(data)} bytes)")
                return data
        except (URLError, HTTPError, ValueError) as e:
            print(f"    재시도 {i+1}/{retries}: {e}")
            time.sleep(2 * (i + 1))
    return None


def main():
    rows = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    out, fail = [], []
    for no, seq, date, title, fs in rows:
        iid = issue_id(no, title, date)
        fname = f"{iid}_{seq}.pdf"
        path = PDF_DIR / fname
        status = "skip"
        if not path.exists() or path.stat().st_size < 1000:
            print(f"[{no:2d}/97] {iid}  {title[:50]}")
            data = fetch(BASE.format(seq=seq, fs=fs))
            if data:
                path.write_bytes(data)
                status = f"ok {len(data)//1024}KB"
            else:
                status = "FAIL"
                fail.append((no, seq, title))
            time.sleep(0.7)  # 서버 부담 완화
        out.append({"no": no, "issue": iid, "seq": seq, "date": date, "title": title,
                    "file": fname, "url": BASE.format(seq=seq, fs=fs), "status": status})
    with open(HERE / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    n_ok = sum(1 for p in PDF_DIR.glob("*.pdf") if p.stat().st_size > 1000)
    print(f"\n완료: pdf/ 에 {n_ok}개 PDF, 실패 {len(fail)}건")
    for f_ in fail:
        print("  실패:", f_)


if __name__ == "__main__":
    main()
