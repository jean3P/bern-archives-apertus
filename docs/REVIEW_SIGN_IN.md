# Test the saved review dashboard

The review dashboard reads saved answers; it does not call a model. Original Jean/Jeni reviews are read-only. A new Hugging Face account starts its own Pending review and exports separately. A draft reference is a provisional evaluation checklist, not an input to live answer generation.

## Update a separate checkout

Save or commit your own work before switching branches. Do not discard another branch's changes.

```bash
git switch main
git pull --ff-only
uv sync --locked --group review-auth
uv run --locked --group review-auth pytest -q tests/ui/test_run_review.py tests/ui/test_reviewer_accounts.py
```

These focused checks use synthetic saved runs. They require neither a GPU nor model inference. The OAuth-server check is skipped if the optional `review-auth` group is not installed.

## Test the already configured dashboard

If an operator has supplied a private dashboard link, open that link rather than starting a second copy. A `127.0.0.1` address points to your own computer, so remote dashboards need your own connection/tunnel.

1. Click **Sign in with Hugging Face** and authorize **Challenge3**. Only profile identity permissions should be requested.
2. Confirm **Signed in as Hugging Face @yourusername** after returning.
3. Choose a saved run folder, then **Start / resume my Hugging Face review**.
4. For a new account, confirm that every case starts **Pending**, with none of Jean's or Jeni's judgments copied into the form.
5. Review one case, click **Save my review (in memory)**, then **Export my reviews separately**.
6. Reload, sign in if needed, and start/resume the same run. Confirm your judgment and account name restore.
7. Confirm the original review collection and its scores remain unchanged.

You must export before closing the tab or changing runs. Signed-in accounts can compare with original judgments after exporting decisions for all cases in that run. Anonymous visitors can already view originals, so the system does not certify blinded review. New accounts receive no guessed institution. Historical manual reviews are not retroactively authenticated.

The real provider redirect has been checked. A successful consent, return and account export still require a real user's test; passing offline checks does not establish that round trip.

## Run your own private copy

Obtain the completed saved run folders separately and set `--runs-root` to their parent directory. Historical baseline exports belong in this checkout's ignored `runs/review-exports/`. Do not commit either collection.

For real sign-in, register an OAuth application with callback `http://127.0.0.1:17863/auth/huggingface/callback` (or your actual HTTPS callback), using a public client without a client secret. Create an ignored, private `.env.review-oauth` in the project root:

```dotenv
BERN_REVIEW_HF_CLIENT_ID=your_registered_public_client_id
BERN_REVIEW_HF_REDIRECT_URI=http://127.0.0.1:17863/auth/huggingface/callback
BERN_REVIEW_SESSION_SECRET=your_locally_generated_random_secret_at_least_32_characters
```

Generate a cryptographically random session secret locally. Never send it through chat or commit it; restrict the file to its owner. On Unix, use `chmod 600 .env.review-oauth`. A server restart signs users out but does not remove their exports.

```bash
uv run --locked --group review-auth python review_app.py \
  --runs-root /path/to/saved/runs \
  --allow-evaluation --port 7863
```

Open the dashboard at the address served by your private connection. If forwarding ports, the browser's callback address must reach that same process. Register the exact callback host/path: `localhost` and `127.0.0.1` are different hosts.

Without OAuth configuration, the dashboard offers read-only original reviews and disables sign-in; typing a name cannot authorize a write. Account exports live under ignored `runs/reviewer-exports/<hashed HF subject>/`, outside original exports. Run names—not absolute storage paths—appear in the selector.

The separate LIVE explorer (`app.py`) makes fresh Apertus requests when **Ask** is clicked. Its Development/Evaluation selector loads only questions and transcription scope, never answer keys or human suggestions. **Answer produced — not human-reviewed** is not a correctness grade.
