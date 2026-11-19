# Umuhinzi AI

Voice-first agricultural assistant for smallholder farmers in Rwanda.

Farmers call a toll-free number or dial a USSD code and speak Kinyarwanda. The
system understands the crop problem, diagnoses the pest, and replies with short
spoken advice. When several farmers report the same pest in one sector, an
outbreak alert is sent to nearby farmers and cooperatives.

> **Status:** Stage 4 (speech in both directions). The server exposes `/health`,
> `/pests`, `/diagnose`, `/asr`, `/tts`, `/register`, `/alerts`, `/reports`, plus
> the Africa's Talking webhooks `/ussd` and `/voice`. Kinyarwanda text-to-speech
> is available via Sunbird (or a silent mock fallback). Outbreak alerts are
> stored and logged in dry-run mode. The Streamlit dashboard shows an audio
> player for the diagnosis reply. All webhooks work with no API keys.

## Stack

| Layer | Tool |
| --- | --- |
| Backend | Python 3.10+ / FastAPI |
| Telephony + USSD + SMS | Africa's Talking developer sandbox (free) |
| Machine learning | scikit-learn (TF-IDF), lightweight |
| Speech recognition | Sunbird AI STT (free developer tier) + mock fallback |
| Speech synthesis | Sunbird AI TTS (Kinyarwanda, `kin`) + mock fallback |
| Storage | SQLite |
| Demo dashboard | Streamlit |
| Tunnel for webhooks | ngrok or cloudflared (free tier) |

Everything used here is free and open-source or on a free developer tier.

## Project structure

```
umuhinzi-ai/
├── app/                 # FastAPI backend
│   ├── main.py          # app entry point and API routes
│   ├── config.py        # env vars / settings
│   ├── data/            # pests.json, training_data.json
│   ├── db/              # SQLite storage (hashed ids, reports, alerts)
│   ├── i18n/            # Kinyarwanda text, all in rw.py (RW-CHECK markers)
│   ├── ml/              # diagnosis, text cleaning, train.py, model.joblib
│   └── services/        # ASR, TTS, audio, alerts, webhooks (ussd.py, voice.py)
├── dashboard/           # Streamlit demo dashboard
├── tests/               # pytest tests
├── requirements.txt
├── .env.example
└── README.md
```

## Windows setup

These commands are for **PowerShell** in the project folder.

### 1. Install Python 3.10+

Check what you have:

```powershell
python --version
```

If Python is missing, install it from <https://www.python.org/downloads/> (tick
**Add python.exe to PATH**) or:

```powershell
winget install --id Python.Python.3.12 --source winget
```

Close and reopen PowerShell afterwards so `python` is found.

### 2. Create the virtual environment

```powershell
python -m venv .venv
```

If PowerShell blocks activation, allow scripts for the current user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 3. Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

### 4. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Create your local `.env`

```powershell
Copy-Item .env.example .env
```

The defaults are safe for local demos: no API key means SMS/voice calls run in
**dry-run mode** (they are logged instead of sent).

### 6. Run the server

