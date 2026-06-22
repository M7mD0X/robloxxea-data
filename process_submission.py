#!/usr/bin/env python3
"""Parse a 'Submit a tool' GitHub issue and prepare an auto-PR.

Input:  ISSUE_BODY env var (the issue body text — GitHub issue forms emit
        a structured plain-text format with `### Field ID` headers followed
        by the user's value).
Output: Writes JSON to result.json describing what happened:
          { "ok": true/false, "reason": "...", "tool": {...}, "feed": "main"|"community" }

If ok=true, also updates mainTools.json or communityTools.json with the new
tool entry (verified/lastVerified/verifiedSizeBytes filled in by the live
HTTP check).

Exit code: 0 if the submission is valid and the JSON was updated, 1 otherwise.
The workflow reads result.json to decide whether to open a PR or comment on
the issue with the validation error.
"""
from __future__ import annotations

import json
import os
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

# Allowed values for fields with constrained inputs.
ALLOWED_CATEGORIES = {
    'Admin Commands', 'ESP / Visuals', 'Remote Spy', 'UI Library',
    'Explorer', 'Script Hub', 'Performance', 'Combat', 'Auto-Farm',
    'Utility', 'Library',
}
# Submissions from the issue form are ALWAYS added to the Community feed.
# The Main Tools feed is maintainer-curated only (official tools, editor's
# choice). If a hand-edited issue body contains a 'Feed' field set to
# 'Main Tools', we reject it explicitly — no way to bypass via the API.
ALLOWED_FEEDS = {'Community'}
ALLOWED_COLORS = {'#22d3ee', '#a855f7', '#ec4899', '#4ade80'}


def parse_issue_body(body: str) -> dict[str, str]:
    """Parse GitHub issue form output into a {field_id: value} dict.

    Issue forms emit plain text like:
        ### Tool name

        Infinite Yield

        ### Author

        EdgeIY
        ...
    """
    fields: dict[str, str] = {}
    # Split on '### ' headers. Each section: header line, blank line, value
    # (until next header or end).
    parts = re.split(r'^### ', body, flags=re.MULTILINE)
    for part in parts[1:]:  # parts[0] is preamble before first header
        lines = part.split('\n', 1)
        if len(lines) < 2:
            continue
        header = lines[0].strip()
        rest = lines[1].strip()
        # Strip trailing "No response" markers GitHub adds when a field is skipped
        if rest == '_No response_':
            rest = ''
        fields[header] = rest
    return fields


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
        return False, 0, f"HTTP {e.code} — the URL returned an error. Check the path, branch, and filename."
    except urllib.error.URLError as e:
        return False, 0, f"Network error: {e.reason}"
    except Exception as e:
        return False, 0, f"Unexpected error: {e}"

    if status != 200:
        return False, len(body), f"HTTP {status}"
    if len(body) < MIN_BODY_BYTES:
        return False, len(body), f"Response body is only {len(body)} bytes — too small to be real Lua source. Likely a 404 stub."
    if not any(tok in body for tok in LUA_TOKENS):
        return False, len(body), "Response body doesn't look like Lua source (no `function`, `local`, `--`, etc. found)."
    return True, len(body), "ok"


def make_slug(name: str) -> str:
    """Infinite Yield -> infinite-yield. Fates Admin -> fates-admin."""
    s = re.sub(r'[^a-zA-Z0-9\s-]', '', name.lower())
    s = re.sub(r'[\s_]+', '-', s).strip('-')
    return s or 'unnamed-tool'


