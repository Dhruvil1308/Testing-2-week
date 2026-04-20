# GuniVox — Ganpat University Intelligent Voice Assistant

An AI-powered outbound voice calling system for Ganpat University admissions. Built with **FastAPI** (backend), **React + Vite** (frontend), **Twilio** (telephony), and **OpenAI** (conversation intelligence).

---

## Features

- **AI Voice Calls** — Automated outbound calls with natural conversation powered by OpenAI GPT-4o-mini
- **Real-time Transcription** — Live call transcription displayed in the dashboard
- **Lead Analytics** — Track call outcomes, user interest, and lead status
- **Course Management** — CRUD operations for university course data
- **Excel Export** — Download call logs and lead data as Excel reports
- **Multilingual** — Supports English, Hindi, and Gujarati
- **Live Voice Agent** — Browser-based voice agent powered by Google Gemini Live API

---

## Tech Stack

| Layer     | Technology                        |
|-----------|-----------------------------------|
| Backend   | Python, FastAPI, SQLite           |
| Frontend  | React 19, TypeScript, Vite        |
| Styling   | TailwindCSS (CDN), Framer Motion  |
| AI        | OpenAI GPT-4o-mini, Google Gemini |
| Telephony | Twilio Voice API                  |
| Deploy    | Render                            |

---

## Environment Variables

Copy `.env.example` to `.env.local` for local development. On Render, set these in the dashboard.

| Variable             | Description                        |
|----------------------|------------------------------------|
| `OPENAI_API_KEY`     | OpenAI API key                     |
| `OPENAI_MODEL`       | Model name (default: `gpt-4o-mini`)|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID                 |
| `TWILIO_AUTH_TOKEN`   | Twilio Auth Token                  |
| `TWILIO_CALLER_ID`   | Twilio phone number (+E.164)       |
| `GEMINI_API_KEY`     | Google Gemini API key              |
| `BASE_URL`           | Public URL for Twilio webhooks     |

---

## Local Development

### Prerequisites
- **Python 3.11+**
- **Node.js 20+**
- **Ngrok** (for Twilio webhooks locally)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/Dhruvil1308/Testing-2-week.git
cd Testing-2-week

# 2. Create Python virtual environment
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Node dependencies
npm install

# 5. Copy environment template and fill in your keys
cp .env.example .env.local

# 6. Start the backend
python server.py

# 7. Start Ngrok tunnel (in a new terminal)
ngrok http 8000

# 8. Start the frontend dev server (in a new terminal)
npm run dev
```

Then open `http://localhost:3000` in your browser.

**Login Credentials:** `Admin` / `Guni@2026`

---

## Deploy on Render

### Option A: One-click with `render.yaml`
1. Push code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**
3. Connect your GitHub repo — Render will auto-detect `render.yaml`
4. Set the secret environment variables in the Render dashboard
5. Deploy!

### Option B: Manual setup
1. **New Web Service** → Connect your GitHub repo
2. **Build Command:** `bash build.sh`
3. **Start Command:** `python server.py`
4. **Environment:** Python 3
5. Set all environment variables from the table above

> **Note:** SQLite data is ephemeral on Render (resets on each deploy). For persistent data, consider upgrading to Render PostgreSQL.

---

## Project Structure

```
├── server.py            # FastAPI backend (API + Twilio + voice logic)
├── prompt_config.py     # AI system prompt configuration
├── outbound.py          # Standalone outbound call script
├── requirements.txt     # Python dependencies
├── package.json         # Node dependencies
├── vite.config.ts       # Vite build configuration
├── tsconfig.json        # TypeScript configuration
├── render.yaml          # Render deployment config
├── build.sh             # Combined build script
├── .env.example         # Environment variable template
├── index.html           # Entry HTML
├── index.tsx            # React entry point
├── index.css            # Global styles
├── App.tsx              # Main React application
├── data.ts              # Course & university data
├── types.ts             # TypeScript type definitions
├── components/
│   ├── VoiceAgent.tsx   # Gemini Live voice agent
│   └── InfoDisplay.tsx  # University info display
└── services/
    └── audioUtils.ts    # Audio encoding/decoding utilities
```

---

## License

This project is for educational and demonstration purposes for Ganpat University.
