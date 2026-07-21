---
name: managing-things3
description: Reads and manages to-dos and projects in Things3 on macOS through AppleScript. Use when the user asks about Things3, their to-do list, tasks, projects, or task management.
---

# Managing Things3

Use the AppleScript scripts in `scripts/` to read and manage to-dos, projects, and tags in Things3. These scripts require Things3 Automation permissions in System Settings > Privacy & Security > Automation.

## View Today and Inbox

```bash
bash scripts/show-today.sh
bash scripts/show-inbox.sh
```

Shows all to-dos in the Today list or Inbox with project, tags, due dates, and notes preview.

## List to-dos with filters

```bash
# List open to-dos
bash scripts/list-todos.sh --status open --limit 50

# Filter by built-in list
bash scripts/list-todos.sh --list "Today" --status open
bash scripts/list-todos.sh --list "Upcoming" --status open
bash scripts/list-todos.sh --list "Logbook" --status completed

# Filter by project
bash scripts/list-todos.sh --project "Website Redesign" --status open

# Filter by tag
bash scripts/list-todos.sh --tag "urgent" --status open

# Combine filters
bash scripts/list-todos.sh --project "Website Redesign" --tag "urgent" --status open
```

Built-in lists: `Inbox`, `Today`, `Upcoming`, `Anytime`, `Someday`, `Logbook`, `Trash`.

## Search to-dos

```bash
bash scripts/search-todos.sh --query "meeting"
bash scripts/search-todos.sh --query "client" --include-completed
```

Searches to-dos by matching text in the name or notes fields.

## Create to-dos

```bash
# Basic to-do
bash scripts/create-todo.sh --name "Call John"

# To-do with notes
bash scripts/create-todo.sh \
  --name "Review PR" \
  --notes "Check the authentication logic"

# To-do with due date
bash scripts/create-todo.sh \
  --name "Submit report" \
  --due "2026-07-25"

# To-do with tags
bash scripts/create-todo.sh \
  --name "Fix bug" \
  --tags "urgent,bug"

# To-do in project
bash scripts/create-todo.sh \
  --name "Design homepage" \
  --project "Website Redesign"

# To-do with schedule (when)
bash scripts/create-todo.sh \
  --name "Prepare slides" \
  --schedule "2026-07-22"

# To-do in built-in list
bash scripts/create-todo.sh \
  --name "Quick task" \
  --list "Today"

# Complete to-do with all options
bash scripts/create-todo.sh \
  --name "Quarterly review" \
  --notes "Prepare Q3 performance metrics" \
  --due "2026-07-30" \
  --tags "work,important" \
  --project "Performance Review" \
  --schedule "2026-07-28"
```

## Complete to-dos

```bash
bash scripts/complete-todo.sh --id "to-do-id"
```

Marks a to-do as completed. Use the ID shown in list/search output.

## Update to-dos

```bash
# Update name
bash scripts/update-todo.sh --id "to-do-id" --set-name "New title"

# Update notes
bash scripts/update-todo.sh --id "to-do-id" --set-notes "Updated notes"

# Update due date
bash scripts/update-todo.sh --id "to-do-id" --set-due "2026-08-01"

# Update schedule (when)
bash scripts/update-todo.sh --id "to-do-id" --set-schedule "2026-07-25"

# Cancel a to-do
bash scripts/update-todo.sh --id "to-do-id" --set-status canceled

# Clear due date
bash scripts/update-todo.sh --id "to-do-id" --clear-due
```

## Move to-dos

```bash
bash scripts/move-todo.sh --id "to-do-id" --to-list "Today"
bash scripts/move-todo.sh --id "to-do-id" --to-project "New Project"
```

Moves a to-do to a different built-in list (Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash) or project.

## Manage projects

```bash
# List projects
bash scripts/list-projects.sh

# Create project
bash scripts/create-project.sh --name "New Project" --area "Work"

# Update project
bash scripts/update-project.sh --id "project-id" --set-name "Updated title" --set-notes "Project notes"
```

## List tags

```bash
bash scripts/list-tags.sh
```

Lists all available tags in Things3.

## Permissions

The first time these scripts run, macOS will prompt for Things3 Automation access. Grant access in System Settings > Privacy & Security > Automation > Things3.

## Notes

- All to-do and project IDs are shown in list/search output
- Due dates use YYYY-MM-DD format
- Schedule values: `today`, `evening`, `tomorrow`, `someday`, `anytime`, or `YYYY-MM-DD`
- Tags are comma-separated for the --tags parameter
- Use the status parameter to filter: `open`, `completed`, `canceled`
- `complete-todo` supports `--dry-run` to preview what would be completed
- `create-todo` can use `--project-id` for more reliable project assignment than `--project` name
- `update-todo` can use `--name` instead of `--id` to find by exact name

## Prerequisites

- Things3 must be installed and running
- macOS Automation permission for Things3 in System Settings > Privacy & Security > Automation