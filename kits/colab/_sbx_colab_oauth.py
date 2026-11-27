"""Configure google-colab-cli OAuth inside /opt/colab/venv for Docker Sandbox proxy.

Loaded automatically via sbx_colab_oauth.pth in /opt/colab/venv's site-packages
(immune to Debian's /usr/lib/python3.*/sitecustomize.py shadowing):

1. Rewrites token_uri on InstalledAppFlow.from_client_config to Google's
   disjoint endpoint (https://accounts.google.com/o/oauth2/token) so
   google-colab never collides with Antigravity's oauth2.googleapis.com/token
   route in the sandbox proxy.
2. Defaults include_client_id=True on requests_oauthlib.OAuth2Session.fetch_token
   (RFC 6749 client_secret_post) so the proxy does not strip client credentials
   sent via Authorization: Basic headers.
3. Populates client_id/client_secret at runtime from colab_cli's bundled
   oauth_config.json when loading the proxy-seeded sentinel credentialFile
   (~/.config/colab-cli/token.json), keeping all client config out of colab.yaml.
"""

_SBX_COLAB_TOKEN_URI = "https://accounts.google.com/o/oauth2/token"


def _load_bundled_installed_config():
    import json
    from importlib import resources

    raw = resources.files("colab_cli").joinpath("oauth_config.json").read_text(encoding="utf-8")
    return json.loads(raw).get("installed", {})


try:
    from functools import wraps
    from requests_oauthlib import OAuth2Session

    _orig_fetch_token = OAuth2Session.fetch_token

    @wraps(_orig_fetch_token)
    def _sbx_fetch_token(self, *args, **kwargs):
        kwargs.setdefault("include_client_id", True)
        return _orig_fetch_token(self, *args, **kwargs)

    OAuth2Session.fetch_token = _sbx_fetch_token
except Exception:
    pass

try:
    from google_auth_oauthlib.flow import InstalledAppFlow

    _orig_from_client_config = InstalledAppFlow.from_client_config.__func__

    @classmethod
    def _sbx_from_client_config(cls, client_config, scopes, **kwargs):
        if isinstance(client_config, dict):
            patched = {}
            for section, value in client_config.items():
                if isinstance(value, dict) and "token_uri" in value:
                    updated = dict(value)
                    updated["token_uri"] = _SBX_COLAB_TOKEN_URI
                    patched[section] = updated
                else:
                    patched[section] = value
            client_config = patched
        return _orig_from_client_config(cls, client_config, scopes, **kwargs)

    InstalledAppFlow.from_client_config = _sbx_from_client_config
except Exception:
    pass

try:
    from google.oauth2.credentials import Credentials

    _orig_from_authorized_user_info = Credentials.from_authorized_user_info.__func__

    @classmethod
    def _sbx_from_authorized_user_info(cls, info, scopes=None):
        if isinstance(info, dict) and (not info.get("client_id") or not info.get("client_secret")):
            try:
                bundled = _load_bundled_installed_config()
                merged = dict(info)
                merged.setdefault("client_id", bundled.get("client_id", ""))
                merged.setdefault("client_secret", bundled.get("client_secret", ""))
                merged["token_uri"] = _SBX_COLAB_TOKEN_URI
                info = merged
            except Exception:
                pass
        creds = _orig_from_authorized_user_info(cls, info, scopes=scopes)
        creds._token_uri = _SBX_COLAB_TOKEN_URI
        return creds

    Credentials.from_authorized_user_info = _sbx_from_authorized_user_info
except Exception:
    pass
