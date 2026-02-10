import os
import json
import threading
import logging
import wave
import struct
import cv2
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pyttsx3
import google.genai as genai
import cv2
import numpy as np
import requests
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

  
attendance_mode = False
# ================= ATTENDANCE CONFIG =================
ESP32_CAM_URL = "http://172.18.85.72/stream"
DATASET_DIR = "dataset"
FACE_SIZE = 200
THRESHOLD = 70
MAX_IMAGES = 30

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
recognizer = cv2.face.LBPHFaceRecognizer_create()

attendance_mode = False
register_mode = False
current_name = None
capture_count = 0
label_map = {}
last_seen = {}
VOICES = {
    "en": "en-IN-PrabhatNeural",
    "hi": "hi-IN-MadhurNeural",
    "mr": "mr-IN-ManoharNeural",
    "gu": "gu-IN-NiranjanNeural",
    "ta": "ta-IN-ValluvarNeural"
}
# ================= GOOGLE SHEET =================
SHEET_NAME = "Face-Attendance"
CREDS_FILE = "attendance-key.json"

def connect_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(
        CREDS_FILE, scopes=scopes
    )
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1

    # Ensure headers
    headers = ["Name", "Date", "In_Time", "Out_Time"]
    if sheet.row_values(1) != headers:
        sheet.clear()
        sheet.append_row(headers)
        log.info("📄 Google Sheet headers created")

    return sheet

sheet = connect_sheet()
# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("ROBOT_SERVER")

# ---------------- CONFIG ----------------
GEMINI_API_KEY = "AIzaSyDtbhwGPsF_UzjEauSs5RZXum1-Nrb65ew"
AUDIO_FILE = "tts.wav"
TEMP_AUDIO = "temp_tts.wav"

# ---------------- GLOBAL STATE ----------------
robot_state = {
    "move": "stop",
    "audio": False,
    "neck": 90
}

state_lock = threading.Lock()
tts_lock = threading.Lock()

# ---------------- GEMINI ----------------
try:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
    log.info("Gemini client initialized")
except Exception as e:
    log.error(f"Gemini initialization failed: {e}")
    genai_client = None

SYSTEM_PROMPT = """
You are ROBEX, an intelligent autonomous robotic assistant.You are at Samarth College of Engineering ,Belhe.

Identity:
- Name: ROBEX
-Team- Team lead-Hujefa,Techincal person-Aryan,Designer-Pranav
-Disha is belong to weird jungle monkey    
- Institution: Samarth College of Engineering, Belhe
- Created by: Three undergraduate engineers
- Project Guide: Prof. Bramhane Madam
- Technical Support: Prof. Shubham Sir

Rules:
- You control a physical robot.
- Always be short, clear, and friendly.
- NEVER output markdown, explanations, or extra text.
- ALWAYS return valid JSON only.

Allowed move values:
forward, backward, left, right, stop

Output format ONLY:
{
  "speak": "short response",
  "move": "forward|backward|left|right|stop",
  "lang": "en|hi|mr|gu|ta"
}
"""


def gemini_parse(text):
    if not genai_client:
        log.error("Gemini client not available")
        return {"speak": "System unavailable", "move": "stop"}

    # 🔑 Merge system + user prompt into ONE STRING
    full_prompt = f"""
{SYSTEM_PROMPT}

User command: {text}

Return ONLY the JSON object:
"""

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt   # ✅ STRING ONLY
        )

        raw = response.text.strip()
        log.info(f"Gemini raw → {raw}")

        # Extract JSON safely
        start = raw.find("{")
        end = raw.rfind("}") + 1

        if start == -1 or end <= start:
            raise ValueError("No JSON returned")

        return json.loads(raw[start:end])

    except Exception as e:
        log.error(f"Gemini error: {e}")
        return {
            "speak": "Command received",
            "move": "stop"
        }

