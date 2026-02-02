# Drupal Issue Queue Skill

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![API](https://img.shields.io/badge/Drupal-API_D7-0678BE)

> One-line summary: a read-only, rate-limited, cached tool for AI agents to search Drupal.org issue queues, summarize threads, and locate patches without scraping.

## Overview

This skill bridges AI agents and the official Drupal.org API (api-d7). It is designed to be a good citizen of Drupal.org infrastructure by enforcing request budgeting, rate limiting, and local caching. It emits structured JSON for agent workflows and readable Markdown for human briefings.

## Triggers and intent

Configure your agent to invoke this skill when a user asks to:

- Find the status of a specific issue.
- Summarize recent comments on an issue.
- Debug an error by checking whether a related issue already exists before patching locally.
- List issues matching status, priority, category, version, or component.
- Check whether a patch is attached to an issue.

## Commands and capabilities

The tool exposes two primary commands via `scripts/dorg.py`.

### 1) `issue`: fetch and summarize

Retrieves metadata, body text, recent comments, and file attachments for a specific issue.

```bash
python scripts/dorg.py issue <nid-or-url> [options]
```

Common options:

- `--mode summary|full` (default: `summary`)
- `--comments N` (default: 10 in summary mode, 50 in full mode)
- `--comment-direction ASC|DESC` (default: `DESC`)
- `--files-limit N|all|0` (default: `10`)
- `--resolve-tags none|api|static` (default: `api`)
- `--tag-map path/to/map.json` (required when `--resolve-tags=static`)
- `--related-mrs`, `--extra-credit`
- `--format json|md` (default: `json`)

### 2) `search`: query projects

Filters the issue queue of a specific project (module, theme, or core).

```bash
python scripts/dorg.py search --project <machine_name> [options]
```

Common options:

- `--status <alias|code>`
- `--priority <alias|code>`
- `--category <alias|code>`
- `--version <string>`
- `--component <string>`
- `--tag-tid <tid>`
- `--limit N` (default: 20)
- `--sort changed|created|nid` (default: `changed`)
- `--direction ASC|DESC` (default: `DESC`)

## Installation

This tool uses the Python standard library.

1. Clone the repository:

```bash
git clone https://github.com/your-username/drupal-issue-queue.git
cd drupal-issue-queue
```

2. Verify the CLI:

```bash
python scripts/dorg.py --help
```

3. Optional: install PyYAML if you use `--resolve-tags=static` with YAML:

```bash
pip install pyyaml
```

## Guardrails and safety

- Read-only: no writes to Drupal.org.
- Request budget: defaults to 30 requests per run; sets `truncated.request_budget_hit` when exceeded.
- Caching: responses cached in `~/.cache/drupal-issue-queue` (TTL default: 1 hour).
- Rate limiting: default 200ms between requests and respects `Retry-After` headers.

## Usage examples

### Agent-friendly JSON

```bash
python scripts/dorg.py search \
  --project metatag \
  --status "needs review" \
  --category bug \
  --format json
```

### Human-readable Markdown

```bash
python scripts/dorg.py issue 3412345 --format md
```

## Field mappings

The tool accepts human-readable aliases for common Drupal codes. See:

- `references/issue-field-mappings.md`
- `references/output-schema.md`
- `references/drupalorg-api-d7.md`

## Related skills

This skill is designed to pair with:

- `https://github.com/scottfalconer/drupal-contribute-fix`
- `https://github.com/scottfalconer/drupal-intent-testing`

## Configuration defaults

Global options available on both commands:

- `--user-agent` to override the default User-Agent string.
- `--cache-dir` (default: `~/.cache/drupal-issue-queue`)
- `--cache-ttl` (default: 3600 seconds)
- `--sleep-ms` (default: 200)
- `--max-requests` (default: 30)

## License

Add a `LICENSE` file to declare the license terms for this project.
