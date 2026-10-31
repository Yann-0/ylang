# Maintenance approval record for 0075ccab

The maintenance activation review packet was finalized on **31 October 2026
(Europe/Paris)** for candidate
`0075ccab0239e525cdb89f1c5fbbec2082f5738d`. This is preparation evidence:
it does not authorize or perform live maintenance, application deployment,
provider activation or paid calls.

The recorded live application still matched
`25dc64b32f5105d717fe21d0d23543920f4fa16e`. A passing snapshot does not reserve
admission for a later operation.

## Retained evidence

The operator packet is retained on-prem as
`maintenance-activation-finalized-packet.zip`:

- SHA-256: `ecb29ffe86d15e72dc44269ec713cbe78f862a8c83e6b7414a4f9a6f726c03b4`.
- 47,708 bytes and 32 files, with archive CRC and every entry hash verified.
- Checksum-manifest SHA-256:
  `d02a3b103a0a965b8b9b307e0d963f807cb82b6246a94d7ee67529ae237f552c`.

The [public manifest](maintenance-approval-0075ccab.json) records these identities
and evidence boundaries. Raw host inventory, private paths, account metadata,
client configuration, command captures and the full operator archive stay
on-prem. This record does not replace the protected installer inputs.

The retained evidence includes an earlier human privileged preflight with
**14 of 14 checks passing**, and a later ordinary-user refresh with
**11 of 11 checks passing**. Eight existing read-only collector boundary checks
passed. Four isolated installer startup/recovery/refusal cases passed.

These results establish their recorded scopes. The ordinary-user refresh does
not recheck private root inputs or the full current firewall. The isolated
installer cases do not establish actual host installation, activation, recovery,
physical power-loss behavior or reboot.

## Access observations

Independent LAN observations are **NOT_RUN**. Internet IPv4 and IPv6 checks are
both **NOT_RUN**, as explicitly requested for this finalization. Public internet
closure is **NOT_PROVED**. No external test service or additional environment
was started to fill that gap.

Server self-probes are not external observations. Missing DNS, routes, usable
baselines or listeners cannot turn a failed connection into a firewall pass.
Any later local closure retains `CLOSED_PENDING_EXTERNAL_PROOFS` until the
applicable independent evidence is available. Publication does not change that
gate.

## Separate activation decision

The retained approval draft is intentionally invalid: it has no usable action
purpose, issue/expiry dates or fresh firewall identity, and its action,
client-pause and disruption flags are false. No protected action authority was
issued or installed.

Before any separately approved maintenance close:

- Pause client reconnect behavior, including the configured Cursor connection;
  a zero-socket snapshot does not establish a persistent pause.
- Account for root SSH forwarding and HTTP proxy paths and confirm their pause.
  Known direct client URLs do not prove these paths absent.
- Refresh the original qualified boot, process/start and static-file identity,
  protected inputs and paths, full normalized firewall identity, and zero
  established service clients. The conservative temperature maximum must be
  strictly below 90 degrees C at actual admission.
- Obtain explicit authority for protected guard/state/dependency installation,
  manager reload and guard start, connection disruption, and the exact-current
  bound Ylang safety stop if closure cannot be proved.

The qualified adapter must independently revalidate its time-bounded protected
authority and current state. Only its dedicated Ylang maintenance table is in
scope. Publication does not install it or change any firewall or service.

## Recovery and remaining boundaries

Future recovery requires separate current authority. Preserve dependencies,
protected files, state, pending stages, the dedicated table and transaction
receipt. Recovery may complete closure or retain a stopped/uncertain hold; it
does not restart Ylang, reopen access, flush shared rules or restore stale data.

Application cutover and migration 17, provider activation, paid or local
inference, reboot and reopening remain separate decisions. Actual host cutover
and maintenance activation remain unexecuted. No production-readiness or prompt
quality-improvement claim follows from this publication.
