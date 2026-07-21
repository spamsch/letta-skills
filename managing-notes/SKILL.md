---
name: managing-notes
description: Creates, reads, searches, and organizes notes in Notes.app on macOS through AppleScript. Use when the user asks about Notes.app, creating notes, searching notes, or organizing notes into folders.
---

# Managing Notes

Use the AppleScript scripts in `scripts/` to create, read, search, and organize notes. These scripts require Notes permissions in System Settings > Privacy & Security > Notes.

## Create notes

```bash
bash scripts/create-note.sh \
  --title "Meeting Notes" \
  --body "Discussion points and action items..."
```

Creates a new note in the default "Notes" folder. Supports plain text and HTML formatting.

**HTML formatting for todo lists:**
```bash
bash scripts/create-note.sh \
  --title "Shopping List" \
  --body "<ul><li>Milk</li><li>Bread</li><li>Eggs</li></ul>" \
  --html
```

**Note in specific folder:**
```bash
bash scripts/create-note.sh \
  --title "Project Plan" \
  --body "Key milestones and deadlines..." \
  --folder "Work"
```

## Search notes

```bash
bash scripts/search-notes.sh --query "project"
bash scripts/search-notes.sh --query "meeting" --folder "Work"
bash scripts/search-notes.sh --query "important" --title-only --limit 10
```

Searches notes by title or content. Use `--title-only` for faster title-only searches, `--show-preview` for content previews, and `--limit` to control result count.

## Read notes

```bash
bash scripts/read-note.sh --title "Meeting Notes"
bash scripts/read-note.sh --title "Project Plan" --folder "Work"
```

Reads the full content of a note by title (supports partial matching).

## List notes

```bash
bash scripts/list-notes.sh
bash scripts/list-notes.sh --folder "Work"
```

Lists all notes or notes in a specific folder.

## Organize folders

```bash
# Create a folder
bash scripts/create-folder.sh --name "Archive"

# List folders
bash scripts/list-folders.sh

# Rename a folder
bash scripts/rename-folder.sh --name "Old Folder" --new-name "New Folder"

# Delete a folder
bash scripts/delete-folder.sh --name "Unwanted Folder"
```

## Move and delete notes

```bash
# Move a note to another folder
bash scripts/move-note.sh \
  --title "Old Note" \
  --to "Work"

# Move a note with source folder specified
bash scripts/move-note.sh \
  --title "Old Note" \
  --from "Notes" \
  --to "Archive"

# Delete a note
bash scripts/delete-note.sh --title "Unwanted Note"
```

## Export notes

```bash
bash scripts/export-note.sh \
  --name "Important Note" \
  --output /tmp/note.txt
```

Exports a note's content to a text file. Can also export all notes from a folder:

```bash
bash scripts/export-note.sh \
  --folder "Work" \
  --output-dir /tmp/work-notes \
  --format html
```

## HTML formatting

Notes.app uses HTML for rich text formatting. Use `--html` flag when creating formatted notes:

- Bullet lists: `<ul><li>Item 1</li><li>Item 2</li></ul>`
- Strikethrough (completed items): `<strike>Completed item</strike>`
- Bold: `<strong>Bold text</strong>`
- Italic: `<em>Italic text</em>`

## Permissions

The first time these scripts run, macOS will prompt for Notes access. Grant access in System Settings > Privacy & Security > Notes.

## Additional options

- `create-note` supports `--body-file` to read note body from a file (useful for large content)
- `create-folder` supports `--parent` to create nested folders
- `list-notes` supports `--recent`, `--with-attachments`, `--limit`, and `--show-folders` options