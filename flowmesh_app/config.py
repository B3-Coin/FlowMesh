"""Strict, cookie-only configuration for a numeric loopback RPC endpoint."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import tomllib
import unicodedata
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """A configuration problem with a message that never repeats input values."""


def _has_control(value: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in value)


def _validate_url(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or _has_control(value)
        or any(char.isspace() for char in value)
    ):
        raise ConfigError("RPC URL must be an HTTP numeric loopback URL with an explicit port.")
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port
        if (
            parts.scheme != "http"
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or "?" in value
            or "#" in value
            or hostname is None
            or "%" in hostname
            or port is None
            or not 1 <= port <= 65535
        ):
            raise ValueError
        port_text = parts.netloc.rsplit(":", 1)[-1]
        if not port_text or any(char not in "0123456789" for char in port_text):
            raise ValueError
        address = ipaddress.ip_address(hostname)
        if not (
            isinstance(address, ipaddress.IPv4Address)
            and address in ipaddress.IPv4Network("127.0.0.0/8")
            or isinstance(address, ipaddress.IPv6Address)
            and address == ipaddress.IPv6Address("::1")
        ):
            raise ValueError
    except ValueError:
        raise ConfigError("RPC URL must use HTTP, a numeric loopback address, an explicit port, and no credentials or extra path.") from None


@dataclass(frozen=True)
class RpcConfig:
    url: str
    wallet: str
    cookie_file: Path
    expected_chain: str = "regtest"
    timeout: float = 5

    def __post_init__(self) -> None:
        _validate_url(self.url)
        if (
            not isinstance(self.wallet, str)
            or not self.wallet.strip()
            or len(self.wallet) > 256
            or _has_control(self.wallet)
        ):
            raise ConfigError("Wallet must be a nonempty name of at most 256 characters without control characters.")
        if not isinstance(self.cookie_file, Path) or _has_control(str(self.cookie_file)):
            raise ConfigError("Cookie file must be a filesystem path without control characters.")
        if not isinstance(self.expected_chain, str) or self.expected_chain not in {
            "main", "test", "testnet4", "signet", "regtest"
        }:
            raise ConfigError("Expected chain must be main, test, testnet4, signet, or regtest.")
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not 0 < self.timeout <= 60
            or not math.isfinite(self.timeout)
        ):
            raise ConfigError("RPC timeout must be a finite number greater than zero and at most 60 seconds.")


def load_config(path: Path) -> RpcConfig:
    """Load only an [rpc] table; resolve cookie paths without following symlinks.

    The operator may explicitly use ~ in either path. Environment variables are
    never expanded, and credentials cannot be supplied in this file.
    """
    try:
        config_path = Path(path).expanduser().absolute()
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError, RuntimeError, TypeError):
        raise ConfigError("Cannot read a valid TOML configuration file.") from None
    if set(data) != {"rpc"} or not isinstance(data["rpc"], dict):
        raise ConfigError("Configuration must contain only an [rpc] table.")
    settings = data["rpc"]
    required = {"url", "wallet", "cookie_file"}
    allowed = required | {"expected_chain", "timeout"}
    if not required <= set(settings) or set(settings) - allowed:
        raise ConfigError("The [rpc] table requires url, wallet, and cookie_file; only expected_chain and timeout are optional.")
    cookie_text = settings["cookie_file"]
    if not isinstance(cookie_text, str) or not cookie_text.strip() or _has_control(cookie_text):
        raise ConfigError("Cookie file must be a nonempty path without control characters.")
    try:
        cookie_path = Path(cookie_text).expanduser()
        if not cookie_path.is_absolute():
            cookie_path = config_path.parent / cookie_path
    except (ValueError, RuntimeError):
        raise ConfigError("Cannot expand the configured cookie file path.") from None
    return RpcConfig(
        url=settings["url"],
        wallet=settings["wallet"],
        cookie_file=cookie_path,
        expected_chain=settings.get("expected_chain", "regtest"),
        timeout=settings.get("timeout", 5),
    )
