# letta-skills

Personal collection of reusable [Letta Code](https://github.com/letta-ai/letta-code) skills — self-contained packages of instructions and scripts that extend an agent with specialized, on-demand capabilities.

Each skill is a top-level folder containing a `SKILL.md` (frontmatter + instructions) plus any bundled `scripts/`, `references/`, or `assets/`. An agent loads a skill's full instructions only when its `name`/`description` match the task at hand.

## Installing a skill

Point an agent at this repo (or a specific subfolder) using the `acquiring-skills` skill, or copy a skill folder directly into the agent's `skills/` directory.

## Skills

| Skill | Description |
|---|---|
| [browsing-with-stagehand](browsing-with-stagehand) | Runs bounded, disposable browser-agent tasks (search, navigate, extract) on real websites using Stagehand and a headless local Chrome profile. |
| [managing-calendar](managing-calendar) | Reads and creates events in Calendar.app on macOS through EventKit and Swift scripts. |
| [managing-email](managing-email) | Searches, reads, downloads attachments from, and safely manages headless email accounts over IMAP or Microsoft Graph. Creates reviewable drafts but never sends mail. |
| [managing-mac-displays](managing-mac-displays) | Inspects, snapshots, parks, unparks, disconnects, and restores physical Mac display layouts with displayplacer while preserving a known recovery path. |
| [managing-moneymoney](managing-moneymoney) | Reads account, category, and transaction data from MoneyMoney on macOS through its read-only AppleScript export API. |
| [managing-notes](managing-notes) | Creates, reads, searches, and organizes notes in Notes.app on macOS through AppleScript. |
| [managing-paperless-ngx](managing-paperless-ngx) | Searches, reads, uploads, downloads, and safely updates documents and metadata in Paperless-ngx through its REST API. |
| [managing-things3](managing-things3) | Reads and manages to-dos and projects in Things3 on macOS through AppleScript. |
| [organizing-downloads](organizing-downloads) | Inspects and safely organizes loose files in Downloads (or another folder) into deterministic type-based subfolders. |
| [running-claude-print](running-claude-print) | Runs bounded Claude Code print-mode analyses in a chosen project directory, delegating review, investigation, or implementation to `claude -p`. |
| [spotlight-search](spotlight-search) | Fast indexed file and document search using macOS Spotlight (mdfind). |

## Conventions

- Skill folder names use gerund form (`managing-x`, `organizing-y`) and match the `name` field in `SKILL.md`.
- No credentials or account configuration are stored in this repo — skills read connection details from the environment or agent-local secrets at runtime.
- Keep `SKILL.md` lean; move detailed references and reusable scripts into `references/`, `scripts/`, or `lib/` within each skill.
- macOS automation skills may include a `lib/` directory with shared helper scripts.

## License

MIT
