# -*- coding: utf-8 -*-
"""
외교부 경제안보 Review 동기화 스크립트 (초기 전체 수집 + 이후 신규 호 증분 업데이트)

사용법:
  python sync_econsec.py            # 게시판을 확인해 새 글을 manifest.json에 추가하고, 없는 PDF를 내려받음
  python sync_econsec.py --all      # 게시판 전체(10페이지)를 다시 훑어 누락분까지 보정
  python sync_econsec.py --offline  # 게시판 접속 없이 manifest.json 기준으로 없는 PDF만 다운로드

출력:
  manifest.json  : [no, seq, date, title, file_seq] 목록 (최신 → 과거 순)
  manifest.csv   : issue id, 파일명, 상태 포함 표
  pdf/{issue}_{seq}.pdf
  new_issues.json: 이번 실행에서 새로 받은 호 목록 (Claude Code가 읽어 위키를 갱신)
"""
import json, re, csv, time, sys, ssl, html as htmllib
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler
from urllib.error import URLError, HTTPError

# 외교부 서버는 첫 접속에 쿠키(TMOSHCooKie 등)를 심고 같은 주소로 307 리다이렉트하므로 쿠키 저장소가 필수
_JAR = CookieJar()


def urlopen(req, timeout=120, context=None):
    opener = build_opener(HTTPCookieProcessor(_JAR), HTTPSHandler(context=context))
    return opener.open(req, timeout=timeout)


# ---------- SSL 컨텍스트 (외교부 서버는 중간 인증서를 주지 않아 Windows Python에서 검증이 실패하는 경우가 있음) ----------
def _ssl_candidates():
    cands = [("기본", ssl.create_default_context())]
    try:
        import certifi
        cands.append(("certifi", ssl.create_default_context(cafile=certifi.where())))
    except ImportError:
        pass
    try:
        import truststore                       # pip install truststore → Windows 인증서 저장소 사용
        cands.append(("truststore", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
    except ImportError:
        pass
    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    cands.append(("검증 생략(mofa.go.kr 한정)", insecure))
    return cands


_SSL = {"ctx": None, "name": None}


def _pick_ssl_context():
    """게시판 첫 페이지로 후보 컨텍스트를 순서대로 시도해 되는 것을 고정."""
    if _SSL["ctx"] is not None:
        return _SSL["ctx"]
    for name, ctx in _ssl_candidates():
        try:
            with urlopen(Request(LIST.format(page=1), headers=HEADERS), timeout=30, context=ctx) as r:
                r.read(200)
            _SSL.update(ctx=ctx, name=name)
            if name != "기본":
                print(f"  [SSL] '{name}' 컨텍스트로 접속합니다.")
            return ctx
        except ssl.SSLError:
            continue
        except (URLError, HTTPError) as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError):
                continue
            _SSL.update(ctx=ctx, name=name)      # SSL 외 오류면 컨텍스트는 문제 없음
            return ctx
    _SSL.update(ctx=_ssl_candidates()[-1][1], name="검증 생략")
    return _SSL["ctx"]

SITE = "https://www.mofa.go.kr"
LIST = SITE + "/www/brd/m_26799/list.do?page={page}"
VIEW = SITE + "/www/brd/m_26799/view.do?seq={seq}"
DOWN = SITE + "/www/brd/m_26799/down.do?brd_id=100863&seq={seq}&data_tp=A&file_seq={fs}"
HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdf"; PDF_DIR.mkdir(exist_ok=True)
MANIFEST = HERE / "manifest.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": SITE + "/www/brd/m_26799/list.do"}


# ---------- 공통 ----------
def get(url, binary=False, retries=3):
    ctx = _pick_ssl_context()
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=120, context=ctx) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "replace")
        except (URLError, HTTPError) as e:
            print(f"    재시도 {i+1}/{retries}: {e}")
            time.sleep(2 * (i + 1))
    return None


def issue_id(no, title, date):
    """게시글 제목 → 호수 식별자 (26-18, 26-E02, 2025-합본, 22-03)"""
    t = title.replace(" ", "")
    if "통합본" in t:
        m = re.search(r"(20\d{2})년", t) or re.search(r"(\d{2})-1호", t)
        y = m.group(1) if m else date[:4]
        y = y if len(y) == 4 else "20" + y
        return f"{y}-합본E" if ("영문" in t or "Economic" in title) else f"{y}-합본"
    m = re.search(r"영문(\d{2})-(\d{1,2})호", t)
    if m:
        return f"{m.group(1)}-E{int(m.group(2)):02d}"
    m = re.search(r"(\d{2})-(\d{1,2})호", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"리뷰(\d{1,2})호", t)
    if m:
        return f"{date[2:4]}-{int(m.group(1)):02d}"
    return f"no{int(no):03d}"


