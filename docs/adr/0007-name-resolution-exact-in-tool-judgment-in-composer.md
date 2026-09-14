# ADR-0007 — Name resolution is exact in the tool; typo judgment stays with the composer

**Status:** Accepted (2026-09-14) · **Ticket:** [#3](https://github.com/mattiasthalen/deck-composer-v2/issues/3)

## Context

Names reach the tools from three places: the composer's own maybeboard, the owner's existing decklists, and lists other people bring (#8). Rule 2 of #1 puts judgment in the composer and mechanics in the tools; rule 7 makes the composer normalise pasted lists into the one canonical format. Scryfall's exact-name lookup is case-insensitive and accepts a single face of a double-faced card; its fuzzy lookup corrects small typos and is weak on multi-word ones. Every name the tool resolves is an exact Scryfall name, the card identity everything else keys on.

## Decision

**The tool resolves exactly.** `cards resolve` matches each name against the catalog first, offline, case-insensitive, either face accepted, and sends only the unknown names to Scryfall's collection endpoint by name. Every name that resolves comes back as its exact Scryfall name, and any card not yet in the catalog enters it. A name that does not resolve is reported as such, with one suggestion from Scryfall's fuzzy endpoint attached, or null when Scryfall has none. The suggestion is never written anywhere; the composer decides whether it is the card meant, asking the owner when unsure.

Rejected: fuzzy resolution inside the tool with a confirmation step. It puts judgment in code, needs a two-phase protocol to hold a pending correction, and Scryfall's fuzzy matching is not reliable enough to act on unasked.

## Consequences

- A typo costs one extra round through the composer, cheap inside a session, and is corrected by the actor with the context to correct it.
- Known names never touch the network, so resolving the owner's own lists works offline.
- The catalog grows by every name ever resolved, owned or not; nothing prunes it, and a regenerated catalog regains those names on the next resolve.
- Anything that later fetches lists from URLs, deferred in #1, feeds names into resolve and inherits this split.
