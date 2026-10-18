"""Saved-run review dashboard (S5). Reads recorded runs only; never calls the model."""

import argparse

from ui.run_review import CSS, THEME, build_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="", help="initial saved run folder")
    parser.add_argument("--runs-root", default="runs", help="folder containing completed saved runs")
    parser.add_argument("--allow-evaluation", action="store_true",
                        help="explicitly allow review of an already-used evaluation split")
    parser.add_argument("--port", type=int, default=7862)
    args = parser.parse_args()
    build_app(args.run, runs_root=args.runs_root, allow_evaluation=args.allow_evaluation).launch(
                               server_name="127.0.0.1", server_port=args.port,
                               share=False, theme=THEME, css=CSS)


if __name__ == "__main__":
    main()
