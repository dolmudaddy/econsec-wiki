# -*- coding: utf-8 -*-
"""위키 공용 유틸: frontmatter 파싱, 위키링크 추출."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
LINK_RE = re.compile(r"\[\[([^\]\|#\\]+)\\?(?:#[^\]\|]*)?(?:\\?\|[^\]]*)?\]\]")  # 표 안의 \| 이스케이프 허용


def _val(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [x.strip().strip('"\'') for x in inner.split(",") if x.strip()] if inner else []
    return v.strip('"\'')


def parse(path):
    """(frontmatter dict | None, body str)"""
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    fm = {}
    for line in text[3:end].strip("\n").split("\n"):
        m = re.match(r"^([A-Za-z_][\w\-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = _val(m.group(2))
    return fm, text[end + 4:]


def pages():
    return [p for p in WIKI.rglob("*.md") if "_templates" not in p.parts]


def links(text):
    # 코드블록 안 링크는 제외
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return [m.group(1).strip() for m in LINK_RE.finditer(text)]
