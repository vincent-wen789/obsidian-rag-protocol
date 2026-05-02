# Example Output

This directory contains example files that demonstrate the Obsidian RAG Protocol in action.

## What's here

```
examples/
├── vault-index.json              # Example index output (3 entries)
├── notes/
│   └── coinbase-japan-analysis.md # Example Obsidian note with frontmatter
└── README.md                      # This file
```

## How to read these

- **vault-index.json** — This is what `rebuild-vault-index.py` produces. Each entry has a `_content_hash` (SHA256), extracted frontmatter (`aliases`, `summary_points`, etc.), and metadata. An agent reads this file once per session to know what's in the vault.

- **coinbase-japan-analysis.md** — An Obsidian note with YAML frontmatter. The indexer reads the frontmatter to populate `vault-index.json`. Notice the `aliases` field: these are the keywords that trigger fuzzy matching when an agent searches the index.

- **Agent matching flow**: Say an agent reads the index and the user asks "Any news on Coinbase?" → The agent scans `aliases` arrays → finds "Coinbase" in entry 0 → reads `wiki/career/company-research.md` → answers with context.

## Try it yourself

1. Copy `vault-index.json` somewhere your agent can read it
2. Add a system prompt rule: "Before answering non-trivial questions, read vault-index.json"
3. Ask your agent a question that matches one of the example aliases