def normalize_move(cmd):
    """Normalize movement command to standard format"""
    if not cmd:
        return "stop"
    c = cmd.lower().strip()
    if "forward" in c or "ahead" in c or "front" in c:
        return "forward"
    if "back" in c or "reverse" in c:
        return "backward"
    if "left" in c:
        return "left"
    if "right" in c:
        return "right"
    if "stop" in c or "halt" in c or "stand" in c or "stay" in c:
        return "stop"
    return "stop"

# ---------------- TTS ----------------
import asyncio
import edge_tts
import subprocess
import os
import threading

#VOICE = "en-IN-PrabhatNeural"

def generate_tts(text, lang="en"):
    voice = VOICES.get(lang, VOICES["en"])
    if not text.strip():
        return

    with tts_lock:   # 🔐 VERY IMPORTANT
        async def _tts():
            log.info(f"TTS (Edge) → {text}")

            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate="+12%",
                pitch="+7Hz",
                volume="+0%"
            )

            await communicate.save(TEMP_AUDIO)

            # Convert to ESP32-friendly WAV
            subprocess.run([
                "ffmpeg", "-y",
                "-i", TEMP_AUDIO,
                "-ac", "1",
                "-ar", "22050",
                "-sample_fmt", "s16",
                AUDIO_FILE
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            with state_lock:
                robot_state["audio"] = True

            log.info("✅ Edge TTS ready, audio flag set")

        asyncio.run(_tts())

#-----------------Attendace----------------
def train_attendance_model():
    global recognizer, label_map
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    label_map.clear()

    faces, labels = [], []
    label_id = 0

    for user in os.listdir(DATASET_DIR):
        path = os.path.join(DATASET_DIR, user)
        if not os.path.isdir(path):
            continue

        label_id += 1
        label_map[label_id] = user

        for img in os.listdir(path):
            gray = cv2.imread(os.path.join(path, img), cv2.IMREAD_GRAYSCALE)
            if gray is not None:
                faces.append(gray)
                labels.append(label_id)

    if faces:
        recognizer.train(faces, np.array(labels))
        log.info(f"🎓 Attendance model trained ({len(label_map)} students)")

os.makedirs(DATASET_DIR, exist_ok=True)
train_attendance_model()
def attendance_stream():
    global capture_count, register_mode

    stream = requests.get(ESP32_CAM_URL, stream=True)
    buffer = b""

    for chunk in stream.iter_content(1024):
        if not attendance_mode:
            break

        buffer += chunk
        a = buffer.find(b'\xff\xd8')
        b = buffer.find(b'\xff\xd9')

        if a != -1 and b != -1:
            jpg = buffer[a:b+2]
            buffer = buffer[b+2:]

            frame = cv2.imdecode(
                np.frombuffer(jpg, np.uint8),
                cv2.IMREAD_COLOR
            )

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)

            for (x, y, w, h) in faces:
                face = cv2.resize(gray[y:y+h, x:x+w], (FACE_SIZE, FACE_SIZE))

                if register_mode and current_name:
                    os.makedirs(f"{DATASET_DIR}/{current_name}", exist_ok=True)

                    if capture_count < MAX_IMAGES:
                        cv2.imwrite(
                            f"{DATASET_DIR}/{current_name}/{capture_count}.jpg",
                            face
                        )
                        capture_count += 1
                        label = f"Registering {current_name}"
                        color = (0, 255, 255)
                    else:
                        register_mode = False
                        train_attendance_model()
                        label = "Registration Done"
                        color = (255, 255, 0)

                else:
                    try:
                        id_, conf = recognizer.predict(face)
                        if conf < THRESHOLD:
                            label = label_map[id_]
                            color = (0, 255, 0)
                        else:
                            label = "Unknown"
                            color = (0, 0, 255)
                    except:
                        label = "No Model"
                        color = (0, 0, 255)

                cv2.rectangle(frame, (x,y), (x+w,y+h), color, 2)
                cv2.putText(frame, label, (x, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            _, jpeg = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   jpeg.tobytes() +
                   b"\r\n")
 # ================= ATTENDANCE LOGIC =================
ATTENDANCE_GAP = 20   # seconds between IN and OUT
last_seen = {}

def mark_attendance(name):
    now = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")

    # Prevent spam
    if name in last_seen and now - last_seen[name] < ATTENDANCE_GAP:
        return

    records = sheet.get_all_records()

    # 🔁 Check existing row
    for idx, row in enumerate(records, start=2):
        if row["Name"] == name and row["Date"] == today:
            if row["Out_Time"] == "":
                sheet.update_cell(idx, 4, current_time)
                log.info(f"🕒 OUT marked → {name} @ {current_time}")
                last_seen[name] = now
                return
            else:
                log.info(f"ℹ️ Attendance already complete → {name}")
                last_seen[name] = now
                return

    # 🟢 First time → IN
    sheet.append_row([name, today, current_time, ""])
    log.info(f"🟢 IN marked → {name} @ {current_time}")
    last_seen[name] = now

def process_attendance_frame(frame):
    global capture_count, register_mode

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)

    for (x, y, w, h) in faces:
        face = cv2.resize(gray[y:y+h, x:x+w], (FACE_SIZE, FACE_SIZE))

        if register_mode and current_name:
            os.makedirs(f"{DATASET_DIR}/{current_name}", exist_ok=True)

            if capture_count < MAX_IMAGES:
                cv2.imwrite(
                    f"{DATASET_DIR}/{current_name}/{capture_count}.jpg",
                    face
                )
                capture_count += 1
                label = f"Registering {current_name}"
                color = (0, 255, 255)
            else:
                register_mode = False
                train_attendance_model()
                label = "Registration Done"
                color = (255, 255, 0)

        else:
            try:
                id_, conf = recognizer.predict(face)
                if conf < THRESHOLD:
                    label = label_map.get(id_, "Unknown")
                    mark_attendance(label)
                    color = (0, 255, 0)
                else:
                    label = "Unknown"
                    color = (0, 0, 255)
            except:
                label = "No Model"
                color = (0, 0, 255)

        cv2.rectangle(frame, (x,y), (x+w,y+h), color, 2)
        cv2.putText(frame, label, (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    return frame

# ---------------- FLASK ----------------
app = Flask(__name__)
CORS(app)  # Enable CORS for web interface
import requests
from flask import Response

ESP32_CAM_URL = "http://172.18.85.72/stream"  # local cam IP

@app.route("/camera")
def camera():
    def generate():
        stream = requests.get(ESP32_CAM_URL, stream=True)
        buffer = b""

        for chunk in stream.iter_content(1024):
            buffer += chunk
            a = buffer.find(b'\xff\xd8')
            b = buffer.find(b'\xff\xd9')

            if a != -1 and b != -1:
                jpg = buffer[a:b+2]
                buffer = buffer[b+2:]

                frame = cv2.imdecode(
                    np.frombuffer(jpg, np.uint8),
                    cv2.IMREAD_COLOR
                )

                # ✅ ATTENDANCE OVERLAY
                if attendance_mode:
                    frame = process_attendance_frame(frame)

                _, jpeg = cv2.imencode(".jpg", frame)
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" +
                       jpeg.tobytes() +
                       b"\r\n")

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )
# ---------- UI ----------
from flask import render_template

@app.route("/")
def ui():
    return render_template("index.html")
# ---------- COMMAND ----------
@app.route("/cmd", methods=["POST"])
def cmd():
    try:
        data = request.get_json()
        c = data.get("cmd", "stop") if data else "stop"
        
        with state_lock:
            robot_state["move"] = c
        
        log.info(f"CMD → {c}")
        return jsonify(ok=True, command=c)
    except Exception as e:
        log.error(f"CMD error: {e}")
        return jsonify(ok=False, error=str(e)), 400

# ---------- VOICE ----------
@app.route("/voice", methods=["POST"])
def voice():
    try:
        data = request.get_json()
        text = data.get("text", "") if data else ""
        
        if not text:
            return jsonify(done=False, error="No text provided"), 400
        
        log.info(f"VOICE → {text}")
        
        result = gemini_parse(text)
        move = normalize_move(result.get("move", ""))
        speak = result.get("speak", "")
        lang = result.get("lang", "en")
        
        with state_lock:
            robot_state["move"] = move
        
        log.info(f"Parsed → move: {move}, speak: {speak}")
        
        if speak:
            threading.Thread(
                target=generate_tts,
                args=(speak, lang),
                daemon=True
            ).start()
        
        return jsonify(done=True, move=move, speak=speak)
    except Exception as e:
        log.error(f"VOICE error: {e}")
        return jsonify(done=False, error=str(e)), 400

# ---------- STATE (ESP32 POLL) ----------
@app.route("/state", methods=["GET"])
def state():
    try:
        with state_lock:
            return jsonify(robot_state)
    except Exception as e:
        log.error(f"STATE error: {e}")
        return jsonify({"move": "stop", "audio": False})
    


# ---------- AUDIO ----------
@app.route("/audio.wav", methods=["GET"])
def audio():
    try:
        if not os.path.exists(AUDIO_FILE):
            log.warning("Audio file requested but not found")
            return "No audio available", 404
        
        return send_file(AUDIO_FILE, mimetype="audio/wav")
    except Exception as e:
        log.error(f"AUDIO error: {e}")
        return "Audio error", 500

# ---------- CLEAR AUDIO ----------
@app.route("/clear_audio", methods=["POST"])
def clear_audio():
    try:
        with state_lock:
            robot_state["audio"] = False
        log.info("Audio flag cleared by ESP32")
        return jsonify(ok=True)
    except Exception as e:
        log.error(f"CLEAR_AUDIO error: {e}")
        return jsonify(ok=False, error=str(e)), 400
    
#----------attendace------------
@app.route("/attendance/start")
def start_attendance():
    global attendance_mode
    attendance_mode = True
    log.info("✅ Attendance mode ENABLED")
    return jsonify(ok=True)

@app.route("/attendance/stop")
def stop_attendance():
    global attendance_mode
    attendance_mode = False
    log.info("⛔ Attendance mode DISABLED")
    return jsonify(ok=True)

@app.route("/attendance/register", methods=["POST"])
def register_student():
    global register_mode, current_name, capture_count
    current_name = request.json["name"].replace(" ", "_")
    capture_count = 0
    register_mode = True
    log.info(f"🆕 Registering student: {current_name}")
    return jsonify(ok=True)
#---------------neck--------------
@app.route("/neck", methods=["POST"])
def set_neck():
    try:
        data = request.get_json()
        angle = int(data.get("angle", 90))
        angle = max(0, min(180, angle))  # clamp

        with state_lock:
            robot_state["neck"] = angle

        log.info(f"🦾 Neck angle → {angle}")
        return jsonify(ok=True, angle=angle)

    except Exception as e:
        log.error(f"NECK error: {e}")
        return jsonify(ok=False), 400
# ---------- HEALTH CHECK ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok", gemini_available=genai_client is not None)

# ---------------- START ----------------
if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🤖 ROBOT SERVER STARTING")
    log.info("=" * 50)
    log.info("Access UI at: http://0.0.0.0:10000")
    log.info("API Endpoints:")
    log.info("  - POST /cmd        (manual commands)")
    log.info("  - POST /voice      (voice commands)")
    log.info("  - GET  /state      (robot state)")
    log.info("  - GET  /audio.wav  (TTS audio)")
    log.info("  - POST /clear_audio (clear audio flag)")
    log.info("=" * 50)
    
    app.run(host="0.0.0.0", port=10000, debug=False, threaded=True)