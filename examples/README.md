# Example vault

A 3-note Obsidian-shaped fixture you can run the indexer / reader / health / link-check against in 30 seconds.

## Layout

```
examples/
├── notes/
│   ├── coinbase-japan-analysis.md    # entity analysis
│   ├── japan-stablecoin-regulation.md # market intel
│   └── meowtype-status.md             # personal project
└── README.md                          # this file
```

`vault-index.json` is **not** committed — it's a build artifact, generated below. Committing it would let it drift from the source notes; CI builds it fresh on every run instead.

## 30-second walkthrough

```bash
# 1. Build the index from the notes above
python3 rebuild-vault-index.py \
  --vault examples \
  --output /tmp/example-index.json \
  --scan notes:cc

# 2. Inspect the index
python3 orp_reader.py --index /tmp/example-index.json status
# 3 entries, updated 2026-..., fresh, schema 1.1

# 3. Match a query (English, Japanese, or both)
python3 orp_reader.py --index /tmp/example-index.json match "stablecoin"
# japan-stablecoin-regulation  examples/notes/japan-stablecoin-regulation.md  [matched: stablecoin]

python3 orp_reader.py --index /tmp/example-index.json match "撤退"
# coinbase-japan-analysis  examples/notes/coinbase-japan-analysis.md  [matched: 撤退]

# 4. Validate index health
python3 orp_health.py --index /tmp/example-index.json
# OK: 3 entries, ... KB, 0 failures, 0 warnings

# 5. Check there are no dead wikilinks
python3 orp_link_check.py --vault examples --ignore-orphans
# Live links: ...  Dead links: 0
```

## What each note demonstrates

- **coinbase-japan-analysis.md** — entity analysis with overlapping CJK + Latin aliases. Try matching "Coinbase", "撤退", or "FSA".
- **japan-stablecoin-regulation.md** — market intel with future-dated `last_action`. Mix of `JPYC`, `USDC Japan`, `改正資金決済法` aliases.
- **meowtype-status.md** — personal project with minimal aliases. Shows that bare frontmatter is enough; you don't need a long alias list to be searchable.

## Use as your starter

Copy `notes/*.md` into your own vault, replace the content with yours, keep the frontmatter shape (`title`, `aliases`, `summary_points`, `last_action`, `status`, `author`). Run the indexer against your vault root and you have a working ORP setup.