```powershell
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/health> — you should see something like:

```json
{"status":"ok","africastalking_configured":false,"asr_backend":"mock","tts_backend":"mock","sunbird_configured":false}
```

`africastalking_configured` is `false` when no real API key is in `.env`
(dry-run mode) and `true` once a real sandbox key is loaded. `tts_backend`
shows whether spoken replies use Sunbird or the silent mock fallback.

Interactive API docs: <http://127.0.0.1:8000/docs>

### 7. Run the tests

```powershell
pytest
```

58 tests cover diagnosis, ASR, TTS, storage/alerts, the dashboard and both webhooks.

## HTTP endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service status, ASR/TTS backends and dry-run flags |
| `GET` | `/pests` | The six-pest knowledge base (summary) |
| `POST` | `/diagnose` | JSON text diagnosis + hashed report + outbreak check |
| `POST` | `/asr` | Multipart audio upload -> transcription -> diagnosis |
| `POST` | `/tts` | Kinyarwanda JSON text -> raw audio bytes |
| `GET` | `/tts/audio/{key}` | Short-lived cached audio used by `<Play>` |
| `POST` | `/register` | Register farmer/cooperative (phone hashed) |
| `GET` | `/alerts` | Stored outbreak alerts (active by default) |
| `GET` | `/reports` | Recent reports (hashed reporter ids only) |
| `POST` | `/ussd` | Africa's Talking USSD callback (form-encoded, plain text) |
| `POST` | `/voice` | Africa's Talking voice callback (form-encoded, voice XML) |

Interactive Swagger docs for all of them: <http://127.0.0.1:8000/docs>.

## Africa's Talking webhooks (dry-run, no keys needed)

Africa's Talking calls *us*, so no `AT_API_KEY` or Sunbird token is required to
exercise the full flow. Reports use the existing diagnosis and outbreak
services: after three reports of the same pest in the same sector, one alert is
stored and logged as `DRY-RUN` (no SMS is sent). Phone numbers are hashed with
`storage.hash_identifier()` before they reach SQLite, and callbacks are logged
with hashed session ids only - never raw phone numbers, full recording URLs or
tokens.

### USSD menu map

Africa's Talking sends the whole path in `text`, using `*` as a separator.
Keep the same `sessionId` for every step of one session.

| `text` value | Meaning |
| --- | --- |
| `""` | Welcome / choose language |
| `1` | Kinyarwanda (`2` = English notice, menus stay Kinyarwanda in this demo) |
| `1*1` | District Gasabo (`2` Kicukiro, `3` Nyarugenge, `4` type a name) |
| `1*1*1` | Sector Kacyiru (`2` Remera, `3` Kimihurura, `4` type a name) |
| `1*1*1*1` | Main menu: 1 describe a problem, 2 pest advice, 3 sector alerts |
| `1*1*1*1*1` | Pick symptom 1 from the numbered list -> diagnosis + `END` advice |
| `1*1*1*1*7` then `1*1*1*1*7<space>your symptoms` | Type your own short symptom |
| `1*1*1*2*4` | Advice for pest 4 (Bean Fly) from the six-pest list |
| `1*1*1*3` | Current active alerts in Kacyiru |

Every response starts with `CON ` (continue) or `END ` (finish) and is at most
182 characters.

### Voice call map

1. First callback: Kinyarwanda greeting + `GetDigits` menu (`1` describe a
   problem, `2` pest advice, `3` sector alerts).
2. Next callbacks: pick district and sector with `GetDigits`.
3. Option `1`: a `Record` action; Africa's Talking posts `recordingUrl` back to
   `/voice`. The backend downloads it, calls the existing `transcribe()` ASR
   step, diagnoses the text and plays short advice. Empty transcription -> a
   prompt asking the farmer to repeat + another `Record`.
4. Option `2`: numbered pest list, then advice. Option `3`: active sector
   alerts. Both end with spoken advice + `<Hangup>`.
5. Spoken replies use `<Play url=".../tts/audio/{key}">` when TTS audio is
   available, and fall back to `<Say>` with `TTS_BACKEND=mock` (or a Sunbird
   error). The audio URL is a short-lived in-memory cache entry; behind ngrok it
   is publicly reachable by Africa's Talking.
6. `isActive=0` ends the call and clears the session.

### Test /ussd locally from the /docs page

This is the quickest way to simulate a farmer without a phone:

1. Start the backend: `uvicorn app.main:app --reload`.
2. Open <http://127.0.0.1:8000/docs> and expand **POST /ussd**.
3. Click **Try it out**. The form fields are `sessionId`, `serviceCode`,
   `phoneNumber` and `text` (Swagger UI sends them as form-encoded data).
4. Use the **same** `sessionId` for all calls, e.g. `docs-demo`. Use
   `serviceCode` `*123#` and any fake `phoneNumber` (e.g. `+250788123456`).
5. Click **Execute** once for each `text` value, in this order:

   ```
   (empty)
   1
   1*1
   1*1*1
   1*1*1*1
   1*1*1*1*1
   ```

6. The last response is an `END ` message with Kinyarwanda advice. To try the
   other branches, use `1*1*1*1*7` then
   `1*1*1*1*7*isazi y'ibishyimbo amababi y'umuhondo` (typed symptom),
   `1*1*1*2*4` (pest advice), or `1*1*1*3` (alerts).
