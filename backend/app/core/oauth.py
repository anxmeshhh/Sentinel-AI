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

if MICROSOFT_CONFIGURED:
    oauth.register(
        name="microsoft",
        client_id=_settings.microsoft_client_id,
        client_secret=_settings.microsoft_client_secret,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
