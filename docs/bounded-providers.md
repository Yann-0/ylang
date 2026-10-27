# Bounded provider execution

Native provider support is disabled by default. The implementation is qualified
with offline HTTP fixtures, not with paid requests or a verified invoice.
Deployment, activation, policy initialization and paid conformance checks remain
separate operator decisions.

## Supported configured routes

The five activity buckets remain `code`, `search`, `reason`, `improve` and
`other`. This catalog covers the model chains observed in the sole
stelliane.dev environment. It does not enable every model in the broader routing
defaults, arbitrary aliases, alternate API hosts or other providers.

| Requested route | Reserved and required response identity |
| --- | --- |
| `anthropic/claude-3-5-sonnet-latest` or `anthropic/claude-sonnet-4-6` | `anthropic/claude-sonnet-4-6` |
| `anthropic/claude-haiku-4-5` or its dated ID | `anthropic/claude-haiku-4-5-20251001` |
| `openai/gpt-4o` or its reviewed dated ID | `openai/gpt-4o-2024-08-06` |
| `mistral/mistral-small-latest` or its reviewed dated ID | `mistral/mistral-small-2603` |

Claude 3.5 is retired. Mapping that legacy request to Sonnet 4.6 is an explicit
replacement, not model identity equivalence. Requested and resolved identities
are retained in reservation metadata; response evidence records the actual model.
Unsupported or changed response models retain uncertainty and freeze further
paid admission.

## Activation gates

`YLANG_BOUNDED_PROVIDERS_ENABLED` is an explicit Boolean, default `false`.
It is restart-only: a hot runtime setting cannot turn it on.
The closed registry uses configured provider keys only; credentials are never
part of stored request/configuration JSON. Account identity is a credential
fingerprint. No request can register a plugin, price, host or transport.

Enabling the registry does not create money authority. A separately reviewed
canonical `default` policy must already exist in the same SQLite database.
`YLANG_DAILY_BUDGET_USD` remains a retrospective routing meter and cannot replace
that policy. Activation must acknowledge old in-flight calls, incomplete legacy
billing and opening liabilities. This change never initializes a live policy.

The catalog/rate review is dated **2026-10-27**, expires **2026-11-26 UTC**, and
quotes last at most 120 seconds. Expired or changed contracts refuse before
transport. These dates do not promise provider account access or future model
availability.

## Conservative money bounds

Each request reserves the reviewed full-context input ceiling plus its explicit
output-token ceiling. K/M context shorthand is rounded up conservatively where
needed. This avoids relying on a character/token heuristic. Supported requests
contain only bounded text messages and the optional JSON-object output contract;
no paid tools, media, batches or server-side services are granted.

The following are conservative **tariff ceilings**, not invoice prices:

| Pinned model | Input ceiling USD / million tokens | Output ceiling USD / million tokens | Hold with 512 output tokens |
| --- | ---: | ---: | ---: |
| Sonnet 4.6 | 6.60 | 16.50 | USD 6.929049600 |
| Haiku 4.5 | 2.00 | 5.00 | USD 0.402560000 |
| GPT-4o 2024-08-06 | 2.50 | 10.00 | USD 0.325120000 |
| Mistral Small 2603 | 0.15 | 0.60 | USD 0.039628800 |

Anthropic input ceilings cover the documented maximum cache-write rate.
Sonnet ceilings also cover the documented 1.1x US inference surcharge without
changing the workspace's inference geography. Anthropic and Mistral requests
explicitly select `standard_only` capacity; OpenAI selects `default`.
Unknown service tiers or billable extensions violate the reviewed contract.

Returned usage is recognized at the conservative ceiling rates. Native
`cost`/ledger amounts are upper liabilities; `cost_actual` stays null and
evidence says `cost_is_upper_bound=true`. Discounts, account contracts, taxes,
non-token fees, external requests and separate databases are not certified.
A provider must honor the documented token/context and tariff contract; software
cannot prevent an out-of-contract external bill. No invoice accuracy or
account-level hard spending guarantee is claimed.

Full-context holds can exceed a small daily/evaluation cap even for short
prompts. Such requests are refused. An uncertain hold does not expire merely
because a timeout, lease or rolling window elapsed.

## Request and transport contract

The prepared request freezes both normalized messages and the complete native
JSON bytes. Funding binds their digests, model, credential identity, tariff
version and token limits. The adapter reconstructs and verifies the native body
before dispatch. Changing any of these facts refuses the attempt.

One fixed HTTPS POST is allowed, to the first-party OpenAI, Anthropic or Mistral
endpoint. There is no proxy discovery, redirect following, SDK retry or transport
cache. DNS waiting, connect/TLS/send/read have a bounded deadline, and response
bytes are capped. The DNS helper cannot send a request after its caller times
out. A truncated response is not valid charge evidence.

Non-2xx statuses, timeouts, disconnects and missing/malformed accounting retain
the full unresolved hold. A status name does not establish that a call was free.
Model/usage contract violations freeze admission. A valid observed tariff amount
above its reservation is retained as `BREACH`; the larger liability is not
discarded.

## Prompt improvement and gateway streaming

Prompt improvement's `{"type":"json_object"}` request goes through the same
shared Engine and ledger. OpenAI/Mistral use their JSON-object parameter with an
explicit instruction. Anthropic uses a deterministic instruction and local
JSON-object validation; no server-enforced schema guarantee is asserted.
Invalid JSON with validated model/usage is a failed, charged attempt; the
captured output and charge evidence are preserved, with no automatic retry.

Native gateway streaming buffers one bounded nonstream provider request, settles
it and writes one usage record before emitting SSE content/usage chunks.
Cancellation after the first emitted chunk cannot erase the financial record.
This has first-byte latency of a full completion and is not incremental provider
streaming. Local Ollama retains its existing path.

Paid tools, structured schemas beyond a JSON object, multimodal input and
unsupported models remain refused. No model quality improvement follows from
successful protocol fixtures.

## Qualification and remaining gates

Offline tests exercise the actual registry and Engine for all five observed
activity chains, native JSON prompt improvement, registered gateway completion
and SSE, request/response identity, no-dispatch admission refusals, cancellation,
uncertain holds, tariff breaches, expiry, truncated HTTP bodies and deadline
behavior. Fixture transports are marked simulated. They cannot establish live
account/model availability, rate accuracy on an invoice or real prompt quality.

Before live activation, review the current provider/account contracts and the
chosen monetary policy, qualify a separately approved bounded canary, and
requalify the deployable snapshot. Running source, configuration, database and
service are not changed by this implementation qualification.

## Contract sources

Primary documentation reviewed on 2026-10-27:

- [Anthropic model lifecycle](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)
- [Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview),
  [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview),
  [pricing](https://platform.claude.com/docs/en/about-claude/pricing) and
  [data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)
- [OpenAI GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) and
  [deprecations](https://developers.openai.com/api/docs/deprecations)
- [Mistral Small 4](https://docs.mistral.ai/models/mistral-small-4-0-26-03),
  [pricing](https://docs.mistral.ai/inference/pricing) and
  [Chat API](https://docs.mistral.ai/api)

See [evaluation methodology](evaluation-methodology.md) for paired reservations
and the distinction between simulated execution, controlled execution and
demonstrated improvement.
