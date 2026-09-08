# FlowMesh

Private initial development repository for a standalone FlowMesh command-line client. Python 3.11 or newer is required; the application uses the Python standard library.

This first version reads an existing local B3 node through authenticated RPC and offers explicitly enabled regtest actions. The matching engine, FN-seat validation, microblocks and settlement remain in `b3coind`. The client does not change the B3 wallet source or enable its Qt trading buttons.

The integration baseline is [B3-Coin/B3-CoinV2 v1.1.4](https://github.com/B3-Coin/B3-CoinV2/tree/b8457dba57298bd377deb1fbb9e2bf091aeb47dc), commit `b8457dba57298bd377deb1fbb9e2bf091aeb47dc`. Compatibility with other releases requires verification. This is a CLI foundation, not a finished exchange UI or evidence of successful live trading.

## Run locally

Use an existing node and a loaded wallet selected for this integration. A dedicated node data directory and wallet keep an experimental setup separate from a savings wallet. The application does not start nodes, create wallets, unlock wallets, import keys or create markets.

Create a private `config.local.toml` using the following structure. Replace the example port, wallet name and absolute cookie path with the values for your node; do not paste the cookie contents into the file.

```toml
[rpc]
url = "http://127.0.0.1:5467"
wallet = "flowmesh-monitor"
cookie_file = "/ABSOLUTE/PATH/TO/NODE/.cookie"
expected_chain = "main"
timeout = 10
```

The URL must use a numeric loopback address and an explicit port. Select the wallet through `wallet`, rather than putting a wallet path into the URL. `expected_chain` must match the chain reported by the node. The cookie authenticates access to that node and must remain private.

From this repository's root:

```sh
python3 -m flowmesh_app --help
python3 -m flowmesh_app --config config.local.toml doctor
python3 -m flowmesh_app --config config.local.toml markets
python3 -m flowmesh_app --config config.local.toml --json markets
python3 -m flowmesh_app --config config.local.toml balance MARKET_ID
python3 -m flowmesh_app --config config.local.toml vault-ops MARKET_ID
```

Replace `MARKET_ID` with a market ID returned by `markets`. Omit it from `vault-ops` to list all publishable operations. `balance` needs an existing FlowMesh account in the selected wallet; the client will not create one just to read its balance. Use global options before the subcommand. JSON output preserves decimal RPC amounts as strings, so downstream consumers should not assume every monetary field is a JSON number.

Mainnet access is read-only in this client. Regtest mutations require both `expected_chain = "regtest"` and the explicit `--allow-regtest-write` flag; the client checks the live node's chain and synchronization state before submitting them. These checks do not establish market quorum, anchor maturity, available funds or transaction finality. See [the regtest guide](docs/REGTEST.md) before using action commands.

## What the results mean

`markets` exposes the daemon's market status, including `available`, `running`, `paused`, `observer_only`, `halt`, `error`, and checkpoint fields when present. A chain above the activation height can still have no markets or a paused market. An observer can read market state without holding a validator seat.

An accepted order is admitted for processing; it is not proof of a fill. A submitted withdrawal request is not an on-chain payout. Checkpoint publication and vault publication are distinct stages, each subject to the daemon's checks and chain confirmation.

The released RPC surface has no order-book, open-order, fill-history or live-price feed. This client does not invent those values, infer fills from balances, or act as an independent validator. It exposes no generic RPC command, public HTTP server, raw proposal injection or automatic recovery operation.

See [architecture](docs/ARCHITECTURE.md), [regtest setup and verification](docs/REGTEST.md), and [security boundaries](docs/SECURITY.md). Run offline checks with `python3 -m unittest discover -s tests -v`; the [release checklist](docs/RELEASE-CHECKLIST.md) separates those checks from live integration and publication. The application is MIT licensed; initial hosting and collaboration remain private.
