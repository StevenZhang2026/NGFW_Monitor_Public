"""TLS settings for requests that leave the local network.

Deliberately separate from the device-side calls in `collectors/` and
`tasks/collect.py`. Those talk to a PA appliance on a management LAN over a
self-signed certificate, and skipping verification there is a bounded trade-off
on a trusted segment. The destinations here — the LLM provider, Feishu, WeCom —
are on the internet, the request headers carry an API key or a webhook token,
and a man-in-the-middle position is routable, so they verify.

A normal deployment needs no configuration here — these destinations use
publicly trusted certificates. Verification only fails on a dev machine that is
connected to GlobalProtect, where traffic passes a TLS-inspecting proxy that
re-signs the chain with a private root CA. Point OUTBOUND_CA_BUNDLE at that CA
(or just disconnect the VPN) instead of switching verification off.
"""

import ssl
from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=1)
def outbound_verify() -> ssl.SSLContext | bool:
    """`verify` value for an httpx client talking to the internet.

    Returns an SSLContext rather than a path because httpx 0.28 deprecated
    `verify=<str>`.
    """
    if not settings.outbound_tls_verify:
        return False
    if settings.outbound_ca_bundle:
        return ssl.create_default_context(cafile=settings.outbound_ca_bundle)
    return True


def tls_error_hint(exc: BaseException) -> str:
    """Guidance to append to a request failure, when it was a cert rejection.

    Without this the operator sees a bare `CERTIFICATE_VERIFY_FAILED` and has no
    way to know the setting that fixes it. Empty string for any other failure.
    """
    if "CERTIFICATE_VERIFY_FAILED" in str(exc):
        return (
            "（TLS 证书校验失败。若处于 TLS 解密代理之后，"
            "把企业根 CA 的 PEM 路径配到 OUTBOUND_CA_BUNDLE）"
        )
    return ""
