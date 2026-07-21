---
name: spotlight-search
description: Fast indexed file and document search using macOS Spotlight (mdfind). Use when the user asks to find files, search documents, locate recently used files, or search by metadata like sender, recipient, or content type.
---

# Spotlight Search

Use the `scripts/search.sh` script for fast indexed search across files and documents using macOS Spotlight. Much faster than AppleScript iteration for email search and file discovery.

**Important:** Mail.app inbox emails are NOT searchable via mdfind. Use the `managing-email` skill for Mail.app inbox search. This tool only finds `.eml` files that have been saved to disk.

## Basic file search

```bash
bash scripts/search.sh --query "project proposal"
bash scripts/search.sh --name "report.pdf"
bash scripts/search.sh --body "quarterly results"
```

Searches by file name, content, or free text across the Spotlight index.

## Search by content type

```bash
bash scripts/search.sh --type pdf --query "contract"
bash scripts/search.sh --type image --name "vacation"
bash scripts/search.sh --type document --query "meeting notes"
bash scripts/search.sh --type spreadsheet --name "budget"
bash scripts/search.sh --type presentation --query "slides"
```

Filter by content type: `email`, `pdf`, `image`, `document`, `presentation`, `spreadsheet`.

## Find recently used files

```bash
bash scripts/search.sh --last-used --days 1 --exclude-apps
bash scripts/search.sh --last-used --days 7 --query "project"
```

Use `--last-used` to search by last-opened date instead of modification date. Combined with `--exclude-apps`, this answers "what did I work on recently" by showing only documents/files, not applications.

## Email search (disk files only)

```bash
bash scripts/search.sh --type email --from "john@example.com"
bash scripts/search.sh --type email --subject "invoice"
bash scripts/search.sh --type email --to "team@company.com" --days 30
```

Searches `.eml` files on disk by sender, recipient, subject, or content. **Does NOT search Mail.app inbox** — that requires Core Spotlight access which is not available to external tools.

## Combined filters

```bash
# PDF files modified in last 7 days
bash scripts/search.sh --type pdf --days 7

# Recent documents with "contract" in content
bash scripts/search.sh --last-used --days 3 --query "contract" --exclude-apps

# Emails from specific sender with attachment
bash scripts/search.sh --type email --from "client@" --has-attachments

# Files in specific directory
bash scripts/search.sh --query "project" --dir ~/Documents/Work
```

## Limit results

```bash
bash scripts/search.sh --query "meeting" --limit 50
```

Use `--limit` to control the number of results (default: 20).

## Email status filters

```bash
bash scripts/search.sh --type email --unread
bash scripts/search.sh --type email --flagged
```

Filters `.eml` files by read status or flagged status (requires Full Disk Access for mail metadata).

## Full Disk Access

For email metadata (sender, recipient, subject, read status, flagged status), the calling app may need Full Disk Access in System Settings > Privacy & Security > Full Disk Access.

## Performance notes

- mdfind uses the Spotlight index and is very fast for large datasets
- mdfind does NOT support the `!=` operator — use post-processing (grep -v) to exclude results
- macOS BSD `awk` does not support 3-argument `match()` — use `$1` for field extraction
- `.eml` files on disk have content type `com.apple.mail.email` (not `.emlx`)