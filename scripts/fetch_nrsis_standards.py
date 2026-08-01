"""Fetch full-text standards from the nrsis.org.cn standards platform.

The platform serves standards page-by-page (base64-encoded single-page PDFs)
rather than as a single downloadable file. This script:

  - searches the public standard directory (标准公开),
  - reads a standard detail page for its number of pages and PDF file code,
  - downloads every page via the readPage endpoint,
  - merges the pages into one PDF with pypdf,
  - saves it into an output directory (default: <repo>/downloads/nrsis).

The script is reusable: any standard number / keyword / detail id supported by
the platform can be fetched, so it can also be used later for other PDFs.

Usage:
    python scripts/fetch_nrsis_standards.py search "TD/T 1027"
    python scripts/fetch_nrsis_standards.py fetch 211171
    python scripts/fetch_nrsis_standards.py fetchall --query "TD/T 1027"
    python scripts/fetch_nrsis_standards.py fetch --id 211171 --out C:/out
    python scripts/fetch_nrsis_standards.py fetch --code a678b... --pages 40
"""

import argparse
import base64
import io
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://www.nrsis.org.cn"
LIST_URL = BASE + "/portal/xxcx/std"
DETAIL_URL = BASE + "/portal/stdDetail/{id}"
READ_URL = BASE + "/mnr_kfs/file/read/{code}"
READ_PAGE_URL = BASE + "/mnr_kfs/file/readPage"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE,
}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "downloads" / "nrsis"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _fetch(url, data=None, referer=None, timeout=60, retries=3):
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as exc:  # noqa: BLE001 - keep CLI resilient
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} attempts: {last}")


def _html(url, **kwargs):
    raw = _fetch(url, **kwargs)
    return raw.decode("utf-8", "ignore")


def _text(node_html):
    return re.sub(r"<[^>]+>", "", node_html).strip()


