---
name: drupal-issue-queue
description: >
  Search Drupal.org issue queues and summarize individual issues for triage.
  Uses a hybrid backend: prefer drupalorg-cli 0.8+ when available for
  agent-aligned issue/project reads, and fall back to api-d7 for advanced
  filtering and file/tag metadata while preserving read-only guardrails.
---

# Drupal Issue Queue

## Guardrails

- Keep all operations read-only.
- Use official interfaces only: Drupal.org API and drupalorg-cli.
- Keep requests single-threaded, cached, and rate-limited.
- Respect request budgets and Retry-After headers.
- Prefer small, scoped queries with explicit limits.

## Commands

Global backend options:

- `--backend auto|api|drupalorg` (default: `auto`)
- `--drupalorg-bin <command-or-path>` (default: `drupalorg`; alias-friendly via login shell)

### Summarize an issue

```bash
python scripts/dorg.py --format json issue <nid-or-url>
python scripts/dorg.py --format md issue <nid-or-url>
python scripts/dorg.py --backend drupalorg --format json issue <nid-or-url> --resolve-tags none --files-limit 0
```

Common options:

- `--mode summary|full` (default: `summary`)
- `--comments N` (default: 10 in summary mode, 50 in full mode)
- `--files-limit N|all|0` (default: 10)
- `--resolve-tags none|api|static` (default: `api`)
- `--tag-map path/to/map.json` (required when `--resolve-tags=static`)
- `--related-mrs` or `--extra-credit`
- `--max-requests`, `--sleep-ms`, `--cache-ttl`, `--user-agent`

When `--backend=drupalorg`, this command supports issue + comments only. Use:

- `--resolve-tags none`
- `--files-limit 0`
- no `--related-mrs` / `--extra-credit`

### Search issues in a project

```bash
python scripts/dorg.py --format json search --project <machine_name>
python scripts/dorg.py --backend drupalorg --format json search --project <machine_name> --status rtbc
```

Common filters:

- `--status <alias|code>`
- `--priority <alias|code>`
- `--category <alias|code>`
- `--version <string>`
- `--component <string>`
- `--tag-tid <tid>`
- `--limit N --sort changed|created|nid --direction ASC|DESC`

`drupalorg` backend search supports only:

- status: `needs review` (`8`) or `rtbc` (`14`)
- default sort/direction (`changed` + `DESC`)
- no priority/category/version/component/tag filters

## Outputs

- JSON output is structured for downstream agents; see `references/output-schema.md`.
- Markdown output provides a human-readable summary and is suitable for briefings.
- Output includes a `source` block with backend metadata and optional auto-fallback reason.

## Contribution Handoff

For fork/MR workflows introduced in drupalorg-cli 0.8+, hand off to these commands:

```bash
drupalorg issue:get-fork <nid> --format=llm
drupalorg issue:setup-remote <nid>
drupalorg issue:checkout <nid> <branch>
drupalorg mr:list <nid> --format=llm
drupalorg mr:status <nid> <mr-iid> --format=llm
drupalorg mr:logs <nid> <mr-iid>
```

## References

- `references/drupalorg-api-d7.md` for endpoints, limits, and headers.
- `references/issue-field-mappings.md` for status/priority/category codes and aliases.
- `references/output-schema.md` for JSON schema and examples.
