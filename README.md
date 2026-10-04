# yt-dlp API — self-hosted on Render

A small Flask API wrapping `yt-dlp` so you can fetch video metadata and direct download
URLs over HTTP — usable from the portfolio dashboard, n8n, Make, Zapier, or any HTTP client.

## What changed in this revision

- **Deno is installed in the image.** YouTube now requires yt-dlp's EJS challenge solver,
  which needs Deno >= 2.3 on `PATH` (the Debian `nodejs` package is far too old). Without it,
  extractions fail with "Signature solving failed / Only images are available".
- **`/health` reports `rev` and the installed `yt-dlp` version**, so you can confirm what a
  deploy is running and how fresh yt-dlp is.
- **Bot-check retry across player clients.** When YouTube refuses the default client (403 /
  "Requested format is not available"), the request is retried with alternative player
  clients (`tv`, `android_vr`, `web_embedded`) before failing — datacenter IPs get
  bot-checked intermittently, and a different client often gets through.
- **Cookies are optional now.** The old build always passed `--cookies /app/cookies.txt`, but
  that file is not in the repo, so on Render every yt-dlp call failed. Cookies are only
  attached when a file actually exists (see `COOKIES_B64` below).
- **No `changeme` fallback.** If `API_KEY` is unset, every request is rejected (401) instead
  of falling back to a guessable key. Comparison uses `hmac.compare_digest`.
- **gunicorn** serves the app (with a 120s worker timeout, longer than the 90s yt-dlp
  subprocess timeout) instead of the Flask dev server.
- **URL validation**: `?url=` must be a public http(s) URL — localhost / private ranges are
  rejected.
- Removed the stray empty `X-Youtube-Identity-Token` header the old build sent.

## Deploy to Render

### Option A — Blueprint (uses `render.yaml`)

1. Push this repo to GitHub (it already lives at `md-hasibur-rahman/yt-dlp-api`).
2. On [render.com](https://render.com): **New → Blueprint** → pick this repo → **Apply**.
3. Render creates the web service, auto-generates `API_KEY`, and health-checks `/health`.
4. Open the service → **Environment** → copy the `API_KEY` value (you need it in the
   dashboard tool or any client).

### Option B — Manual web service

1. **New → Web Service** → connect this repo.
2. Language/Environment: **Docker** (Dockerfile is in the repo root).
3. Region: Singapore (or nearest), Plan: Free.
4. Environment variables: `API_KEY` = any long random string (Render can generate one).
5. **Deploy**. Your base URL will be `https://<service-name>.onrender.com`.

### Optional: cookies (raises YouTube success rate)

Datacenter IPs (Render included) get hit by YouTube bot checks more often. Attaching your
own browser cookies helps. Cookies must **never** be committed to the repo:

1. Export cookies for `youtube.com` in Netscape format (e.g. with the “Get cookies.txt
   LOCALLY” browser extension), while signed in to your own account.
2. Base64-encode the file:
   ```bash
   base64 -w0 cookies.txt > cookies.b64
   ```
3. In Render → your service → **Environment**, add:
   - `COOKIES_B64` = the contents of `cookies.b64` (mark it as a secret)
4. Redeploy. `/health` reports `{"status":"ok","cookies":true}` so you can confirm.

Notes: cookies expire after a few weeks — refresh `COOKIES_B64` when extraction starts
failing again. If you run the container elsewhere, you can instead mount a file and set
`COOKIES_FILE=/path/to/cookies.txt`.

### Other env vars (all optional)

| Variable | Default | Purpose |
|---|---|---|
| `API_KEY` | *(empty — API locked)* | Required. Sent by clients as `X-API-Key`. |
| `COOKIES_B64` | *(unset)* | Base64 Netscape cookies, written to `/tmp` at startup. |
| `COOKIES_FILE` | `/app/cookies.txt` | Path to a mounted cookie file (used if it exists). |
| `YTDLP_EXTRACTOR_ARGS` | `youtube:player_client=default,web` | Tune if YouTube changes clients. |
| `YTDLP_TIMEOUT` | `90` | Seconds before a yt-dlp subprocess is killed. |
| `PORT` | `5000` | Render sets this; the server binds to it. |

## API endpoints

All endpoints except `/health` require the header:

```
X-API-Key: your-secret-key
```

### `GET /health`

```json
{ "status": "ok", "cookies": true, "rev": "2", "ytdlp": "2025.x.x" }
```

`cookies` shows whether a cookie file is active, `ytdlp` shows the installed yt-dlp
version (rebuild the service to refresh it), and `rev` identifies the app revision.

### `GET /info?url=VIDEO_URL`

Metadata for one video (`--dump-json --no-playlist`): `title`, `duration`,
`duration_string`, `thumbnail`, `uploader`, `uploader_url`, `view_count`, `like_count`,
`description`, `upload_date`, `webpage_url`, `extractor`, and a `formats` array with
`format_id`, `format_note`, `ext`, `resolution`, `filesize`.

### `GET /download-url?url=VIDEO_URL&format=FORMAT`

Direct CDN URL(s); nothing is downloaded to the server.

- `format` (optional): any yt-dlp format string. Default `bestvideo+bestaudio/best`.
- When the format matches separate video + audio streams, `download_url` is a **list**
  (video URL first, audio URL second) — download both and merge with ffmpeg, or ask for a
  single combined stream like `best` / `best[ext=mp4]`.

### `GET /audio-url?url=VIDEO_URL`

`{ "audio_url": "https://..." }` — shortcut for `bestaudio`.

### `GET /subtitles?url=VIDEO_URL`

`{ "output": "<yt-dlp --list-subs output>" }`.

## Quick test

```bash
BASE=https://your-service.onrender.com
KEY=your-api-key

curl -s $BASE/health
curl -s -H "X-API-Key: $KEY" "$BASE/info?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"
curl -s -H "X-API-Key: $KEY" "$BASE/audio-url?url=https://youtu.be/dQw4w9WgXcQ"
```

## Notes

- **Free tier sleeps after ~15 min idle** — the first request after a sleep can take ~30–60s
  while the container starts. The portfolio dashboard tool shows a friendly “waking the
  server” hint on timeouts.
- **No file storage** — the API only returns URLs and metadata.
- **yt-dlp freshness matters** — YouTube changes frequently; redeploy periodically (the
  Docker build installs the latest yt-dlp) and keep `yt-dlp>=2025.1.15` or newer.
- **Security** — this API can fetch any public URL on your behalf; keep `API_KEY` private.
  A blank key locks every endpoint. Cookies/`COOKIES_B64` are login credentials: treat them
  like passwords and never commit them.
