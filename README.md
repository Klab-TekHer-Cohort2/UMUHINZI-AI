# Umuhinzi AI

Voice-first agricultural assistant for smallholder farmers in Rwanda.

Farmers call a toll-free number or dial a USSD code and speak Kinyarwanda. The
system understands the crop problem, diagnoses the pest, and replies with short
spoken advice. When several farmers report the same pest in one sector, an
outbreak alert is sent to nearby farmers and cooperatives.

> **Status:** Stage 2 + Sunbird ASR. The server exposes `/health`, `/pests`,
> `/diagnose` and `/asr`, and the Streamlit dashboard supports audio upload and
> microphone recording. Voice/USSD webhooks and outbreak alerts come next.

## Stack

| Layer | Tool |
| --- | --- |
| Backend | Python 3.10+ / FastAPI |
| Telephony + USSD + SMS | Africa's Talking developer sandbox (free) |
| Machine learning | scikit-learn (TF-IDF), lightweight |
| Speech recognition | Sunbird AI STT (free developer tier) + mock fallback |
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
│   ├── db/              # database helpers (later)
│   ├── i18n/            # Kinyarwanda text, all in rw.py
│   ├── ml/              # diagnosis, text cleaning, train.py, model.joblib
│   └── services/        # ASR (mock + Sunbird), audio conversion, alerts (later)
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
{"status":"ok","africastalking_configured":false}
```

`africastalking_configured` is `false` when no real API key is in `.env`
(dry-run mode) and `true` once a real sandbox key is loaded.

Interactive API docs: <http://127.0.0.1:8000/docs>

### 7. Run the tests

```powershell
pytest
```

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
SUNBIRD_API_TOKEN=paste_your_token_here
SUNBIRD_TIMEOUT_SECONDS=45
```

4. Restart the backend. `/health` should show
   `"asr_backend": "sunbird", "sunbird_configured": true`.

The token is never sent to the dashboard and is never logged. If the API returns
401/403, create a fresh token at <https://api.sunbird.ai/keys>.

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
- transcription, diagnosis, confidence and the Kinyarwanda reply.

Use the sidebar to check the backend connection. The dashboard reads the backend
URL from `UMUHINZI_API_URL` (default `http://127.0.0.1:8000`).

## Notes for reviewers / presenters

- **Placeholders are marked** with `TODO` or `MOCK` in the code.
- **Kinyarwanda text still to be checked by a native speaker** is marked with
  `# RW-CHECK` in `app/i18n/rw.py` and `_meta.review_note` in
  `app/data/pests.json`.
- Never commit `.env`; it is already in `.gitignore`.
