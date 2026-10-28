from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "change-this-device-token")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "change-this-dashboard-token")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

app = FastAPI(title="ESP32-S3 AIoT Assistant", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development only; restrict for deployment.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Device-Token", "X-Dashboard-Token"],
)

pending_commands = deque()
issued_commands = {}

device_state = {
    "command_results": {},
    "device_id": "esp32-s3",
    "online": False,
    "ip": None,
    "rssi": None,
    "uptime_ms": 0,
    "led": None,
    "last_seen": None,
    "last_command_result": None,
}

ALLOWED_ACTIONS = {
    "led_on",
    "led_off",
    "pulse",
    "blink",
    "stop_blink",
}


def require_device_token(x_device_token: str = Header(default="")):
    if not DEVICE_TOKEN or x_device_token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Device token tidak valid")


def require_dashboard_token(x_dashboard_token: str = Header(default="")):
    if not DASHBOARD_TOKEN or x_dashboard_token != DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="Dashboard token tidak valid")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class HeartbeatRequest(BaseModel):
    device_id: str = Field(default="esp32-s3", max_length=80)
    ip: str | None = None
    rssi: int | None = None
    uptime_ms: int | None = None
    led: bool | None = None


class CommandResult(BaseModel):
    command_id: str
    success: bool
    message: str = Field(default="", max_length=300)


def _normalize_text(message: str) -> str:
    punctuation = str.maketrans({
        char: " " for char in ".,!?;:'\"()[]{}-/\\"
    })
    return " ".join((message or "").lower().translate(punctuation).split())


def _is_negated_led_command(message: str) -> bool:
    text = _normalize_text(message).replace("jangan lupa", "")
    negative_markers = (
        "jangan", "tidak usah", "tak usah", "enggak usah",
        "nggak usah", "gak usah", "ga usah", "tidak perlu",
        "enggak perlu", "nggak perlu", "gak perlu", "ga perlu",
        "batalkan", "batal",
    )
    led_terms = (
        "led", "lampu", "nyalakan", "nyalain", "hidupkan",
        "hidupin", "matikan", "matiin", "padamkan", "kedip",
        "berkedip", "blink", "pulse",
    )
    return (
        any(term in text for term in negative_markers)
        and any(term in text for term in led_terms)
    )


def local_parse(message: str):
    """Recognize common Indonesian ESP32 commands without AI."""
    text = _normalize_text(message)

    if _is_negated_led_command(text):
        return {
            "action": None,
            "reply": (
                "Perintah tidak dijalankan karena pesan mengandung "
                "larangan. Kirim satu perintah langsung jika diperlukan."
            ),
        }

    # Check stop before blink, because both may contain the word 'kedip'.
    stop_terms = (
        "stop blink", "stop blinking", "stop berkedip",
        "hentikan kedipan", "hentikan berkedip",
        "berhenti berkedip", "matikan kedipan", "stop kedip",
    )
    if any(term in text for term in stop_terms):
        return {
            "action": "stop_blink",
            "reply": "Baik, perintah menghentikan kedipan akan dikirim.",
        }

    blink_terms = (
        "bikin led kedip", "bikin lampu kedip",
        "buat led berkedip", "buat lampu berkedip",
        "led berkedip terus", "lampu berkedip terus",
        "kedip terus", "berkedip terus", "blink",
        "led kedip", "lampu kedip",
    )
    if any(term in text for term in blink_terms):
        return {
            "action": "blink",
            "reply": "Baik, perintah LED RGB berkedip akan dikirim.",
        }

    pulse_terms = (
        "pulse", "kedip sekali", "berkedip sekali", "kedip sebentar",
        "kedipkan led", "kedipkan lampu", "buat led berkedip",
        "buat lampu berkedip", "led berkedip", "lampu berkedip",
        "kedip", "berkedip",
    )
    # The specific continuous-blink phrases above are checked first.
    if any(term in text for term in pulse_terms):
        return {
            "action": "pulse",
            "reply": "Baik, efek LED singkat akan dikirim.",
        }

    off_terms = (
        "matikan led", "matikan lampu", "matiin led", "matiin lampu",
        "padamkan led", "padamkan lampu", "nonaktifkan led",
        "nonaktifkan lampu", "led off", "lampu off",
        "turn off led", "turn off lampu",
    )
    on_terms = (
        "nyalakan led", "nyalakan lampu", "nyalain led",
        "nyalain lampu", "hidupkan led", "hidupkan lampu",
        "hidupin led", "hidupin lampu", "aktifkan led",
        "aktifkan lampu", "led on", "lampu on",
        "turn on led", "turn on lampu", "buat led nyala",
        "buat lampu nyala",
    )
    status_terms = (
        "status", "kondisi", "cek perangkat", "cek esp", "cek esp32",
        "perangkat online", "online", "terhubung", "sinyal wifi",
        "wifi kuat", "wifi lemah", "wifi terhubung", "koneksi wifi",
        "rssi", "alamat ip", "ip address", "uptime",
    )

    actions = []
    if any(term in text for term in off_terms):
        actions.append("led_off")
    if any(term in text for term in on_terms):
        actions.append("led_on")
    wants_status = any(term in text for term in status_terms)

    if len(actions) > 1 or (actions and wants_status):
        return {
            "action": None,
            "reply": (
                "Aku mendeteksi beberapa maksud. Kirim satu perintah "
                "terlebih dahulu."
            ),
        }

    if wants_status:
        return {
            "action": "status",
            "reply": "Aku periksa informasi terakhir dari ESP32.",
        }

    if actions:
        action = actions[0]
        replies = {
            "led_on": "Baik, perintah menyalakan LED akan dikirim.",
            "led_off": "Baik, perintah mematikan LED akan dikirim.",
        }
        return {"action": action, "reply": replies[action]}

    return {
        "action": None,
        "reply": (
            "Perintah belum dikenali. Coba nyalakan LED, matikan LED, "
            "buat LED berkedip, hentikan kedipan, atau cek status ESP32."
        ),
    }


