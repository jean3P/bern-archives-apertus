"""One explicit archival question with a new, non-overwriting run directory."""

import argparse
import json
from pathlib import Path
import sys

from core.answering import run_answer


def main():
    parser = argparse.ArgumentParser(description="Answer from Stapfer evidence with Apertus and checked citations")
    parser.add_argument("question")
    parser.add_argument("--transcription-id", type=int)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--out", type=Path, help="New run directory; existing paths are never overwritten")
    parser.add_argument("--no-query-rewrite", action="store_true", help="Diagnostic literal/explicit-code retrieval only")
    parser.add_argument("--retrieval-mode", choices=("standard", "entity", "coverage", "bound"), default="standard",
                        help="Opt-in named-subject selection followed by related-answer retrieval")
    parser.add_argument("--pipeline", choices=("apertus", "apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"), default="apertus",
                        help="Baseline, concise Apertus/Qwen-only answers, rejected parts experiment, or inactive hybrid")
    args = parser.parse_args()
    try:
        result, directory = run_answer(args.question, args.transcription_id,
            data_dir=args.data_dir, out=args.out, rewrite=not args.no_query_rewrite, pipeline=args.pipeline,
            retrieval_mode=args.retrieval_mode)
    except (OSError, ValueError) as error:
        parser.exit(1, "Cannot create the answer run (" + type(error).__name__ + "). Use a fresh --out path.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Run records: " + str(directory), file=sys.stderr)
    if result["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
