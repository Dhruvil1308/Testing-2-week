import os
import logging
import json
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from openai import OpenAI
from dotenv import load_dotenv
from openpyxl import Workbook

# Import our configuration
from prompt_config import SYSTEM_PROMPT

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment (graceful — on Render, env vars are set via dashboard)
if os.path.exists(".env.local"):
    load_dotenv(".env.local")
else:
    load_dotenv()  # fallback to .env if present

# Configure OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Configure Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_CALLER_ID")

if not all([os.getenv("OPENAI_API_KEY"), TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    logger.error("❌ CRITICAL: Missing API Keys in .env.local")
    logger.error("Please ensure OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_CALLER_ID are set.")
    # We won't exit here to allow the server to start for 'dry run' debugging, but functionality will be broken.

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app = FastAPI()

# Enable CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev, restrict in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- PUBLIC URL HELPER (Render / Ngrok) ---
def get_public_url() -> str:
    """Returns the public-facing URL for Twilio webhooks.
    Priority: BASE_URL env var > RENDER_EXTERNAL_URL > Ngrok auto-detect."""
    url = os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if url:
        return url.rstrip("/")
    # Fallback: try ngrok API (local dev only)
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as response:
            data = json.loads(response.read().decode())
            for tunnel in data['tunnels']:
                if tunnel['proto'] == 'https':
                    return tunnel['public_url']
    except Exception:
        pass
    return None

# --- DATABASE SETUP (SQLite) ---
DB_FILE = "gunivox.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid TEXT UNIQUE,
            phone_number TEXT,
            status TEXT,
            started_at TEXT,
            end_reason TEXT,
            user_name TEXT,
            interest TEXT,
            lead_status TEXT,
            follow_up TEXT,
            transcript TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            fees TEXT,
            brochure_url TEXT
        )
    ''')
    conn.commit()
    conn.close()
    
    populate_default_courses()

def populate_default_courses():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM courses")
    if c.fetchone()[0] == 0:
        defaults = [
            ("BCA", "Bachelor of Computer Applications. 10+2 English required.", "70,000/yr", None),
            ("MCA", "Master of Computer Applications. Needs BCA/BE/BSc.", "1,40,000/yr", None),
            ("BSc IT", "Bachelor of Science in IT (Data Science/Cyber Security).", "75,000 - 85,000/yr", None),
            ("MSc IT", "Master of Science in IT.", "75,000 - 1,00,000/yr", None)
        ]
        c.executemany("INSERT INTO courses (name, description, fees, brochure_url) VALUES (?, ?, ?, ?)", defaults)
        conn.commit()
        print("✅ Default courses populated.")
    conn.close()

init_db()

# Simple in-memory chat history (Call SID -> Message List)
sessions: Dict[str, List[Dict[str, str]]] = {}

# --- HELPER FUNCTIONS ---

def save_call_log(call_sid: str, data: dict):
    """Upserts call data into SQLite."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Check if exists
    c.execute("SELECT id FROM calls WHERE call_sid = ?", (call_sid,))
    exists = c.fetchone()
    
    if not exists:
         c.execute('''
            INSERT INTO calls (call_sid, phone_number, status, started_at)
            VALUES (?, ?, ?, ?)
         ''', (call_sid, data.get('phone_number'), 'initiated', datetime.now().isoformat()))
    else:
        # Dynamic Update based on keys in data
        fields = []
        values = []
        for key, val in data.items():
            if key in ['status', 'end_reason', 'user_name', 'interest', 'lead_status', 'follow_up', 'transcript']:
                fields.append(f"{key} = ?")
                values.append(val)
        
        if fields:
            values.append(call_sid)
            sql = f"UPDATE calls SET {', '.join(fields)} WHERE call_sid = ?"
            c.execute(sql, values)
            
    conn.commit()
    conn.close()

def export_db_to_excel(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Exports SQLite data to leads.xlsx for download with optional date filtering."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    query = "SELECT * FROM calls"
    params = []
    
    if start_date and end_date:
        query += " WHERE started_at BETWEEN ? AND ?"
        params.extend([f"{start_date}T00:00:00", f"{end_date}T23:59:59"])
    
    query += " ORDER BY id DESC"
    
    c.execute(query, params)
    rows = c.fetchall()
    columns = [description[0] for description in c.description]
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Call Logs"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    
    filename = "leads.xlsx"
    wb.save(filename)
    return filename

# --- API MODELS ---
class LoginRequest(BaseModel):
    username: str
    password: str

class CallRequest(BaseModel):
    phone_number: str

class Course(BaseModel):
    name: str
    description: str
    fees: str
    brochure_url: Optional[str] = None

# --- API ENDPOINTS (Frontend Connection) ---

@app.post("/api/login") 
async def login(creds: LoginRequest):   
    if creds.username == "Admin" and creds.password == "Guni@2026":
        return {"token": "fake-jwt-token-for-demo", "user": "Admin"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/call")
async def trigger_call(req: CallRequest):
    try:
        public_url = get_public_url()

        if not public_url:
            raise HTTPException(status_code=500, detail="No public URL configured. Set BASE_URL env var or ensure Ngrok is running.")

        logger.info(f"🔗 Using Public URL: {public_url}")
        twiml_url = f"{public_url}/voice"

        call = twilio_client.calls.create(
            to=req.phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=twiml_url,
            status_callback=f"{public_url}/status",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
        )
        
        # Initialize log
        save_call_log(call.sid, {"phone_number": req.phone_number})
        
        return {"success": True, "call_sid": call.sid, "status": "initiated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/end_call/{call_sid}")
async def end_call(call_sid: str):
    try:
        call = twilio_client.calls(call_sid).update(status='completed')
        save_call_log(call_sid, {"status": "completed", "end_reason": "user_initiated"})
        return {"success": True, "status": call.status}
    except Exception as e:
        logger.error(f"Failed to end call {call_sid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_stats(start_date: Optional[str] = None, end_date: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    query_total = "SELECT COUNT(*) FROM calls"
    query_positive = "SELECT COUNT(*) FROM calls WHERE lead_status='Positive'"
    params = []
    
    if start_date and end_date:
        range_cond = " WHERE started_at BETWEEN ? AND ?"
        query_total += range_cond
        query_positive += " AND started_at BETWEEN ? AND ?"
        params.extend([f"{start_date}T00:00:00", f"{end_date}T23:59:59"])
        
    c.execute(query_total, params)
    total = c.fetchone()[0]
    
    # For positive leads, we need to repeat params or handle separately
    if start_date and end_date:
        c.execute(query_positive, params)
    else:
        c.execute(query_positive)
    positive = c.fetchone()[0]
    
    c.execute("SELECT * FROM calls ORDER BY id DESC LIMIT 5")
    recent_calls = []
    columns = [desc[0] for desc in c.description]
    for row in c.fetchall():
        recent_calls.append(dict(zip(columns, row)))

    conn.close()
    return {"total_calls": total, "positive_leads": positive, "recent_calls": recent_calls}

@app.get("/api/calls")
async def get_calls(q: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    query = "SELECT * FROM calls"
    params = []
    conditions = []
    
    if q:
        conditions.append("(phone_number LIKE ? OR user_name LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    
    if start_date and end_date:
        conditions.append("started_at BETWEEN ? AND ?")
        params.extend([f"{start_date}T00:00:00", f"{end_date}T23:59:59"])
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY id DESC"
    
    c.execute(query, params)
    calls = []
    columns = [desc[0] for desc in c.description]
    for row in c.fetchall():
        calls.append(dict(zip(columns, row)))
    
    conn.close()
    return calls

# --- COURSE MANAGEMENT ENDPOINTS ---

@app.get("/api/courses")
async def get_courses():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM courses")
    courses = []
    columns = [desc[0] for desc in c.description]
    for row in c.fetchall():
        courses.append(dict(zip(columns, row)))
    conn.close()
    return courses

@app.post("/api/courses")
async def add_course(course: Course):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO courses (name, description, fees, brochure_url) VALUES (?, ?, ?, ?)",
              (course.name, course.description, course.fees, course.brochure_url))
    conn.commit()
    course_id = c.lastrowid
    conn.close()
    return {**course.dict(), "id": course_id}

@app.put("/api/courses/{course_id}")
async def update_course(course_id: int, course: Course):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE courses SET name=?, description=?, fees=?, brochure_url=? WHERE id=?",
              (course.name, course.description, course.fees, course.brochure_url, course_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/courses/{course_id}")
async def delete_course(course_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/download")
async def download_excel(start_date: Optional[str] = None, end_date: Optional[str] = None):
    filepath = export_db_to_excel(start_date, end_date)
    return FileResponse(path=filepath, filename="GuniVox_Leads.xlsx", media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.delete("/api/calls/{call_id}")
async def delete_call(call_id: int):
    """Deletes a call log by its ID."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM calls WHERE id = ?", (call_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"success": True}

@app.get("/api/call/{call_sid}")
async def get_call_status(call_sid: str):
    """Returns the live status and transcript of a specific call."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT status, transcript FROM calls WHERE call_sid = ?", (call_sid,))
    row = c.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Call not found")

    status, transcript_json = row
    transcript = json.loads(transcript_json) if transcript_json else []
    
    # If session is active in memory, prefer that for latest transcript
    if call_sid in sessions:
        transcript = [msg for msg in sessions[call_sid] if msg['role'] != 'system']

    return {"call_sid": call_sid, "status": status, "transcript": transcript}

def analyze_transcript(call_sid: str):
    """Analyzes the full transcript of a completed call to extract metadata.
    This is the GUARANTEED fallback — even if per-message tags failed, 
    this function will correctly extract name, interest, and lead status."""
    
    if call_sid not in sessions:
        logger.warning(f"⚠️ No session found for {call_sid}, skipping analysis.")
        return
    
    # Build a clean transcript string for analysis
    clean_messages = [msg for msg in sessions[call_sid] if msg['role'] != 'system']
    if not clean_messages:
        return
    
    transcript_text = "\n".join([
        f"{'User' if msg['role'] == 'user' else 'GuniVox'}: {msg['content']}" 
        for msg in clean_messages
    ])
    
    analysis_prompt = f"""Analyze this call transcript and extract the following information.
Return ONLY a JSON object with these exact keys. If a value is not found, use null.

{{
  "user_name": "The caller's actual name (not 'Unknown')",
  "interest": "The specific course or field they showed interest in (e.g., BCA, MCA, Engineering)",
  "lead_status": "Positive if they showed genuine interest, Negative if they refused, Pending if unclear",
  "email": "Their email address if provided"
}}

TRANSCRIPT:
{transcript_text}

Return ONLY the JSON, no other text."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": analysis_prompt}],
            temperature=0.1,
            max_tokens=200
        )
        result_text = response.choices[0].message.content.strip()
        
        # Clean markdown code fences if present
        result_text = re.sub(r'^```(?:json)?\s*', '', result_text)
        result_text = re.sub(r'\s*```$', '', result_text)
        
        data = json.loads(result_text)
        logger.info(f"📊 Transcript Analysis for {call_sid}: {data}")
        
        # Build update dict, only include non-null values
        update = {}
        if data.get("user_name") and data["user_name"].lower() not in ["unknown", "null", "none", ""]:
            update["user_name"] = data["user_name"]
        if data.get("interest") and data["interest"].lower() not in ["unknown", "null", "none", ""]:
            update["interest"] = data["interest"]
        if data.get("lead_status") and data["lead_status"].lower() not in ["unknown", "null", "none", ""]:
            update["lead_status"] = data["lead_status"]
        
        if update:
            save_call_log(call_sid, update)
            logger.info(f"✅ Updated call {call_sid} with analyzed data: {update}")
        else:
            logger.info(f"ℹ️ No extractable metadata found for {call_sid}")
            
    except Exception as e:
        logger.error(f"❌ Transcript analysis failed for {call_sid}: {e}")

@app.post("/status")
async def call_status_webhook(CallSid: str = Form(...), CallStatus: str = Form(...)):
    """Updates call status from Twilio. When call completes, runs transcript analysis."""
    logger.info(f"📡 Status Update for {CallSid}: {CallStatus}")
    save_call_log(CallSid, {"status": CallStatus})
    
    # When a call ends, analyze the full transcript to extract metadata
    if CallStatus in ("completed", "busy", "no-answer", "canceled", "failed"):
        analyze_transcript(CallSid)
        # Clean up session memory
        if CallSid in sessions:
            del sessions[CallSid]
    
    return Response(status_code=200)

@app.post("/api/calls/{call_id}/reanalyze")
async def reanalyze_call(call_id: int):
    """Re-analyze a call's transcript to extract missing metadata."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT call_sid, transcript FROM calls WHERE id = ?", (call_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    
    call_sid, transcript_json = row
    if not transcript_json:
        raise HTTPException(status_code=400, detail="No transcript available for this call")
    
    # Parse the stored transcript and temporarily load into sessions for analysis
    try:
        messages = json.loads(transcript_json)
        sessions[call_sid] = [{"role": "system", "content": ""}] + messages
        analyze_transcript(call_sid)
        # Clean up
        if call_sid in sessions:
            del sessions[call_sid]
        return {"success": True, "message": "Call re-analyzed successfully"}
    except Exception as e:
        logger.error(f"Re-analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- CORE VOICE LOGIC (Updated to use SQLite) ---

def get_system_prompt_with_courses():
    """Fetches courses from DB and appends to System Prompt."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT name, description, fees FROM courses")
        rows = c.fetchall()
        conn.close()

        course_text = "\n".join([f"- **{r[0]}:** {r[2]}. {r[1]}" for r in rows])
        if not course_text:
            course_text = "- No specific course data available. Ask the user what they are interested in."
        
        return SYSTEM_PROMPT + course_text + """

### CRITICAL OUTPUT FORMAT — FOLLOW THIS EXACTLY IN EVERY SINGLE RESPONSE:
LANG: [code] | TEXT: [spoken text] | NAME: [name or Unknown] | INTEREST: [course or Unknown] | STATUS: [Positive/Negative/Pending]

EXAMPLES:
User: "Yes I can talk."
Output: LANG: en-IN | TEXT: That's lovely! May I know your good name? | NAME: Unknown | INTEREST: Unknown | STATUS: Pending

User: "My name is Manoj"
Output: LANG: en-IN | TEXT: Just to be sure, did you say your name is Manoj? | NAME: Manoj | INTEREST: Unknown | STATUS: Pending

User: "I'm interested in BCA"
Output: LANG: en-IN | TEXT: Great choice! BCA is 70,000 per year. Want to know more? | NAME: Manoj | INTEREST: BCA | STATUS: Positive

User: "What are the fees?"
Output: LANG: en-IN | TEXT: The yearly fee for BCA is 70,000 rupees! | NAME: Manoj | INTEREST: BCA | STATUS: Positive

REMEMBER: NAME, INTEREST, and STATUS must appear in EVERY response. Once you learn the name or interest, keep repeating it in subsequent responses. Never drop these tags."""
    except Exception as e:
        logger.error(f"Error serving prompt: {e}")
        return SYSTEM_PROMPT

def get_openai_response(call_sid: str, user_input: str) -> Dict[str, str]:
    if call_sid not in sessions:
        # Inject dynamic course data at start of session
        dynamic_prompt = get_system_prompt_with_courses()
        sessions[call_sid] = [{"role": "system", "content": dynamic_prompt}]

    sessions[call_sid].append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=sessions[call_sid],
            temperature=0.7,
            max_tokens=250
        )
        raw_text = response.choices[0].message.content.strip()
        sessions[call_sid].append({"role": "assistant", "content": raw_text})
        
        # Parse Structured Data
        ai_data = {"lang": "en-IN", "text": raw_text}
        
        # Lang & Text
        # Robust regex to capture text even if format is slightly off
        # We look for "TEXT:" ... until a pipe "|" or end of string
        text_match = re.search(r"TEXT:\s*(.*?)(?=\s*\||$)", raw_text, re.DOTALL | re.IGNORECASE)
        lang_match = re.search(r"LANG:\s*([a-z-]+)", raw_text, re.IGNORECASE)
        
        if lang_match: ai_data["lang"] = lang_match.group(1).strip()
        
        if text_match: 
            ai_data["text"] = text_match.group(1).strip()
        else:
            # Fallback: If AI forgot "TEXT:", use the whole string but try to strip common metadata tags
            cleaned_text = re.sub(r"(LANG|STATUS|INTEREST|NAME|FOLLOW_UP):\s*.*?(?=\||$)", "", raw_text, flags=re.IGNORECASE)
            ai_data["text"] = cleaned_text.strip().strip('|')

        # Metadata extraction
        metadata = {}
        # We look for tags like NAME: or User Name: etc.
        patterns = [
            ("user_name", r"(NAME|User Name|Client Name):\s*(.*?)(?=\s*\||STATUS|INTEREST|LANG|TEXT|$)"),
            ("interest", r"(INTEREST|Course|Field|Goal):\s*(.*?)(?=\s*\||STATUS|NAME|LANG|TEXT|$)"),
            ("lead_status", r"(STATUS|Lead Status|Result):\s*(.*?)(?=\s*\||NAME|INTEREST|LANG|TEXT|$)"),
            ("follow_up", r"(FOLLOW_UP|Next Step):\s*(.*?)(?=\s*\||$)")
        ]
        
        for key, pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
            if match: 
                val = match.group(2).strip().strip('|').strip()
                if val.lower() != "unknown" and val:
                    metadata[key] = val
        
        # Save transcript & metadata
        # Filter out system messages for cleaner logs/excel
        clean_transcript = [msg for msg in sessions[call_sid] if msg['role'] != 'system']
        full_transcript = json.dumps(clean_transcript) 
        metadata["transcript"] = full_transcript
        
        save_call_log(call_sid, metadata)

        return ai_data

    except Exception as e:
        logger.error(f"OpenAI Error: {e}")
        return {"lang": "en-IN", "text": "I'm sorry, I didn't catch that."}

@app.post("/voice")
async def handle_voice(request: Request):
    response = VoiceResponse()
    greeting = "Hello! This is GuniVox calling from Ganpat University. Are you available for a quick talk?"
    hints = "Yes, No, Admission, Fees, BCA, MCA, Engineering, Pharmacy, Management, Hello, Interested, Busy, Call back, Stop, Wait, Hold on"
    gather = Gather(input="speech", action="/respond", speech_timeout="auto", enhanced=True, language="en-IN", hints=hints)
    gather.say(f'<speak><prosody rate="95%">{greeting}</prosody></speak>', voice="Google.en-IN-Neural2-D", language="en-IN")
    response.append(gather)
    return Response(content=str(response), media_type="text/xml")

@app.post("/respond")
async def handle_respond(request: Request, SpeechResult: str = Form(None), CallSid: str = Form(None)):
    response = VoiceResponse()
    if not SpeechResult:
        response.say("I didn't hear anything. Hello?", voice="Google.en-IN-Neural2-D", language="en-IN")
        response.append(Gather(input="speech", action="/respond", language="en-IN"))
        return Response(content=str(response), media_type="text/xml")

    ai_data = get_openai_response(CallSid, SpeechResult)
    
    # Voice selection
    voice = "Google.en-IN-Neural2-D"
    if ai_data["lang"] == "gu-IN": voice = "Google.gu-IN-Standard-A"
    
    # Text cleaning
    text = ai_data["text"].replace("[HANGUP]", "").strip()
    
    # Speech Hints for faster/better recognition (Expanded for names and emails)
    hints = "Yes, No, Admission, Fees, BCA, MCA, Engineering, Pharmacy, Management, Hello, Interested, Busy, Call back, " \
            "at, dot, gmail, com, yahoo, outlook, hotmail, underscore, dash, " \
            "B-C-A, M-C-A, B-Sc, M-Sc, my name is, I am interested in"

    if "[HANGUP]" in ai_data["text"]:
        if text: response.say(f'<speak>{text}</speak>', voice=voice, language=ai_data["lang"])
        response.hangup()
    else:
        # Use hints to improve accuracy and speed
        gather = Gather(input="speech", action="/respond", language="en-IN", hints=hints, speech_timeout="auto")
        if text: gather.say(f'<speak>{text}</speak>', voice=voice, language=ai_data["lang"])
        response.append(gather)
        
    return Response(content=str(response), media_type="text/xml")

# --- SERVE FRONTEND STATIC FILES (Production) ---
# Mount the built frontend. This MUST come after all /api routes.
frontend_dir = Path(__file__).parent / "dist"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")
    
    # Serve index.html for all non-API, non-file routes (SPA fallback)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # If the path matches a static file, serve it
        file_path = frontend_dir / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise serve index.html (SPA client-side routing)
        return FileResponse(str(frontend_dir / "index.html"))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"🚀 GuniVox Backend Running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
