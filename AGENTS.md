# Agent Operating Guide

This repository has an active OCR product implementation and a Harness v0-derived
operating model.

The current job of agents is to evolve the product and its collaboration
harness together. Do not add unrelated application shells, package scripts,
CI, or tests without a selected story or maintenance need.

## Source Of Truth

Read in this order:

1. The user-provided prompt or accepted change request.
2. `README.md` for runtime and developer commands.
3. `docs/product/` for current product contracts.
4. `docs/stories/` for selected work packets and historical evidence.
5. `docs/TEST_MATRIX.md` for behavior-to-proof status.
6. `docs/decisions/` for accepted technical direction.
7. `docs/HARNESS.md`, `docs/FEATURE_INTAKE.md`, and `docs/CONTEXT_RULES.md`
   for the agent operating model.
8. `.\scripts\bin\harness-cli.exe query ...` on Windows, or
   `scripts/bin/harness-cli query ...` on macOS/Linux, for durable operational
   state such as intakes, traces, stories, backlog, and audit results.

Markdown remains the human-readable contract. `harness.db` is the ignored,
repository-local operational record. Use `import brownfield` to refresh the
durable record from accepted markdown state; do not treat it as a replacement
for product contracts, stories, decisions, or executable proof.

## Task Loop

For every task:

1. For a mutating task, run `.\scripts\bootstrap-harness.ps1` on Windows or
   `scripts/bootstrap-harness.sh` on macOS/Linux.
2. Classify and record the request with `docs/FEATURE_INTAKE.md` and
   `harness-cli intake`.
3. Identify whether the input is a new spec, spec slice, change request, new
   initiative, maintenance request, or harness improvement.
4. Locate the affected product docs and story files.
5. Query `harness-cli query matrix --active --summary` and check
   `docs/TEST_MATRIX.md` for existing proof and gaps.
6. Work only inside the selected lane: tiny, normal, or high-risk.
7. Before finishing, ask:
   - Did product truth change?
   - Did validation expectations change?
   - Did architecture rules change?
   - Did we discover a repeated failure pattern?
   - Did the next agent need a clearer instruction?
8. Update routine harness files directly, or add a proposal to
   `docs/HARNESS_BACKLOG.md` when the change is structural.
9. For normal and high-risk work, record a `harness-cli trace` with validation
   evidence and run `harness-cli audit`. When synchronizing pre-existing
   markdown state, run `harness-cli import brownfield` before recording the
   synchronization trace.

## Harness Change Policy

Agents may update directly:

- Story status and evidence.
- `docs/TEST_MATRIX.md` rows.
- Links from story packets to product docs.
- Validation notes and reports.
- Small clarifications tied to the current task.

Agents should ask for human confirmation before:

- Changing architecture direction.
- Removing validation requirements.
- Changing the source-of-truth hierarchy.
- Changing risk classification rules.
- Replacing the feature workflow.

## Done Definition

A task is done only when:

- The requested change is completed or the blocker is documented.
- Relevant docs, stories, and test matrix entries remain current.
- Validation commands were run when they exist.
- Missing harness capabilities were added to `docs/HARNESS_BACKLOG.md`.
- The durable Harness record has an intake and, for normal or high-risk work,
  a trace with the actual outcome and proof limits.
- `harness-cli audit` was run after durable Harness changes.
- The final response says what changed and what was not attempted.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **pocr** (5489 symbols, 8725 relationships, 185 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/pocr/context` | Codebase overview, check index freshness |
| `gitnexus://repo/pocr/clusters` | All functional areas |
| `gitnexus://repo/pocr/processes` | All execution flows |
| `gitnexus://repo/pocr/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

<!-- HARNESS:BEGIN -->
## Harness

Choose the request class before any Harness operation.

- When the requested outcome is only an answer, explanation, review, diagnosis,
  plan, or status report: inspect only the material needed to respond. Keep the
  task read-only. Do not bootstrap, initialize or migrate a database, record
  intake, or record a trace.
- When the user explicitly asks to change, build, fix, or write repository
  artifacts: first run `scripts/bootstrap-harness.sh`
  on macOS/Linux or `.\scripts\bootstrap-harness.ps1` on Windows. Then use
  `docs/FEATURE_INTAKE.md` to classify and record the request, query
  `scripts/bin/harness-cli query matrix --active --summary` on macOS/Linux or
  `.\scripts\bin\harness-cli.exe query matrix --active --summary` on Windows,
  and retrieve only the lane- and task-specific context described in
  `docs/CONTEXT_RULES.md`.
<!-- HARNESS:END -->
