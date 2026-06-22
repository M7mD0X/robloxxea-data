#!/usr/bin/env python3
"""Re-verify every loadstring in the RobloxXea data feeds.

For each tool in mainTools.json and communityTools.json:
  1. Extract the URL from the loadstring (handles HttpGet, HttpGetAsync).
  2. HTTP-GET it with a short timeout and a Roblox-executor-style User-Agent.
  3. Mark the tool `verified: true` iff response is 200 AND body is >1KB AND
     body looks like Lua (contains at least one of: `function`, `local`,
     `--`, `loadstring`, `return`, `end`).
  4. Update `lastVerified` to today's date in ISO format.
  5. Update `verifiedSizeBytes` to the actual response body size.

If any tool is broken, the script exits with code 1 so the GitHub Action can
open an issue. The script writes the updated JSON files in place (pretty-
printed with 2-space indent), then prints a summary report to stdout.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

USER_AGENT = "RobloxXeaVerifier/1.0 (+https://github.com/M7mD0X/robloxxea-data)"
TIMEOUT_SECONDS = 12
MIN_BODY_BYTES = 1024

URL_RE = re.compile(
    r"""(?:HttpGet|HttpGetAsync|request)\s*\(\s*['"]([^'"]+)['"]"""
)
LUA_TOKENS = (b'function', b'local', b'--', b'loadstring', b'return', b'end')


def extract_url(loadstring: str) -> str | None:
    m = URL_RE.search(loadstring)
    if m:
        return m.group(1)
    m = re.search(r'https?://[^\s\'")]+', loadstring)
    return m.group(0) if m else None


def verify_loadstring(url: str) -> tuple[bool, int, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        return False, 0, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, 0, f"URL error: {e.reason}"
    except Exception as e:
        return False, 0, f"error: {e}"

    if status != 200:
        return False, len(body), f"HTTP {status}"
    if len(body) < MIN_BODY_BYTES:
        return False, len(body), f"body too small ({len(body)} bytes)"
    if not any(tok in body for tok in LUA_TOKENS):
        return False, len(body), "body doesn't look like Lua source"
    return True, len(body), "ok"


def process_file(path: Path) -> tuple[int, int, list[dict]]:
    data = json.loads(path.read_text())
    tools = data.get("tools", [])
    today = date.today().isoformat()
    broken = []

    for tool in tools:
        url = extract_url(tool.get("loadstring", ""))
        if not url:
            print(f"  X {tool['id']:30} couldn't extract URL")
            tool["verified"] = False
            tool["lastVerified"] = today
            tool["verifiedSizeBytes"] = 0
            broken.append({**tool, "_reason": "no URL found"})
            continue

        was_verified = tool.get("verified", False)
        ok, size, reason = verify_loadstring(url)
        tool["verified"] = ok
        tool["lastVerified"] = today
        tool["verifiedSizeBytes"] = size

        mark = "OK" if ok else "X "
        size_str = f"{size:,}B" if size else "-"
        print(f"  {mark} {tool['id']:30} {size_str:>10}  {reason}")

        if not ok:
            broken.append({**tool, "_reason": reason, "_url": url})

    if "_meta" in data:
        data["_meta"]["updated"] = today
        data["_meta"]["version"] = bump_patch(data["_meta"].get("version", "1.0.0"))

    path.write_text(json.dumps(data, indent=2) + "\n")
    verified_count = sum(1 for t in tools if t.get("verified"))
    return verified_count, len(tools) - verified_count, broken


def bump_patch(v: str) -> str:
    parts = v.split(".")
    if len(parts) == 3 and parts[2].isdigit():
        parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)
    return v


def main() -> int:
    repo_root = Path(__file__).parent
    files = [repo_root / "mainTools.json", repo_root / "communityTools.json"]

    total_verified = 0
    total_broken = 0
    all_broken: list[dict] = []

    for f in files:
        print(f"\n=== {f.name} ===")
        v, b, broken = process_file(f)
        total_verified += v
        total_broken += b
        all_broken.extend(broken)

    print(f"\n=== Summary ===")
    print(f"  Verified: {total_verified}")
    print(f"  Broken:   {total_broken}")

    if all_broken:
        report_path = repo_root / "verification-report.md"
        lines = [
            "# RobloxXea Loadstring Verification Report",
            "",
            f"**Date:** {date.today().isoformat()}",
            f"**Verified:** {total_verified}",
            f"**Broken:** {total_broken}",
            "",
            "## Broken loadstrings",
            "",
        ]
        for t in all_broken:
            lines.append(f"### {t.get('name', t.get('id', 'unknown'))}")
            lines.append(f"- **Tool ID:** `{t.get('id')}`")
            lines.append(f"- **Reason:** `{t.get('_reason')}`")
            if t.get("_url"):
                lines.append(f"- **URL:** {t['_url']}")
            if t.get("repo"):
                lines.append(f"- **Repo:** {t['repo']}")
            lines.append("")
        report_path.write_text("\n".join(lines))
        print(f"  Report written to: {report_path}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
