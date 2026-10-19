"""Saved-run review dashboard (S5). Reads recorded runs only; never calls the model."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from ui.run_review import CSS, THEME, build_app


def main():
    # Dedicated ignored operator configuration, not the model/LIVE environment.
    load_dotenv(Path(__file__).resolve().parent / ".env.review-oauth", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="", help="initial saved run folder")
    parser.add_argument("--runs-root", default="runs", help="folder containing completed saved runs")
    parser.add_argument("--allow-evaluation", action="store_true",
                        help="explicitly allow review of an already-used evaluation split")
    parser.add_argument("--port", type=int, default=7862)
    parser.add_argument("--host", default="127.0.0.1", help="bind address; use 0.0.0.0 only inside a private container")
    args = parser.parse_args()
    if os.environ.get("BERN_REVIEW_HF_CLIENT_ID", "").strip():
        import uvicorn
        from ui.hf_review_auth import build_authenticated_server
        server = build_authenticated_server(args.run, runs_root=args.runs_root,
                                             allow_evaluation=args.allow_evaluation, server_name=args.host)
        uvicorn.run(server, host=args.host, port=args.port, access_log=False)
        return
    build_app(args.run, runs_root=args.runs_root, allow_evaluation=args.allow_evaluation).launch(
                               server_name=args.host, server_port=args.port,
                               share=False, theme=THEME, css=CSS)


if __name__ == "__main__":
    main()
