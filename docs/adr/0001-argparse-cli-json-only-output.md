# ADR-0001 — Tools are argparse subcommands of one CLI and emit JSON only

**Status:** Accepted (2026-09-14) · **Ticket:** [#2](https://github.com/mattiasthalen/deck-composer-v2/issues/2)

## Context

The system design (#1) fixed rule 6: one CLI entry point, one subcommand per module, output written for a model to read, and every failure says what to do next. The caller is the composer, a Claude Code skill running in a session, or the owner typing into that same session. There is no GUI and no other human-facing surface. Seven modules are planned; ingest is the first and sets the contract the others inherit.

The project runs offline from committed files for a single owner, so every runtime dependency is a cost with no one to amortise it over.

## Decision

**One `deck-composer` entry point built on argparse.** Each module registers one subcommand. Rejected: click, which adds a dependency for decorator ergonomics and a test runner the project does not need, since callers are a model and tests call the functions directly; typer, which is click plus rich, the same objection at a larger size.

**JSON is the only output format.** A subcommand that succeeds prints exactly one JSON object to stdout and exits 0; the object always carries a `next` field with one sentence saying what to do now. A subcommand that fails its contract prints exactly one JSON object to stderr, `{"error", "detail", "next"}`, and exits 1. Usage errors exit 2 with argparse's message. Rejected: a markdown renderer or `--format md` alongside JSON. It is a second output format to keep in step for every subcommand, the composer already renders for humans, and JSON is readable enough for a model. A flag defaulting to JSON can be added later without breaking any caller.

## Consequences

- Every tool result is machine-checkable and can be piped or parsed; error handling is one renderer shared by all subcommands.
- No third-party runtime dependency for the CLI layer.
- Help text is plain argparse. A human reading raw tool output reads JSON.
- The `next` field is mandatory on every path. A subcommand without one is out of contract.
- Adding an output format later is additive; removing or renaming a success field is a breaking change to the composer and is versioned through the package version.