def parse_with_ai(message: str):
    """Parse a command with OpenAI and validate the result."""
    if _is_negated_led_command(message):
        return local_parse(message)
    if not OPENAI_API_KEY or OpenAI is None:
        return None

    instructions = (
        "Kamu adalah parser perintah bahasa Indonesia untuk demo ESP32 LED RGB. "
        "Keluarkan hanya JSON valid dengan key action dan reply. "
        "action hanya boleh bernilai led_on, led_off, pulse, blink, "
        "stop_blink, status, atau null. Jangan membuat aksi lain. "
        "led_on berarti menyalakan LED RGB terus-menerus; "
        "led_off berarti mematikan LED RGB; "
        "pulse berarti efek singkat satu kali; "
        "blink berarti LED RGB berkedip berulang kali; "
        "stop_blink berarti menghentikan kedipan dan mematikan LED; "
        "status berarti meminta informasi perangkat. "
        "Pahami bahasa sehari-hari seperti 'nyalain lampu', "
        "'lampunya dimatiin', 'bikin LED kedip', 'kedip terus', "
        "'hentikan kedipan', dan 'stop berkedip'. "
        "Jika pengguna meminta menghentikan kedipan, pilih stop_blink. "
        "Jika pesan melarang aksi, tidak jelas, meminta beberapa aksi "
        "sekaligus, atau tidak terkait kontrol/status ESP32, pilih action null. "
        "Jangan mengarang data perangkat. Tulis reply singkat dalam bahasa Indonesia."
    )

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=instructions,
            input=message,
        )
        parsed = json.loads(response.output_text.strip())
        if not isinstance(parsed, dict):
            return None

        action = parsed.get("action")
        if action is not None:
            if not isinstance(action, str) or action not in (ALLOWED_ACTIONS | {"status"}):
                return None

        reply = parsed.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            return None

        return {"action": action, "reply": reply.strip()[:400]}
    except Exception:
        return None


def parse_message(message: str):
    """Use AI while retaining recognized local commands as a fallback."""
    local_result = local_parse(message)

    if _is_negated_led_command(message):
        return local_result

    ai_result = parse_with_ai(message)
    if ai_result is None:
        return local_result
    if ai_result["action"] is None and local_result["action"] is not None:
        return local_result
    return ai_result


@app.get("/")
def root():
    return {
        "service": "ESP32-S3 AIoT Assistant",
        "status": "running",
        "health": "/api/health",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "esp32-aiot-backend"}


