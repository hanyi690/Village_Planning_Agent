"""Fetch full-text standards from the SAMR national-standards platform.

The public system (国家标准全文公开系统, openstd.samr.gov.cn) exposes the
full text of GB / GB/T / GB/Z standards. The PDF is not linked directly;
it is served only after a session flow:

  GET  /bzgk/gb/index                  -> establish JSESSIONID
  GET  /bzgk/gb/std_list?p.p2=<kw>      -> search results (hcno ids)
  GET  /bzgk/gb/newGbInfo?hcno=<hcno>   -> detail page
  GET  /bzgk/std/showGb?type=download   -> marks the standard downloadable
       &hcno=<hcno>
  GET  /bzgk/std/viewGb?hcno=<hcno>     -> the actual PDF

Standards that are 采标 (adopted from ISO/IEC with copyright) or outside the
system scope (food / environment / construction) return no PDF.

The script is reusable for any keyword / standard number on the platform.

Usage:
    python scripts/fetch_openstd_standards.py search "土地利用现状分类"
    python scripts/fetch_openstd_standards.py fetch --stdno "GB/T 21010-2017"
    python scripts/fetch_openstd_standards.py fetch --hcno 224BF9DA69F053DA22AC758AAAADEEAA
    python scripts/fetch_openstd_standards.py fetchall "城市用地分类" --out C:/out
"""

import argparse
import http.cookiejar
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://openstd.samr.gov.cn"
INDEX_URL = BASE + "/bzgk/gb/index"
LIST_URL = BASE + "/bzgk/std/std_list"
DETAIL_URL = BASE + "/bzgk/gb/newGbInfo"
SHOW_URL = BASE + "/bzgk/std/showGb"
VIEW_URL = BASE + "/bzgk/std/viewGb"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "downloads" / "openstd"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OpenStdClient:
    def __init__(self, timeout=60, retries=3):
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.timeout = timeout
        self.retries = retries

    def _request(self, path, referer=None, headers=None):
        h = {"User-Agent": UA, "Accept": "*/*"}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(path, headers=h)
                return self.opener.open(req, timeout=self.timeout).read()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                last = exc
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"failed after {self.retries} attempts: {last}")

    def _html(self, path, referer=None):
        raw = self._request(path, referer=referer)
        return raw.decode("utf-8", "ignore") if raw else ""

    def bootstrap(self):
        self._request(INDEX_URL)

    def search(self, keyword, page=1, page_size=10):
        query = urllib.parse.urlencode({
            "page": page, "pageSize": page_size, "p.p1": 0,
            "p.p2": keyword, "p.p90": "circulation_date", "p.p91": "desc",
        })
        html = self._html(LIST_URL + "?" + query)
        results = []
        for block in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            hcno = re.findall(r"showInfo\('([0-9A-F]+)'\)", block)
            if not hcno:
                continue
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
            stdno = next((c for c in cells if re.match(r"^[A-Z]+/T?\s?[A-Z0-9 .-]+$", c)), "")
            title = next((c for c in cells if re.search(r"[\u4e00-\u9fff]", c) and c != stdno), "")
            results.append({"hcno": hcno[0], "stdno": stdno, "title": title})
        return results

    def download(self, hcno, stdno="", title=""):
        detail = self._html(DETAIL_URL + f"?hcno={hcno}")
        if not detail:
            return None, "detail page not found (probably not a national standard)"
        self._request(SHOW_URL + f"?type=download&hcno={hcno}&request_locale=zh",
                      referer=DETAIL_URL + f"?hcno={hcno}")
        data = self._request(VIEW_URL + f"?hcno={hcno}",
                             referer=SHOW_URL + f"?type=download&hcno={hcno}&request_locale=zh")
        if not data:
            return None, "no full text available on this platform"
        if not data.startswith(b"%PDF"):
            return None, "response was not a PDF (standard likely 采标 / out of scope)"
        return data, ""


def _sanitize(name):
    name = _ILLEGAL.sub("-", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name or "unnamed"


def _save(data, stdno, title, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _sanitize(f"{stdno} {title}") if stdno else "unnamed"
    path = out_dir / f"{name}.pdf"
    path.write_bytes(data)
    return path


def cmd_search(client, args):
    results = client.search(args.query)
    print(f"{len(results)} result(s) for {args.query!r}:")
    for r in results:
        print(f"  {r['hcno']}  {r['stdno']:<22} {r['title']}")


def cmd_fetch(client, args):
    if args.hcno:
        hcno = args.hcno
    elif args.stdno:
        found = None
        for page in range(1, 11):
            results = client.search(args.stdno, page=page)
            found = next((r for r in results if r["stdno"].replace(" ", "").upper()
                          == args.stdno.replace(" ", "").upper()), None)
            if found:
                break
            if not results:
                break
        if not found:
            raise SystemExit(f"no standard matched {args.stdno!r}")
        hcno = found["hcno"]
        args.title = args.title or found["title"]
    else:
        raise SystemExit("need --hcno or --stdno")
    print(f"downloading hcno={hcno} ...")
    data, err = client.download(hcno, args.stdno or "", args.title or "")
    if data is None:
        raise SystemExit(f"failed: {err}")
    path = _save(data, args.stdno or "", args.title or "", args.out)
    print(f"saved: {path} ({len(data)} bytes)")
    return path


def cmd_fetchall(client, args):
    page = 1
    saved = 0
    seen = 0
    while page <= 100:
        results = client.search(args.query, page=page)
        if not results:
            break
        seen += len(results)
        for r in results:
            print(f"  [{r['hcno']}] {r['stdno']} {r['title']}")
            data, err = client.download(r["hcno"], r["stdno"], r["title"])
            if data is None:
                print(f"    skipped: {err}")
                continue
            path = _save(data, r["stdno"], r["title"], args.out)
            print(f"    saved: {path} ({len(data)} bytes)")
            saved += 1
        if len(results) < 10:
            break
        page += 1
    print(f"\n{saved} of {seen} standards saved to {args.out}")
    return saved


def build_parser():
    parser = argparse.ArgumentParser(prog="fetch_openstd_standards")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="search the national standards directory")
    p_search.add_argument("query")
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch", help="download one standard")
    p_fetch.add_argument("--hcno", help="hex detail id, e.g. 224BF9DA...")
    p_fetch.add_argument("--stdno", help="standard number, e.g. GB/T 21010-2017")
    p_fetch.add_argument("--title", default="")
    p_fetch.add_argument("--out", default=str(DEFAULT_OUT))
    p_fetch.set_defaults(func=cmd_fetch)

    p_all = sub.add_parser("fetchall", help="search then download every result")
    p_all.add_argument("query")
    p_all.add_argument("--out", default=str(DEFAULT_OUT))
    p_all.set_defaults(func=cmd_fetchall)

    return parser


def main():
    args = build_parser().parse_args()
    client = OpenStdClient()
    client.bootstrap()
    sys.exit(args.func(client, args))


if __name__ == "__main__":
    main()
