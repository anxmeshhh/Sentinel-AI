"""Google/Microsoft OAuth client registration.

Each provider is only registered if its client id/secret is actually
configured, so the app runs fine with neither set - the corresponding
/auth/{provider}/login route just returns a clear "not configured" error
until real credentials are added to .env (see .env.example).
"""

from authlib.integrations.starlette_client import OAuth

from app.core.config import get_settings

_settings = get_settings()
oauth = OAuth()

GOOGLE_CONFIGURED = bool(_settings.google_client_id and _settings.google_client_secret)
MICROSOFT_CONFIGURED = bool(_settings.microsoft_client_id and _settings.microsoft_client_secret)

if GOOGLE_CONFIGURED:
    oauth.register(
        name="google",
        client_id=_settings.google_client_id,
        client_secret=_settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # Separate client for the Calendar/Gmail "Connect" flow (as opposed to
    # login above) - broader data scopes. access_type=offline + prompt=consent
    # (what makes Google actually issue a refresh_token) are passed explicitly
    # at the authorize_redirect() call site in routes/integrations.py, not
    # here - verified directly that client_kwargs doesn't reliably propagate
    # access_type through to the real redirect URL.
    #
    # calendar.events (not the broader "calendar" scope) - read+write on
    # events specifically (what the AI Command orchestrator needs to create
    # events/Meet links), without granting calendar *settings* access.
    # Existing connections were authorized under the old read-only
    # calendar.readonly scope; they need to go through "Reconnect Google"
    # once for this to take effect - prompt=consent already forces a real
    # re-consent screen showing the new scope, no separate migration needed.
    # drive.readonly - Drive search/metadata only, never write, same
    # least-privilege posture as everything else. Also means another
    # "Reconnect Google" is needed for existing connections, same as the
    # calendar.events scope bump above.
    #
    # calendar.readonly, alongside calendar.events - confirmed directly that
    # calendar.events alone 403s with "insufficient scope" when reading a
    # calendar other than the user's own (e.g. Google's public "Holidays in
    # India" calendar, id en.indian#holiday@group.v.calendar.google.com) -
    # calendar.events is scoped to the user's own event operations, not
    # arbitrary calendarId lookups. Both scopes together: full read of any
    # calendar the token can see, plus write on the user's own events.
    oauth.register(
        name="google_data",
        client_id=_settings.google_client_id,
        client_secret=_settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": (
                "openid email "
                "https://www.googleapis.com/auth/calendar.readonly "
                "https://www.googleapis.com/auth/calendar.events "
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/drive.readonly"
            ),
        },
    )

GITHUB_CONFIGURED = bool(_settings.github_client_id and _settings.github_client_secret)

if GITHUB_CONFIGURED:
    # GitHub is not an OpenID provider, so there is no discovery document to
    # point at - the two endpoints are given explicitly.
    #
    # Scopes: `repo` covers private repository metadata (the client fetches
    # titles, timestamps, authors and file paths only - never diffs, see
    # github_client.py), and `read:org` is what lets an org member see the
    # org's repositories at all. Nothing here grants write access; the one
    # write action Sentinel declares for GitHub is unavailable precisely
    # because it would need a scope this deliberately does not request.
    oauth.register(
        name="github",
        client_id=_settings.github_client_id,
        client_secret=_settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "repo read:org"},
    )

if MICROSOFT_CONFIGURED:
    oauth.register(
        name="microsoft",
        client_id=_settings.microsoft_client_id,
        client_secret=_settings.microsoft_client_secret,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # Separate client for the Microsoft 365 "Connect" data flow, mirroring
    # google_data. offline_access is what makes Entra issue a refresh_token;
    # Mail.Read + Calendars.Read are Sprint 1's least-privilege Graph scopes
    # (read-only, metadata used). Extended per sprint as services are added.
    # "common" allows both work/school and personal Microsoft accounts.
    #
    # Deliberately NO "openid"/"email" scope here, so Microsoft issues no ID
    # token and authlib never tries to validate one. Reason: the "common"
    # endpoint's discovery document advertises issuer
    # "https://login.microsoftonline.com/{tenantid}/v2.0" - a LITERAL,
    # unsubstituted template, confirmed directly against Microsoft's live
    # metadata - while a real ID token's `iss` claim is the concrete signed-in
    # tenant. authlib compares the two verbatim, they can never match, and
    # authorize_access_token() raises mid-validation before our code even
    # runs. We only need the access_token to call Graph, so skipping the ID
    # token sidesteps a landmine baked into Microsoft's multi-tenant endpoint
    # rather than working around it after the fact. Account identity is
    # resolved from Graph's own /me instead (see integrations.py callback).
    oauth.register(
        name="microsoft_data",
        client_id=_settings.microsoft_client_id,
        client_secret=_settings.microsoft_client_secret,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        # User.Read is the baseline Graph needs to serve /me at all (that's
        # what fetch_account_identity calls) - confirmed directly: without it
        # Graph returns 403 on /me even with Mail.Read/Calendars.Read granted,
        # since those only cover mail/calendar resources, not the profile
        # endpoint itself. It's the single most common Graph delegated scope
        # and needs no admin consent on a personal or standard work account.
        client_kwargs={"scope": "offline_access User.Read Mail.Read Calendars.Read Team.ReadBasic.All Channel.ReadBasic.All"},
    )

# Slack OAuth v2 is driven manually (see integrations/slack_auth.py), not through
# authlib: v2 uses comma-separated bot scopes and a non-standard token response
# (the bot token at `access_token`, plus `team`/`authed_user`), so an explicit
# exchange is more predictable than bending authlib to it. This flag only gates
# whether the routes are live.
SLACK_CONFIGURED = bool(_settings.slack_client_id and _settings.slack_client_secret)
