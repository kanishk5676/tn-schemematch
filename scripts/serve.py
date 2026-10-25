#!/usr/bin/env python3
"""Run the web interview.

    python scripts/serve.py                       # live, with the model
    python scripts/serve.py --backend none        # rules only, no network at all

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


def build_client(backend: str, model: str | None):
    from tn_schemematch.systems.clients import has_credentials, make_client
    if not has_credentials(backend):
        env_var = "ANTHROPIC_API_KEY" if backend == "anthropic" else "OPENAI_API_KEY"
        print(f"\n  No credentials found for the {backend} backend.")
        print(f"  Set {env_var}, or run rules-only with --backend none:\n")
        print(f"    export {env_var}='...'")
        print(f"    python scripts/serve.py --backend none\n")
        raise SystemExit(2)
    return make_client(backend, model, max_retries=1)


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
    args = parser.parse_args()

    client = build_client(args.backend, args.model)
    app = create_app(client=client, max_questions=args.max_questions, debug=args.debug,
                     vault_dir=args.vault_dir)
    print(f"\n  TN-SchemeMatch → http://{args.host}:{args.port}")
    print(f"  model: {getattr(client, 'name', 'none (rules only)')}\n")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
