"""Parse PDFs using the MinerU standard-precision API (v4).

The standard API needs a token (env MINERU_TOKEN). Pipeline:

  POST /api/v4/file-urls/batch     -> get signed upload URLs (per file)
  PUT  <signed-url> <file bytes>   -> upload each file
  GET  /api/v4/extract-results/batch/<batch_id>   -> poll until state=done
  GET  <full_zip_url>              -> download the result zip
  unzip                            -> extract full.md (and *.json backups)

Output for each PDF: <out>/<pdf-stem>/full.md (plus layout/content_list json).

CLI:
    python scripts/parse_mineru.py <pdf>... [--out DIR] [--model vlm|pipeline] [--ocr] [--poll SECS]
"""

import argparse
import http.client
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://mineru.net"
BATCH_URL = BASE + "/api/v4/file-urls/batch"
BATCH_STATUS = BASE + "/api/v4/extract-results/batch/{batch_id}"
DEFAULT_POLL = 5
DEFAULT_TIMEOUT = 60 * 30


def _token():
    tok = os.environ.get("MINERU_TOKEN")
    if not tok:
        raise SystemExit("MINERU_TOKEN not set in environment (check .env)")
    return tok.strip().strip('"').strip("'")


def _post_json(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _get_json(url, headers=None):
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _put_bytes(url, data):
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=300)
    conn.request("PUT", parsed.path + "?" + parsed.query, body=data,
                 headers={"Content-Length": str(len(data))})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body


def _download(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def submit_paths(paths, model="vlm", is_ocr=False):
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    files = [{"name": Path(p).name, "data_id": Path(p).stem, "is_ocr": is_ocr} for p in paths]
    payload = {"files": files, "model_version": model, "enable_table": True, "enable_formula": True}
    res = _post_json(BATCH_URL, payload, headers=headers)
    if res.get("code") != 0:
        raise SystemExit(f"submit failed: {res}")
    batch_id = res["data"]["batch_id"]
    urls = res["data"]["file_urls"]
    for path, url in zip(paths, urls):
        with open(path, "rb") as f:
            data = f.read()
        status, _ = _put_bytes(url, data)
        if status not in (200, 201):
            raise SystemExit(f"upload failed for {path}: HTTP {status}")
        print(f"uploaded {Path(path).name} ({len(data)} bytes)")
    return batch_id


def poll_batch(batch_id, poll=DEFAULT_POLL, timeout=DEFAULT_TIMEOUT):
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    url = BATCH_STATUS.format(batch_id=batch_id)
    start = time.time()
    while time.time() - start < timeout:
        res = _get_json(url, headers=headers)
        if res.get("code") != 0:
            raise SystemExit(f"status error: {res}")
        items = res["data"]["extract_result"]
        states = [it["state"] for it in items]
        done = all(s == "done" for s in states)
        failed = [it for it in items if it["state"] == "failed"]
        if failed:
            for it in failed:
                print(f"FAILED: {it['file_name']} -> {it.get('err_msg')}")
        if done:
            return res["data"]
        progressed = [it for it in items if "extract_progress" in it]
        if progressed:
            p = progressed[0]["extract_progress"]
            print(f"[{int(time.time()-start)}s] state={states} progress {p.get('extracted_pages','?')}/{p.get('total_pages','?')}")
        else:
            print(f"[{int(time.time()-start)}s] state={states}")
        time.sleep(poll)
    raise SystemExit(f"timeout after {timeout}s; batch_id={batch_id}")


def download_results(data, paths, out_dir):
    by_name = {Path(p).name: it for it in data["extract_result"] for p in paths if Path(p).name == it["file_name"]}
    for path in paths:
        item = by_name.get(Path(path).name)
        if not item or not item.get("full_zip_url"):
            print(f"  no result zip for {Path(path).name}")
            continue
        zip_bytes = _download(item["full_zip_url"])
        stem = Path(path).stem
        target = Path(out_dir) / stem
        target.mkdir(parents=True, exist_ok=True)
        try:
            (target / "_source_filename.txt").write_text(Path(path).name, encoding="utf-8")
        except OSError as exc:
            print(f"  warn: could not write _source_filename.txt for {stem}: {exc}")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(target)
        md = target / "full.md"
        print(f"  {stem}: {'md OK ' + str(md.stat().st_size) + 'B' if md.exists() else 'NO full.md'}; zip files: {[n for n in zf.namelist()][:8]}")
    return data


def main():
    p = argparse.ArgumentParser(prog="parse_mineru")
    p.add_argument("pdfs", nargs="+", help="local PDF file paths")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--model", default="vlm", choices=["vlm", "pipeline"])
    p.add_argument("--ocr", action="store_true", help="enable OCR (required for scanned PDFs)")
    p.add_argument("--poll", type=int, default=DEFAULT_POLL)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = p.parse_args()

    for path in args.pdfs:
        if not Path(path).exists():
            raise SystemExit(f"missing: {path}")
    Path(args.out).mkdir(parents=True, exist_ok=True)

    print(f"submitting {len(args.pdfs)} file(s) model={args.model} ocr={args.ocr}")
    batch_id = submit_paths(args.pdfs, model=args.model, is_ocr=args.ocr)
    print(f"batch_id={batch_id}")
    data = poll_batch(batch_id, poll=args.poll, timeout=args.timeout)
    download_results(data, args.pdfs, args.out)


if __name__ == "__main__":
    main()