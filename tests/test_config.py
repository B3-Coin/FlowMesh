from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest

from flowmesh_app.config import ConfigError, RpcConfig, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def write_config(self, text):
        path = self.directory / "flowmesh.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def config(self, **overrides):
        values = {"url": "http://127.0.0.1:18443", "wallet": "my wallet", "cookie_file": self.directory / ".cookie"}
        values.update(overrides)
        return RpcConfig(**values)

    def test_numeric_loopback_variants(self):
        for url in ("http://127.0.0.1:18443", "http://127.34.56.78:1/", "http://[::1]:65535", "http://[0:0:0:0:0:0:0:1]:18443/"):
            with self.subTest(url=url):
                self.assertEqual(self.config(url=url).url, url)

    def test_rejects_unsafe_or_ambiguous_urls(self):
        values = (
            "http://localhost:18443", "http://example.com:18443",
            "http://192.168.1.1:18443", "http://0.0.0.0:18443",
            "http://[::]:18443", "http://[::ffff:127.0.0.1]:18443",
            "http://[::1%25lo0]:18443", "https://127.0.0.1:18443",
            "ftp://127.0.0.1:18443", "http://127.0.0.1",
            "http://127.0.0.1:0", "http://127.0.0.1:65536",
            "http://127.0.0.1:-1", "http://127.0.0.1:+80",
            "http://127.0.0.1:８０", "http://127.0.0.1:18443/wallet/foo",
            "http://127.0.0.1:18443/?", "http://127.0.0.1:18443/#",
            "http://127.0.0.1:18443/?password=topsecret",
            "http://alice:topsecret@127.0.0.1:18443", "http://@127.0.0.1:18443",
            " http://127.0.0.1:18443", "http://127.0.0.1:18443\n",
            "http://127.0.0.1:\t18443", "http://127.0.0.1:18443/\\evil",
            "http://2130706433:18443", "http://127.1:18443",
            "http://0177.0.0.1:18443", "http://127.000.0.1:18443",
            "http://[broken:18443", "", None, 42,
        )
        for value in values:
            with self.subTest(url=value), self.assertRaises(ConfigError) as caught:
                self.config(url=value)
            self.assertNotIn("topsecret", str(caught.exception))

    def test_wallet_validation_and_frozen_config(self):
        for wallet in ("", "   ", "x" * 257, "name\n", "name\x00", "name\u200b", None, 42):
            with self.subTest(wallet=wallet), self.assertRaises(ConfigError):
                self.config(wallet=wallet)
        valid = self.config(wallet="research/钱包 & #?%")
        with self.assertRaises(FrozenInstanceError):
            valid.wallet = "other"

    def test_chain_and_timeout_validation(self):
        for chain in ("main", "test", "testnet4", "signet", "regtest"):
            self.assertEqual(self.config(expected_chain=chain).expected_chain, chain)
        for chain in ("mainnet", "testnet", "", [], True):
            with self.subTest(chain=chain), self.assertRaises(ConfigError):
                self.config(expected_chain=chain)
        for timeout in (0, -1, 61, True, "5", float("nan"), float("inf"), 10**1000):
            with self.subTest(timeout=timeout), self.assertRaises(ConfigError):
                self.config(timeout=timeout)
        self.assertEqual(self.config(timeout=0.1).timeout, 0.1)

    def test_load_defaults_and_relative_cookie_path(self):
        path = self.write_config('[rpc]\nurl = "http://127.0.0.1:18443"\nwallet = "flowmesh"\ncookie_file = "regtest/.cookie"\n')
        config = load_config(path)
        self.assertEqual(config.cookie_file, self.directory / "regtest" / ".cookie")
        self.assertEqual(config.expected_chain, "regtest")
        self.assertEqual(config.timeout, 5)

    def test_explicit_home_expansion_but_no_environment_expansion(self):
        path = self.write_config('[rpc]\nurl = "http://127.0.0.1:18443"\nwallet = "flowmesh"\ncookie_file = "~/.b3/regtest/.cookie"\n')
        self.assertEqual(load_config(path).cookie_file, Path("~/.b3/regtest/.cookie").expanduser())
        path = self.write_config('[rpc]\nurl = "http://127.0.0.1:18443"\nwallet = "flowmesh"\ncookie_file = "$RPC_COOKIE"\n')
        self.assertEqual(load_config(path).cookie_file, self.directory / "$RPC_COOKIE")

    def test_cookie_symlink_is_not_resolved_by_loading(self):
        target = self.directory / "real-cookie"
        target.write_text("__cookie__:secret", encoding="ascii")
        link = self.directory / "cookie-link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this platform.")
        path = self.write_config('[rpc]\nurl = "http://127.0.0.1:18443"\nwallet = "flowmesh"\ncookie_file = "cookie-link"\n')
        self.assertEqual(load_config(path).cookie_file, link)
        self.assertTrue(load_config(path).cookie_file.is_symlink())

    def test_strict_tables_keys_types_and_malformed_files(self):
        valid = '[rpc]\nurl = "http://127.0.0.1:18443"\nwallet = "flowmesh"\ncookie_file = ".cookie"\n'
        invalid = (
            "", "rpc = 42", "[rpc", valid + 'password = "topsecret"\n',
            valid + '[extra]\nvalue = 1\n', valid.replace('wallet = "flowmesh"\n', ""),
            valid.replace('cookie_file = ".cookie"', 'cookie_file = ""'),
            valid.replace('cookie_file = ".cookie"', 'cookie_file = false'),
            valid + 'timeout = nan\n', valid + 'timeout = true\n',
            valid + '[rpc.extra]\nvalue = 1\n',
        )
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ConfigError) as caught:
                load_config(self.write_config(text))
            self.assertNotIn("topsecret", str(caught.exception))
        with self.assertRaises(ConfigError):
            load_config(self.directory / "absent")

    def test_direct_config_requires_path(self):
        with self.assertRaises(ConfigError):
            self.config(cookie_file="/some/cookie")
        with self.assertRaises(ConfigError):
            self.config(cookie_file=Path("cookie\x00secret"))


if __name__ == "__main__":
    unittest.main()
