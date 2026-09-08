import base64
from decimal import Decimal
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flowmesh_app.config import RpcConfig
from flowmesh_app.rpc import MAX_COOKIE_BYTES, MAX_RESPONSE_BYTES, RpcClient, RpcError, WRITE_METHODS


CHAIN = {"chain": "regtest", "initialblockdownload": False, "blocks": 100, "headers": 100}


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.read_sizes = []

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class FakeConnection:
    def __init__(self, factory, host, port, timeout):
        self.factory = factory
        self.host, self.port, self.timeout = host, port, timeout
        self.closed = False
        self.request_data = None

    def request(self, verb, path, body, headers):
        self.request_data = (verb, path, json.loads(body), headers)
        self.factory.requests.append(self.request_data)

    def getresponse(self):
        if not self.factory.replies:
            raise AssertionError("Unexpected offline RPC request")
        value = self.factory.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, FakeResponse):
            return value
        if callable(value):
            value = value(self.request_data)
        envelope = {"jsonrpc": "2.0", "id": self.request_data[2]["id"], "result": value}
        return FakeResponse(json.dumps(envelope).encode("utf-8"))

    def close(self):
        self.closed = True


class OfflineHTTP:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.connections = []

    def __call__(self, host, port, timeout):
        connection = FakeConnection(self, host, port, timeout)
        self.connections.append(connection)
        return connection


class RpcTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cookie = self.directory / ".cookie"
        self.cookie.write_bytes(b"__cookie__:topsecret")
        self.cookie.chmod(0o600)
        # Any overlooked networking in a test fails before opening a real socket.
        socket_guard = patch("socket.socket", side_effect=AssertionError("Live networking is forbidden in tests"))
        socket_guard.start()
        self.addCleanup(socket_guard.stop)

    def config(self, **overrides):
        settings = dict(url="http://127.0.0.1:18443", wallet="flowmesh", cookie_file=self.cookie)
        settings.update(overrides)
        return RpcConfig(**settings)

    def mock_http(self, *replies):
        factory = OfflineHTTP(replies)
        mock = patch("flowmesh_app.rpc.http.client.HTTPConnection", factory)
        mock.start()
        self.addCleanup(mock.stop)
        return factory

    def test_chain_request_uses_node_path_and_exact_id(self):
        factory = self.mock_http(CHAIN)
        self.assertEqual(RpcClient(self.config()).call("getblockchaininfo"), CHAIN)
        verb, path, request, headers = factory.requests[0]
        self.assertEqual((verb, path, request["method"], request["id"]), ("POST", "/", "getblockchaininfo", 1))
        self.assertEqual(request["jsonrpc"], "2.0")
        self.assertEqual(headers["Authorization"], "Basic " + base64.b64encode(b"__cookie__:topsecret").decode())
        self.assertTrue(factory.connections[0].closed)

    def test_read_rechecks_chain_then_uses_encoded_wallet(self):
        factory = self.mock_http(CHAIN, [{"market": "B3/USD"}])
        client = RpcClient(self.config(wallet="a/b 钱包?x=#%"))
        self.assertEqual(client.call("listflowmeshmarkets"), [{"market": "B3/USD"}])
        self.assertEqual([request[1] for request in factory.requests], ["/", "/wallet/a%2Fb%20%E9%92%B1%E5%8C%85%3Fx%3D%23%25"])
        self.assertEqual([request[2]["id"] for request in factory.requests], [1, 2])

    def test_network_info_uses_node_path(self):
        factory = self.mock_http(CHAIN, {"version": 1})
        RpcClient(self.config()).call("getnetworkinfo")
        self.assertEqual([request[1] for request in factory.requests], ["/", "/"])

    def test_special_dot_wallet_names_are_encoded(self):
        factory = self.mock_http(CHAIN, [])
        RpcClient(self.config(wallet="..")).call("listflowmeshmarkets")
        self.assertEqual(factory.requests[-1][1], "/wallet/%2E%2E")

    def test_float_results_are_exact_decimal(self):
        factory = self.mock_http(CHAIN, FakeResponse(b'{"jsonrpc":"2.0","id":2,"result":{"amount":0.1234567890123456789,"count":7}}'))
        result = RpcClient(self.config()).call("getflowmeshbalance", ["B3"])
        self.assertEqual(result["amount"], Decimal("0.1234567890123456789"))
        self.assertIsInstance(result["count"], int)
        self.assertEqual(factory.requests[-1][2]["params"], ["B3"])

    def test_cookie_is_read_fresh_between_requests(self):
        def rotate_cookie(request):
            self.cookie.write_bytes(b"__cookie__:newsecret")
            return CHAIN
        factory = self.mock_http(rotate_cookie, [])
        RpcClient(self.config()).call("listflowmeshmarkets")
        auth = [request[3]["Authorization"] for request in factory.requests]
        self.assertNotEqual(auth[0], auth[1])
        self.assertEqual(auth[1], "Basic " + base64.b64encode(b"__cookie__:newsecret").decode())

    def test_proxy_environment_is_ignored_and_timeout_is_explicit(self):
        factory = self.mock_http(CHAIN)
        with patch.dict(os.environ, {"HTTP_PROXY": "http://untrusted.invalid:8080", "http_proxy": "http://untrusted.invalid:8080"}):
            RpcClient(self.config(url="http://[::1]:18443", timeout=2.5)).call("getblockchaininfo")
        connection = factory.connections[0]
        self.assertEqual((connection.host, connection.port, connection.timeout), ("::1", 18443, 2.5))

    def test_chain_mismatch_never_reaches_requested_method(self):
        factory = self.mock_http({**CHAIN, "chain": "main"})
        with self.assertRaisesRegex(RpcError, "configured expected chain"):
            RpcClient(self.config()).call("getflowmeshbalance", ["B3"])
        self.assertEqual(len(factory.requests), 1)

    def test_each_read_operation_reverifies_chain(self):
        factory = self.mock_http(CHAIN, [], {**CHAIN, "chain": "main"})
        client = RpcClient(self.config())
        client.call("listflowmeshmarkets")
        with self.assertRaises(RpcError):
            client.call("listflowmeshmarkets")
        self.assertEqual([r[2]["method"] for r in factory.requests], ["getblockchaininfo", "listflowmeshmarkets", "getblockchaininfo"])

    def test_all_write_methods_require_explicit_boolean_authorization(self):
        factory = self.mock_http()
        client = RpcClient(self.config())
        for method in WRITE_METHODS:
            for authorization in (False, 1, "yes", None):
                with self.subTest(method=method, authorization=authorization), self.assertRaises(RpcError):
                    client.call(method, [], allow_regtest_write=authorization)
        self.assertFalse(factory.requests)

    def test_write_pin_must_be_regtest_before_connecting(self):
        factory = self.mock_http()
        with self.assertRaisesRegex(RpcError, "expected_chain"):
            RpcClient(self.config(expected_chain="main")).call("submitflowmeshorder", [], allow_regtest_write=True)
        self.assertFalse(factory.requests)

    def test_all_supported_writes_are_gated_and_wallet_scoped(self):
        factory = self.mock_http(*[reply for _ in WRITE_METHODS for reply in (CHAIN, {"accepted": True})])
        client = RpcClient(self.config())
        for method in sorted(WRITE_METHODS):
            self.assertEqual(client.call(method, ["example"], allow_regtest_write=True), {"accepted": True})
        for before, mutation in zip(factory.requests[::2], factory.requests[1::2]):
            self.assertEqual((before[1], before[2]["method"]), ("/", "getblockchaininfo"))
            self.assertEqual(mutation[1], "/wallet/flowmesh")

    def test_write_gate_rejects_unsynced_and_malformed_chain_state(self):
        cases = (
            {**CHAIN, "chain": "main"}, {**CHAIN, "initialblockdownload": True},
            {**CHAIN, "initialblockdownload": 0}, {**CHAIN, "headers": 101},
            {**CHAIN, "blocks": True}, {**CHAIN, "headers": -1},
            {**CHAIN, "blocks": 100.0}, {"chain": "regtest"}, [], None,
        )
        for state in cases:
            with self.subTest(state=state):
                factory = OfflineHTTP([state])
                with patch("flowmesh_app.rpc.http.client.HTTPConnection", factory), self.assertRaises(RpcError):
                    RpcClient(self.config()).call("createflowmeshvaulttx", [], allow_regtest_write=True)
                self.assertEqual(len(factory.requests), 1)

    def test_unknown_and_sensitive_methods_never_connect(self):
        factory = self.mock_http()
        client = RpcClient(self.config())
        for method in ("walletpassphrase", "walletlock", "dumpprivkey", "importprivkey", "sendrawtransaction", "addnode", "stop", "getnewaddress", "help", "getwalletinfo", "", None, []):
            with self.subTest(method=method), self.assertRaises(RpcError):
                client.call(method, allow_regtest_write=True)
        self.assertFalse(factory.requests)

    def test_invalid_params_never_connect(self):
        factory = self.mock_http()
        client = RpcClient(self.config())
        for params in ({}, (), "secret", [float("nan")], [float("inf")], [object()]):
            with self.subTest(params=params), self.assertRaises(RpcError):
                client.call("listflowmeshmarkets", params)
        self.assertFalse(factory.requests)

    def test_http_errors_redirects_and_transport_errors_never_echo_secrets(self):
        cases = [FakeResponse(b"__cookie__:topsecret", status) for status in (301, 302, 303, 307, 308, 401, 403, 502)]
        cases.extend((TimeoutError("__cookie__:topsecret"), http.client.BadStatusLine("__cookie__:topsecret")))
        for reply in cases:
            with self.subTest(reply=reply):
                factory = OfflineHTTP([reply])
                with patch("flowmesh_app.rpc.http.client.HTTPConnection", factory), self.assertRaises(RpcError) as caught:
                    RpcClient(self.config()).call("getblockchaininfo")
                self.assertNotIn("topsecret", str(caught.exception))
                self.assertEqual(len(factory.requests), 1)
                self.assertTrue(factory.connections[0].closed)

    def test_server_error_keeps_numeric_code_but_omits_remote_text_and_data(self):
        response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -5, "message": "__cookie__:topsecret", "data": {"Authorization": "Basic X19jb29raWVfXzp0b3BzZWNyZXQ="}}}
        self.mock_http(FakeResponse(json.dumps(response).encode(), 500))
        with self.assertRaises(RpcError) as caught:
            RpcClient(self.config()).call("getblockchaininfo")
        self.assertEqual(caught.exception.code, -5)
        self.assertNotIn("topsecret", str(caught.exception))
        self.assertNotIn("X19jb29raWVfXzp0b3BzZWNyZXQ=", str(caught.exception))

    def test_lost_or_invalid_write_response_reports_unknown_outcome_without_retry(self):
        cases = (TimeoutError("__cookie__:topsecret"), FakeResponse(b"malformed secret"), FakeResponse(b"secret", 502))
        for reply in cases:
            with self.subTest(reply=reply):
                factory = OfflineHTTP([CHAIN, reply])
                with patch("flowmesh_app.rpc.http.client.HTTPConnection", factory), self.assertRaises(RpcError) as caught:
                    RpcClient(self.config()).call("submitflowmeshorder", [], allow_regtest_write=True)
                self.assertIn("outcome may be unknown", str(caught.exception))
                self.assertIn("inspect node and wallet state before retrying", str(caught.exception))
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual([request[2]["method"] for request in factory.requests], ["getblockchaininfo", "submitflowmeshorder"])
                self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_malformed_json_envelopes_and_nonfinite_values_are_rejected(self):
        bodies = (
            b"not json topsecret", b"\xff", b"[]", b"{}",
            b'{"jsonrpc":"2.0","id":99,"result":{}}',
            b'{"jsonrpc":"2.0","id":true,"result":{}}',
            b'{"jsonrpc":"2.0","id":1.0,"result":{}}',
            b'{"jsonrpc":"1.0","id":1,"result":{}}',
            b'{"jsonrpc":"2.0","id":1,"id":1,"result":{}}',
            b'{"jsonrpc":"2.0","id":1,"error":null}',
            b'{"jsonrpc":"2.0","id":1,"error":"topsecret"}',
            b'{"jsonrpc":"2.0","id":1,"error":{"code":true,"message":"topsecret"}}',
            b'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":false}}',
            b'{"jsonrpc":"2.0","id":1,"result":{},"error":{"code":-1,"message":"topsecret"}}',
            b'{"jsonrpc":"2.0","id":1,"result":NaN}',
            b'{"jsonrpc":"2.0","id":1,"result":Infinity}',
            b'{"jsonrpc":"2.0","id":1,"result":-Infinity}',
            b'{"jsonrpc":"2.0","id":1,"result":1e9999999999999999999999999999999999999999}',
        )
        for body in bodies:
            with self.subTest(body=body):
                factory = OfflineHTTP([FakeResponse(body)])
                with patch("flowmesh_app.rpc.http.client.HTTPConnection", factory), self.assertRaises(RpcError) as caught:
                    RpcClient(self.config()).call("getblockchaininfo")
                self.assertNotIn("topsecret", str(caught.exception))

    def test_response_size_is_bounded(self):
        response = FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 2))
        self.mock_http(response)
        with self.assertRaisesRegex(RpcError, "response exceeds"):
            RpcClient(self.config()).call("getblockchaininfo")
        self.assertEqual(response.read_sizes, [MAX_RESPONSE_BYTES + 1])

    def test_cookie_size_format_and_missing_cookie_fail_without_connecting(self):
        factory = self.mock_http()
        for cookie in (b"", b"secret", b":secret", b"__cookie__:", b"__cookie__:sec ret", b"__cookie__:secret\n\n", b"__cookie__:secret\x00", b"x" * (MAX_COOKIE_BYTES + 1)):
            with self.subTest(cookie=cookie[:20]):
                self.cookie.write_bytes(cookie)
                with self.assertRaises(RpcError):
                    RpcClient(self.config()).call("getblockchaininfo")
        self.cookie.unlink()
        with self.assertRaises(RpcError):
            RpcClient(self.config()).call("getblockchaininfo")
        self.assertFalse(factory.connections)

    def test_cookie_accepts_one_terminal_newline(self):
        for ending in (b"\n", b"\r\n"):
            self.cookie.write_bytes(b"__cookie__:secret" + ending)
            factory = OfflineHTTP([CHAIN])
            with patch("flowmesh_app.rpc.http.client.HTTPConnection", factory):
                RpcClient(self.config()).call("getblockchaininfo")
            self.assertEqual(factory.requests[0][3]["Authorization"], "Basic " + base64.b64encode(b"__cookie__:secret").decode())

    def test_cookie_symlink_and_directory_are_rejected(self):
        factory = self.mock_http()
        with self.assertRaises(RpcError):
            RpcClient(self.config(cookie_file=self.directory)).call("getblockchaininfo")
        link = self.directory / "cookie-link"
        try:
            link.symlink_to(self.cookie)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this platform.")
        with self.assertRaises(RpcError):
            RpcClient(self.config(cookie_file=link)).call("getblockchaininfo")
        self.assertFalse(factory.connections)

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits are not Windows ACLs")
    def test_group_and_world_cookie_access_is_rejected(self):
        factory = self.mock_http()
        for mode in (0o644, 0o640, 0o604, 0o620, 0o601):
            with self.subTest(mode=oct(mode)):
                self.cookie.chmod(mode)
                with self.assertRaisesRegex(RpcError, "permissions"):
                    RpcClient(self.config()).call("getblockchaininfo")
        self.assertFalse(factory.connections)

    @unittest.skipUnless(os.name == "posix", "POSIX FIFO check")
    def test_fifo_cookie_is_rejected_without_opening(self):
        fifo = self.directory / "fifo"
        os.mkfifo(fifo, 0o600)
        factory = self.mock_http()
        with self.assertRaises(RpcError):
            RpcClient(self.config(cookie_file=fifo)).call("getblockchaininfo")
        self.assertFalse(factory.connections)


if __name__ == "__main__":
    unittest.main()
