#!/usr/bin/env python3
"""check-layers.py — verify that every expected giulia layer is importable.

Run with:
    uv run python scripts/check-layers.py

Exit code 0 = all layers healthy.
Exit code 1 = one or more layers failed to import.

Analogous to `nest doctor` in nandatown.
"""

from __future__ import annotations

import importlib
import sys

LAYERS: dict[str, list[str]] = {
    "giulia.agents.core": ["GiuliaAgent", "AgentYAMLConfig"],
    "giulia.agents.auth.token_mint": ["mint_token", "mint_exchanged_token"],
    "giulia.agents.auth.jwt_auth": ["sign_jwt", "verify_jwt", "JWTValidationError"],
    "giulia.agents.auth.crypto": ["load_private_key_from_file", "public_key_to_jwk"],
    "giulia.agents.a2a": ["to_a2a_giulia"],
    "giulia.agents.delegation": ["DelegationHandler"],
    "giulia.agents.orchestration": ["record_heartbeat"],
    "giulia.agents.registry_client": [
        "register_private_agent",
        "build_agent_card",
        "start_heartbeat",
    ],
    "giulia.agents.services": [],
    "giulia.agents.push_notifications": [],
    "giulia.agents.google_chat": [],
    "giulia.agents.middlewares": [
        "ApiKeyMiddleware",
        "RequestLoggingMiddleware",
        "StripPrefixMiddleware",
    ],
    "giulia.agents.utils.urn": ["urn_to_slug", "urn_to_python_identifier"],
    "giulia.providers": [],
    "giulia.registry": [],
}

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0

print(f"\n{BOLD}giulia layer check{RESET}\n" + "─" * 40)

for module_path, symbols in LAYERS.items():
    try:
        mod = importlib.import_module(module_path)
    except Exception as exc:
        print(f"  {RED}FAIL{RESET}  {module_path}\n        {exc}")
        failed += 1
        continue

    missing = [s for s in symbols if not hasattr(mod, s)]
    if missing:
        print(
            f"  {RED}FAIL{RESET}  {module_path} — missing symbols: {', '.join(missing)}"
        )
        failed += 1
    else:
        label = f"({len(symbols)} symbols)" if symbols else "(importable)"
        print(f"  {GREEN}OK{RESET}    {module_path} {label}")
        passed += 1

print("─" * 40)
total = passed + failed
print(f"\n{passed}/{total} checks passed\n")

if failed:
    sys.exit(1)
