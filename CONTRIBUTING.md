# Contributing to Obsidian RAG Protocol 🎉

First things first — **thank you** for being here. Whether you're filing a bug report, suggesting an idea, or writing code, your contribution matters. This project was created by a marketing professional who learned by doing, and we want this to be a welcoming place for everyone — engineers and non-engineers alike.

No contribution is too small. A typo fix, a clearer sentence, a bug report — it all counts.

---

## Quick Links

- **Bug reports** → [Open an issue](https://github.com/wjameswen888/obsidian-rag-protocol/issues)
- **Feature ideas** → [Open an issue](https://github.com/wjameswen888/obsidian-rag-protocol/issues)
- **Questions** → [Open an issue](https://github.com/wjameswen888/obsidian-rag-protocol/issues) (we don't have a Discussion board yet, issues work fine)

---

## Reporting Bugs 🐛

Found something broken? Here's what helps us fix it fastest:

1. **Check if it's already reported** — search existing issues first
2. **Open a new issue** with:
   - What you expected to happen
   - What actually happened
   - The exact command you ran (including all `--vault`, `--output`, `--scan` arguments)
   - Your setup: Python version, OS, vault location (local vs iCloud)
   - The output the script printed (the `✅` line or any error message)

**Wrong vault path?** That's the #1 bug report — and it's not a bug 😄 Double-check your `--vault` path uses the full absolute path.

**Tip:** If the index shows all entries as "changed" on every run, something external (iCloud, git, backup software) is modifying your files. That's not a bug in the script — but we'd still like to hear about it so we can document workarounds.

---

## Suggesting Features 💡

Have an idea? We'd love to hear it. Open an issue and describe:

- **What you're trying to accomplish** (the problem, not just the solution)
- **How you'd imagine it working** (a rough idea is fine)
- **Why it fits the protocol** — this project is intentionally lean. The spec is the source of truth, and new features should align with its design philosophy:
  - Zero external dependencies (Python stdlib only)
  - Human-readable, machine-queryable output
  - Deterministic over clever
  - Curated aliases over auto-generated ones

No need to write a perfect proposal. Even a one-line "it would be cool if..." is a great starting point.

---

## Submitting Changes (Pull Requests) 🛠️

We follow the classic GitHub flow — fork, branch, PR. Here's the step-by-step:

### 1. Fork the repo

Click the **Fork** button on GitHub. Clone your fork locally:

```bash
git clone https://github.com/YOUR-USERNAME/obsidian-rag-protocol.git
cd obsidian-rag-protocol
```

### 2. Create a branch

Give it a descriptive name:

```bash
git checkout -b fix-typo-in-readme
git checkout -b add-cutoff-days-flag
git checkout -b improve-frontmatter-parsing
```

### 3. Make your changes

Edit away! A few notes:

- **The reference implementation is `rebuild-vault-index.py`** — a single-file Python script. Keep it that way. Don't split it into a package.
- **The protocol spec is `OBSIDIAN-RAG-PROTOCOL.md`** — this is the source of truth. Any change to how the protocol works should update the spec first, then the implementation follows.

### 4. Test your changes

There's no formal test suite. To verify things work:

```bash
# Run the script against your vault (or a test vault)
python3 rebuild-vault-index.py \
  --vault /path/to/your/vault \
  --output /tmp/test-vault-index.json \
  --scan wiki/projects hermes-knowledge/

# Check the output is valid JSON
python3 -c "import json; json.load(open('/tmp/test-vault-index.json')); print('✅ Valid JSON')"

# Verify incremental rebuild shows 0 changes when nothing changed
python3 rebuild-vault-index.py \
  --vault /path/to/your/vault \
  --output /tmp/test-vault-index.json \
  --scan wiki/projects hermes-knowledge/
# Should output: ✅ vault-index.json rebuilt: N entries (0 changed)
```

If you changed the indexing logic, also verify:
- Files with `rag_exclude: true` in frontmatter are excluded
- The `updated` date in the output reflects today
- Entry IDs are lowercase, hyphenated (not spaces or underscores)
- Content hashes are correct (run twice — second time should show 0 changes)

### 5. Commit and push

```bash
git add -A
git commit -m "Fix: description of what you changed"
git push origin fix-typo-in-readme
```

Write commit messages that future-you will understand. A sentence is fine.

### 6. Open a Pull Request

Go to your fork on GitHub and click **New Pull Request**. In the description:

- What you changed and why
- How you tested it
- Any gotchas or follow-ups you noticed

That's it! We'll review and merge.

---

## Code Style 📏

Keep it simple — that's the whole point of this project.

- **Python standard library only.** No `pip install`, no `requirements.txt`, no third-party packages. The reference implementation uses `hashlib`, `json`, `re`, `sys`, `argparse`, `pathlib`, `datetime`, and `typing` — that's it.
- **Single file.** The reference implementation is one script (`rebuild-vault-index.py`). Don't break it into modules.
- **Readability over cleverness.** This project is maintained by someone who isn't a software engineer by trade. Clear, obvious code beats elegant one-liners.
- **Docstrings on functions.** A one-line docstring is enough — just tell us what the function does.
- **Type hints on function signatures.** They help readability and catch mistakes.
- **No linter config, no formatter setup.** Use your judgment. If it reads well, it's fine.
- **Frontmatter parsing** should handle:
  - `key: value` (simple)
  - `key: [a, b, c]` (inline list)
  - Multi-line YAML lists
  - Scalar aliases (a string instead of a list → auto-wrap)

---

## The Protocol Spec is the Source of Truth 📜

When in doubt, refer to `OBSIDIAN-RAG-PROTOCOL.md`. It defines:

- The vault index schema (what fields, what types, what they mean)
- The indexing algorithm (scan, exclude, hash, extract)
- Alias resolution priority (frontmatter → curated map → previous run → fallback)
- Auto context injection rules (what triggers a read, how matching works, error handling)
- Bidirectional multi-agent protocol (directory partitioning, collaboration channels)
- Incremental rebuild strategy (when to skip, when to re-extract)

**If the implementation and the spec disagree, the spec wins.** File it as a bug — either the implementation needs fixing, or the spec needs updating.

If you want to change how the protocol works:
1. Update the spec first (`OBSIDIAN-RAG-PROTOCOL.md`)
2. Then update the implementation (`rebuild-vault-index.py`)
3. Then update docs (`README.md`, `INSTALL.md`) if the change affects users

---

## Ways to Contribute Without Writing Code 🤝

This project is for everyone, not just developers. Here are some ways to help:

- **Report bugs** — even "it didn't work for me" is useful
- **Suggest features** — what would make this more useful for your workflow?
- **Improve documentation** — fix typos, clarify confusing steps, add examples
- **Share your setup** — how are you using ORP? What agent? What vault structure? Open an issue and tell us about it
- **Translate** — the README exists in English, 中文, and 日本語. More translations welcome!
- **Test with different vaults** — try it on your own Obsidian vault and report what works and what doesn't

---

## A Note on Tone

This project was built by someone who came to infrastructure work from a non-engineering background. The code is meant to be approachable. The docs are meant to be readable. If something is confusing — in the code, the docs, or this very file — that's a bug in the documentation, and we'd love a fix for it.

Be kind in issues and reviews. Assume good intent. Ask "how can I help?" before "why did you do it this way?"

Welcome aboard. 🚀