def main() -> int:
    body = os.environ.get('ISSUE_BODY', '')
    if not body:
        print('ERROR: ISSUE_BODY env var is empty.', file=sys.stderr)
        write_result(ok=False, reason='Internal error: issue body was empty.')
        return 1

    fields = parse_issue_body(body)

    # --- Validate required fields ---
    # Note: 'Feed' is intentionally NOT in this list. All user submissions
    # go to the Community feed — the Main Tools feed is maintainer-curated.
    required = ['Tool name', 'Author', 'Repository URL', 'Loadstring',
                'Category', 'Description']
    missing = [f for f in required if not fields.get(f)]
    if missing:
        write_result(ok=False, reason=f'Missing required fields: {", ".join(missing)}.')
        return 1

    name = fields['Tool name'].strip()
    author = fields['Author'].strip()
    repo = fields['Repository URL'].strip()
    loadstring = fields['Loadstring'].strip()
    category = fields['Category'].strip()
    # Hardcoded: user submissions always go to Community. If someone hand-
    # edits the issue body to include a 'Feed' field, we validate it below
    # and reject 'Main Tools' explicitly.
    submitted_feed = fields.get('Feed', '').strip()
    feed = 'Community'
    description = fields['Description'].strip()
    tags_raw = fields.get('Tags', '').strip()
    icon = fields.get('Icon initials (optional)', '').strip()
    icon_color = fields.get('Icon color (optional)', '').strip().lower()

    # --- Validate constrained fields ---
    if category not in ALLOWED_CATEGORIES:
        write_result(ok=False, reason=f'Invalid category "{category}". Must be one of: {", ".join(sorted(ALLOWED_CATEGORIES))}.')
        return 1
    # Explicit guard: if a hand-edited issue body tries to set Feed to
    # 'Main Tools', reject it. This makes the policy enforced in code, not
    # just by the form — no way to bypass via the API.
    if submitted_feed and submitted_feed not in ALLOWED_FEEDS:
        write_result(ok=False, reason=f'Feed "{submitted_feed}" is not allowed for user submissions. All submissions go to the Community feed — the Main Tools feed is maintainer-curated. Remove the Feed field from your issue and resubmit.')
        return 1
    if icon_color and icon_color not in ALLOWED_COLORS:
        write_result(ok=False, reason=f'Invalid icon color "{icon_color}". Must be one of: {", ".join(sorted(ALLOWED_COLORS))}.')
        return 1
    if not repo.startswith('https://github.com/'):
        write_result(ok=False, reason=f'Repository URL must start with "https://github.com/". Got: {repo}')
        return 1

    # --- Validate loadstring format ---
    url = extract_url(loadstring)
    if not url:
        write_result(ok=False, reason='Could not extract a URL from the loadstring. Expected format: `loadstring(game:HttpGet(\'https://...\'))()`')
        return 1

    # --- Verify loadstring actually resolves to real Lua ---
    ok, size, reason = verify_loadstring(url)
    if not ok:
        write_result(ok=False, reason=f'Loadstring verification failed: {reason}', url=url)
        return 1

    # --- Build the tool entry ---
    slug = make_slug(name)
    today = date.today().isoformat()
    tags = [t.strip().lower() for t in tags_raw.split(',') if t.strip()] if tags_raw else []
    if not icon:
        icon = name[:2].upper()

    tool = {
        'id': slug,
        'name': name,
        'author': author,
        'category': category,
        'description': description,
        'loadstring': loadstring,
        'repo': repo,
        'icon': icon,
        'iconColor': icon_color or '#22d3ee',
        'tags': tags,
        'featured': False,
        'verified': True,
        'lastVerified': today,
        'verifiedSizeBytes': size,
    }

    # --- Check for duplicates ---
    repo_root = Path(__file__).parent
    json_file = repo_root / ('mainTools.json' if feed == 'Main Tools' else 'communityTools.json')
    data = json.loads(json_file.read_text())
    existing_ids = {t['id'] for t in data['tools']}
    existing_repos = {t.get('repo', '').lower() for t in data['tools'] if t.get('repo')}
    if slug in existing_ids:
        write_result(ok=False, reason=f'A tool with id "{slug}" already exists. If you are updating an existing tool, please open a regular issue instead.', tool=tool, feed=feed)
        return 1
    if repo.lower() in existing_repos:
        write_result(ok=False, reason=f'A tool from repo "{repo}" is already in the directory.', tool=tool, feed=feed)
        return 1

    # --- Append and write ---
    data['tools'].append(tool)
    if '_meta' in data:
        data['_meta']['updated'] = today
        data['_meta']['version'] = bump_patch(data['_meta'].get('version', '1.0.0'))
    json_file.write_text(json.dumps(data, indent=2) + '\n')

    write_result(ok=True, reason='Loadstring verified, JSON updated.', tool=tool, feed=feed, url=url)
    print(f'OK — added {slug} to {json_file.name}')
    return 0


def bump_patch(v: str) -> str:
    parts = v.split('.')
    if len(parts) == 3 and parts[2].isdigit():
        parts[2] = str(int(parts[2]) + 1)
        return '.'.join(parts)
    return v


def write_result(*, ok: bool, reason: str, tool: dict | None = None,
                 feed: str | None = None, url: str | None = None) -> None:
    result = {'ok': ok, 'reason': reason}
    if tool: result['tool'] = tool
    if feed: result['feed'] = feed
    if url: result['url'] = url
    Path('result.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    sys.exit(main())
