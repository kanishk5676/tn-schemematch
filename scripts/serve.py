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


def build_client(backend: str, model: str):
    if backend == "none":
        return None
    env_var = "ANTHROPIC_API_KEY" if backend == "anthropic" else "OPENAI_API_KEY"
    if not os.environ.get(env_var):
        print(f"\n  {env_var} is not set.")
        print(f"  Set it, or run rules-only with --backend none:\n")
        print(f"    export {env_var}='...'")
        print(f"    python scripts/serve.py --backend none\n")
        raise SystemExit(2)
    from tn_schemematch.systems.clients import AnthropicClient, CachingClient, OpenAIClient
    inner = (AnthropicClient(model=model, max_retries=1) if backend == "anthropic"
             else OpenAIClient(model=model, max_retries=1))
    return CachingClient(inner)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "openai", "none"],
                        default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", 5001)))
    parser.add_argument("--max-questions", type=int, default=15)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    client = build_client(args.backend, args.model)
    app = create_app(client=client, max_questions=args.max_questions, debug=args.debug)
    print(f"\n  TN-SchemeMatch → http://{args.host}:{args.port}")
    print(f"  model: {getattr(client, 'name', 'none (rules only)')}\n")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
