"""Real self-hosted Hugging Face OAuth via Authlib, never Gradio's local mock login."""

import os
import secrets
import time
from urllib.parse import urlparse

from ui.reviewer_accounts import ReviewerIdentity


def oauth_settings():
    client_id = os.environ.get("BERN_REVIEW_HF_CLIENT_ID", "").strip()
    redirect = os.environ.get("BERN_REVIEW_HF_REDIRECT_URI",
                              "http://127.0.0.1:17863/auth/huggingface/callback")
    parsed = urlparse(redirect)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/auth/huggingface/callback"
            or parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Use the registered HTTPS callback, or HTTP on a loopback host only.")
    return client_id, redirect


class SessionIdentities:
    def __init__(self):
        self.identities = {}

    def issue(self, identity):
        self.identities = {key: entry for key, entry in self.identities.items() if entry[1] > time.time()}
        key = secrets.token_urlsafe(32)
        self.identities[key] = (identity, time.time() + 8 * 3600)
        return key

    def get(self, key):
        identity, expiry = self.identities.get(key, (None, 0))
        return identity if expiry > time.time() else None

    def gradio_identity(self, request):
        # username is injected by Gradio from the FastAPI auth dependency, not a UI input.
        return self.get(getattr(request, "username", None)) if request is not None else None


def build_authenticated_server(default_run="", *, runs_root="runs", allow_evaluation=False):
    """Only called after operator OAuth configuration; no host PAT or mock profile fallback."""
    client_id, redirect_uri = oauth_settings()
    if not client_id:
        raise ValueError("Set BERN_REVIEW_HF_CLIENT_ID from a registered Hugging Face OAuth application.")
    secret = os.environ.get("BERN_REVIEW_SESSION_SECRET", "")
    if len(secret) < 32:
        raise ValueError("Set a private BERN_REVIEW_SESSION_SECRET of at least 32 characters.")
    try:
        from authlib.integrations.starlette_client import OAuth
        from starlette.middleware.sessions import SessionMiddleware
    except ImportError as exc:
        raise RuntimeError("Install the optional review-auth group: uv sync --locked --group review-auth") from exc
    from fastapi import FastAPI, Request
    from fastapi.responses import RedirectResponse, PlainTextResponse
    import gradio as gr
    from ui.run_review import CSS, THEME, build_app

    app = FastAPI()
    identities = SessionIdentities()
    # SessionMiddleware is added last so it also wraps the queued-session guard below.
    sessions = {}

    @app.middleware("http")
    async def separate_browser_sessions(request, call_next):
        # Gradio State is indexed by a caller-supplied session hash. Bind it to a
        # signed browser session as well, including read/SSE requests.
        path = request.url.path
        browser = request.session.setdefault("browser", secrets.token_urlsafe(32))
        if path.startswith("/gradio_api/"):
            if path.startswith(tuple("/gradio_api/" + part for part in
                                      ("call/", "run/", "api/", "reset", "cancel", "component_server",
                                       "stream/", "upload", "file=", "deep_link"))):
                return PlainTextResponse("Use the dashboard's queued review interface.", status_code=404)
            session_hash = request.query_params.get("session_hash")
            if request.method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
                try:
                    session_hash = (await request.json()).get("session_hash", session_hash)
                except (ValueError, AttributeError):
                    return PlainTextResponse("Invalid dashboard request.", status_code=400)
            if path.startswith("/gradio_api/heartbeat/"):
                session_hash = path.rsplit("/", 1)[-1]
            if session_hash:
                if not isinstance(session_hash, str) or len(session_hash) > 256:
                    return PlainTextResponse("Invalid dashboard session.", status_code=400)
                principal = request.session.get("review_identity")
                principal = principal if identities.get(principal) else "guest:" + browser
                sessions_copy = {key: entry for key, entry in sessions.items() if entry[1] > time.time()}
                sessions.clear()
                sessions.update(sessions_copy)
                if session_hash in sessions and sessions[session_hash][0] != principal:
                    return PlainTextResponse("This dashboard session belongs to another sign-in. Reload the page.",
                                             status_code=403)
                sessions[session_hash] = (principal, time.time() + 8 * 3600)
        return await call_next(request)
    oauth = OAuth()
    oauth.register(name="huggingface", client_id=client_id,
                   client_secret=os.environ.get("BERN_REVIEW_HF_CLIENT_SECRET") or None,
                   server_metadata_url="https://huggingface.co/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid profile", "code_challenge_method": "S256",
                                  "token_endpoint_auth_method": "client_secret_basic" if os.environ.get(
                                      "BERN_REVIEW_HF_CLIENT_SECRET") else "none"})

    @app.get("/auth/huggingface/login")
    async def login(request: Request):
        return await oauth.huggingface.authorize_redirect(request, redirect_uri)

    @app.get("/auth/huggingface/callback")
    async def callback(request: Request):
        try:
            token = await oauth.huggingface.authorize_access_token(request)
            info = token.get("userinfo") or await oauth.huggingface.userinfo(token=token)
            identity = ReviewerIdentity(info["sub"], info["preferred_username"])
        except Exception:
            # Never print access tokens, codes, state, provider bodies or exception details.
            return PlainTextResponse("Sign-in failed. Return to the dashboard and try again.", status_code=401)
        previous = request.session.get("review_identity")
        identities.identities.pop(previous, None)
        request.session.clear()
        request.session["review_identity"] = identities.issue(identity)
        return RedirectResponse("/", status_code=303)

    @app.get("/auth/logout")
    async def logout(request: Request):
        identities.identities.pop(request.session.get("review_identity"), None)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    def authentication(request: Request):
        key = request.session.get("review_identity")
        return key if identities.get(key) is not None else "anonymous-read-only"

    dashboard = build_app(default_run, runs_root=runs_root, allow_evaluation=allow_evaluation,
                          identity_provider=identities.gradio_identity, oauth_enabled=True)
    app = gr.mount_gradio_app(app, dashboard, path="/", auth_dependency=authentication,
                             server_name="127.0.0.1", show_error=False, theme=THEME, css=CSS)
    app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie="bern_review_session",
                       same_site="lax", https_only=redirect_uri.startswith("https://"), max_age=8 * 3600)
    return app
