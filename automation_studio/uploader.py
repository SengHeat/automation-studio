"""YouTube Data API v3 video uploader with OAuth2 device-code flow.

No external libraries required — uses only urllib and the standard library.

Setup:
  1. Create a project in Google Cloud Console.
  2. Enable the YouTube Data API v3.
  3. Create OAuth 2.0 credentials (Desktop application) and download
     client_secrets.json.
  4. In the Studio UI → YouTube tab: authorize once to save youtube_token.json.
  5. Subsequent uploads reuse the saved refresh token automatically.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)


def _post_form(url, data):
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_client_secrets(path):
    """Parse client_secrets.json and return {client_id, client_secret}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    block = data.get("installed") or data.get("web") or {}
    if not block.get("client_id"):
        raise ValueError(
            "client_secrets.json must contain an 'installed' or 'web' section "
            "with a client_id.")
    return {"client_id": block["client_id"], "client_secret": block["client_secret"]}


def load_tokens(token_path):
    if token_path and os.path.exists(token_path):
        with open(token_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tokens(token_path, tokens):
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def start_device_flow(client_id):
    """Initiate the device-code auth flow. Returns the full API response dict."""
    return _post_form(_DEVICE_CODE_URL, {"client_id": client_id, "scope": _SCOPE})


def poll_device_token(client_id, client_secret, device_code,
                      interval=5, timeout=300, log=print):
    """Poll until the user authorizes. Returns token dict or raises TimeoutError."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(interval)
        try:
            data = _post_form(_TOKEN_URL, {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth2:grant-type:device_code",
            })
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))

        if "access_token" in data:
            return data
        error = data.get("error", "")
        if error == "authorization_pending":
            log("  Waiting for user to authorize in browser...")
        elif error == "slow_down":
            interval += 5
        elif error:
            raise RuntimeError(f"OAuth error: {error} — {data.get('error_description', '')}")

    raise TimeoutError("Device authorization timed out after 5 minutes.")


def get_valid_token(client_secrets_path, token_path, log=print):
    """Return a current access_token, refreshing if it has expired."""
    secrets = load_client_secrets(client_secrets_path)
    tokens = load_tokens(token_path)
    if not tokens.get("refresh_token"):
        raise ValueError(
            "No saved refresh token found. Use 'Authorize YouTube' first.")

    issued_at = tokens.get("issued_at", 0)
    expires_in = int(tokens.get("expires_in", 3600))
    if time.time() > issued_at + expires_in - 60:
        log("  Refreshing YouTube access token...")
        new_tokens = _post_form(_TOKEN_URL, {
            "client_id": secrets["client_id"],
            "client_secret": secrets["client_secret"],
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        })
        new_tokens["refresh_token"] = tokens["refresh_token"]
        new_tokens["issued_at"] = time.time()
        save_tokens(token_path, new_tokens)
        tokens = new_tokens

    return tokens["access_token"]


def upload_to_youtube(video_path, title, description, tags, privacy,
                      client_secrets_path, token_path, log=print):
    """Upload *video_path* to YouTube and return the video ID.

    Args:
        video_path: Local path to the .mp4 file.
        title: Video title (max 100 chars).
        description: Video description.
        tags: Comma-separated tag string.
        privacy: "private", "unlisted", or "public".
        client_secrets_path: Path to client_secrets.json.
        token_path: Path to saved token JSON (created by authorize flow).
        log: Callable for progress messages.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    access_token = get_valid_token(client_secrets_path, token_path, log)
    file_size = os.path.getsize(video_path)

    metadata = json.dumps({
        "snippet": {
            "title": (title or os.path.basename(video_path))[:100],
            "description": description or "",
            "tags": [t.strip() for t in (tags or "").split(",") if t.strip()],
            "categoryId": "24",  # Entertainment
        },
        "status": {"privacyStatus": privacy or "private"},
    }).encode("utf-8")

    # 1. Initiate resumable upload session
    init_req = urllib.request.Request(
        _UPLOAD_URL, data=metadata,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        }, method="POST")
    with urllib.request.urlopen(init_req, timeout=30) as resp:
        upload_uri = resp.headers.get("Location")

    if not upload_uri:
        raise RuntimeError("YouTube API did not return an upload URI.")

    mb = file_size // (1024 * 1024)
    log(f"  Uploading {os.path.basename(video_path)} ({mb} MB) to YouTube...")

    # 2. Stream the file in 8 MB chunks (resumable protocol)
    chunk_size = 8 * 1024 * 1024
    uploaded = 0
    video_id = None

    with open(video_path, "rb") as f:
        while uploaded < file_size:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            end = uploaded + len(chunk) - 1
            put_req = urllib.request.Request(
                upload_uri, data=chunk,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {uploaded}-{end}/{file_size}",
                }, method="PUT")
            try:
                with urllib.request.urlopen(put_req, timeout=600) as resp:
                    body = resp.read().decode("utf-8")
                    if body:
                        video_id = json.loads(body).get("id")
                uploaded += len(chunk)
            except urllib.error.HTTPError as exc:
                if exc.code == 308:  # Resume Incomplete — expected for non-final chunks
                    range_hdr = exc.headers.get("Range", "")
                    if range_hdr:
                        uploaded = int(range_hdr.split("-")[-1]) + 1
                    else:
                        uploaded += len(chunk)
                else:
                    raise
            pct = min(uploaded * 100 // file_size, 100)
            log(f"  Upload: {pct}%")

    if not video_id:
        raise RuntimeError("Upload completed but YouTube did not return a video ID.")

    log(f"  ✅ YouTube upload complete: https://youtu.be/{video_id}")
    return video_id