7. Check <http://127.0.0.1:8000/reports> - the reporter is a SHA-256 hash, not
   the phone number you entered. Use a new `sessionId` to start over.

### PowerShell and curl examples

```powershell
# First USSD step (text is empty)
$ussd = @{
    sessionId   = "demo-1"
    serviceCode = "*123#"
    phoneNumber = "+250788123456"
    text        = ""
}
Invoke-RestMethod http://127.0.0.1:8000/ussd -Method Post -Body $ussd

# Continue the same session with: 1, 1*1, 1*1*1, 1*1*1*1, 1*1*1*1*1
$ussd.text = "1*1*1*1*1"
Invoke-RestMethod http://127.0.0.1:8000/ussd -Method Post -Body $ussd

# Voice menu step (press 1 for "describe a problem")
$voice = @{
    sessionId    = "call-1"
    isActive     = "1"
    callerNumber = "+250788123456"
    dtmfDigits   = "1"
    recordingUrl = ""
}
Invoke-RestMethod http://127.0.0.1:8000/voice -Method Post -Body $voice

# Text-to-speech: save the Kinyarwanda reply as a WAV file.
# With TTS_BACKEND=mock the file is empty and X-Audio-Available is 0.
$tts = @{ text = "Inyo y'ibigori: Kura udukoko ku mababi." } | ConvertTo-Json
Invoke-WebRequest http://127.0.0.1:8000/tts -Method Post `
  -ContentType "application/json" -Body $tts -OutFile reply.wav
```

curl.exe (ships with Windows) equivalent:

```powershell
curl.exe -X POST http://127.0.0.1:8000/ussd `
  -d "sessionId=demo-2" -d "serviceCode=*123#" `
  -d "phoneNumber=%2B250788123456" -d "text=1*1*1*1*1"

curl.exe -X POST http://127.0.0.1:8000/tts `
  -H "Content-Type: application/json" `
  -d "{\"text\": \"Inyo y'ibigori: Kura udukoko.\"}" -o reply.wav
```

### Connect the Africa's Talking sandbox with ngrok

1. Start the backend in one terminal:
   `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
2. Install ngrok (for example `winget install ngrok.ngrok`), sign in, then run
   `ngrok http 8000` in a second terminal.
3. Copy the HTTPS forwarding URL, e.g.
   `https://abcd-1234.ngrok-free.app`. It changes when ngrok restarts, so the
   callback URLs must be updated after each restart.
