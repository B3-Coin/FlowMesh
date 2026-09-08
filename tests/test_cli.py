import argparse
import contextlib
from decimal import Decimal
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flowmesh_app.cli import (
    WRITE_COMMANDS, display_markets, identifier, main, output_index, parser,
    positive_integer, request_for, safe_text, withdrawal_amount,
)
from flowmesh_app.rpc import RpcError


MARKET = "12" * 32
ASSET = "34" * 32
EFFECT = "56" * 32
ADDRESS = "STestAddress123"


class ArgumentTests(unittest.TestCase):
    def request(self, command):
        return request_for(parser().parse_args(command))

    def test_order_rpc_integer_units_and_sequence(self):
        method, params = self.request(["order", MARKET, "bid", "100000000", "100", "--sequence", "0"])
        self.assertEqual(method, "submitflowmeshorder")
        self.assertEqual(params, [MARKET, "bid", 100000000, 100, 0])
        self.assertIs(type(params[2]), int)

    def test_optional_sequence_is_omitted_not_null(self):
        self.assertEqual(self.request(["cancel", MARKET, "ask"]), ("cancelflowmeshorder", [MARKET, "ask"]))

    def test_readonly_routes(self):
        for command, expected in [
            (["markets"], ("listflowmeshmarkets", [])),
            (["balance", MARKET], ("getflowmeshbalance", [MARKET])),
            (["vault-ops"], ("listflowmeshvaultoperations", [])),
            (["vault-ops", MARKET], ("listflowmeshvaultoperations", [MARKET])),
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.request(command), expected)

    def test_mutation_routes(self):
        for command, expected in [
            (["validator-start"], ("startflowmeshvalidator", [])),
            (["validator-stop"], ("stopflowmeshvalidator", [])),
            (["checkpoint", MARKET], ("createflowmeshcheckpoint", [MARKET])),
            (["admit-deposit", MARKET, EFFECT, "2"], ("submitflowmeshdeposit", [MARKET, EFFECT, 2])),
            (["publish-vault", EFFECT], ("createflowmeshvaulttx", [EFFECT])),
            (["publish-vault", EFFECT, "--destination", ADDRESS], ("createflowmeshvaulttx", [EFFECT, ADDRESS])),
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.request(command), expected)

    def test_b3_withdrawal_uses_exact_decimal_string(self):
        method, params = self.request(["withdraw", MARKET, "B3", "0.000000001", ADDRESS])
        self.assertEqual(method, "requestflowmeshwithdrawal")
        self.assertEqual(params, [MARKET, "B3", "0.000000001", ADDRESS])

    def test_colored_withdrawal_uses_json_integer(self):
        method, params = self.request(["withdraw", MARKET, ASSET, "40", ADDRESS, "--sequence", "7"])
        self.assertEqual(method, "requestflowmeshwithdrawal")
        self.assertEqual(params, [MARKET, ASSET, 40, ADDRESS, 7])

    def test_invalid_amounts(self):
        for value in ("0", "-1", "1e5", "1.0", "NaN", "Infinity", "9223372036854775808", "١٢"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    positive_integer(value)
        for value in ("0", "-0.1", "1e-9", "0.0000000001", "NaN", "1.2.3", "9999999999999999999"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    withdrawal_amount("B3", value)
        with self.assertRaises(argparse.ArgumentTypeError):
            withdrawal_amount(ASSET, "40.0")

    def test_ids_and_output_indices(self):
        self.assertEqual(identifier("AB" * 32), "ab" * 32)
        for value in ("00" * 32, "g" * 64, "abcd", MARKET + "\n"):
            with self.assertRaises(argparse.ArgumentTypeError):
                identifier(value)
        self.assertEqual(output_index("0"), 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            output_index(str(1 << 32))

    def test_no_generic_rpc_unlock_or_secret_import(self):
        for command in ("rpc", "walletpassphrase", "sendmsgtopeer", "importflowmeshkey", "sendtoaddress"):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser().parse_args([command])


class ClientCommandTests(unittest.TestCase):
    def run_cli(self, argv, *, chain="regtest", response=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        config = SimpleNamespace(expected_chain=chain)
        with patch("flowmesh_app.cli.load_config", return_value=config) as load:
            with patch("flowmesh_app.cli.RpcClient") as constructor:
                constructor.return_value.call.return_value = response
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(argv)
                calls = constructor.return_value.call.call_args_list
                constructed = constructor.call_count
        return code, stdout.getvalue(), stderr.getvalue(), calls, constructed, load.call_count

    def test_every_write_requires_explicit_opt_in(self):
        commands = [
            ["order", MARKET, "bid", "1", "1"], ["cancel", MARKET, "ask"],
            ["validator-start"], ["validator-stop"], ["checkpoint", MARKET],
            ["admit-deposit", MARKET, EFFECT, "0"],
            ["withdraw", MARKET, "B3", "1", ADDRESS], ["publish-vault", EFFECT],
        ]
        self.assertEqual({c[0] for c in commands}, WRITE_COMMANDS)
        for command in commands:
            with self.subTest(command=command):
                code, _, error, calls, constructed, loaded = self.run_cli(command)
                self.assertEqual(code, 1)
                self.assertIn("--allow-regtest-write", error)
                self.assertEqual((calls, constructed, loaded), ([], 0, 0))

    def test_explicit_flag_cannot_enable_mainnet_writes(self):
        for chain in ("main", "test", "testnet4", "signet"):
            with self.subTest(chain=chain):
                code, _, error, calls, constructed, _ = self.run_cli(
                    ["--allow-regtest-write", "validator-start"], chain=chain)
                self.assertEqual(code, 1)
                self.assertIn("restricted", error)
                self.assertEqual((calls, constructed), ([], 0))

    def test_readonly_mainnet_empty_markets_are_honest(self):
        code, out, error, calls, _, _ = self.run_cli(["markets"], chain="main", response=[])
        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        self.assertIn("No markets discovered", out)
        self.assertEqual(calls[0].args, ("listflowmeshmarkets", []))
        self.assertIs(calls[0].kwargs["allow_regtest_write"], False)

    def test_write_result_is_not_misrepresented_as_final(self):
        code, out, error, calls, _, _ = self.run_cli(
            ["--allow-regtest-write", "order", MARKET, "bid", "100000000", "100"],
            response={"accepted": True, "action_id": EFFECT})
        self.assertEqual((code, error), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["network"], "regtest")
        self.assertIn("not proof of a fill", result["note"])
        self.assertEqual(calls[0].args, ("submitflowmeshorder", [MARKET, "bid", 100000000, 100]))
        self.assertIs(calls[0].kwargs["allow_regtest_write"], True)

    def test_json_decimal_output_preserves_exact_value(self):
        code, out, _, _, _, _ = self.run_cli(
            ["--json", "balance", MARKET], response={"available": Decimal("12345678.000000001")})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["available"], "12345678.000000001")

    def test_invalid_withdrawal_rejected_before_reading_credentials(self):
        code, _, _, calls, constructed, loaded = self.run_cli(
            ["--allow-regtest-write", "withdraw", MARKET, "B3", "NaN", ADDRESS])
        self.assertEqual(code, 1)
        self.assertEqual((calls, constructed, loaded), ([], 0, 0))

    def test_doctor_only_reads_and_preserves_reported_state(self):
        client = Mock()
        client.call.side_effect = [
            {"chain": "main", "blocks": 815595, "headers": 815600, "initialblockdownload": True},
            {"version": 10104, "subversion": "/B3Hive:1.1.4/", "connections": 4},
            [],
        ]
        out = io.StringIO()
        with patch("flowmesh_app.cli.load_config", return_value=SimpleNamespace(expected_chain="main")):
            with patch("flowmesh_app.cli.RpcClient", return_value=client):
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(["--json", "doctor"]), 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["chain"]["initialblockdownload"])
        self.assertEqual(result["market_count"], 0)
        self.assertEqual([call.args[0] for call in client.call.call_args_list],
                         ["getblockchaininfo", "getnetworkinfo", "listflowmeshmarkets"])

    def test_rpc_failure_not_retried(self):
        out = io.StringIO()
        client = Mock()
        client.call.side_effect = RpcError("Node did not answer; transaction outcome is unknown")
        with patch("flowmesh_app.cli.load_config", return_value=SimpleNamespace(expected_chain="regtest")):
            with patch("flowmesh_app.cli.RpcClient", return_value=client), contextlib.redirect_stderr(out):
                self.assertEqual(main(["--allow-regtest-write", "checkpoint", MARKET]), 1)
        self.assertEqual(client.call.call_count, 1)
        self.assertIn("outcome is unknown", out.getvalue())

    def test_terminal_control_characters_are_not_rendered(self):
        self.assertNotIn("\x1b", safe_text("\x1b[2J"))
        self.assertNotIn("\n", safe_text("bad\nforged line"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            display_markets([{"market_id": MARKET, "error": "\x1b[2J\nforged"}])
        self.assertNotIn("\x1b", out.getvalue())

    def test_unexpected_market_result_fails_closed(self):
        with self.assertRaises(RpcError):
            display_markets({"fake": "market"})


if __name__ == "__main__":
    unittest.main()
