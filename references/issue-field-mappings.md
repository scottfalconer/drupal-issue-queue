# Issue field mappings

These mappings are used by `scripts/dorg.py` to translate human aliases into numeric codes
for search filters. If Drupal.org updates the codes, update both this file and the script.

## Status codes (field_issue_status)

| Code | Label |
|------|-------|
| 1 | Active |
| 2 | Fixed |
| 3 | Closed (duplicate) |
| 4 | Postponed |
| 5 | Closed (won't fix) |
| 6 | Closed (works as designed) |
| 7 | Closed (fixed) |
| 8 | Needs review |
| 13 | Needs work |
| 14 | Reviewed & tested by the community (RTBC) |
| 15 | Patch (to be ported) |
| 16 | Postponed (maintainer needs more info) |
| 17 | Closed (outdated) |
| 18 | Closed (cannot reproduce) |

Alias examples: `active`, `needs review`, `rtbc`, `needs work`, `fixed`, `duplicate`, `outdated`.

## Priority codes (field_issue_priority)

| Code | Label |
|------|-------|
| 400 | Critical |
| 300 | Major |
| 200 | Normal |
| 100 | Minor |

Alias examples: `critical`, `major`, `normal`, `minor`.

## Category codes (field_issue_category)

| Code | Label |
|------|-------|
| 1 | Bug report |
| 2 | Feature request |
| 3 | Task |
| 4 | Support request |
| 5 | Plan |

Alias examples: `bug`, `feature`, `task`, `support`, `plan`.