4. In the Africa's Talking sandbox dashboard
   (<https://account.africastalking.com>):
   - **USSD**: create/select a service code (for example `*123#`) and set its
     callback URL to `https://YOUR-TUNNEL/ussd`.
   - **Voice**: set the inbound call callback URL to
     `https://YOUR-TUNNEL/voice`.
5. Use the sandbox's USSD simulator / test number to dial the code, or call the
   sandbox voice number. Every step appears in the uvicorn log as a hashed
   session id; `/reports` and `/alerts` show the stored result.
6. You do **not** need `AT_API_KEY` for inbound webhooks. Add sandbox
   credentials to `.env` only if you later want the app to send outbound SMS or
   place calls. Keep secrets out of git and out of logs.

## Stage 2: pest knowledge base and diagnosis

- Knowledge base: `app/data/pests.json` (6 pests, Kinyarwanda + English).
- Training phrases: `app/data/training_data.json`.
- Model: TF-IDF + Logistic Regression, trained automatically on first use, or
  manually with:

```powershell
python -m app.ml.train
```

- If the model is not confident, keyword matching is used. If both are unsure,
  the reply politely asks the farmer to describe the problem again.

Try it in PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/pests

$body = @{ text = "amababi y'ibigori arashye kandi afite uduhumbi" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/diagnose -Method Post `
  -ContentType "application/json" -Body $body
```

Expected: `fall_armyworm` with a short Kinyarwanda `reply_rw`.

## Speech recognition (Sunbird AI)

Speech recognition is behind one function: `transcribe(audio)` in
`app/services/asr.py`. The backend is chosen by `ASR_BACKEND` in `.env`:

- `mock` (default) — no network. Text input is returned as-is; real audio
  returns `MOCK_ASR_TEXT` if you set it, otherwise an empty string so the app
  politely asks the farmer to repeat.
- `sunbird` — real Kinyarwanda speech-to-text (`language=kin`). If the token is
  missing/expired, the API times out, or the response is invalid, the app logs a
  clear warning and falls back to mock.

### Get a free Sunbird token

1. Register at <https://api.sunbird.ai/register> and verify your email.
2. Open <https://api.sunbird.ai/keys> and copy your access token.
   (You can also call `POST https://api.sunbird.ai/auth/token` with your
   username/password; it returns `{"access_token": "..."}`.)
3. Put it only in your local `.env` (never in code or git):

```env
ASR_BACKEND=sunbird
TTS_BACKEND=sunbird
SUNBIRD_API_TOKEN=paste_your_token_here
SUNBIRD_TIMEOUT_SECONDS=45
```

4. Restart the backend. `/health` should show
   `"asr_backend": "sunbird", "tts_backend": "sunbird",
   "sunbird_configured": true`.

The token is shared by STT and TTS, is never sent to the dashboard and is never
logged. If the API returns 401/403, create a fresh token at
<https://api.sunbird.ai/keys>.

## Text-to-speech (Sunbird AI)

Speech synthesis lives behind `synthesize(text)` in `app/services/tts.py`. The
backend is chosen by `TTS_BACKEND` in `.env`:

- `mock` (default) — no network and empty audio. `/tts` returns an empty body
  with `X-Audio-Available: 0`, the dashboard hides the player, and `/voice`
  uses `<Say>` instead of `<Play>`.
- `sunbird` — calls `POST https://api.sunbird.ai/tasks/audio/speech` with
  `language=kin` and `response_mode=stream`, using the same
  `SUNBIRD_API_TOKEN` as STT. If Sunbird returns a signed `audio_url` instead of
  raw bytes, the backend downloads it. Missing/expired tokens, timeouts and bad
  responses are logged as warnings (never the token or signed URL) and fall
  back to mock.

Optional settings in `.env`:

```env
TTS_BACKEND=sunbird
SUNBIRD_TTS_URL=https://api.sunbird.ai/tasks/audio/speech
# SUNBIRD_TTS_VOICE=your_preferred_voice
```

`POST /tts` returns the audio bytes directly with the correct `Content-Type`
(e.g. `audio/wav`). The same byte array is cached for one hour under a SHA-256
key returned in `X-Audio-Key`; `GET /tts/audio/{key}` serves it to Africa's
Talking so `<Play>` can fetch it during a call. Clear the cache by restarting
the server.

### Audio conversion (optional)

Sunbird accepts WAV, MP3, OGG, M4A and more. For other phone formats (e.g. AMR),
install **ffmpeg** so the backend can convert to mono 16 kHz WAV:

```powershell
winget install --id Gyan.FFmpeg --source winget
```

Without ffmpeg the original bytes are sent anyway; if Sunbird rejects them the
farmer is asked to repeat.

### Test audio upload from PowerShell

```powershell
# curl.exe ships with Windows; `-F` uploads the file as multipart/form-data.
curl.exe -X POST http://127.0.0.1:8000/asr -F "audio=@C:\path\to\recording.wav"
```

With the mock backend and no `MOCK_ASR_TEXT`, the response contains an empty
transcription plus the Kinyarwanda "please repeat" message. That is expected.

## Run the demo dashboard

With the backend running in one terminal, open a second terminal:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run dashboard/app.py
```

The dashboard opens at <http://localhost:8501>. It supports:

- audio file upload,
- microphone recording (Streamlit 1.38+),
- a text-only demo tab,
- transcription, diagnosis, confidence and the Kinyarwanda reply,
- an audio player that speaks the reply (when `TTS_BACKEND=sunbird` works).

Use the sidebar to check the backend connection. The dashboard reads the backend
URL from `UMUHINZI_API_URL` (default `http://127.0.0.1:8000`).

## Notes for reviewers / presenters

- **Placeholders are marked** with `TODO` or `MOCK` in the code.
- **Kinyarwanda text still to be checked by a native speaker** is marked with
  `# RW-CHECK` in `app/i18n/rw.py` and `_meta.review_note` in
  `app/data/pests.json`.
- Never commit `.env`; it is already in `.gitignore`.
