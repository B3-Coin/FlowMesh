# Architecture

## Scope and baseline

FlowMesh is a separate Python application that controls a narrow set of existing local RPC methods. Its initial scope is read-only monitoring on mainnet and explicit actions on regtest. It is not an extracted matching engine, a public exchange service or a replacement B3 node.

The baseline is [B3-Coin/B3-CoinV2 v1.1.4](https://github.com/B3-Coin/B3-CoinV2/tree/b8457dba57298bd377deb1fbb9e2bf091aeb47dc), commit `b8457dba57298bd377deb1fbb9e2bf091aeb47dc`. References below describe that source version, rather than the state of any live node.

```text
FlowMesh CLI
    │ local authenticated wallet RPC
    ▼
Dedicated b3coind + selected wallet
    │ existing B3 P2P connections
    ├──────── FN operators' b3coind validators
    │            verify execution and exchange BLS attestations
    ▼
Certified FlowMesh entries
    │ checkpoint and vault-publication transactions
    ▼
B3 chain
```

The CLI is responsible for configuration, argument validation, a fixed command-to-RPC mapping and presenting returned results. The daemon owns authenticated trading-account actions, canonical chain state, anchored FN seats, deterministic execution, certificates, its durable signing journal, and settlement validation.

Qt can remain disabled. There is no dependency on its trading widgets or its placeholder backend. A separate daemon can have its own data directory, wallet and, when sharing a machine, distinct P2P and RPC ports. Do not run two node processes against one data directory or operate one seat key from independent signing journals.

## RPC boundary

| CLI command | Existing RPC | Mode |
| --- | --- | --- |
| `doctor` | Node and selected-wallet diagnostic reads | Read |
| `markets` | `listflowmeshmarkets` | Read |
| `balance MARKET` | `getflowmeshbalance` | Read |
| `vault-ops [MARKET]` | `listflowmeshvaultoperations` | Read |
| `order MARKET SIDE PRICE_ATOMS QUANTITY` | `submitflowmeshorder` | Regtest write |
| `cancel MARKET SIDE` | `cancelflowmeshorder` | Regtest write |
| `validator-start` | `startflowmeshvalidator` | Regtest write |
| `validator-stop` | `stopflowmeshvalidator` | Regtest write |
| `checkpoint MARKET` | `createflowmeshcheckpoint` | Regtest write |
| `admit-deposit MARKET TXID VOUT` | `submitflowmeshdeposit` | Regtest write |
| `withdraw MARKET ASSET AMOUNT DESTINATION` | `requestflowmeshwithdrawal` | Regtest write |
| `publish-vault EFFECT_ID` | `createflowmeshvaulttx` | Regtest write |

Order, cancellation and withdrawal commands accept optional account sequences. `publish-vault` accepts a destination for a withdrawal receipt. The exact command syntax is available through `python3 -m flowmesh_app COMMAND --help`.

All action commands require `--allow-regtest-write`, an expected regtest chain, and a matching live node that passes the client's synchronization checks. RPC acceptance is a daemon response, not an additional consensus validation performed by this application. Calls do not become atomic with the chain: its tip can change after a status read.

`submitflowmeshorder` takes limit-order parameters, not a caller-signed action. The daemon signs using the selected wallet's independent FlowMesh account key. The exposed APIs do not provide a supported FlowMesh RPC for submitting an external proposal, certificate or arbitrary signed action. The core's hidden, testing-only `sendmsgtopeer` is deliberately outside this application's command surface.

The relevant core definitions are [wallet RPC registration](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/wallet/rpc/wallet.cpp), [FlowMesh RPCs](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/wallet/rpc/flowmesh.cpp), and [asset, deposit and seat preparation](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/wallet/rpc/assets.cpp). Preparation and wallet-unlock methods are not exposed by this client.

## FN validation and settlement

FN operators run the existing daemon with keys corresponding to their bound seats. The daemon carries `fmaction`, `fmprop`, `fmattest` and `fmcert` messages over its existing P2P connections. A holder does not validate merely by receiving a JSON summary from the application. Its node checks the canonical anchor, active seat membership, proposal authentication, account evidence and execution result before producing an attestation.

Market availability is separate from activation. The baseline requires at least four anchor-final seats for a runnable market and a certified, connected genesis checkpoint before local actions are accepted. Later seat changes and settlement also depend on chain-derived state. Status fields provide observations, not a client-side proof that every prerequisite is satisfied.

Orders, certificates and B3 transactions have different completion conditions:

1. An action is accepted for processing.
2. The mesh executes and certifies an entry.
3. A publisher submits the selected checkpoint transaction.
4. Once an effect is publishable, a publisher submits its vault transaction.
5. Chain confirmation and the required subsequent settlement processing determine the resulting state.

There is no automatic publisher loop in this initial client. Re-read status and publishable effects between deliberate actions. A timeout can leave the result of a mutation unknown; investigate before repeating it.

Implementation evidence is in [the service](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/node/flowmesh_service.cpp), [the runtime](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/node/flowmesh_runtime.cpp), and [P2P message handling](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/src/net_processing.cpp).

## Boundaries for later development

The current RPCs do not export an order book, complete execution log, open orders, individual fills or a live price feed. A graphical trading application needs an explicit market-data design before displaying those features. Balances and microblock hashes are not substitutes for execution history.

A future engine process would need integrations for canonical chain and seat snapshots, deposit verification, checkpoint connection and reorg handling, P2P transport, deterministic state replay, and persistent signing locks. These are currently in-process boundaries, not a ready-made remote RPC contract. Extracting them is a separate protocol and engineering project; adding a front end alone does not accomplish it.

The current CLI does not change epochs, discard signing records, replace validator sets, force a checkpoint, or initiate recovery. See [security boundaries](SECURITY.md) for the consequences of locked signing positions and unavailable quorum.
