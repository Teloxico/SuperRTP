#!/usr/bin/env python3
"""
Minimal PixelLab API client (https://api.pixellab.ai/v2), standard library only.

Every generation made through `generate()` is archived for provenance under
.cache/pixellab/<name>/ (git-ignored):

    input-<n>.png    every image sent, decoded from the request
    request.json     endpoint and parameters, with each embedded image replaced by
                     {"file", "sha256"} pointing at its input-<n>.png
    output-<n>.png   every image returned, decoded from base64 (or downloaded from the
                     result's file links)
    result.json      the response, images replaced the same way, plus the generations
                     charged and the terms version; written last, so its presence marks
                     the job done and a rerun never pays for it twice

The token comes from PIXELLAB_API_KEY in the environment or in the repository's
git-ignored .env. Terms (https://www.pixellab.ai/termsofservice, last updated
2025-11-23): the user owns the copyright of the outputs (1.3) and may distribute them
for any purpose except training other models (3.3); programmatic use must go through
this official API (2.2).

    python3 tools/asset_generation/pixellab_client.py --balance
"""

import argparse
import base64
import copy
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)

from repo import REPO_ROOT, resolve_within, write_json  # noqa: E402

API_BASE = "https://api.pixellab.ai/v2"
TERMS_URL = "https://www.pixellab.ai/termsofservice"
TERMS_VERSION = "2025-11-23"
ARCHIVE_DIR = os.path.join(REPO_ROOT, ".cache", "pixellab")
POLL_INTERVAL_S = 5
JOB_TIMEOUT_S = 900


def api_key() -> str:
    key = os.environ.get("PIXELLAB_API_KEY")
    env_path = os.path.join(REPO_ROOT, ".env")
    if not key and os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                name, sep, value = line.strip().partition("=")
                if sep and name.strip() == "PIXELLAB_API_KEY":
                    key = value.strip().strip("\"'")
    if not key:
        raise RuntimeError("PIXELLAB_API_KEY is not set (environment or .env)")
    return key


def call(method: str, path: str, payload=None, timeout: float = 120.0):
    """One API request; returns the decoded JSON body and raises with the server's message on HTTP errors."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + api_key(),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {body}") from None


def wait_for_job(job_id: str, timeout_s: float = JOB_TIMEOUT_S) -> dict:
    """Polls a background job until it completes; raises if it fails or times out."""
    deadline = time.monotonic() + timeout_s
    while True:
        job = call("GET", f"/background-jobs/{job_id}")
        if job.get("status") == "completed":
            return job
        if job.get("status") == "failed":
            raise RuntimeError(f"PixelLab job {job_id} failed: {json.dumps(job.get('last_response'))[:1000]}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"PixelLab job {job_id} still '{job.get('status')}' after {timeout_s:.0f} s")
        time.sleep(POLL_INTERVAL_S)


def png_image(png_bytes: bytes) -> dict:
    """The API's Base64Image object for a PNG."""
    return {"type": "base64", "base64": base64.b64encode(png_bytes).decode("ascii"), "format": "png"}


def _externalize(node, job_dir: str, prefix: str, counter: list):
    """Replaces every embedded base64 image in `node` with a file reference, writing the file."""
    if isinstance(node, dict):
        if node.get("type") == "base64" and isinstance(node.get("base64"), str):
            raw = base64.b64decode(node["base64"])
            name = f"{prefix}-{counter[0]}.{node.get('format') or 'png'}"
            counter[0] += 1
            with open(os.path.join(job_dir, name), "wb") as f:
                f.write(raw)
            return {"file": name, "sha256": hashlib.sha256(raw).hexdigest()}
        return {k: _externalize(v, job_dir, prefix, counter) for k, v in node.items()}
    if isinstance(node, list):
        return [_externalize(v, job_dir, prefix, counter) for v in node]
    return node


def _download_files(files: dict, job_dir: str) -> dict:
    """Downloads a result's unauthenticated file links (VFX) next to the other outputs."""
    saved = {}
    for label, url in files.items():
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        name = "file-" + os.path.basename(url.split("?", 1)[0])
        with urllib.request.urlopen(url, timeout=120) as resp:
            raw = resp.read()
        with open(resolve_within(job_dir, name), "wb") as f:
            f.write(raw)
        saved[label] = {"file": name, "url": url, "sha256": hashlib.sha256(raw).hexdigest()}
    return saved


def generate(name: str, endpoint: str, payload: dict, result_path: str = None) -> dict:
    """
    Runs one generation and archives it under .cache/pixellab/<name>/.

    `result_path` is a follow-up GET whose answer holds the final result (e.g.
    "/tilesets/{tileset_id}"), formatted with the submit response's fields. A job whose
    result.json exists is returned from the archive without calling the API.
    """
    job_dir = resolve_within(ARCHIVE_DIR, name)
    result_file = os.path.join(job_dir, "result.json")
    if os.path.exists(result_file):
        with open(result_file, encoding="utf-8") as f:
            return json.load(f)
    os.makedirs(job_dir, exist_ok=True)
    write_json(os.path.join(job_dir, "request.json"),
               {"endpoint": endpoint, "payload": _externalize(copy.deepcopy(payload), job_dir, "input", [0])})

    submitted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    response = call("POST", endpoint, payload)
    usage = [response.get("usage")]
    if response.get("background_job_id"):
        job = wait_for_job(response["background_job_id"])
        usage.append(job.get("usage"))
        final = job.get("last_response") or {}
        if result_path:
            final = call("GET", result_path.format(**response))
            usage.append(final.get("usage"))
    else:
        final = response

    files = _download_files(final.get("files") or {}, job_dir) if isinstance(final, dict) else {}
    record = {
        "endpoint": endpoint,
        "submitted_at": submitted_at,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "submit_response": _externalize(response, job_dir, "submit", [0]),
        "result": _externalize(final, job_dir, "output", [0]),
        "downloaded_files": files,
        "usage": [u for u in usage if u],
        "terms": {"url": TERMS_URL, "version": TERMS_VERSION},
    }
    write_json(result_file, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--balance", action="store_true", help="print the account's remaining generations and credit")
    args = parser.parse_args()
    if args.balance:
        print(json.dumps(call("GET", "/balance"), indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