# ---------- 게시판 파싱 ----------
ROW_RE = re.compile(
    r"<tr>.*?<div>\s*(\d+)\s*</div>.*?<a href=\"\./view\.do\?seq=(\d+)[^\"]*\"[^>]*>(.*?)</a>.*?(\d{4}-\d{2}-\d{2})",
    re.S)
FILE_RE = re.compile(r"down\.do\?brd_id=100863&(?:amp;)?seq=(\d+)&(?:amp;)?data_tp=A&(?:amp;)?file_seq=(\d+)\"[^>]*>.*?<span>(.*?)</span>", re.S)


def parse_list(page):
    h = get(LIST.format(page=page))
    if h is None:
        return None
    rows = []
    for no, seq, title, date in ROW_RE.findall(h):
        title = htmllib.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", title))).strip()
        rows.append([int(no), int(seq), date, title])
    return rows


def pick_file_seq(seq):
    """상세 페이지의 첨부 중 PDF(이름 있는 것)의 file_seq 선택. 없으면 1"""
    h = get(VIEW.format(seq=seq))
    if not h:
        return 1
    cands = [(int(fs), htmllib.unescape(name).strip()) for s, fs, name in FILE_RE.findall(h) if int(s) == seq]
    pdfs = [fs for fs, n in cands if n.lower().endswith(".pdf")]
    return pdfs[0] if pdfs else (cands[0][0] if cands else 1)


def sync_manifest(full=False):
    rows = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    known = {r[1] for r in rows}
    new = []
    page = 1
    while True:
        lst = parse_list(page)
        if lst is None:
            print("게시판 접속 실패 — 오프라인 모드로 계속합니다."); break
        if not lst:
            break
        fresh = [r for r in lst if r[1] not in known]
        for r in fresh:
            r.append(pick_file_seq(r[1]))
            new.append(r); known.add(r[1])
            print(f"  신규: {r[0]} | {r[2]} | {r[3][:60]}")
            time.sleep(0.5)
        if not full and len(fresh) < len(lst):   # 이미 아는 글이 섞이면 이후 페이지는 과거분
            break
        page += 1
        if page > 30:
            break
    if new:
        rows = sorted(rows + new, key=lambda r: -r[0])
        MANIFEST.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    return rows, new


# ---------- 다운로드 ----------
def download_missing(rows):
    out, fail, got = [], [], []
    for no, seq, date, title, fs in rows:
        iid = issue_id(no, title, date)
        fname = f"{iid}_{seq}.pdf"; path = PDF_DIR / fname
        status = "skip"
        if not path.exists() or path.stat().st_size < 1000:
            print(f"[{no:3d}] {iid}  {title[:50]}")
            data = get(DOWN.format(seq=seq, fs=fs), binary=True)
            if data and data[:4] == b"%PDF":
                path.write_bytes(data); status = f"ok {len(data)//1024}KB"
                got.append({"no": no, "issue": iid, "seq": seq, "date": date, "title": title, "file": fname})
            else:
                status = "FAIL"; fail.append((no, seq, title))
                if len(fail) >= 3 and not got:
                    print("\n연속 3건 실패 — 서버 접속 문제로 판단해 중단합니다. 네트워크 확인 후 다시 실행하세요.")
                    break
            time.sleep(0.7)
        out.append({"no": no, "issue": iid, "seq": seq, "date": date, "title": title,
                    "file": fname, "url": DOWN.format(seq=seq, fs=fs), "status": status})
    with open(HERE / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    return got, fail


def main():
    full = "--all" in sys.argv
    offline = "--offline" in sys.argv
    if offline:
        rows = json.loads(MANIFEST.read_text(encoding="utf-8")); new = []
    else:
        print("게시판 확인 중..."); rows, new = sync_manifest(full)
        print(f"  manifest: {len(rows)}건 (신규 {len(new)}건)")
    got, fail = download_missing(rows)
    (HERE / "new_issues.json").write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for p in PDF_DIR.glob("*.pdf") if p.stat().st_size > 1000)
    print(f"\n완료: pdf/ {n_ok}개 | 이번에 새로 받음 {len(got)}건 | 실패 {len(fail)}건")
    for g in got:
        print("  NEW:", g["issue"], g["title"][:70])
    for f_ in fail:
        print("  실패:", f_)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨. 다시 실행하면 이미 받은 파일은 건너뜁니다.")
