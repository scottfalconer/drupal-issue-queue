# drupal-issue-queue

Read-only Drupal issue triage helper with a hybrid backend:

- `api` backend: Drupal.org `api-d7` with filtering, tags, and file metadata.
- `drupalorg` backend: uses `drupalorg-cli` 0.8+ for agent-aligned issue/project reads.
- `auto` backend (default): prefers `drupalorg` when compatible, otherwise falls back to `api`.

## Requirements

- Python 3.9+
- Optional: `drupalorg` CLI (`0.8.0+`) available as command/path.
  - Alias-based setups are supported (for example `alias drupalorg='ddev drupalorg'`).

## Usage

Issue summary:

```bash
python scripts/dorg.py --format json issue <nid-or-url>
python scripts/dorg.py --backend drupalorg --format md issue <nid-or-url> --resolve-tags none --files-limit 0
```

Project search:

```bash
python scripts/dorg.py --format json search --project drupal --limit 5
python scripts/dorg.py --backend drupalorg --format json search --project drupal --status rtbc
```

## Backend Compatibility

`--backend=drupalorg` intentionally supports a narrower option set.

- `issue` requires:
  - `--resolve-tags none`
  - `--files-limit 0`
  - no `--related-mrs` / `--extra-credit`
- `search` supports:
  - status `needs review` (`8`) or `rtbc` (`14`) only
  - default sort `changed` and direction `DESC`
  - no priority/category/version/component/tag filters

When `--backend=auto`, unsupported combinations automatically fall back to `api` and include the reason under `source.auto_fallback_reason`.

## Output

JSON output remains schema-stable for issue/search payloads and now includes:

```json
{
  "source": {
    "backend": "api|drupalorg",
    "tool": "api-d7|drupalorg-cli",
    "auto_fallback_reason": "optional string"
  }
}
```

## Handoff To Merge-Request Workflow

This skill stays read-only. For fork/MR actions, use `drupalorg-cli` directly:

```bash
drupalorg issue:get-fork <nid> --format=llm
drupalorg issue:setup-remote <nid>
drupalorg issue:checkout <nid> <branch>
drupalorg mr:list <nid> --format=llm
drupalorg mr:status <nid> <mr-iid> --format=llm
drupalorg mr:logs <nid> <mr-iid>
```
