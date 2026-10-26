#!/usr/bin/env python3
"""Run Udhavi, the scheme assistant, in a browser.

    python scripts/serve.py --backend none                    # no model: guided mode only
    python scripts/serve.py --model claude-haiku-5-5          # cheap model, ~1 cent a chat
    python scripts/serve.py --daily-budget 0.50               # stop spending at $0.50 a day

With no model, or once the daily budget is spent, the assistant carries on in guided mode:
fixed questions in Tamil or English, answered by button, number or voice.

Bootstraps sys.path the same way scripts/demo.py does, so it runs correctly regardless of
what state the editable install's console script is in. `schemematch serve` is the same
thing with a nicer name.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tn_schemematch.web import create_app  # noqa: E402


def build_client(backend: str, model: str | None, meter=None):
    from tn_schemematch.systems.clients import has_credentials, make_client
    if not has_credentials(backend):
        # Never refuse to start: without a key the assistant runs in guided mode.
        env_var = "ANTHROPIC_API_KEY" if backend == "anthropic" else "OPENAI_API_KEY"
        print(f"\n  No {env_var} found — starting in guided mode (no model).")
        print(f"  To let people talk freely, set it and restart:  export {env_var}='...'")
        return None
    return make_client(backend, model, max_retries=1, meter=meter)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "openai", "none"],
                        default="anthropic")
    parser.add_argument("--model", default=None,
                        help="defaults to claude-opus-5-5 (anthropic) / gpt-4o (openai)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", 5001)))
    parser.add_argument("--max-questions", type=int, default=15)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--vault-dir", default=None,
                        help="where saved profiles and documents live (default data/vault)")
    parser.add_argument("--daily-budget", type=float,
                        default=float(os.environ["DAILY_BUDGET_USD"])
                        if os.environ.get("DAILY_BUDGET_USD") else None,
                        help="US dollars the model may spend per day; then guided mode")
    args = parser.parse_args()

    from tn_schemematch.systems.budget import UsageMeter
    from tn_schemematch.vault import DEFAULT_VAULT_DIR
    vault_dir = Path(args.vault_dir) if args.vault_dir else DEFAULT_VAULT_DIR
    meter = UsageMeter(path=vault_dir / "usage.json", daily_budget_usd=args.daily_budget)
    client = None if args.backend == "none" else build_client(args.backend, args.model, meter)
    app = create_app(client=client, max_questions=args.max_questions, debug=args.debug,
                     vault_dir=args.vault_dir)
    print(f"\n  Udhavi → http://{args.host}:{args.port}")
    print(f"  model: {getattr(client, 'name', 'none — guided mode only')}")
    if client is not None:
        cap = (f"${args.daily_budget:.2f} a day" if args.daily_budget is not None
               else "no daily cap (set --daily-budget)")
        print(f"  spent today: ${meter.spent_today():.4f} · {cap}")
    print()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
