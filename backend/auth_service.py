# auth_service.py — local disk or env-var OAuth token (works in both modes).

import json
import os
import tempfile

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config


def _from_env():
    if not config.GMAIL_TOKEN_JSON_ENV:
        return None
    creds = Credentials.from_authorized_user_info(
        json.loads(config.GMAIL_TOKEN_JSON_ENV), config.GMAIL_SCOPES,
    )
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _from_disk():
    creds = None
    if os.path.exists(config.GMAIL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(
            config.GMAIL_TOKEN_PATH, config.GMAIL_SCOPES,
        )
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            cred_path = config.GMAIL_CREDENTIALS_PATH
            if config.GMAIL_CREDENTIALS_JSON_ENV:
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
                    t.write(config.GMAIL_CREDENTIALS_JSON_ENV)
                    cred_path = t.name
            flow = InstalledAppFlow.from_client_secrets_file(
                cred_path, config.GMAIL_SCOPES,
            )
            creds = flow.run_local_server(port=0)
        with open(config.GMAIL_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def get_gmail_credentials():
    if config.RUN_MODE == "cloud":
        creds = _from_env()
        if not creds:
            raise RuntimeError("GMAIL_TOKEN_JSON env var missing in cloud mode")
        return creds
    return _from_disk()


_svc = None


def get_gmail_service():
    global _svc
    if _svc is not None:
        return _svc
    _svc = build("gmail", "v1", credentials=get_gmail_credentials(),
                 cache_discovery=False)
    return _svc


if __name__ == "__main__":
    get_gmail_service()
    print("Gmail OK")