@app.get("/api/status")
def get_status(_: None = Depends(require_dashboard_token)):
    last_seen = device_state["last_seen"]
    online = False
    if last_seen:
        try:
            seen = datetime.fromisoformat(last_seen)
            online = (datetime.now(timezone.utc) - seen).total_seconds() <= 30
        except (ValueError, TypeError):
            online = False

    current = dict(device_state)
    current["online"] = online
    return {"device": current, "queued_commands": len(pending_commands)}


@app.post("/api/chat")
def chat(request: ChatRequest, _: None = Depends(require_dashboard_token)):
    parsed = parse_message(request.message)
    action = parsed["action"]

    if action == "status":
        seen = device_state.get("last_seen")
        online = False
        if seen:
            try:
                last_seen = datetime.fromisoformat(seen)
                online = (datetime.now(timezone.utc) - last_seen).total_seconds() <= 30
            except (ValueError, TypeError):
                online = False

        led = device_state.get("led")
        led_text = "menyala" if led is True else "mati" if led is False else "belum diketahui"
        rssi = device_state.get("rssi")
        rssi_text = f"{rssi} dBm" if isinstance(rssi, (int, float)) else "belum tersedia"
        ip_text = device_state.get("ip") or "belum tersedia"
        uptime_ms = device_state.get("uptime_ms")
        uptime_text = f"{int(uptime_ms / 1000)} detik" if isinstance(uptime_ms, (int, float)) and uptime_ms >= 0 else "belum tersedia"

        if online:
            reply = (
                f"ESP32 sedang online. LED: {led_text}. "
                f"Sinyal Wi-Fi (RSSI): {rssi_text}. IP: {ip_text}. "
                f"Uptime: {uptime_text}."
            )
        else:
            reply = (
                "ESP32 belum mengirim heartbeat dalam 30 detik terakhir. "
                f"Data terakhir — LED: {led_text}; RSSI: {rssi_text}; "
                f"IP: {ip_text}; uptime: {uptime_text}. Nilai ini mungkin lama."
            )
        return {"reply": reply, "command": None}

    if action not in ALLOWED_ACTIONS:
        return {"reply": parsed["reply"], "command": None}

    command = {
        "id": str(uuid4()),
        "action": action,
        "duration_ms": 1000 if action == "pulse" else 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending_commands.append(command)
    issued_commands[command["id"]] = command
    return {"reply": parsed["reply"], "command": command}


@app.post("/api/heartbeat", dependencies=[Depends(require_device_token)])
def heartbeat(request: HeartbeatRequest):
    device_state["device_id"] = request.device_id
    device_state["ip"] = request.ip
    device_state["rssi"] = request.rssi
    if request.uptime_ms is not None:
        device_state["uptime_ms"] = request.uptime_ms
    if request.led is not None:
        device_state["led"] = request.led
    device_state["last_seen"] = datetime.now(timezone.utc).isoformat()
    device_state["online"] = True
    return {"ok": True}


@app.get("/api/commands/next", dependencies=[Depends(require_device_token)])
def next_command():
    if not pending_commands:
        return {"command": None}
    return {"command": pending_commands.popleft()}


@app.post("/api/commands/result", dependencies=[Depends(require_device_token)])
def command_result(result: CommandResult):
    command = issued_commands.pop(result.command_id, None)
    if command is None:
        raise HTTPException(
            status_code=404,
            detail="Command ID tidak ditemukan atau sudah diproses",
        )

    if result.success:
        action = command["action"]
        if action == "led_on":
            device_state["led"] = True
        elif action in ("led_off", "stop_blink"):
            device_state["led"] = False

    result_data = {
        "command_id": result.command_id,
        "status": "success" if result.success else "failed",
        "success": result.success,
        "message": result.message,
    }
    device_state["last_command_result"] = result_data
    device_state.setdefault("command_results", {})[result.command_id] = result_data
    return {"ok": True}


@app.get("/api/commands/{command_id}/result")
def get_command_result(
    command_id: str,
    _: None = Depends(require_dashboard_token),
):
    if command_id in issued_commands:
        return {
            "command_id": command_id,
            "status": "pending",
            "success": None,
            "message": "Menunggu hasil eksekusi dari ESP32.",
        }

    result = device_state.get("command_results", {}).get(command_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Hasil perintah tidak ditemukan.")
    return result
