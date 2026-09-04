"""AIROS V3 - AI Gateway package (DEC-005).

The gateway is the ONLY place that knows about AI providers and their keys
(ISS-004). Engines and routers receive an injected key and never read
secrets themselves.
"""

from ai.gateway import GatewayError, extract_rich_profile_from_text

__all__ = ["GatewayError", "extract_rich_profile_from_text"]
