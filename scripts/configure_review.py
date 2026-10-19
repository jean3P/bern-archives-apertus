"""Create a local OAuth configuration without printing secrets or overwriting existing settings."""

import argparse
import os
from pathlib import Path
import secrets
from urllib.parse import urlparse


def configure(client_id, callback="http://127.0.0.1:17863/auth/huggingface/callback", output=".env.review-oauth"):
    if not client_id or any(c.isspace() or c in "'\"$#=" for c in client_id):
        raise ValueError("Provide the public OAuth client ID, not a client secret or access token")
    parsed = urlparse(callback)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/auth/huggingface/callback"
            or parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or any(c.isspace() or c in "'\"$#" for c in callback)):
        raise ValueError("Use the registered HTTPS callback, or HTTP on a loopback host only")
    path = Path(output)
    # O_EXCL prevents accidental replacement of a configured server's private settings.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(f"BERN_REVIEW_HF_CLIENT_ID={client_id}\n"
                     f"BERN_REVIEW_HF_REDIRECT_URI={callback}\n"
                     f"BERN_REVIEW_SESSION_SECRET={secrets.token_urlsafe(48)}\n")
    path.chmod(0o600)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--callback", default="http://127.0.0.1:17863/auth/huggingface/callback")
    parser.add_argument("--out", default=".env.review-oauth")
    args = parser.parse_args()
    try:
        path = configure(args.client_id, args.callback, args.out)
    except FileExistsError:
        parser.exit(1, "Configuration already exists and was kept unchanged. Edit it locally if necessary.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Configuration not created: {error}\n")
    print(f"Created {path.name}; the private session secret was generated locally and is not displayed.")
    print(f"Register this exact Redirect URI in the OAuth application settings: {args.callback}")


if __name__ == "__main__":
    main()
