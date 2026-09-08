# Regtest guide

This guide separates the core release test from testing this RPC client. Both use disposable regtest state. The client does not provision a chain, make test assets, bind FN seats, create a vault deposit, unlock a wallet or advance the chain clock.

## Verify the core release independently

Use a separate build of [B3-Coin/B3-CoinV2 v1.1.4](https://github.com/B3-Coin/B3-CoinV2/tree/b8457dba57298bd377deb1fbb9e2bf091aeb47dc), with a wallet-enabled daemon and CLI. Verify that its source commit is `b8457dba57298bd377deb1fbb9e2bf091aeb47dc`. Keep this build and its test state separate from a production node's directories.

The upstream [feature_flowmesh_release.py](https://github.com/B3-Coin/B3-CoinV2/blob/b8457dba57298bd377deb1fbb9e2bf091aeb47dc/test/functional/feature_flowmesh_release.py) is the existing end-to-end release gate. It creates four independent regtest wallets, configures the modern transition and FlowMesh test pins, binds FN seats, bootstraps a test market and checks deposit, certification, checkpoint, trade and withdrawal behavior. It also exercises restart and reindex behavior. The special daemon options are maintained in that test's `B3_ARGS`; an ordinary fresh regtest node is not equivalent to this prepared mesh.

From the pinned core source directory, inspect its own supported options:

```sh
python3 -B test/functional/feature_flowmesh_release.py --help
```

For an already configured build, the independent release test can be invoked as follows. Replace both absolute paths. The build's generated `test/config.ini` must point to the matching binaries, and the chosen `--tmpdir` must not already exist.

```sh
python3 -B test/functional/feature_flowmesh_release.py \
  --configfile /ABSOLUTE/CORE/BUILD/test/config.ini \
  --tmpdir /ABSOLUTE/EXISTING/TEST-PARENT/fresh-release-run \
  --nocleanup
```

`--configfile`, `--tmpdir` and `--nocleanup` are supported by the pinned framework. `--nocleanup` retains its temporary files, but successful completion still stops its nodes. It does not leave a live playground for this application. Failed runs may leave child processes running; identify them from that run's logs and data directories before managing them. Do not point this test at an existing wallet or node directory.

A passing core release gate is evidence about that core build, not proof that this client has been tested against it. This repository does not copy or modify the upstream test harness. Record core-test and client-integration results separately.

## Prepare an application test environment

A core operator must deliberately provide a running disposable regtest mesh. The release test is the reference for its required setup; merely setting this client's `expected_chain` to `regtest` does not configure the daemon.

Before testing actions, establish:

- Matching core binaries, isolated data directories and explicit loopback RPC ports.
- A node that reports `chain = "regtest"`, has finished its initial download and passes this client's synchronization checks.
- A loaded integration wallet; a trading account and confirmed test deposit when testing trading commands.
- A known test market, enough anchor-final bound FN seats, and a certified, connected genesis checkpoint.
- Appropriate test-only balances and fee funds for the operation being exercised.
- Separately managed wallet unlock and validator provisioning, plus a controlled mechanism for advancing regtest blocks and time.

The daemon is authoritative for these conditions. The CLI does not independently prove quorum, deposit maturity or custody safety.

Create a private `config.local.toml` for one of those nodes:

```toml
[rpc]
url = "http://127.0.0.1:18443"
wallet = "flowmesh-regtest"
cookie_file = "/ABSOLUTE/PATH/TO/ISOLATED/NODE/regtest/.cookie"
expected_chain = "regtest"
timeout = 10
```

The port and wallet name above are examples, not the release harness's assigned values. Use the actual node's cookie file and listening port. Run `doctor` and `markets` first. Keep monitoring a real network in a separate configuration with `expected_chain = "main"` and no write flag.

## Exercise one operation at a time

The syntax below uses uppercase placeholders; replace them with actual IDs and values from the disposable mesh. Global options come before the command. Every write requires `--allow-regtest-write`.

| Command after `python3 -m flowmesh_app --config config.local.toml --allow-regtest-write` | Meaning |
| --- | --- |
| `order MARKET_ID bid PRICE_ATOMS QUANTITY [--sequence N]` | Submit a limit bid; `ask` is also supported |
| `cancel MARKET_ID bid [--sequence N]` | Cancel this account's standing bid; `ask` is also supported |
| `validator-start` | Arm this wallet's stored seat keys in the node |
| `validator-stop` | Clear all armed FlowMesh seat keys in the node |
| `checkpoint MARKET_ID` | Publish the daemon-selected pending certified checkpoint |
| `admit-deposit MARKET_ID TXID VOUT` | Submit an already created and sufficiently confirmed deposit |
| `withdraw MARKET_ID ASSET AMOUNT DESTINATION [--sequence N]` | Submit a withdrawal request |
| `publish-vault EFFECT_ID [--destination ADDRESS]` | Publish an eligible sweep or withdrawal transaction |

`PRICE_ATOMS` is a positive integer number of native B3 atomic units per colored-asset base unit. `QUANTITY` is a positive integer count of colored-asset base units. The pinned modern denomination is **1 B3 = 1,000,000,000 atomic units**. For example, `100000000` price atoms means 0.1 B3 per base unit. Do not treat the price parameter as a decimal B3 amount.

Withdrawal amounts use a different convention: `ASSET=B3` takes a decimal B3 amount, with up to nine fractional digits; a colored asset ID takes an exact integer number of base units. At the RPC boundary, a B3 decimal may be encoded as text to preserve precision, while a colored-asset amount must be a JSON integer. The destination is the address committed by the withdrawal request. Publishing its later vault transaction requires that same destination; a deposit sweep needs only its effect ID.

Use an explicit sequence only when intentionally managing the wallet account's sequence. The daemon's default is the current certified next sequence, which does not by itself account for other pending submissions. Avoid concurrent submissions from multiple clients during initial testing.

## Observe completion

After an accepted order, check the resulting certified account state against the expected test scenario. The CLI cannot report a fill history that the RPC does not expose. An acceptance response alone is not a completed trade.

After a certified entry, inspect `markets` for a pending checkpoint and publish it deliberately. After the chain connects the checkpoint, inspect `vault-ops` for publishable effects. Publish same-market/asset withdrawals one at a time, wait for confirmation, and refresh the list because candidate pool inputs can overlap. Confirm the payout and subsequent settlement through the core test scenario; do not equate an empty list with proof of a particular payment.

If an RPC times out after submission, its result may be unknown. Check pending/certified state and transaction status before retrying. If a market reports `paused`, a non-`none` `halt`, an error, or an unexpected handoff, preserve the evidence and investigate in the core environment. The client has no recovery command.

Record the source commit, binary version, configuration's chain and wallet name, operations exercised, observed outputs, and whether the test used a live regtest node or a mock RPC server. Exclude cookies, passphrases and secret keys. Unit tests and source review alone do not establish end-to-end mesh behavior.
