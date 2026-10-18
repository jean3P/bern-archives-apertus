"""Saved-run review dashboard (S5). Reads recorded runs only; never calls the model."""

import argparse

from ui.run_review import CSS, THEME, build_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="", help="saved development run folder")
    parser.add_argument("--port", type=int, default=7862)
    args = parser.parse_args()
    build_app(args.run).launch(server_name="127.0.0.1", server_port=args.port,
                               share=False, theme=THEME, css=CSS)


if __name__ == "__main__":
    main()