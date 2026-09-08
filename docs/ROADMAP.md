# Development stages

This repository is deliberately separate from B3-CoinV2. Its initial commit
does not modify Qt, consensus, node configuration or any live wallet.

## Initial foundation

- A local-only Python client with explicit wallet selection and chain pinning.
- Read-only market and account status, without fabricated market data.
- Deliberate regtest order, validator, checkpoint and vault operations.
- Offline command, configuration and transport tests.

This is not a completed trading UI or a demonstrated live market.

## Next: disposable end-to-end rehearsal

Prepare an isolated four-seat regtest mesh using the pinned core release's
setup as the reference. Exercise this client against it and record deposits,
certification, an exact-fee trade, checkpoint inclusion, vault publication and
withdrawal settlement. Keep this evidence separate from mocked unit tests.
Do not use real USDT, live savings wallets or shared signing journals.

## Then: market data and application UI

Design a verifiable market-data interface for order-book snapshots and
certified execution history. The current wallet RPC does not expose those
feeds. A graphical client must distinguish pending actions, certified results
and on-chain settlement. Keep public market-data serving separate from local
wallet authorization; do not expose wallet RPC or its cookie to a browser or
public server.

## Later: explicitly approved mainnet use

Mainnet writes are not an option in this client. Any addition needs a separate
review of wallet authorization, amount and fee bounds, transaction previews,
uncertain-outcome reconciliation, signing persistence and market liveness,
followed by explicit authorization of test funds and participants. A change
to repository visibility also requires an explicit decision.

Extracting the matching/validation engine into another process is a different
project from building this client. Preserve canonical chain inputs,
deterministic execution, existing certificate rules and one durable signing
history per seat if that work is pursued.
