# Harness

The project has an active PaddleOCR/FastAPI implementation. Its Harness lets
humans and agents turn current product changes into safe, validated work.

The app is what users touch. The harness is what agents touch.

## Mental Model

```text
------------------+
| Human intent    |
+------------------+
         |
         v
+------------------+
| Feature intake   |
+------------------+
         |
         v
+------------------+
| Story packet     |
+------------------+
         |
         v
+------------------+
| Agent work loop  |
+------------------+
         |
         v
+------------------+
| Product delta    |
+------------------+
         |
         v
+------------------+
| Validation proof |
+------------------+
         |
         v
+------------------+
| Harness delta    |
+------------------+
         |
         v
+------------------+
| Next intent      |
+------------------+
```

Every task has two possible outputs:

1. Product delta: app code, tests, API shape, data model, or product docs.
2. Harness delta: docs, templates, validation expectations, backlog items, or
   decision records that make the next task easier.

## Harness Scope

The current Harness includes:

- Agent entrypoint.
- Feature intake and risk lanes.
- Story packets, decisions, validation reports, and a test matrix.
- A repository-local durable CLI and SQLite operational record for intakes,
  traces, stories, decisions, backlog, and audits.
- Existing application, test, Docker, and product-contract surfaces that the
  Harness coordinates but does not replace.

The Harness deliberately does not:

- Require a project-specific `SPEC.md`.
- Replace the accepted product contracts, story packets, decisions, or
  executable tests with database records.
- Prescribe a new application stack or overwrite the existing FastAPI,
  PaddleOCR, PostgreSQL, Kafka, Redis, or provider integration choices.
- Create unrelated application surfaces, tests, CI, or infrastructure without
  a selected story or maintenance request.

## Source Hierarchy

```text
User-provided spec or prompt
  input material for first buildout or future changes

docs/product/*
  current product contract derived from accepted input

docs/stories/*
  story-sized work packets and historical evidence

docs/TEST_MATRIX.md
  behavior-to-proof control panel

docs/decisions/*
  why the contract changed
```

Product docs plus executable tests are the living product contract. The durable
Harness database records task operations and may be refreshed from markdown with
`harness-cli import brownfield`; it is not a competing source of product truth.

## Spec Lifecycle

The Harness does not require a tracked monolithic project spec. When the human
provides a new specification, treat it as input material, not as a permanent
operating manual. Use it to populate or revise product docs, story packets,
architecture decisions, and validation expectations.

After the specification has been decomposed, do not keep extending it as the
living product plan. Ongoing work should update the smaller product docs,
stories, test matrix, and decision records.

Ongoing work should enter the harness as one of these input types:

- New spec: a project specification that needs to become product docs and
  initial story candidates.
- Spec slice: a selected behavior from the provided spec.
- Change request: a bounded behavior change, bug fix, or product refinement.
- New initiative: a larger product area that needs multiple stories.
- Maintenance request: dependency, architecture, performance, security, or
  operational work.
- Harness improvement: a process, template, proof, or agent-instruction change.

The spec-to-work loop is:

```text
human intent or supplied spec
  -> classify input type
  -> update or create product contract
  -> create story packet or initiative notes when needed
  -> define validation proof
  -> implement or document the blocker
  -> update product docs, stories, test matrix, and decisions
  -> capture harness friction
```

Large product areas should use scoped initiative notes instead of a second
monolithic specification. An initiative should explain the goal, affected
product docs, candidate stories, validation shape, open decisions, and exit
criteria. If initiative work becomes a repeated pattern, add a template or
proposal to `docs/HARNESS_BACKLOG.md`.

## Growth Rule

The harness grows from friction.

When an agent is confused, repeats manual reasoning, needs a new validation
command, discovers a missing rule, or sees a recurring failure pattern, it must
either improve the harness directly or add a proposal to `HARNESS_BACKLOG.md`.

## Validation Ladder

The repository already has validation entrypoints. Use the smallest relevant
proof from `README.md`, the selected story packet, and `docs/TEST_MATRIX.md`;
for example:

```text
quick
  python -m compileall app tests scripts
  focused python -m pytest tests/...

integration
  route, provider, worker, database, queue, or container checks required by
  the selected story

e2e
  public workflow proof when the selected story requires it

platform
  Docker, CPU/GPU, deployment, or other runtime smoke checks

release
  full relevant suite, log checks, and performance proof
```

Do not claim proof that was not run. Existing matrix rows explicitly distinguish
implemented behavior from partial or missing integration, E2E, performance, and
durability evidence.

## Durable Harness Workflow

For a mutating task:

1. Run `scripts/bootstrap-harness.sh` on macOS/Linux or
   `.\scripts\bootstrap-harness.ps1` on Windows.
2. Classify and record the request with `harness-cli intake`.
3. Query the active matrix and retrieve lane-specific context.
4. Update product artifacts and run the relevant validation.
5. Record a trace for normal or high-risk work, including files changed,
   validation evidence, outcome, and proof limits.
6. Run `harness-cli audit`.

When absorbing accepted markdown state that predates the durable layer, run
`harness-cli import brownfield` first, then record the synchronization trace.
