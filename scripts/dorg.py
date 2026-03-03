#!/usr/bin/env python3
"""
Drupal.org issue queue helper (read-only).

Uses the Drupal.org API (api-d7) with caching, request budgeting,
rate limiting, and single-threaded access.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://www.drupal.org/api-d7"
MAX_PAGE_LIMIT = 50
TAG_RESOLVE_LIMIT = 10
BASH_ALIAS_PREFIX = "shopt -s expand_aliases; if [ -f ~/.bashrc ]; then source ~/.bashrc >/dev/null 2>&1; fi; "

ISSUE_STATUS = {
    1: "Active",
    2: "Fixed",
    3: "Closed (duplicate)",
    4: "Postponed",
    5: "Closed (won't fix)",
    6: "Closed (works as designed)",
    7: "Closed (fixed)",
    8: "Needs review",
    13: "Needs work",
    14: "Reviewed & tested by the community",
    15: "Patch (to be ported)",
    16: "Postponed (maintainer needs more info)",
    17: "Closed (outdated)",
    18: "Closed (cannot reproduce)",
}

ISSUE_PRIORITY = {
    400: "Critical",
    300: "Major",
    200: "Normal",
    100: "Minor",
}

ISSUE_CATEGORY = {
    1: "Bug report",
    2: "Feature request",
    3: "Task",
    4: "Support request",
    5: "Plan",
}

STATUS_ALIASES = {
    "active": 1,
    "fixed": 2,
    "closed duplicate": 3,
    "duplicate": 3,
    "postponed": 4,
    "closed wont fix": 5,
    "wont fix": 5,
    "closed works as designed": 6,
    "works as designed": 6,
    "closed fixed": 7,
    "needs review": 8,
    "needs work": 13,
    "rtbc": 14,
    "reviewed tested by the community": 14,
    "patch to be ported": 15,
    "postponed needs info": 16,
    "needs info": 16,
    "closed outdated": 17,
    "outdated": 17,
    "closed cannot reproduce": 18,
    "cannot reproduce": 18,
}

PRIORITY_ALIASES = {
    "critical": 400,
    "major": 300,
    "normal": 200,
    "minor": 100,
}

CATEGORY_ALIASES = {
    "bug": 1,
    "bug report": 1,
    "feature": 2,
    "feature request": 2,
    "task": 3,
    "support": 4,
    "support request": 4,
    "plan": 5,
}


class BudgetExceeded(Exception):
    """Raised when the request budget is exhausted."""


class DrupalOrgError(Exception):
    """Raised for API and parsing errors."""


def normalize_alias(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.strip().lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_ts(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def extract_list(payload: Any) -> List[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "list" in payload:
            items = payload["list"]
            if isinstance(items, list):
                return items
            if isinstance(items, dict):
                return _dict_indexed_list(items)
        if all(isinstance(v, dict) for v in payload.values()):
            return _dict_indexed_list(payload)
    return []


def _dict_indexed_list(items: Dict[str, Any]) -> List[Any]:
    try:
        keys = sorted(items.keys(), key=lambda k: int(k))
    except (ValueError, TypeError):
        keys = sorted(items.keys())
    return [items[k] for k in keys]


def first_field_value(field: Any, keys: Tuple[str, ...] = ("value",)) -> Optional[Any]:
    for item in ensure_list(field):
        if isinstance(item, dict):
            for key in keys:
                if key in item:
                    return item.get(key)
    return None


class HtmlToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.in_pre = False
        self.in_code = False
        self.link_stack: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attrs_dict = dict(attrs)
        if tag == "pre":
            self._ensure_newline()
            self.parts.append("```")
            self.in_pre = True
        elif tag == "code":
            if not self.in_pre:
                self.parts.append("`")
                self.in_code = True
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "p":
            self._ensure_newline()
        elif tag == "li":
            self._ensure_newline()
            self.parts.append("- ")
        elif tag == "a":
            href = attrs_dict.get("href") or ""
            self.link_stack.append({"href": href, "text": ""})

    def handle_endtag(self, tag: str):
        if tag == "pre":
            if self.parts and not self.parts[-1].endswith("\n"):
                self.parts.append("\n")
            self.parts.append("```")
            self.parts.append("\n")
            self.in_pre = False
        elif tag == "code":
            if self.in_code:
                self.parts.append("`")
                self.in_code = False
        elif tag == "a":
            link = self.link_stack.pop() if self.link_stack else None
            if link:
                text = link.get("text", "").strip()
                href = link.get("href", "").strip()
                if text and href:
                    self.parts.append(f"{text} ({href})")
                elif href:
                    self.parts.append(href)
                else:
                    self.parts.append(text)
        elif tag == "p":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self.link_stack:
            self.link_stack[-1]["text"] += data
        else:
            self.parts.append(data)

    def _ensure_newline(self):
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: Optional[str]) -> str:
    if not html:
        return ""
    parser = HtmlToMarkdown()
    parser.feed(html)
    parser.close()
    return parser.get_text()


class Cache:
    def __init__(self, cache_dir: Path, ttl: int):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, url: str) -> Optional[Any]:
        path = self._path_for(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        fetched_at = payload.get("fetched_at")
        if fetched_at is None:
            return None
        if time.time() - fetched_at > self.ttl:
            return None
        return payload.get("data")

    def set(self, url: str, data: Any) -> None:
        path = self._path_for(url)
        payload = {"fetched_at": time.time(), "data": data}
        try:
            path.write_text(json.dumps(payload))
        except OSError:
            return


class RequestBudget:
    def __init__(self, max_requests: int):
        self.max_requests = max_requests
        self.count = 0
        self.hit = False

    def consume(self) -> None:
        if self.count >= self.max_requests:
            self.hit = True
            raise BudgetExceeded("Request budget exceeded")
        self.count += 1


class RateLimiter:
    def __init__(self, sleep_ms: int):
        self.sleep_seconds = max(0.0, sleep_ms / 1000.0)
        self.last_request = 0.0

    def wait(self):
        if self.sleep_seconds <= 0:
            return
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.sleep_seconds:
            time.sleep(self.sleep_seconds - elapsed)
        self.last_request = time.time()


class DrupalOrgClient:
    def __init__(
        self,
        user_agent: str,
        cache: Cache,
        budget: RequestBudget,
        limiter: RateLimiter,
        max_retries: int = 2,
    ):
        self.user_agent = user_agent
        self.cache = cache
        self.budget = budget
        self.limiter = limiter
        self.max_retries = max_retries

    def get_json(self, url: str) -> Any:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        attempt = 0
        while True:
            self.budget.consume()
            self.limiter.wait()
            request = urllib.request.Request(url)
            request.add_header("User-Agent", self.user_agent)
            request.add_header("Accept", "application/json")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8")
                    data = json.loads(body)
                    self.cache.set(url, data)
                    return data
            except urllib.error.HTTPError as error:
                if error.code in (429, 503) and attempt < self.max_retries:
                    retry_after = error.headers.get("Retry-After")
                    self._sleep_retry(retry_after)
                    attempt += 1
                    continue
                raise DrupalOrgError(f"HTTP {error.code} for {url}")
            except urllib.error.URLError as error:
                raise DrupalOrgError(f"Network error for {url}: {error.reason}")
            except json.JSONDecodeError:
                raise DrupalOrgError(f"Invalid JSON for {url}")

    def _sleep_retry(self, retry_after: Optional[str]) -> None:
        if not retry_after:
            time.sleep(2)
            return
        seconds = _parse_retry_after(retry_after)
        time.sleep(min(seconds, 60))


def _parse_retry_after(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return 5


def build_url(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    url = f"{API_BASE}/{path}"
    if params:
        return f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    return url


def parse_nid(value: str) -> str:
    if value.isdigit():
        return value
    match = re.search(r"/node/(\d+)", value)
    if match:
        return match.group(1)
    match = re.search(r"/issues/(\d+)", value)
    if match:
        return match.group(1)
    match = re.search(r"(\d+)$", value)
    if match:
        return match.group(1)
    raise DrupalOrgError(f"Unable to parse issue nid from '{value}'")


def parse_alias(value: Optional[str], aliases: Dict[str, int]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    normalized = normalize_alias(value)
    return aliases.get(normalized)


def select_file_refs(file_refs: List[Dict[str, Any]], limit: Optional[int]) -> List[Dict[str, Any]]:
    if limit == 0:
        return []
    if not file_refs:
        return []
    ordered = [item for item in file_refs if isinstance(item, dict)]
    if not ordered:
        return []
    if any(to_int(item.get("timestamp")) for item in ordered):
        ordered.sort(key=lambda item: to_int(item.get("timestamp")) or 0)
    if limit is None:
        return ordered
    if len(ordered) <= limit:
        return ordered
    return ordered[-limit:]


def file_is_patch(name: str, mime: str) -> bool:
    lower = name.lower()
    if lower.endswith((".patch", ".diff", ".txt")):
        return True
    if mime.startswith("text/"):
        return True
    return False


def build_status(code: Optional[int], mapping: Dict[int, str]) -> Dict[str, Any]:
    if code is None:
        return {"code": None, "label": None}
    return {"code": code, "label": mapping.get(code, "Unknown")}


def build_tag_list(tags: List[Any]) -> List[Dict[str, Any]]:
    result = []
    for tag in tags:
        tid = None
        name = None
        if isinstance(tag, dict):
            tid = tag.get("tid")
            name = tag.get("name")
        elif isinstance(tag, (str, int)):
            tid = tag
        if tid is not None:
            result.append({"tid": str(tid), "name": name})
    return result


def resolve_tags(
    client: DrupalOrgClient,
    tags: List[Any],
    mode: str,
    tag_map: Optional[Dict[str, str]],
    budget: RequestBudget,
) -> Tuple[List[Dict[str, Any]], bool]:
    if mode == "none":
        return build_tag_list(tags), False

    resolved: List[Dict[str, Any]] = []
    truncated = False
    for idx, tag in enumerate(tags):
        if isinstance(tag, dict):
            tid = tag.get("tid")
        elif isinstance(tag, (str, int)):
            tid = tag
        else:
            tid = None
        if tid is None:
            continue
        if idx >= TAG_RESOLVE_LIMIT:
            truncated = True
            resolved.append({"tid": str(tid), "name": None})
            continue
        if mode == "static":
            name = None
            if tag_map:
                name = tag_map.get(str(tid))
            resolved.append({"tid": str(tid), "name": name})
            if name is None:
                truncated = True
            continue
        if mode == "api":
            try:
                term = client.get_json(build_url(f"taxonomy_term/{tid}.json"))
            except (DrupalOrgError, BudgetExceeded):
                budget.hit = True
                truncated = True
                resolved.append({"tid": str(tid), "name": None})
                continue
            name = term.get("name") if isinstance(term, dict) else None
            resolved.append({"tid": str(tid), "name": name})
            if name is None:
                truncated = True
    return resolved, truncated


def load_tag_map(path: Optional[str]) -> Optional[Dict[str, str]]:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        raise DrupalOrgError(f"Tag map not found: {path}")
    if file_path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise DrupalOrgError("PyYAML not installed; use JSON for --tag-map") from exc
        data = yaml.safe_load(file_path.read_text())
    else:
        data = json.loads(file_path.read_text())
    if not isinstance(data, dict):
        raise DrupalOrgError("Tag map must be a mapping of tid -> name")
    return {str(k): str(v) for k, v in data.items()}


def issue_to_summary(
    node: Dict[str, Any],
    comments: List[Dict[str, Any]],
    files: List[Dict[str, Any]],
    tags: List[Dict[str, Any]],
    truncated_flags: Dict[str, bool],
) -> Dict[str, Any]:
    nid = str(node.get("nid")) if node.get("nid") is not None else None
    url = node.get("url") or (f"https://www.drupal.org/node/{nid}" if nid else None)
    created_ts = to_int(node.get("created"))
    updated_ts = to_int(node.get("changed"))
    status_code = to_int(node.get("field_issue_status"))
    priority_code = to_int(node.get("field_issue_priority"))
    category_code = to_int(node.get("field_issue_category"))
    version = first_field_value(node.get("field_issue_version"), ("value", "tid"))
    component = first_field_value(node.get("field_issue_component"), ("value", "tid"))
    body_html = first_field_value(node.get("body"), ("value",))
    related_mrs = node.get("related_mrs")
    related_urls: List[str] = []
    if isinstance(related_mrs, list):
        for entry in related_mrs:
            if isinstance(entry, dict) and entry.get("url"):
                related_urls.append(entry.get("url"))
            elif isinstance(entry, str):
                related_urls.append(entry)
    return {
        "nid": nid,
        "title": node.get("title"),
        "url": url,
        "created_ts": created_ts,
        "created": format_ts(created_ts),
        "updated_ts": updated_ts,
        "updated": format_ts(updated_ts),
        "status": build_status(status_code, ISSUE_STATUS),
        "priority": build_status(priority_code, ISSUE_PRIORITY),
        "category": build_status(category_code, ISSUE_CATEGORY),
        "version": version,
        "component": component,
        "tags": tags,
        "related_mrs": related_urls,
        "comment_count": to_int(node.get("comment_count")),
        "last_comment_ts": to_int(node.get("last_comment_timestamp")),
        "body_markdown": html_to_markdown(body_html),
        "latest_comments": comments,
        "files": files,
        "truncated": truncated_flags,
    }


def comment_summary(comment: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(comment.get("cid")) if comment.get("cid") is not None else None
    created_ts = to_int(comment.get("created"))
    body_html = first_field_value(comment.get("comment_body"), ("value",))
    return {
        "cid": cid,
        "created_ts": created_ts,
        "created": format_ts(created_ts),
        "author_uid": comment.get("uid"),
        "author_name": comment.get("name"),
        "body_markdown": html_to_markdown(body_html),
    }


def file_summary(file_data: Dict[str, Any]) -> Dict[str, Any]:
    fid = str(file_data.get("fid")) if file_data.get("fid") is not None else None
    name = file_data.get("filename") or ""
    mime = file_data.get("filemime") or ""
    size = to_int(file_data.get("filesize"))
    url = file_data.get("url") or file_data.get("uri")
    timestamp_ts = to_int(file_data.get("timestamp"))
    return {
        "fid": fid,
        "name": name,
        "mime": mime,
        "size": size,
        "url": url,
        "timestamp_ts": timestamp_ts,
        "is_patch": file_is_patch(name, mime),
        "cid": file_data.get("cid"),
    }


def attach_files_to_comments(comments: List[Dict[str, Any]], files: List[Dict[str, Any]]) -> None:
    by_cid: Dict[str, List[Dict[str, Any]]] = {}
    for file_item in files:
        cid = file_item.get("cid")
        if cid is None:
            continue
        by_cid.setdefault(str(cid), []).append(file_item)
    for comment in comments:
        cid = comment.get("cid")
        if cid is None:
            continue
        attachments = by_cid.get(str(cid))
        if attachments:
            comment["attachments"] = attachments


def issue_to_markdown(summary: Dict[str, Any]) -> str:
    lines = []
    title = summary.get("title") or "Issue"
    lines.append(f"# {title}")
    if summary.get("url"):
        lines.append(summary["url"])
    lines.append("")
    lines.append("## Metadata")
    lines.append(f"- NID: {summary.get('nid')}")
    status = summary.get("status", {})
    priority = summary.get("priority", {})
    category = summary.get("category", {})
    lines.append(f"- Status: {status.get('label')} ({status.get('code')})")
    lines.append(f"- Priority: {priority.get('label')} ({priority.get('code')})")
    lines.append(f"- Category: {category.get('label')} ({category.get('code')})")
    lines.append(f"- Version: {summary.get('version')}")
    lines.append(f"- Component: {summary.get('component')}")
    lines.append(f"- Created: {summary.get('created')}")
    lines.append(f"- Updated: {summary.get('updated')}")
    lines.append(f"- Comment count: {summary.get('comment_count')}")
    lines.append(f"- Last comment: {format_ts(summary.get('last_comment_ts'))}")
    source = summary.get("source") or {}
    if source.get("backend"):
        lines.append(f"- Source backend: {source.get('backend')}")
        if source.get("auto_fallback_reason"):
            lines.append(f"- Backend fallback: {source.get('auto_fallback_reason')}")
    tags = summary.get("tags") or []
    if tags:
        tag_parts = []
        for tag in tags:
            name = tag.get("name") or "?"
            tag_parts.append(f"{name} ({tag.get('tid')})")
        lines.append(f"- Tags: {', '.join(tag_parts)}")
    related_mrs = summary.get("related_mrs") or []
    if related_mrs:
        lines.append("- Related MRs:")
        for mr in related_mrs:
            lines.append(f"  - {mr}")
    truncated = summary.get("truncated") or {}
    if any(truncated.values()):
        lines.append(f"- Truncated: {truncated}")
    lines.append("")
    body = summary.get("body_markdown") or ""
    if body:
        lines.append("## Body")
        lines.append(body)
        lines.append("")
    comments = summary.get("latest_comments") or []
    if comments:
        lines.append("## Latest comments")
        for comment in comments:
            lines.append(f"### {comment.get('created')} (cid {comment.get('cid')})")
            author = comment.get("author_name") or comment.get("author_uid")
            if author:
                lines.append(f"By: {author}")
            lines.append(comment.get("body_markdown") or "")
            attachments = comment.get("attachments")
            if attachments:
                lines.append("Attachments:")
                for attachment in attachments:
                    lines.append(f"- {attachment.get('name')} ({attachment.get('fid')})")
            lines.append("")
    files = summary.get("files") or []
    if files:
        lines.append("## Files")
        for file_item in files:
            lines.append(
                f"- {file_item.get('name')} ({file_item.get('fid')}), {file_item.get('mime')}, {file_item.get('size')} bytes"
            )
            if file_item.get("url"):
                lines.append(f"  {file_item.get('url')}")
    return "\n".join(lines).strip() + "\n"


def search_to_markdown(payload: Dict[str, Any]) -> str:
    lines = []
    project = payload.get("project", {})
    lines.append(f"# Issue search: {project.get('machine_name')}")
    lines.append(f"Project NID: {project.get('nid')}")
    lines.append("")
    query = payload.get("query", {})
    if query:
        lines.append(f"Query: {query}")
    source = payload.get("source") or {}
    if source.get("backend"):
        lines.append(f"Source backend: {source.get('backend')}")
        if source.get("auto_fallback_reason"):
            lines.append(f"Backend fallback: {source.get('auto_fallback_reason')}")
    lines.append(f"Returned: {payload.get('count')} (limit {payload.get('limit')})")
    truncated = payload.get("truncated") or {}
    if any(truncated.values()):
        lines.append(f"Truncated: {truncated}")
    lines.append("")
    lines.append("## Results")
    for issue in payload.get("results", []):
        status = issue.get("status", {})
        priority = issue.get("priority", {})
        category = issue.get("category", {})
        line = (
            f"- {issue.get('nid')}: {issue.get('title')} | "
            f"{status.get('label')} ({status.get('code')}), "
            f"{priority.get('label')} ({priority.get('code')}), "
            f"{category.get('label')} ({category.get('code')}) | "
            f"Updated {issue.get('updated')}"
        )
        lines.append(line)
        if issue.get("url"):
            lines.append(f"  {issue.get('url')}")
    return "\n".join(lines).strip() + "\n"


def build_user_agent(user_agent: Optional[str]) -> str:
    if user_agent:
        return user_agent
    user = os.environ.get("USER") or "user"
    host = socket.gethostname() or "localhost"
    return f"drupal-issue-queue/0.1 (contact: {user}@{host})"


def command_issue_api(args: argparse.Namespace) -> Dict[str, Any]:
    nid = parse_nid(args.nid_or_url)
    cache = Cache(Path(args.cache_dir), args.cache_ttl)
    budget = RequestBudget(args.max_requests)
    limiter = RateLimiter(args.sleep_ms)
    client = DrupalOrgClient(build_user_agent(args.user_agent), cache, budget, limiter)

    if args.resolve_tags == "static" and not args.tag_map:
        raise DrupalOrgError("--resolve-tags=static requires --tag-map")

    query_params = {}
    if args.extra_credit:
        query_params["drupalorg_extra_credit"] = 1
    if args.related_mrs:
        query_params["related_mrs"] = 1

    issue_url = build_url(f"node/{nid}.json", query_params)

    node = client.get_json(issue_url)
    if not isinstance(node, dict):
        raise DrupalOrgError("Unexpected issue response")

    tags_raw = ensure_list(node.get("taxonomy_vocabulary_9"))
    tag_map = load_tag_map(args.tag_map) if args.resolve_tags == "static" else None
    tags, tags_truncated = resolve_tags(client, tags_raw, args.resolve_tags, tag_map, budget)

    comments_limit = args.comments
    if comments_limit is None:
        comments_limit = 10 if args.mode == "summary" else 50

    comments: List[Dict[str, Any]] = []
    if comments_limit > 0:
        comments = fetch_comments(
            client,
            nid,
            comments_limit,
            args.comment_direction,
            paginate=args.mode == "full",
        )
        comments = [comment_summary(c) for c in comments]

    files_limit = args.files_limit
    file_refs = ensure_list(node.get("field_issue_files"))
    selected_files = select_file_refs(file_refs, files_limit)
    files: List[Dict[str, Any]] = []
    for ref in selected_files:
        fid = ref.get("fid") if isinstance(ref, dict) else None
        if not fid:
            continue
        try:
            file_data = client.get_json(build_url(f"file/{fid}.json"))
        except BudgetExceeded:
            budget.hit = True
            break
        if isinstance(file_data, dict):
            files.append(file_summary(file_data))

    attach_files_to_comments(comments, files)

    comment_count = to_int(node.get("comment_count"))
    comments_truncated = False
    if comment_count is not None:
        comments_truncated = comment_count > len(comments)
    elif comments_limit and len(comments) >= comments_limit:
        comments_truncated = True

    files_truncated = len(file_refs) > len(files)

    truncated_flags = {
        "comments": comments_truncated,
        "files": files_truncated,
        "tag_resolution": tags_truncated,
        "request_budget_hit": budget.hit,
    }

    summary = issue_to_summary(node, comments, files, tags, truncated_flags)
    summary["source"] = {"backend": "api", "tool": "api-d7"}
    return summary


def fetch_comments(
    client: DrupalOrgClient,
    nid: str,
    limit: int,
    direction: str,
    paginate: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    remaining = limit
    page = 0
    while remaining > 0:
        per_page = min(MAX_PAGE_LIMIT, remaining)
        params = {
            "node": nid,
            "sort": "cid",
            "direction": direction,
            "limit": per_page,
        }
        if paginate:
            params["page"] = page
        url = build_url("comment.json", params)
        try:
            data = client.get_json(url)
        except BudgetExceeded:
            client.budget.hit = True
            break
        items = extract_list(data)
        if not items:
            break
        results.extend(items)
        remaining = limit - len(results)
        if len(items) < per_page or not paginate:
            break
        page += 1
    return results[:limit]


def command_search_api(args: argparse.Namespace) -> Dict[str, Any]:
    cache = Cache(Path(args.cache_dir), args.cache_ttl)
    budget = RequestBudget(args.max_requests)
    limiter = RateLimiter(args.sleep_ms)
    client = DrupalOrgClient(build_user_agent(args.user_agent), cache, budget, limiter)

    project_nid = get_project_nid(client, args.project)
    if project_nid is None:
        raise DrupalOrgError(f"Project not found: {args.project}")

    status, priority, category = parse_search_filters(args)

    limit = max(1, args.limit)
    results: List[Dict[str, Any]] = []
    page = 0

    while len(results) < limit:
        per_page = min(MAX_PAGE_LIMIT, limit - len(results))
        params: Dict[str, Any] = {
            "type": "project_issue",
            "field_project": project_nid,
            "limit": per_page,
            "page": page,
            "sort": args.sort,
            "direction": args.direction,
        }
        if status is not None:
            params["field_issue_status"] = status
        if priority is not None:
            params["field_issue_priority"] = priority
        if category is not None:
            params["field_issue_category"] = category
        if args.version:
            params["field_issue_version"] = args.version
        if args.component:
            params["field_issue_component"] = args.component
        if args.tag_tid:
            params["taxonomy_vocabulary_9"] = args.tag_tid

        try:
            data = client.get_json(build_url("node.json", params))
        except BudgetExceeded:
            budget.hit = True
            break
        items = extract_list(data)
        if not items:
            break
        results.extend(items)
        if len(items) < per_page:
            break
        page += 1

    results = results[:limit]
    formatted = [search_issue_summary(item) for item in results]

    payload = {
        "project": {"machine_name": args.project, "nid": str(project_nid)},
        "query": {
            "status": status,
            "priority": priority,
            "category": category,
            "version": args.version,
            "component": args.component,
            "tag_tid": args.tag_tid,
            "sort": args.sort,
            "direction": args.direction,
        },
        "count": len(formatted),
        "limit": limit,
        "results": formatted,
        "truncated": {
            "limit": len(formatted) >= limit,
            "request_budget_hit": budget.hit,
        },
        "source": {"backend": "api", "tool": "api-d7"},
    }
    return payload


def search_issue_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    nid = str(node.get("nid")) if node.get("nid") is not None else None
    url = node.get("url") or (f"https://www.drupal.org/node/{nid}" if nid else None)
    created_ts = to_int(node.get("created"))
    updated_ts = to_int(node.get("changed"))
    status_code = to_int(node.get("field_issue_status"))
    priority_code = to_int(node.get("field_issue_priority"))
    category_code = to_int(node.get("field_issue_category"))
    return {
        "nid": nid,
        "title": node.get("title"),
        "url": url,
        "created_ts": created_ts,
        "created": format_ts(created_ts),
        "updated_ts": updated_ts,
        "updated": format_ts(updated_ts),
        "status": build_status(status_code, ISSUE_STATUS),
        "priority": build_status(priority_code, ISSUE_PRIORITY),
        "category": build_status(category_code, ISSUE_CATEGORY),
    }


def get_project_nid(client: DrupalOrgClient, machine_name: str) -> Optional[int]:
    params = {"field_project_machine_name": machine_name, "limit": 1}
    data = client.get_json(build_url("node.json", params))
    items = extract_list(data)
    if items:
        return to_int(items[0].get("nid"))
    return None


def parse_files_limit(value: str) -> Optional[int]:
    if value == "all":
        return None
    if value == "0":
        return 0
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("files-limit must be an integer, 0, or 'all'") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("files-limit must be >= 0")
    return parsed


def parse_search_filters(args: argparse.Namespace) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    status = parse_alias(args.status, STATUS_ALIASES)
    priority = parse_alias(args.priority, PRIORITY_ALIASES)
    category = parse_alias(args.category, CATEGORY_ALIASES)

    if args.status and status is None:
        raise DrupalOrgError(f"Unknown status alias: {args.status}")
    if args.priority and priority is None:
        raise DrupalOrgError(f"Unknown priority alias: {args.priority}")
    if args.category and category is None:
        raise DrupalOrgError(f"Unknown category alias: {args.category}")
    return status, priority, category


def comments_limit_for_issue(args: argparse.Namespace) -> int:
    comments_limit = args.comments
    if comments_limit is None:
        comments_limit = 10 if args.mode == "summary" else 50
    return max(0, comments_limit)


def resolve_drupalorg_bin(binary: str) -> Optional[str]:
    if not binary:
        return None
    parts = shlex.split(binary)
    if not parts:
        return None

    first = parts[0]
    has_separator = os.path.sep in first or (os.path.altsep and os.path.altsep in first)
    if has_separator and os.path.isfile(first) and os.access(first, os.X_OK):
        return binary
    if shutil.which(first):
        return binary

    probe = subprocess.run(
        ["bash", "-lc", BASH_ALIAS_PREFIX + f"type {shlex.quote(first)}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return binary
    return None


def run_drupalorg_json(drupalorg_bin: str, command: List[str]) -> Any:
    base = shlex.split(drupalorg_bin)
    if not base:
        raise DrupalOrgError("drupalorg command is empty")
    shell_cmd = " ".join(shlex.quote(part) for part in (base + command))
    process = subprocess.run(
        ["bash", "-lc", BASH_ALIAS_PREFIX + shell_cmd],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        stderr = process.stderr.strip()
        stdout = process.stdout.strip()
        detail = stderr or stdout or f"exit code {process.returncode}"
        raise DrupalOrgError(f"drupalorg command failed ({' '.join(command)}): {detail}")

    output = process.stdout.strip()
    if not output:
        raise DrupalOrgError(f"drupalorg command returned empty output ({' '.join(command)})")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DrupalOrgError(f"drupalorg returned invalid JSON ({' '.join(command)})") from exc


def drupalorg_issue_compatibility_reasons(args: argparse.Namespace) -> List[str]:
    reasons: List[str] = []
    if args.resolve_tags != "none":
        reasons.append("--resolve-tags must be 'none'")
    if args.tag_map:
        reasons.append("--tag-map is only supported with the api backend")
    if args.files_limit != 0:
        reasons.append("--files-limit must be 0")
    if args.related_mrs:
        reasons.append("--related-mrs is only supported with the api backend")
    if args.extra_credit:
        reasons.append("--extra-credit is only supported with the api backend")
    return reasons


def drupalorg_search_issue_type(status_code: Optional[int]) -> Optional[str]:
    if status_code is None:
        return "all"
    if status_code == 14:
        return "rtbc"
    if status_code == 8:
        return "review"
    return None


def drupalorg_search_compatibility_reasons(args: argparse.Namespace) -> List[str]:
    status, priority, category = parse_search_filters(args)
    reasons: List[str] = []
    if priority is not None:
        reasons.append("--priority is only supported with the api backend")
    if category is not None:
        reasons.append("--category is only supported with the api backend")
    if args.version:
        reasons.append("--version is only supported with the api backend")
    if args.component:
        reasons.append("--component is only supported with the api backend")
    if args.tag_tid:
        reasons.append("--tag-tid is only supported with the api backend")
    if args.sort != "changed":
        reasons.append("--sort must remain 'changed'")
    if args.direction != "DESC":
        reasons.append("--direction must remain 'DESC'")
    if drupalorg_search_issue_type(status) is None:
        reasons.append("--status only supports 'needs review' or 'rtbc' with drupalorg backend")
    return reasons


def choose_issue_backend(args: argparse.Namespace) -> Tuple[str, Optional[str], Optional[str]]:
    if args.backend == "api":
        return "api", None, None

    drupalorg_bin = resolve_drupalorg_bin(args.drupalorg_bin)
    reasons = drupalorg_issue_compatibility_reasons(args)

    if args.backend == "drupalorg":
        if drupalorg_bin is None:
            raise DrupalOrgError(f"drupalorg backend requested but binary not found: {args.drupalorg_bin}")
        if reasons:
            raise DrupalOrgError("drupalorg backend incompatible with selected options: " + "; ".join(reasons))
        return "drupalorg", drupalorg_bin, None

    if drupalorg_bin and not reasons:
        return "drupalorg", drupalorg_bin, None
    if drupalorg_bin and reasons:
        return "api", None, "; ".join(reasons)
    return "api", None, "drupalorg binary not found"


def choose_search_backend(args: argparse.Namespace) -> Tuple[str, Optional[str], Optional[str]]:
    if args.backend == "api":
        return "api", None, None

    drupalorg_bin = resolve_drupalorg_bin(args.drupalorg_bin)
    reasons = drupalorg_search_compatibility_reasons(args)

    if args.backend == "drupalorg":
        if drupalorg_bin is None:
            raise DrupalOrgError(f"drupalorg backend requested but binary not found: {args.drupalorg_bin}")
        if reasons:
            raise DrupalOrgError("drupalorg backend incompatible with selected options: " + "; ".join(reasons))
        return "drupalorg", drupalorg_bin, None

    if drupalorg_bin and not reasons:
        return "drupalorg", drupalorg_bin, None
    if drupalorg_bin and reasons:
        return "api", None, "; ".join(reasons)
    return "api", None, "drupalorg binary not found"


def drupalorg_comment_summary(comment: Dict[str, Any]) -> Dict[str, Any]:
    created_ts = to_int(comment.get("created"))
    body_html = comment.get("body_value")
    return {
        "cid": str(comment.get("cid")) if comment.get("cid") is not None else None,
        "created_ts": created_ts,
        "created": format_ts(created_ts),
        "author_uid": comment.get("author_id"),
        "author_name": comment.get("author_name"),
        "body_markdown": html_to_markdown(body_html),
    }


def command_issue_drupalorg(args: argparse.Namespace, drupalorg_bin: str) -> Dict[str, Any]:
    nid = parse_nid(args.nid_or_url)
    comments_limit = comments_limit_for_issue(args)
    command = ["issue:show", nid, "--format=json"]
    if comments_limit > 0:
        command.append("--with-comments")

    payload = run_drupalorg_json(drupalorg_bin, command)
    if not isinstance(payload, dict):
        raise DrupalOrgError("Unexpected drupalorg issue response")

    all_comments = [drupalorg_comment_summary(c) for c in ensure_list(payload.get("comments")) if isinstance(c, dict)]
    all_comments.sort(key=lambda item: ((item.get("created_ts") or 0), to_int(item.get("cid")) or 0))
    if args.comment_direction == "DESC":
        all_comments.reverse()
    selected_comments = all_comments[:comments_limit] if comments_limit > 0 else []

    created_ts = to_int(payload.get("created"))
    updated_ts = to_int(payload.get("changed"))
    status_code = to_int(payload.get("field_issue_status"))
    priority_code = to_int(payload.get("field_issue_priority"))
    category_code = to_int(payload.get("field_issue_category"))
    comment_count = len(all_comments) if comments_limit > 0 else 0
    last_comment_ts = max((c.get("created_ts") or 0 for c in all_comments), default=0) or None

    return {
        "nid": str(payload.get("nid")) if payload.get("nid") is not None else nid,
        "title": payload.get("title"),
        "url": f"https://www.drupal.org/node/{nid}",
        "created_ts": created_ts,
        "created": format_ts(created_ts),
        "updated_ts": updated_ts,
        "updated": format_ts(updated_ts),
        "status": build_status(status_code, ISSUE_STATUS),
        "priority": build_status(priority_code, ISSUE_PRIORITY),
        "category": build_status(category_code, ISSUE_CATEGORY),
        "version": payload.get("field_issue_version"),
        "component": payload.get("field_issue_component"),
        "tags": [],
        "related_mrs": [],
        "comment_count": comment_count,
        "last_comment_ts": last_comment_ts,
        "body_markdown": html_to_markdown(payload.get("body_value")),
        "latest_comments": selected_comments,
        "files": [],
        "truncated": {
            "comments": len(selected_comments) < len(all_comments),
            "files": False,
            "tag_resolution": False,
            "request_budget_hit": False,
        },
        "source": {"backend": "drupalorg", "tool": "drupalorg-cli", "command": "issue:show"},
    }


def command_search_drupalorg(args: argparse.Namespace, drupalorg_bin: str) -> Dict[str, Any]:
    status, priority, category = parse_search_filters(args)
    issue_type = drupalorg_search_issue_type(status)
    if issue_type is None:
        raise DrupalOrgError("drupalorg search backend only supports status 'needs review' or 'rtbc'")

    command = [
        "project:issues",
        args.project,
        issue_type,
        "--limit",
        str(max(1, args.limit)),
        "--format=json",
    ]
    payload = run_drupalorg_json(drupalorg_bin, command)
    if not isinstance(payload, dict):
        raise DrupalOrgError("Unexpected drupalorg project:issues response")

    results = []
    for issue in ensure_list(payload.get("issues")):
        if not isinstance(issue, dict):
            continue
        status_code = to_int(issue.get("field_issue_status"))
        nid = str(issue.get("nid")) if issue.get("nid") is not None else None
        results.append(
            {
                "nid": nid,
                "title": issue.get("title"),
                "url": f"https://www.drupal.org/node/{nid}" if nid else None,
                "created_ts": None,
                "created": None,
                "updated_ts": None,
                "updated": None,
                "status": build_status(status_code, ISSUE_STATUS),
                "priority": build_status(None, ISSUE_PRIORITY),
                "category": build_status(None, ISSUE_CATEGORY),
            }
        )

    return {
        "project": {"machine_name": args.project, "nid": None},
        "query": {
            "status": status,
            "priority": priority,
            "category": category,
            "version": args.version,
            "component": args.component,
            "tag_tid": args.tag_tid,
            "sort": args.sort,
            "direction": args.direction,
        },
        "count": len(results),
        "limit": max(1, args.limit),
        "results": results[: max(1, args.limit)],
        "truncated": {
            "limit": len(results) >= max(1, args.limit),
            "request_budget_hit": False,
        },
        "source": {"backend": "drupalorg", "tool": "drupalorg-cli", "command": "project:issues"},
    }


def command_issue(args: argparse.Namespace) -> Dict[str, Any]:
    backend, drupalorg_bin, fallback_reason = choose_issue_backend(args)
    if backend == "drupalorg":
        try:
            return command_issue_drupalorg(args, drupalorg_bin or args.drupalorg_bin)
        except DrupalOrgError:
            if args.backend == "drupalorg":
                raise
            payload = command_issue_api(args)
            payload.setdefault("source", {})
            payload["source"]["auto_fallback_reason"] = "drupalorg execution failed; fell back to api backend"
            return payload

    payload = command_issue_api(args)
    if fallback_reason:
        payload.setdefault("source", {})
        payload["source"]["auto_fallback_reason"] = fallback_reason
    return payload


def command_search(args: argparse.Namespace) -> Dict[str, Any]:
    backend, drupalorg_bin, fallback_reason = choose_search_backend(args)
    if backend == "drupalorg":
        try:
            return command_search_drupalorg(args, drupalorg_bin or args.drupalorg_bin)
        except DrupalOrgError:
            if args.backend == "drupalorg":
                raise
            payload = command_search_api(args)
            payload.setdefault("source", {})
            payload["source"]["auto_fallback_reason"] = "drupalorg execution failed; fell back to api backend"
            return payload

    payload = command_search_api(args)
    if fallback_reason:
        payload.setdefault("source", {})
        payload["source"]["auto_fallback_reason"] = fallback_reason
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drupal.org issue queue helper")
    parser.add_argument(
        "--backend",
        choices=["auto", "api", "drupalorg"],
        default="auto",
        help="Data source backend: auto (prefer drupalorg when compatible), api, or drupalorg",
    )
    parser.add_argument(
        "--drupalorg-bin",
        default="drupalorg",
        help="drupalorg command or executable path (aliases supported via login shell)",
    )
    parser.add_argument("--user-agent", help="Custom User-Agent string")
    parser.add_argument(
        "--cache-dir",
        default=str(Path.home() / ".cache" / "drupal-issue-queue"),
        help="Cache directory",
    )
    parser.add_argument("--cache-ttl", type=int, default=3600, help="Cache TTL in seconds")
    parser.add_argument("--sleep-ms", type=int, default=200, help="Sleep milliseconds between requests")
    parser.add_argument("--max-requests", type=int, default=30, help="Request budget")
    parser.add_argument("--format", choices=["json", "md"], default="json", help="Output format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    issue_parser = subparsers.add_parser("issue", help="Fetch and summarize a single issue")
    issue_parser.add_argument("nid_or_url", help="Issue nid or URL")
    issue_parser.add_argument("--mode", choices=["summary", "full"], default="summary")
    issue_parser.add_argument("--comments", type=int, help="Max comments to fetch")
    issue_parser.add_argument(
        "--comment-direction",
        choices=["ASC", "DESC"],
        default="DESC",
        help="Comment sort direction",
    )
    issue_parser.add_argument(
        "--files-limit",
        type=parse_files_limit,
        default=10,
        help="Number of file metadata lookups (0, integer, or 'all')",
    )
    issue_parser.add_argument(
        "--resolve-tags",
        choices=["none", "api", "static"],
        default="api",
        help="Tag resolution mode",
    )
    issue_parser.add_argument("--tag-map", help="Path to JSON/YAML tag map for static resolution")
    issue_parser.add_argument("--related-mrs", action="store_true", help="Include related MRs")
    issue_parser.add_argument("--extra-credit", action="store_true", help="Include credit metadata")

    search_parser = subparsers.add_parser("search", help="Search issues for a project")
    search_parser.add_argument("--project", required=True, help="Project machine name")
    search_parser.add_argument("--status", help="Issue status alias or code")
    search_parser.add_argument("--priority", help="Issue priority alias or code")
    search_parser.add_argument("--category", help="Issue category alias or code")
    search_parser.add_argument("--version", help="Issue version")
    search_parser.add_argument("--component", help="Issue component")
    search_parser.add_argument("--tag-tid", help="Tag taxonomy term id")
    search_parser.add_argument("--limit", type=int, default=20, help="Max results")
    search_parser.add_argument(
        "--sort",
        choices=["changed", "created", "nid"],
        default="changed",
        help="Sort field",
    )
    search_parser.add_argument(
        "--direction",
        choices=["ASC", "DESC"],
        default="DESC",
        help="Sort direction",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "issue":
            payload = command_issue(args)
            output = issue_to_markdown(payload) if args.format == "md" else json.dumps(payload, indent=2)
        elif args.command == "search":
            payload = command_search(args)
            output = search_to_markdown(payload) if args.format == "md" else json.dumps(payload, indent=2)
        else:
            raise DrupalOrgError("Unknown command")
    except BudgetExceeded as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except DrupalOrgError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
