---
name: managing-moneymoney
description: Reads account, category, and transaction data from MoneyMoney on macOS through its read-only AppleScript export API. Use when the user asks about MoneyMoney, family finances, bank balances, spending, transactions, categories, budget analysis, or a MoneyMoney data export.
---

# Reading MoneyMoney data

Use only the export commands. Never invoke MoneyMoney commands that create transfers, direct debits, transactions, or change transaction metadata.

## Workflow

1. Confirm the requested scope: accounts/categories, date range, and any account or category filter. For a vague finance question, start with the narrowest relevant period and summarize rather than dumping records.
2. Check that MoneyMoney is installed, has been opened, and its database is unlocked. macOS may ask the calling app to authorize Automation access.
3. Run `scripts/export_moneymoney.py`. Prefer `--output /tmp/moneymoney.json` for transaction exports, then analyze that file locally and remove it afterward. Do not preserve raw exports unless the user explicitly asks.
4. Report the requested aggregate or finding. Treat account numbers, IBANs, merchant text, purposes, and transaction records as sensitive; show only the minimum needed.

## Commands

```bash
# List accounts or categories
python3 scripts/export_moneymoney.py accounts
python3 scripts/export_moneymoney.py categories

# Export only the relevant records to a temporary local file
python3 scripts/export_moneymoney.py transactions \
  --from 2026-07-01 --to 2026-07-31 \
  --account 'Household checking' \
  --output /tmp/moneymoney-july.json
```

`--account` accepts an account UUID, IBAN, account number, account name, or account-group name. `--category` accepts a category UUID, name, or a backslash-delimited nested path. The script returns JSON converted from MoneyMoney's plist export.

For command syntax, filters, expected privacy behavior, and recovery guidance, read [references/apple-script-api.md](references/apple-script-api.md).