def _sanitize(name):
    name = _ILLEGAL.sub("-", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name or "unnamed"


def search(keyword, page=1, page_size=50):
    query = urllib.parse.urlencode(
        {"pageNo": page, "pageSize": page_size, "key": keyword}
    )
    html = _html(LIST_URL + "?" + query)
    results = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        ids = re.findall(r"/portal/stdDetail/(\d+)", block)
        if not ids:
            continue
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        cells = [c for c in cells if c]
        stdno = next((c for c in cells if re.match(r"^[A-Z]{1,3}/T?\s?[A-Z0-9. -]+$", c)), "")
        title = next((c for c in cells if re.search(r"[\u4e00-\u9fff]", c) and c != stdno), "")
        results.append({"id": ids[0], "stdno": stdno, "title": title})
    return results


def detail(detail_id):
    html = _html(DETAIL_URL.format(id=detail_id))
    h4 = re.findall(r"<h4.*?</h4>", html, re.S)
    title = _text(h4[0]).split("实施反馈")[0].strip() if h4 else ""
    stdno = re.findall(r"<b>([A-Za-z0-9 /-]+)</b>", html)
    stdno = stdno[0].strip() if stdno else ""
    code = re.findall(r"/mnr_kfs/file/read/([0-9a-f]+)", html)
    pages = 0
    if code:
        viewer = _html(READ_URL.format(code=code[0]), referer=DETAIL_URL.format(id=detail_id))
        pages = re.findall(r"size\s*:\s*parseInt\('(\d+)'\)", viewer)
        pages = int(pages[0]) if pages else 0
    return {
        "id": detail_id,
        "stdno": stdno,
        "title": title,
        "pages": pages,
        "code": code[0] if code else "",
    }


def download(code, pages, out_path, referer=None, progress=None):
    pages_bytes = []
    for page in range(1, pages + 1):
        data = urllib.parse.urlencode({"code": code, "page": page}).encode()
        raw = _fetch(READ_PAGE_URL, data=data, referer=referer)
        page_pdf = base64.b64decode(raw)
        if not page_pdf.startswith(b"%PDF"):
            raise RuntimeError(f"page {page} did not return a PDF")
        pages_bytes.append(page_pdf)
        if progress:
            progress(page, pages)
    return _merge(pages_bytes, out_path)


def _merge(pages_bytes, out_path):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for chunk in pages_bytes:
        reader = PdfReader(io.BytesIO(chunk))
        for page in reader.pages:
            writer.add_page(page)
    with open(out_path, "wb") as fh:
        writer.write(fh)
    return out_path


def _save(d, out_dir, progress=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _sanitize(f"{d['stdno']} {d['title']}") if d["stdno"] else d["id"]
    out_path = out_dir / f"{name}.pdf"
    referer = READ_URL.format(code=d["code"])
    download(d["code"], d["pages"], out_path, referer=referer, progress=progress)
    return out_path


def _confirm_pdf(path, expected):
    try:
        from pypdf import PdfReader

        actual = len(PdfReader(str(path)).pages)
        ok = actual == expected
        print(f"  verified: {actual} pages (expected {expected}) -> {'OK' if ok else 'MISMATCH'}")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"  verify failed: {exc}")
        return False


def cmd_search(args):
    rows = search(args.query)
    print(f"{len(rows)} result(s) for {args.query!r}:")
    for r in rows:
        flag = "pdf?" if True else ""
        print(f"  {r['id']:<8} {r['stdno']:<20} {r['title']} {flag}")


def cmd_fetch(args):
    if args.id:
        d = detail(args.id)
    elif args.code:
        d = {"id": "", "stdno": args.stdno or "", "title": args.title or "",
             "pages": args.pages or 0, "code": args.code}
    else:
        raise SystemExit("need --id or --code")
    if not d["code"]:
        raise SystemExit(f"detail {d['id']} has no downloadable full text on nrsis")
    if not d["pages"] and not args.pages:
        raise SystemExit("cannot determine page count (use --pages)")
    if not d["pages"]:
        d["pages"] = args.pages

    def progress(page, total):
        print(f"  page {page}/{total}")

    path = _save(d, args.out, progress=progress)
    print(f"saved: {path}")
    _confirm_pdf(path, d["pages"])
    return path


def cmd_fetchall(args):
    rows = search(args.query)
    print(f"{len(rows)} result(s) for {args.query!r}")
    paths = []
    for r in rows:
        print(f"  [{r['id']}] {r['stdno']} {r['title']}")
        try:
            d = detail(r["id"])
        except RuntimeError as exc:
            print(f"    detail failed: {exc}")
            continue
        if not d["code"]:
            print("    no full text available on nrsis")
            continue

        def progress(page, total, d=d):
            print(f"    page {page}/{total}")

        try:
            path = _save(d, args.out, progress=progress)
            _confirm_pdf(path, d["pages"])
            paths.append(str(path))
        except RuntimeError as exc:
            print(f"    download failed: {exc}")
    print(f"\n{len(paths)} file(s) saved to {args.out}")
    return paths


def build_parser():
    parser = argparse.ArgumentParser(prog="fetch_nrsis_standards")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="search the public standard directory")
    p_search.add_argument("query")
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch", help="download one standard by detail id or file code")
    p_fetch.add_argument("--id", help="detail page id, e.g. 211171")
    p_fetch.add_argument("--code", help="file code (uuid), e.g. a678b043...")
    p_fetch.add_argument("--pages", type=int, default=0)
    p_fetch.add_argument("--stdno", default="")
    p_fetch.add_argument("--title", default="")
    p_fetch.add_argument("--out", default=str(DEFAULT_OUT))
    p_fetch.set_defaults(func=cmd_fetch)

    p_all = sub.add_parser("fetchall", help="search then download every result with full text")
    p_all.add_argument("query")
    p_all.add_argument("--out", default=str(DEFAULT_OUT))
    p_all.set_defaults(func=cmd_fetchall)

    return parser


def main():
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
