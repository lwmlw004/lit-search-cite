# Research Knowledge Network Incremental Workflow

This workflow updates an existing Obsidian Research Knowledge Network from a
new local `lit-search-cite` capture batch. It is offline-first and read-only by
default for the target vault.

## Goals

The repeatable path is:

1. New capture batch.
2. Inventory current vault and capture records.
3. Identify new, update, no-op, duplicate, conflict, and version-pair cases.
4. Generate a Codex analysis queue.
5. Build an isolated preview vault and diff.
6. Verify DOI uniqueness, YAML, wikilinks, `.obsidian`, PDF-copy status, and
   generated structure.
7. Apply only after human review and explicit CLI authorization.
8. Verify idempotency and write a batch report.

The workflow does not read Zotero sqlite, does not start Zotero, does not
access the network, does not use OCR, and does not copy PDFs into Obsidian.

## Stages

### inventory

Reads:

- `captured.json` from the new capture directory.
- `literature/*.md` from the target vault.
- An optional current Research Knowledge Network runtime.

Writes only runtime files under `--out`.

### prepare

Classifies each incoming article:

- `new`: DOI is not present in the current vault literature inventory.
- `update`: DOI is present but the note lacks the Codex managed analysis block.
- `noop`: DOI is present and already has the managed analysis block.
- `duplicate_in_capture`: DOI appears more than once in the new capture.
- `conflict_missing_doi`: no DOI is available.
- `conflict_duplicate_vault_notes`: the same DOI maps to multiple vault notes.

It also detects version pairs by normalized title across incoming capture items
and, when supplied, the current runtime.

### preview

Creates an isolated preview vault under `--out/preview_vault`, copies only the
target files needed for comparison, creates metadata stubs for new articles,
and runs the Research Knowledge Network writer against that preview copy.
On Windows, when `--out/preview_vault` would create paths near the legacy
260-character limit, the script automatically places the isolated preview vault
under the shorter ignored workspace `evals/workspace/rni/<timestamp>` and
records that path in `preview_diff.json`.

The formal vault is never written during preview.

### verify

Checks the preview output:

- each capture DOI has exactly one literature note;
- generated wikilinks resolve to notes in the preview vault;
- generated notes have YAML frontmatter;
- `.obsidian` exists;
- PDF copy count is zero.

### apply

`apply` is disabled unless both are true:

- `--stage apply`
- `--allow-apply`

It also requires `--obsidian-importer`, the path to
`obsidian_vault_mcp.py`. The apply path backs up target files, runs
`import-capture --no-copy-pdfs`, and then writes the Research Knowledge Network
managed blocks and nodes. Do not run apply until the preview package has been
reviewed.

## Example Preview

```powershell
python scripts\research-network-incremental.py `
  --capture-dir references\captured\20260713_100728 `
  --workflow-dir references\workflows\20260713_100712 `
  --current-runtime references\workflows\20260713_100712\research_knowledge_network\20260718_formal_deploy `
  --vault "C:\Users\you\Documents\Obsidian Vault" `
  --out references\workflows\20260713_100712\research_knowledge_network\incremental_noop_preview `
  --stage preview
```

## Output Files

- `inventory.json`
- `prepare_plan.json`
- `analysis_queue.json`
- `preview_diff.json`
- `verify_report.json`
- `batch_report.md`
- `summary.json`

These are runtime artifacts. They should not be committed.

## Human Review Checklist

Before apply:

- `conflict_count` is zero.
- every DOI in `verify_report.json` has exactly one match.
- `broken_wikilinks_count` is zero.
- `yaml_missing_count` is zero.
- `pdfs_copied` is zero unless the user explicitly changed policy.
- preview changed files are expected.
- version pairs are intentionally folded, not treated as independent evidence.
- the target vault path is the intended vault.

## Safety Boundaries

Do not use this workflow to bypass publisher access, export browser cookies,
process Zotero queues, modify Zotero storage, or write `zotero.sqlite`. The
script operates on local capture metadata and Obsidian Markdown only.
