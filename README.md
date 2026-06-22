# robloxxea-data

Auto-updating JSON feed of **verified** Roblox scripting tools for the [RobloxXea](https://github.com/M7mD0X/robloxxea) PWA.

## Files

| File | Description |
|------|-------------|
| [`mainTools.json`](./mainTools.json) | Curated toolkit — 12 hand-picked, universal, open-source Roblox scripting tools (Infinite Yield, Unnamed ESP, Hydroxide, Fates Admin, WindUI, Orion Library, etc.) |
| [`communityTools.json`](./communityTools.json) | Auto-updating community feed — 9 community-published tools (Sp3arParvus, FxkeDex, ItzXery ESP, FPS GUI, etc.) |
| [`verify_loadstrings.py`](./verify_loadstrings.py) | Verification script — runs every Monday at 08:00 UTC via GitHub Actions |

## Why this repo exists

Every tool entry includes a `loadstring` field that the RobloxXea app copies to the user's clipboard so they can paste it into their executor. **If the loadstring URL 404s, the app is useless for that tool.** This repo exists to:

1. **Decouple data from app code** — community can submit new tools via PR without re-deploying the React app.
2. **Auto-verify loadstrings** — a weekly GitHub Action re-fetches every loadstring URL and flips the `verified` field to `false` if a repo goes dark. The Action also opens a GitHub issue so maintainers are notified.
3. **Surface verification state in the UI** — the app fetches these JSON files at runtime and renders a green "✓ Verified" or pink "Unverified" badge on every tool card.

## Verification logic

A tool is marked `verified: true` iff:

- HTTP response is `200 OK`
- Response body is at least `1024` bytes (filters out GitHub's 404 HTML stubs and tiny redirect pages)
- Response body contains at least one of these Lua tokens: `function`, `local`, `--`, `loadstring`, `return`, `end`

Each tool entry tracks:

```json
{
  "verified": true,
  "lastVerified": "2026-06-22",
  "verifiedSizeBytes": 482145
}
```

## Schema

Both JSON files share the same shape so the app's `ToolCard` component renders them interchangeably:

```json
{
  "_meta": {
    "name": "string",
    "version": "1.0.0",
    "updated": "2026-06-22",
    "description": "string"
  },
  "tools": [
    {
      "id": "unique-slug",
      "name": "Display Name",
      "author": "GitHub username or org",
      "category": "Admin Commands | ESP / Visuals | Remote Spy | UI Library | Explorer | Script Hub | Performance | Combat | Auto-Farm | Utility | Library",
      "description": "1-3 sentence accurate description.",
      "loadstring": "loadstring(game:HttpGet('https://raw.githubusercontent.com/.../file.lua'))()",
      "repo": "https://github.com/owner/repo",
      "icon": "2-3 letter initials",
      "iconColor": "#22d3ee",
      "tags": ["tag1", "tag2"],
      "featured": false,
      "verified": true,
      "lastVerified": "2026-06-22",
      "verifiedSizeBytes": 482145
    }
  ]
}
```

## Adding a tool

There are **two ways** to add a tool, depending on which feed it belongs to:

### Community tab — via issue form (for everyone)

1. Open the [Submit a tool](https://github.com/M7mD0X/robloxxea-data/issues/new?template=submit-a-tool.yml&labels=submission) issue form.
2. Fill in the fields (name, author, repo URL, loadstring, category, description). The bot auto-verifies the loadstring on submit and opens a PR.
3. A maintainer reviews and merges. Done.

**All user submissions go to the Community tab.** This is enforced in code (`process_submission.py` rejects any `Feed` field that isn't `Community`), so hand-editing the issue body to say "Main Tools" won't bypass the policy.

### Main Tools tab — via direct PR (maintainer only)

The Main Tools tab is curated by the maintainer (official tools, editor's choice, dev's picks). To add or promote a tool here:

1. Fork the repo.
2. Append a new entry to `mainTools.json` (or move an entry from `communityTools.json` if promoting). Set `featured: true` for tools that should get a ★ Featured badge.
3. Fill in all fields except `verified`, `lastVerified`, and `verifiedSizeBytes` — the verifier populates those automatically on the next run.
4. Open a PR. The `Verify loadstrings` workflow runs on push — a green check means your loadstring actually resolves to real Lua source.
5. Once merged, the RobloxXea app picks up the new tool on the next user visit (cached for up to 24h by the service worker).

## URLs the app uses

The app fetches these raw URLs (NetworkFirst via the service worker, so it works offline once cached):

- `https://raw.githubusercontent.com/M7mD0X/robloxxea-data/main/mainTools.json`
- `https://raw.githubusercontent.com/M7mD0X/robloxxea-data/main/communityTools.json`

These URLs are baked into the app's build via `VITE_MAIN_TOOLS_URL` and `VITE_COMMUNITY_TOOLS_URL` env vars in the [main app's deploy workflow](https://github.com/M7mD0X/robloxxea/blob/main/.github/workflows/deploy.yml).
