# Output schema

This skill emits JSON for downstream agents and Markdown for human readers.

## Issue summary JSON

```
{
  "nid": "123456",
  "title": "Issue title",
  "url": "https://www.drupal.org/node/123456",
  "created_ts": 1700000000,
  "created": "2023-11-14T12:00:00+00:00",
  "updated_ts": 1700001000,
  "updated": "2023-11-14T12:16:40+00:00",
  "status": { "code": 1, "label": "Active" },
  "priority": { "code": 200, "label": "Normal" },
  "category": { "code": 1, "label": "Bug report" },
  "version": "10.2.x",
  "component": "Views",
  "tags": [ { "tid": "24656", "name": "php" } ],
  "related_mrs": ["https://git.drupalcode.org/..."],
  "comment_count": 12,
  "last_comment_ts": 1700002000,
  "body_markdown": "...",
  "latest_comments": [
    {
      "cid": "555",
      "created_ts": 1700001500,
      "created": "2023-11-14T12:25:00+00:00",
      "author_uid": "123",
      "author_name": "username",
      "body_markdown": "...",
      "attachments": [
        {
          "fid": "777",
          "name": "fix.patch",
          "mime": "text/plain",
          "size": 1024,
          "url": "https://www.drupal.org/files/issues/...",
          "timestamp_ts": 1700001400,
          "is_patch": true,
          "cid": "555"
        }
      ]
    }
  ],
  "files": [
    {
      "fid": "777",
      "name": "fix.patch",
      "mime": "text/plain",
      "size": 1024,
      "url": "https://www.drupal.org/files/issues/...",
      "timestamp_ts": 1700001400,
      "is_patch": true,
      "cid": "555"
    }
  ],
  "truncated": {
    "comments": false,
    "files": false,
    "tag_resolution": false,
    "request_budget_hit": false
  },
  "source": {
    "backend": "api",
    "tool": "api-d7",
    "auto_fallback_reason": "optional when --backend=auto falls back"
  }
}
```

## Search results JSON

```
{
  "project": { "machine_name": "metatag", "nid": "123" },
  "query": {
    "status": 1,
    "priority": 200,
    "category": 1,
    "version": "10.2.x",
    "component": "Views",
    "tag_tid": "24656",
    "sort": "changed",
    "direction": "DESC"
  },
  "count": 20,
  "limit": 20,
  "results": [
    {
      "nid": "123456",
      "title": "Issue title",
      "url": "https://www.drupal.org/node/123456",
      "created_ts": 1700000000,
      "created": "2023-11-14T12:00:00+00:00",
      "updated_ts": 1700001000,
      "updated": "2023-11-14T12:16:40+00:00",
      "status": { "code": 1, "label": "Active" },
      "priority": { "code": 200, "label": "Normal" },
      "category": { "code": 1, "label": "Bug report" }
    }
  ],
  "truncated": {
    "limit": true,
    "request_budget_hit": false
  },
  "source": {
    "backend": "api",
    "tool": "api-d7",
    "auto_fallback_reason": "optional when --backend=auto falls back"
  }
}
```

## Markdown output

When `--format md` is used, the script emits a readable summary with metadata, body,
latest comments, and file list for issues, or a bulleted list for search results.
