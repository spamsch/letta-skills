# MoneyMoney read-only export API

MoneyMoney's scripting dictionary exposes three read-only export commands used by this skill:

| Command | Result |
| --- | --- |
| `export accounts` | XML property list of accounts, balances, ownership, hierarchy, and identifiers. |
| `export categories` | XML property list of categories, UUIDs, hierarchy, and built-in budget data. |
| `export transactions ... as "plist"` | XML property list of transactions. |

For transaction exports, `from date` is required. `to date`, `from account`, and `from category` are optional. Dates are ISO `YYYY-MM-DD`. Account references may be a UUID, IBAN, account number, account name, or account-group name. Category references may be a UUID, a category name, or a nested path separated with backslashes.

## Safety boundary

The API also exposes transfer, direct-debit, transaction creation, and transaction-editing commands. Do not use them. This skill is strictly for reading data.

Do not send financial exports to third-party services, commit them, or retain them beyond the requested analysis without explicit approval. Keep raw results in `/tmp` where possible and delete them after use.

## Failures

- **Application not running / database locked:** Open MoneyMoney and unlock its database, then retry.
- **Automation denied:** In macOS System Settings, allow the invoking terminal or application under Privacy & Security → Automation to control MoneyMoney.
- **No matching records:** Verify the date boundary and account/category spelling. Run the unfiltered export only if necessary.
- **Export parsing failure:** Preserve neither the malformed output nor its data. Report the failure and inspect MoneyMoney's current scripting dictionary with `sdef /Applications/MoneyMoney.app`.
