# ADR-0004 — Card data fetches through Scryfall's collection endpoint, never bulk files

**Status:** Accepted (2026-09-14) · **Ticket:** [#3](https://github.com/mattiasthalen/deck-composer-v2/issues/3)

## Context

Rule 4 of #1: composing from owned cards needs no network; Scryfall is needed only when a new export adds printings and when validating unowned names. Owned printings are identified by Scryfall ID on every lot (A1, verified on 883 rows); unowned cards arrive as names from the composer, the maybeboard and other people's lists.

Measured 2026-09-14: all 676 owned printings resolved through `POST /cards/collection` in 10 requests with zero misses. The endpoint accepts up to 75 identifiers per request, `id` and `name` mixed, and returns a `not_found` list per identifier; a `name` identifier resolves a single face name to the full double-faced name. Scryfall's bulk files, compressed: oracle_cards 24.6 MB, default_cards 78.2 MB, refreshed daily. Scryfall asks for a User-Agent and Accept header, 50 to 100 ms between requests, and forbids caching prices beyond a day; this project drops prices entirely.

## Decision

**All fetching goes through the collection endpoint.** Owned printings by `id`, everything else by `name`, up to 75 identifiers per request, one request at a time, 100 ms apart, with an identifying User-Agent and an Accept header, backing off on 429. The fuzzy endpoint is called only to attach one suggestion to a name that failed to resolve; its answer is never stored.

Rejected: bulk data. default_cards is 78 MB compressed per refresh and mostly cards nobody owns; oracle_cards is smaller but carries no printing-level data, so the printings list and token ownership by printing would need the endpoint anyway; both are refreshed daily and are never fresher than the endpoint. At ten times today's collection the endpoint costs about a hundred requests, under a minute.

**The committed catalog is a whitelist projection.** Only the fields the design names are written; prices, purchase links and images never pass. Cached Scryfall responses used as test fixtures are scrubbed of the same keys, with a test that enforces it, extending the fixture policy that already blanks purchase prices in export rows.

## Consequences

- Enrichment and refresh are the only operations that touch the network, and both say how many requests they made.
- A card Scryfall cannot find is reported per identifier, so one bad lot never hides behind a bulk file that simply lacks it.
- Retries and 429 handling are implementation choices (#1 branch 19); the request budget is small enough that a failed run is repeated whole.
- Should Scryfall change the endpoint's contract, one module, the Scryfall client, changes; the catalog format does not.
- Bulk files can be revisited if the collection grows far past the design target; nothing in the catalog format depends on how its contents arrived.
