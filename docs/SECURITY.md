# Security boundaries

This initial repository is private. Do not publish it, change its hosting visibility or share operational configuration as part of routine development. Report findings through the repository's private collaboration channel without attaching secrets.

## Local access and authority

The client connects only to a numeric loopback RPC address using the configured node cookie. It does not expose a server, accept arbitrary RPC method names, take keys or wallet passphrases as command arguments, or unlock a wallet. Its command mapping is intentionally small.

A node cookie is still a powerful credential: the daemon may authorize more RPC methods than this client exposes. Protect the cookie file and the local account running this program. A loopback connection does not protect against compromised software on the same host. Keep cookie contents, private keys and passphrases out of source control, terminal transcripts and issue attachments. Local configurations and test artifacts must remain outside tracked repository content.

Mainnet commands are read-only in this application. Every mutation needs a deliberate `--allow-regtest-write` flag, configured `expected_chain = "regtest"`, and a live matching node that passes the application's synchronization checks. These are application safeguards; they do not restrict another program using the same credential or prove that the responding process is an authentic, correctly built B3 node.

Use a dedicated experimental data directory and wallet. Do not load savings spending keys into an experimental setup. A second process on the same machine needs its own data directory and nonconflicting ports; two processes must not share one writable node database.

## Wallet keys and validator keys

The released core keeps the wallet's FlowMesh trading-account key independent from payment, finality and FN-seat keys. RPC order and withdrawal methods sign using that trading key inside the daemon. This application receives the result rather than the private key.

`startflowmeshvalidator` behaves differently from ordinary wallet signing. In the pinned release, it requires an unlocked wallet and copies all of that wallet's stored FN-seat BLS keys into the daemon's process-wide FlowMesh service. Locking the wallet again, including expiry of its unlock timeout, does not remove those copies. `stopflowmeshvalidator` explicitly clears the armed FlowMesh collection. The CLI never invokes wallet unlock automatically.

Validator control is **node-wide**: starting from another wallet replaces the node's armed key collection; stopping from a selected wallet clears all armed FlowMesh seat keys in that node. A returned `running` value means the worker was armed, not that its keys belong to the active set or that the mesh has enough signers to make progress.

Provisioning and key backups belong to the core operator's separate procedure. BLS records are encrypted at rest when the wallet is encrypted; an unencrypted wallet does not gain encryption merely because the keys are FlowMesh keys. The CLI has no key-import, key-export or seat-binding operation.

These semantics come from the pinned release's [validator RPCs](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/wallet/rpc/flowmesh.cpp), [node key provider](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/node/flowmesh_service.cpp), and [wallet lock and key storage](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/wallet/wallet.cpp).

## Signing locks and halted markets

Production signatures are bound to the market, anchored seat set, epoch and sequence. The core persists signing locks for each `(epoch, sequence)` position before signing, and those locks have no erase operation. They prevent signing a conflicting entry after a restart; they are not a cache to clear when the mesh stalls.

An unavailable quorum, an incomplete seat handoff, a conflicting certificate, an invalidated anchor or a durable-store failure can leave a market paused or halted. A timeout does not authorize replacing its committee, advancing its epoch, discarding locks or signing an alternative entry at a locked position. Increasing the B3 chain height alone does not resolve every such condition.

Operate a seat signing key through one authoritative persistent signing history. Running the same key from independent data directories can defeat local conflict protection. Preserve the core's FlowMesh store and signing evidence when investigating a halt. The CLI does not delete them, force a checkpoint, reindex a node, choose a replacement epoch or initiate automatic recovery.

The permanent journal contract is defined in [production_engine.h](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/flowmesh/production_engine.h). Any recovery design or engine extraction needs separate review against that contract and the connected chain state.

## Funds, publication and uncertain outcomes

A vault deposit can depend on a qualifying mesh quorum before it becomes usable or recoverable. This client does not create bootstrap deposits, and its regtest features are not a reason to send real funds into a test market.

Action acceptance, certification, checkpoint inclusion, a vault payout transaction and final settlement are different states. The application reports the daemon's response and does not guarantee depth, quorum, fills, finality or recovery. Publishers provide native B3 transaction fees, even when the effect concerns a colored asset.

Treat an interrupted or timed-out mutation as potentially submitted. Investigate the daemon's account sequence, pending actions, checkpoints and transactions before sending another request. Do not infer idempotency from a transport failure. Keep the returned identifiers and sanitized diagnostics for reconciliation.

The fixed command surface excludes the core's testing-only generic P2P message injector. Adding raw action signing, external proposal submission, automatic retries, public network access or unattended publication changes this trust boundary and requires separate design and verification.
