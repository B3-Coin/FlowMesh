# Initial release checklist

The initial version is `0.1.0`, an alpha standalone Python 3.11+ command-line
companion for a local B3 Core JSON-RPC endpoint. It has no required runtime
packages and no embedded node. This checklist is a review document; it does not
authorize a tag, release, package publication, node operation, or wallet change.

The integration baseline is B3-Coin/B3-CoinV2 `v1.1.4`, commit
`b8457dba57298bd377deb1fbb9e2bf091aeb47dc`. The initial command scope is:

- Read-only inspection: `doctor`, `markets`, `balance`, and `vault-ops`.
- Explicit regtest actions: `order`, `cancel`, `validator-start`,
  `validator-stop`, `checkpoint`, `admit-deposit`, `withdraw`, and
  `publish-vault`. Each requires the write flag, an expected regtest chain,
  and a live node that passes the transport's chain and synchronization checks.

Mainnet access remains read-only. The daemon owns the matching engine,
validation, signing, and settlement. The client does not create nodes, wallets,
markets, or vault deposits; unlock wallets; import keys; expose a generic RPC
interface; or provide a graphical exchange, order book, or fill history.
Initial repository hosting and collaboration remain private.

## Scope and review

- [ ] Confirm the command list and behavior in `README.md` match the implemented
  CLI and its help output.
- [ ] Describe every unsupported operation and any prototype-only behavior in
  the user documentation before calling the version ready to use.
- [ ] Keep deployment, funding, real node operations, and use of cached user
  credentials outside the initial offline validation scope.
- [ ] Confirm configuration, RPC authentication, failures, and output do not
  disclose passwords, cookie contents, or wallet secrets.
- [ ] Confirm loopback restrictions and RPC method restrictions cannot be
  bypassed by malformed configuration or command arguments.
- [ ] Review changes with a second reader and resolve material findings.

## Offline verification

From the repository root, run:

```sh
python -m unittest discover -s tests -v
python -m flowmesh_app --help
```

- [ ] Tests use only temporary test files and fake RPC responses or loopback
  test servers. They must not discover or connect to a real node, load user
  wallet data, read cached credentials, or transfer funds.
- [ ] All five CI configurations pass: Linux on Python 3.11, 3.12, and 3.13;
  Windows and macOS on Python 3.13.
- [ ] Verify package metadata, `flowmesh_app` version, and documentation agree
  on `0.1.0`, and check that a locally built distribution contains the package
  and MIT license. Packaging may require separately installed build tools;
  the application's runtime and unit tests do not require external packages.
- [ ] Exercise the installed `flowmesh --help` entry point in a disposable
  environment with locally available build tools.
- [ ] Verify examples contain placeholders and no personal paths, credentials,
  private endpoints, funding information, or wallet data.

## Publication gate

- [ ] Record the exact reviewed commit and validation results.
- [ ] Obtain the repository owner's explicit instruction before creating a
  tag, publishing a package, or creating a hosted release.
- [ ] If a live integration test is later requested, agree its exact endpoint,
  allowed RPC methods, and data access separately before running it.

CI only checks the source. It has read-only repository permissions, uses
immutable action commits, and performs no release or publishing actions.
