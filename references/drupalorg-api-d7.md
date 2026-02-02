# Drupal.org API (api-d7) reference

Base URL: https://www.drupal.org/api-d7

## Requirements

- Send `Accept: application/json` or use `.json` endpoints.
- Use a descriptive User-Agent with contact info.
- Single-threaded requests.
- Cache responses locally.
- Respect rate limiting and Retry-After headers.

## Common endpoints

Project lookup (machine name -> project nid):

```
GET /node.json?field_project_machine_name=<machine>&limit=1
```

Issue search for a project:

```
GET /node.json?type=project_issue&field_project=<project_nid>
```

Optional filters:

- `field_issue_status` (code)
- `field_issue_priority` (code)
- `field_issue_category` (code)
- `field_issue_version` (string)
- `field_issue_component` (string)
- `taxonomy_vocabulary_9` (tag term id)

Issue detail:

```
GET /node/<nid>.json
GET /node/<nid>.json?related_mrs=1
GET /node/<nid>.json?drupalorg_extra_credit=1
```

Comments (filter by node id):

```
GET /comment.json?node=<issue_nid>
```

File metadata:

```
GET /file/<fid>.json
```

Taxonomy term lookup:

```
GET /taxonomy_term/<tid>.json
```

## Pagination and limits

- Query endpoints accept `limit`, `page`, `sort`, and `direction`.
- Maximum `limit` per request is 50; paginate when more results are needed.
- For comments, sort by `cid` for stable paging.

## Resources

RESTWS resources: node, comment, file, taxonomy_term, taxonomy_vocabulary.
