import base64
import hmac
import json
import os
import subprocess
import tempfile
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

app = Flask(__name__)

# A blank key must lock the API down, never fall back to a guessable default.
API_KEY = os.environ.get("API_KEY", "").strip()
YTDLP_TIMEOUT = int(os.environ.get("YTDLP_TIMEOUT", "90"))
REV = "2"


def _ytdlp_version():
    try:
        return subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, timeout=15
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


YTDLP_VERSION = _ytdlp_version()
EXTRACTOR_ARGS = os.environ.get(
    "YTDLP_EXTRACTOR_ARGS", "youtube:player_client=default,web"
)
MAX_ERROR_CHARS = 2000

_PRIVATE_HOST_PREFIXES = (
    "localhost",
    "127.",
    "10.",
    "192.168.",
    "169.254.",
    "0.",
    "[::1]",
)
_PRIVATE_172 = tuple(f"172.{n}." for n in range(16, 32))


def _cookies_args():
    """Cookies are optional and never committed. Either point COOKIES_FILE (default
    /app/cookies.txt) at a mounted file, or hand the file in as base64 via COOKIES_B64 —
    it is written to /tmp at startup so the secret lives in the environment, not the repo."""
    candidate = os.environ.get("COOKIES_FILE", "/app/cookies.txt")
    if candidate and os.path.isfile(candidate):
        return ["--cookies", candidate]
    encoded = os.environ.get("COOKIES_B64", "").strip()
    if encoded:
        try:
            target = os.path.join(tempfile.gettempdir(), "ytdlp-cookies.txt")
            with open(target, "wb") as handle:
                handle.write(base64.b64decode(encoded))
            os.chmod(target, 0o600)
            return ["--cookies", target]
        except Exception as exc:  # start without cookies rather than crash
            app.logger.warning(
                "Could not decode COOKIES_B64 (%s); continuing without cookies",
                type(exc).__name__,
            )
    return []


_COOKIES_ARGS = _cookies_args()
COOKIES_ENABLED = bool(_COOKIES_ARGS)
YTDLP_BASE = ["yt-dlp", "--extractor-args", EXTRACTOR_ARGS, *_COOKIES_ARGS]

if not API_KEY:
    app.logger.warning(
        "API_KEY is not set — every request will be rejected. Set API_KEY in the environment."
    )
if COOKIES_ENABLED:
    app.logger.info("Cookie file enabled for yt-dlp.")


def auth(req):
    provided = req.headers.get("X-API-Key", "")
    if not API_KEY:
        return False
    return hmac.compare_digest(provided, API_KEY)


def _tail(text):
    return (text or "").strip()[-MAX_ERROR_CHARS:]


def _is_public_http_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if not host:
        return False
    if host.startswith(_PRIVATE_HOST_PREFIXES) or host.startswith(_PRIVATE_172):
        return False
    return True


def _parse_url_request():
    url = request.args.get("url", "").strip()
    if not url:
        return None, (jsonify({"error": "Missing ?url= parameter"}), 400)
    if not _is_public_http_url(url):
        return None, (jsonify({"error": "url must be a public http(s) URL"}), 400)
    return url, None


def _run(args):
    return subprocess.run(
        YTDLP_BASE + args,
        capture_output=True,
        text=True,
        timeout=YTDLP_TIMEOUT,
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "cookies": COOKIES_ENABLED,
            "rev": REV,
            "ytdlp": YTDLP_VERSION,
        }
    )


@app.route("/info", methods=["GET"])
def get_info():
    if not auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    url, error = _parse_url_request()
    if error:
        return error

    try:
        result = _run(["--dump-json", "--no-playlist", url])
        if result.returncode != 0:
            return jsonify({"error": _tail(result.stderr)}), 500

        data = json.loads(result.stdout)
        return jsonify(
            {
                "title": data.get("title"),
                "duration": data.get("duration"),
                "duration_string": data.get("duration_string"),
                "thumbnail": data.get("thumbnail"),
                "uploader": data.get("uploader"),
                "uploader_url": data.get("uploader_url"),
                "view_count": data.get("view_count"),
                "like_count": data.get("like_count"),
                "description": data.get("description"),
                "upload_date": data.get("upload_date"),
                "webpage_url": data.get("webpage_url"),
                "extractor": data.get("extractor"),
                "formats": [
                    {
                        "format_id": f.get("format_id"),
                        "format_note": f.get("format_note"),
                        "ext": f.get("ext"),
                        "resolution": f.get("resolution"),
                        "filesize": f.get("filesize"),
                    }
                    for f in data.get("formats", [])
                ],
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out"}), 504
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse yt-dlp output"}), 500
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 500


@app.route("/download-url", methods=["GET"])
def get_download_url():
    if not auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    url, error = _parse_url_request()
    if error:
        return error
    fmt = request.args.get("format", "bestvideo+bestaudio/best").strip() or "bestvideo+bestaudio/best"

    try:
        result = _run(["-f", fmt, "--get-url", url])
        if result.returncode != 0:
            return jsonify({"error": _tail(result.stderr)}), 500

        urls = [line for line in result.stdout.strip().split("\n") if line]
        return jsonify(
            {
                "download_url": urls[0] if len(urls) == 1 else urls,
                "format": fmt,
            }
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out"}), 504
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 500


@app.route("/audio-url", methods=["GET"])
def get_audio_url():
    if not auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    url, error = _parse_url_request()
    if error:
        return error

    try:
        result = _run(["-f", "bestaudio", "--get-url", url])
        if result.returncode != 0:
            return jsonify({"error": _tail(result.stderr)}), 500

        return jsonify({"audio_url": result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out"}), 504
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 500


@app.route("/subtitles", methods=["GET"])
def get_subtitles():
    if not auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    url, error = _parse_url_request()
    if error:
        return error

    try:
        result = _run(["--list-subs", "--skip-download", url])
        if result.returncode != 0:
            return jsonify({"error": _tail(result.stderr)}), 500
        return jsonify({"output": result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out"}), 504
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
