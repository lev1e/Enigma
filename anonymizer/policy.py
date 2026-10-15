"""Optional administrator policy for the AI chat (P1). The app only READS it; it never writes it.

No file = nothing is restricted (owner decision, P1): any provider, anonymized or original data, any host.
The file can later be used by the security service to tighten that without a new build.

Location (first that exists wins):
  1. environment variable ANONYMIZER_POLICY (a file path)
  2. Windows: %ProgramData%\\Anonymizer\\policy.json
  3. macOS:   /Library/Application Support/Anonymizer/policy.json
  4. Linux:   /etc/anonymizer/policy.json

Format (all keys optional):
  {"version": 1,
   "allow_originals_to_external": true,           # false = original data may go only to providers of tier "internal"
   "allowed_hosts": ["tedorra.corp.example"],     # empty or absent = no host restriction
   "providers": [{"id": "tedorra", "tier": "internal", "base_url": "https://tedorra.corp.example/v1"}]}

A provider's tier is "internal" or "external". Policy wins over the user's own "internal" flag: a provider matched by id
or by exact scheme + host + port gets the tier from the policy; an unmatched one uses the user's flag, else "external".
A file that exists but cannot be read or is malformed is NOT treated as "no policy": it restricts to the safe side
(originals never leave, other keys ignored) and `status()` says why.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

TIERS = ("internal", "external")


@dataclass(frozen=True)
class Policy:
    present: bool = False
    valid: bool = True
    allow_originals_to_external: bool = True
    allowed_hosts: tuple = ()
    providers: tuple = ()                 # ({"id", "tier", "origin"}, ...)
    note: str = ""


def candidate_paths() -> list[Path]:
    env = os.environ.get("ANONYMIZER_POLICY")
    if env:
        return [Path(env)]
    if os.name == "nt":
        return [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Anonymizer" / "policy.json"]
    if sys.platform == "darwin":
        return [Path("/Library/Application Support/Anonymizer/policy.json")]
    return [Path("/etc/anonymizer/policy.json")]


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url or "")
    if not parts.hostname:
        return ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def load() -> Policy:
    """Read on every call (the file is tiny): a policy change applies to the next request."""
    for path in candidate_paths():
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            hosts = data.get("allowed_hosts") or []
            if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
                raise ValueError("allowed_hosts")
            provs = []
            for item in data.get("providers") or []:
                if not isinstance(item, dict) or item.get("tier") not in TIERS:
                    raise ValueError("providers")
                provs.append({"id": str(item.get("id", "")), "tier": item["tier"], "origin": _origin(str(item.get("base_url", "")))})
            allow = data.get("allow_originals_to_external", True)
            if not isinstance(allow, bool):
                raise ValueError("allow_originals_to_external")
            return Policy(True, True, allow, tuple(h.strip().lower() for h in hosts if h.strip()), tuple(provs))
        except (OSError, ValueError):
            return Policy(True, False, False, (), (), "Файл политики безопасности не читается: исходные данные не отправляются.")
    return Policy()


def tier_of(policy: Policy, provider_id: str, base_url: str, user_internal: bool) -> str:
    origin = _origin(base_url)
    for item in policy.providers:
        if (item["id"] and item["id"] == provider_id) or (origin and item["origin"] == origin):
            return item["tier"]
    return "internal" if user_internal else "external"


def host_allowed(policy: Policy, base_url: str) -> bool:
    if not policy.allowed_hosts:
        return True
    host = (urllib.parse.urlsplit(base_url or "").hostname or "").lower()
    return host in policy.allowed_hosts


def enforce_host(base_url: str) -> None:
    """Called from `llm.validate`: a host outside the allow-list is refused before any byte is written."""
    from .llm import LLMError
    if not host_allowed(load(), base_url):
        raise LLMError("config", "Адрес сервера не входит в список разрешённых политикой безопасности")


def check_originals(policy: Policy, tier: str) -> str:
    """'' when original data may go to a provider of this tier, else a Russian reason."""
    if not policy.present:
        return ""
    if tier == "internal" and policy.valid:
        return ""
    if policy.allow_originals_to_external and policy.valid:
        return ""
    return policy.note or "Политика безопасности не разрешает отправлять исходные данные внешним моделям."


def status() -> dict:
    p = load()
    return {"present": p.present, "valid": p.valid, "allow_originals_to_external": p.allow_originals_to_external,
            "allowed_hosts": list(p.allowed_hosts), "note": p.note}
