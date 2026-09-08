"""A small, non-custodial local-RPC client, not a replacement consensus engine."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from typing import Any

from . import __version__
from .config import ConfigError, load_config
from .rpc import RpcClient, RpcError

MAX_INTEGER = (1 << 63) - 1
WRITE_COMMANDS = frozenset({
    "order", "cancel", "validator-start", "validator-stop", "checkpoint",
    "admit-deposit", "withdraw", "publish-vault",
})


def identifier(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value) or int(value, 16) == 0:
        raise argparse.ArgumentTypeError("expected a nonzero 64-character hexadecimal ID")
    return value.lower()


def positive_integer(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,19}", value):
        raise argparse.ArgumentTypeError("expected a positive integer, not a decimal or exponent")
    result = int(value)
    if not 0 < result <= MAX_INTEGER:
        raise argparse.ArgumentTypeError("integer must be between 1 and 9223372036854775807")
    return result


def nonnegative_integer(value: str) -> int:
    if value == "0":
        return 0
    return positive_integer(value)


def output_index(value: str) -> int:
    result = nonnegative_integer(value)
    if result > (1 << 32) - 1:
        raise argparse.ArgumentTypeError("output index must fit an unsigned 32-bit integer")
    return result


def asset(value: str) -> str:
    return "B3" if value.upper() == "B3" else identifier(value)


def destination(value: str) -> str:
    if not value or len(value) > 200 or not value.isascii() or not value.isalnum():
        raise argparse.ArgumentTypeError("expected a public B3 receiving address")
    # The node, with the selected network's rules, performs address validation.
    return value


def withdrawal_amount(asset_id: str, text: str) -> int | str:
    if asset_id != "B3":
        return positive_integer(text)
    if not re.fullmatch(r"[0-9]{1,19}(\.[0-9]{1,9})?", text):
        raise argparse.ArgumentTypeError("B3 amount requires a positive decimal with at most 9 places")
    atoms = Decimal(text) * 1_000_000_000
    if not 0 < atoms <= MAX_INTEGER:
        raise argparse.ArgumentTypeError("B3 amount is outside the positive signed-64-bit atom range")
    # AmountFromValue accepts decimal strings; never round-trip money via float.
    return text


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="flowmesh",
        description="Standalone B3 FlowMesh RPC client. Mainnet is read-only; no wallet keys are imported.",
        epilog="Global flags precede the command. The app never unlocks wallets or changes their configuration.",
    )
    result.add_argument("--version", action="version", version=f"FlowMesh app {__version__}")
    result.add_argument("--config", type=Path, default=Path("config.local.toml"))
    result.add_argument("--json", action="store_true", help="JSON output; decimal RPC values become exact strings")
    result.add_argument(
        "--allow-regtest-write", action="store_true",
        help="explicitly permit a single regtest operation; never enables mainnet writes",
    )
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="read node version, sync state and discovered market status")
    sub.add_parser("markets", help="list real markets; an empty result is not fabricated into a demo market")
    balance = sub.add_parser("balance", help="read the selected wallet's market balance")
    balance.add_argument("market", type=identifier)
    effects = sub.add_parser("vault-ops", help="list connected, unconsumed vault operations")
    effects.add_argument("market", type=identifier, nargs="?")

    order = sub.add_parser("order", help="REGTEST: submit a limit order; acceptance is not a fill")
    order.add_argument("market", type=identifier)
    order.add_argument("side", choices=("bid", "ask"))
    order.add_argument("price_atoms", type=positive_integer, help="integer B3 atoms per base-asset unit; 1 B3 = 1e9 atoms")
    order.add_argument("quantity", type=positive_integer, help="integer base-asset units")
    order.add_argument("--sequence", type=nonnegative_integer)
    cancel = sub.add_parser("cancel", help="REGTEST: submit a cancellation for this wallet's standing side")
    cancel.add_argument("market", type=identifier)
    cancel.add_argument("side", choices=("bid", "ask"))
    cancel.add_argument("--sequence", type=nonnegative_integer)
    sub.add_parser("validator-start", help="REGTEST: arm this wallet's FN keys (replaces node-wide armed keys)")
    sub.add_parser("validator-stop", help="REGTEST: disarm ALL FN keys in this node")
    checkpoint = sub.add_parser("checkpoint", help="REGTEST: publish the next certified checkpoint; spends B3 fees")
    checkpoint.add_argument("market", type=identifier)
    deposit = sub.add_parser("admit-deposit", help="REGTEST: admit an existing, sufficiently buried vault deposit")
    deposit.add_argument("market", type=identifier)
    deposit.add_argument("txid", type=identifier)
    deposit.add_argument("vout", type=output_index)
    withdraw = sub.add_parser("withdraw", help="REGTEST: request withdrawal, not an immediate on-chain payout")
    withdraw.add_argument("market", type=identifier)
    withdraw.add_argument("asset", type=asset)
    withdraw.add_argument("amount", help="B3 decimal amount or integer base-asset units")
    withdraw.add_argument("destination", type=destination)
    withdraw.add_argument("--sequence", type=nonnegative_integer)
    vault = sub.add_parser("publish-vault", help="REGTEST: publish a connected vault effect; spends B3 fees")
    vault.add_argument("effect_id", type=identifier)
    vault.add_argument("--destination", type=destination)
    return result


def request_for(args: argparse.Namespace) -> tuple[str, list[Any]]:
    command = args.command
    if command == "markets":
        return "listflowmeshmarkets", []
    if command == "balance":
        return "getflowmeshbalance", [args.market]
    if command == "vault-ops":
        return "listflowmeshvaultoperations", [args.market] if args.market else []
    if command == "order":
        params = [args.market, args.side, args.price_atoms, args.quantity]
        method = "submitflowmeshorder"
    elif command == "cancel":
        params = [args.market, args.side]
        method = "cancelflowmeshorder"
    elif command == "withdraw":
        params = [args.market, args.asset, withdrawal_amount(args.asset, args.amount), args.destination]
        method = "requestflowmeshwithdrawal"
    elif command == "validator-start":
        return "startflowmeshvalidator", []
    elif command == "validator-stop":
        return "stopflowmeshvalidator", []
    elif command == "checkpoint":
        return "createflowmeshcheckpoint", [args.market]
    elif command == "admit-deposit":
        return "submitflowmeshdeposit", [args.market, args.txid, args.vout]
    elif command == "publish-vault":
        return "createflowmeshvaulttx", [args.effect_id] + ([args.destination] if args.destination else [])
    else:
        raise ValueError("unsupported command")
    if args.sequence is not None:
        params.append(args.sequence)
    return method, params


def safe_text(value: Any) -> str:
    """Do not allow RPC-controlled terminal escape sequences or injected lines."""
    if value is None:
        return "not reported"
    return "".join(char if char.isprintable() else "?" for char in str(value))


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("unsupported RPC value")


def display_markets(markets: Any) -> None:
    if not isinstance(markets, list):
        raise RpcError("Node returned an unexpected market-list shape")
    if not markets:
        print("No markets discovered. No sample prices, balances or markets have been substituted.")
        return
    for index, market in enumerate(markets, 1):
        if not isinstance(market, dict):
            raise RpcError("Node returned an unexpected market entry")
        print(f"{index}. {safe_text(market.get('market_id'))}")
        for key in ("base_asset_id", "available", "running", "paused", "observer_only",
                    "pending_handoff", "halt", "error", "next_microblock_sequence",
                    "checkpoint_pending", "genesis_checkpoint_required"):
            if key in market:
                print(f"   {key}: {safe_text(market[key])}")
    print("Market status is not an order book or a guarantee of withdrawal readiness.")


def execute(args: argparse.Namespace) -> Any:
    writing = args.command in WRITE_COMMANDS
    if writing and not args.allow_regtest_write:
        raise ConfigError("This command requires --allow-regtest-write before the command; mainnet writes are never supported")
    request = None if args.command == "doctor" else request_for(args)
    config = load_config(args.config)
    if writing and config.expected_chain != "regtest":
        raise ConfigError("Trading and validator actions are restricted to an explicitly configured regtest node")
    client = RpcClient(config)
    if args.command == "doctor":
        chain = client.call("getblockchaininfo")
        network = client.call("getnetworkinfo")
        markets = client.call("listflowmeshmarkets")
        if not isinstance(chain, dict) or not isinstance(network, dict) or not isinstance(markets, list):
            raise RpcError("Node returned an unexpected diagnostic result")
        return {
            "app_version": __version__, "operation": "read-only",
            "chain": {key: chain.get(key) for key in ("chain", "blocks", "headers", "initialblockdownload")},
            "node": {key: network.get(key) for key in ("version", "subversion", "connections")},
            "market_count": len(markets), "markets": markets,
            "note": "The existing B3 daemon owns validation and signing; this app does not replace it.",
        }
    assert request is not None
    method, params = request
    result = client.call(method, params, allow_regtest_write=writing)
    if writing:
        return {
            "network": "regtest", "operation": args.command, "result": result,
            "note": "RPC success is not proof of a fill, quorum, checkpoint inclusion or completed withdrawal. Inspect the node's certified state.",
        }
    return result


def main(argv: list[str] | None = None) -> int:
    cli_parser = parser()
    args = cli_parser.parse_args(argv)
    try:
        result = execute(args)
        if args.command == "markets" and not args.json:
            display_markets(result)
        elif args.command == "doctor" and not args.json:
            print(f"FlowMesh app {__version__} — read-only inspection")
            print(f"Chain: {safe_text(result['chain']['chain'])} | blocks: {safe_text(result['chain']['blocks'])} | headers: {safe_text(result['chain']['headers'])}")
            print(f"Node: {safe_text(result['node']['subversion'])} | peers: {safe_text(result['node']['connections'])}")
            print(f"Initial block download: {safe_text(result['chain']['initialblockdownload'])}")
            display_markets(result["markets"])
        else:
            print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False, default=json_default))
    except (ConfigError, RpcError, argparse.ArgumentTypeError) as exc:
        print(f"FlowMesh: {safe_text(exc)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("FlowMesh: interrupted; any already-submitted action may still execute. Do not retry blindly.", file=sys.stderr)
        return 130
    return 0
