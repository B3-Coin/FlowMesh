"""Small, fail-closed RPC transport. No live connection is opened on import.

Cookie permissions are checked on POSIX. Windows mode bits cannot establish
whether another account has access: operators must restrict the file's ACL.
No environment proxy settings, redirects, retries, or persistent auth are used.
"""

from __future__ import annotations

import base64
from decimal import Decimal, DecimalException
import http.client
import itertools
import json
import os
import stat
from typing import Any
from urllib.parse import quote, urlsplit

from .config import RpcConfig


MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_COOKIE_BYTES = 4096
READ_METHODS = frozenset({
    "getblockchaininfo", "getnetworkinfo", "listflowmeshmarkets",
    "getflowmeshbalance", "listflowmeshvaultoperations",
})
WRITE_METHODS = frozenset({
    "submitflowmeshorder", "cancelflowmeshorder", "startflowmeshvalidator",
    "stopflowmeshvalidator", "createflowmeshcheckpoint", "submitflowmeshdeposit",
    "requestflowmeshwithdrawal", "createflowmeshvaulttx",
})
NODE_METHODS = frozenset({"getblockchaininfo", "getnetworkinfo"})


class RpcError(Exception):
    """Locally authored error text and, if valid, the server's numeric code."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object member")
        result[key] = value
    return result


def _cookie_auth(config: RpcConfig) -> str:
    """Read a bounded, regular cookie through an independently checked handle."""
    descriptor: int | None = None
    try:
        before = config.cookie_file.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise RpcError("RPC cookie must be a regular file, not a symlink.")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(config.cookie_file, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RpcError("RPC cookie changed while opening; try again explicitly.")
        if os.name == "posix" and opened.st_mode & 0o077:
            raise RpcError("RPC cookie permissions must restrict all access to its owner (for example, mode 0600).")
        if opened.st_size > MAX_COOKIE_BYTES:
            raise RpcError("RPC cookie exceeds the allowed size.")
        cookie = os.read(descriptor, MAX_COOKIE_BYTES + 1)
        if len(cookie) > MAX_COOKIE_BYTES:
            raise RpcError("RPC cookie exceeds the allowed size.")
        if cookie.endswith(b"\r\n"):
            cookie = cookie[:-2]
        elif cookie.endswith(b"\n"):
            cookie = cookie[:-1]
        username, separator, password = cookie.partition(b":")
        if (
            not separator or not username or not password
            or any(byte < 33 or byte > 126 for byte in cookie)
        ):
            raise RpcError("RPC cookie has an invalid authentication format.")
        return "Basic " + base64.b64encode(cookie).decode("ascii")
    except OSError:
        raise RpcError("Cannot securely read the RPC cookie file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


class RpcClient:
    def __init__(self, config: RpcConfig) -> None:
        if not isinstance(config, RpcConfig):
            raise TypeError("RpcClient requires RpcConfig.")
        self.config = config
        parts = urlsplit(config.url)
        self._host = parts.hostname
        self._port = parts.port
        component = quote(config.wallet, safe="")
        if component in {".", ".."}:
            component = component.replace(".", "%2E")
        self._wallet_path = "/wallet/" + component
        self._ids = itertools.count(1)

    def verify_chain(self, *, require_synced_regtest: bool = False) -> dict[str, Any]:
        """Fetch fresh chain state, enforce the pin, and optionally gate writes."""
        if require_synced_regtest and self.config.expected_chain != "regtest":
            raise RpcError("Writes require expected_chain to be regtest.")
        info = self._request("getblockchaininfo", [])
        if not isinstance(info, dict) or info.get("chain") != self.config.expected_chain:
            raise RpcError("Node chain does not match the configured expected chain.")
        if require_synced_regtest:
            blocks, headers = info.get("blocks"), info.get("headers")
            if (
                info.get("chain") != "regtest"
                or info.get("initialblockdownload") is not False
                or type(blocks) is not int
                or type(headers) is not int
                or blocks < 0
                or headers < 0
                or headers > blocks
            ):
                raise RpcError("Writes require a synchronized regtest node with initial block download complete.")
        return info

    def call(
        self, method: str, params: list[Any] | None = None,
        *, allow_regtest_write: bool = False,
    ) -> Any:
        """Call an allowed method, checking the chain immediately before use.

        The write keyword must be explicitly True. The CLI's confirmation is
        additional protection; this transport always enforces the same gate.
        """
        if not isinstance(method, str) or method not in READ_METHODS | WRITE_METHODS:
            raise RpcError("RPC method is not supported by this application.")
        if params is not None and not isinstance(params, list):
            raise RpcError("RPC parameters must be a list.")
        arguments = [] if params is None else params
        if method == "getblockchaininfo" and arguments:
            raise RpcError("getblockchaininfo does not accept parameters.")
        self._encode_request(method, arguments, 0)
        if method in WRITE_METHODS:
            if allow_regtest_write is not True:
                raise RpcError("Writes require explicit regtest write authorization.")
            self.verify_chain(require_synced_regtest=True)
        else:
            info = self.verify_chain()
            if method == "getblockchaininfo":
                return info
        return self._request(method, arguments)

    @staticmethod
    def _encode_request(method: str, params: list[Any], request_id: int) -> bytes:
        try:
            body = json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                ensure_ascii=True, allow_nan=False, separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError, OverflowError):
            raise RpcError("RPC parameters must contain finite JSON values.") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise RpcError("RPC request exceeds the allowed size.")
        return body

    def _request(self, method: str, params: list[Any]) -> Any:
        request_id = next(self._ids)
        body = self._encode_request(method, params, request_id)
        authorization = _cookie_auth(self.config)
        connection = http.client.HTTPConnection(self._host, self._port, timeout=self.config.timeout)
        try:
            connection.request(
                "POST", "/" if method in NODE_METHODS else self._wallet_path,
                body=body,
                headers={"Authorization": authorization, "Content-Type": "application/json", "Accept": "application/json", "Connection": "close"},
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                raise RpcError("RPC redirects are not permitted.")
            if response.status in (401, 403):
                raise RpcError("RPC authentication or authorization was rejected.")
            if response.status not in (200, 400, 404, 500):
                raise RpcError("RPC server returned an unexpected HTTP status.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RpcError("RPC response exceeds the allowed size.")
            try:
                envelope = json.loads(
                    raw.decode("utf-8"), parse_float=Decimal,
                    parse_constant=_reject_constant, object_pairs_hook=_unique_object,
                )
            except (ValueError, UnicodeError, RecursionError, OverflowError, DecimalException):
                raise RpcError("RPC server returned invalid JSON.") from None
            if (
                not isinstance(envelope, dict)
                or envelope.get("jsonrpc") != "2.0"
                or type(envelope.get("id")) is not int
                or envelope["id"] != request_id
            ):
                raise RpcError("RPC response has an invalid version or request ID.")
            if "error" in envelope and envelope["error"] is not None:
                error = envelope["error"]
                if (
                    not isinstance(error, dict)
                    or type(error.get("code")) is not int
                    or not isinstance(error.get("message"), str)
                    or "result" in envelope and envelope["result"] is not None
                ):
                    raise RpcError("RPC server returned an invalid error response.")
                code = error["code"]
                # Remote messages/data may contain reflected credentials. Omit them.
                raise RpcError(f"RPC request failed (code {code}).", code=code)
            if "result" not in envelope or response.status != 200:
                raise RpcError("RPC server returned an invalid result response.")
            return envelope["result"]
        except RpcError as error:
            if method in WRITE_METHODS and error.code is None:
                raise RpcError(
                    str(error) + " Submission outcome may be unknown; inspect node and wallet state before retrying."
                ) from None
            raise
        except (OSError, http.client.HTTPException):
            if method in WRITE_METHODS:
                raise RpcError("Cannot complete the local RPC request. Submission outcome may be unknown; inspect node and wallet state before retrying.") from None
            raise RpcError("Cannot complete the local RPC request; check the node and timeout.") from None
        finally:
            connection.close()
