import json
import os
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import ollama
import paho.mqtt.client as mqtt


MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.8.100")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mustard-brain")
OLLAMA_MODEL = "mustard-brain"

DISPLAY_TOPIC = os.getenv("DISPLAY_TOPIC", "apps/eowyn/text")
GIMLI_TOPIC = os.getenv("GIMLI_TOPIC", "apps/gimli/text")
SKIPPY_CONTROL_TOPIC = os.getenv("SKIPPY_CONTROL_TOPIC", "apps/skippy/control")

SUBSCRIPTIONS = [
    ("meep/tracking", 0),
    ("apps/skippy/events", 0),
    ("apps/yodel/control", 0),
]

# Minimum seconds between publishing to each output topic
OUTPUT_COOLDOWNS = {
    DISPLAY_TOPIC: 8.0,
    GIMLI_TOPIC: 8.0,
    SKIPPY_CONTROL_TOPIC: 4.0,
}

DISPLAY_MODES = {"render_text", "fast_read", "clear"}
GIMLI_MODES = {"render_text", "clear", "test", "test2", "test3", "test4"}
SKIPPY_COMMANDS = {"open", "close", "left", "right", "middle", "beep"}

# Face bounding-box width thresholds (dist field; larger = closer to camera)
PROXIMITY_NEAR = 250  # arm's reach
PROXIMITY_MID = 130   # conversational distance (~1m)
# below PROXIMITY_MID → "far"

PRESENCE_TIMEOUT = 8.0  # seconds without a tracking event before declaring idle

SYSTEM_MESSAGE = (
    "You control robots and displays in a room. "
    'Input JSON: {"state":{"mood":"...","presence":"...","proximity":"..."},"event":"...","history":[...]}. '
    'Output ONLY JSON: {"state_patch":{},"actions":[]}. '
    "Eowyn (64x32 LED, two independent lines): "
    '{"type":"display_text","target":"eowyn","mode":"render_text","text":"WORD","stream":"top","color":"FC00","loop":true,"speed":60} '
    '{"type":"display_text","target":"eowyn","mode":"render_text","text":"reaction","stream":"bottom","color":"FFE0","loop":false,"speed":30} '
    '{"type":"display_text","target":"eowyn","mode":"clear","stream":"top"} '
    "fast_read is RARE — only for intentional long-form user messages: "
    '{"type":"display_text","target":"eowyn","mode":"fast_read","text":"full sentence here"} '
    "Gimli (32x16 LED, single line, no color, no streams): "
    '{"type":"display_gimli","mode":"render_text","text":"WORD","direction":"left","speed":30} '
    '{"type":"display_gimli","mode":"clear"} '
    '{"type":"display_gimli","mode":"test"} '
    '{"type":"display_gimli","mode":"test2"} '
    "Skippy: "
    '{"type":"skippy_control","command":"open|close|left|right|middle|beep"} '
    "Colors: F800=red FC00=orange FFE0=yellow 07E0=green 001F=blue FFFF=white. "
    "Top stream = persistent mood word (loop:true, slow speed). "
    "Bottom stream = event reaction word (loop:false, fast speed). "
    "Be very sparse. Prefer render_text. Use gimli test modes for excitement/sound events."
)

brain_executor = ThreadPoolExecutor(max_workers=1)
last_publish_at: dict[str, float] = {}
ollama_client = ollama.Client()

_lock = threading.Lock()
_queue: dict[str, Any] = {"processing": False, "pending": None}

# Persistent state — updated by state_patch from each brain response
_state: dict[str, Any] = {"mood": "idle", "presence": "idle", "proximity": "unknown"}
_history: deque[str] = deque(maxlen=5)
_current_proximity = "unknown"

_mqtt_client: mqtt.Client | None = None
_presence_timer: threading.Timer | None = None

_MOOD_COLORS: dict[str, str] = {
    "idle": "001F",
    "curious": "FFE0",
    "engaged": "07E0",
    "watching": "FC00",
    "alert": "F800",
    "excited": "F800",
}
_last_top_word: str = ""


# ── helpers ───────────────────────────────────────────────────────────────────

def decode_payload(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def can_publish(topic: str, stream: str | None = None) -> bool:
    cooldown = OUTPUT_COOLDOWNS.get(topic, 0.0)
    now = time.time()
    key = f"{topic}:{stream}" if stream else topic
    last = last_publish_at.get(key)
    if last is not None and (now - last) < cooldown:
        return False
    last_publish_at[key] = now
    return True


def classify_proximity(dist: int) -> str:
    if dist >= PROXIMITY_NEAR:
        return "near"
    elif dist >= PROXIMITY_MID:
        return "mid"
    return "far"


def build_prompt(event_label: str) -> str:
    with _lock:
        snapshot = {"state": dict(_state), "event": event_label, "history": list(_history)}
    return json.dumps(snapshot, separators=(",", ":"))


def record_event(label: str) -> None:
    with _lock:
        _history.append(label)


def emit_thinking(client: mqtt.Client) -> None:
    publish_json(client, GIMLI_TOPIC, {"event": "render_text", "text": "...", "direction": "left", "speed": 60})


def push_top_stream(client: mqtt.Client) -> None:
    """Deterministically mirror current mood to Eowyn top stream."""
    global _last_top_word
    with _lock:
        mood = _state.get("mood", "idle")
    word = mood.upper()
    if word == _last_top_word:
        return
    _last_top_word = word
    color = _MOOD_COLORS.get(mood.lower(), "FFFF")
    publish_json(client, DISPLAY_TOPIC, {
        "event": "render_text",
        "text": word,
        "stream": "top",
        "direction": "left",
        "speed": 65,
        "loop": True,
        "color": color,
    })
    last_publish_at[f"{DISPLAY_TOPIC}:top"] = time.time()


# ── brain ─────────────────────────────────────────────────────────────────────

def extract_response(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}, []
    try:
        obj = json.loads(text[start : end + 1])
        patch = obj.get("state_patch", {})
        if not isinstance(patch, dict):
            patch = {}
        actions = obj.get("actions", [])
        if isinstance(actions, dict):
            actions = [actions]
        return patch, actions if isinstance(actions, list) else []
    except json.JSONDecodeError:
        return {}, []


def ask_brain(prompt: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    t0 = time.time()
    response = ollama_client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        stream=False,
        keep_alive=-1,
        format="json",
    )
    elapsed = time.time() - t0
    content = response["message"]["content"]
    patch, actions = extract_response(content)
    print(f"[timing] ollama={elapsed:.2f}s patch={patch} actions={actions}")
    return patch, actions


# ── publishers ────────────────────────────────────────────────────────────────

def publish_json(client: mqtt.Client, topic: str, payload: dict[str, Any]) -> None:
    client.publish(topic, json.dumps(payload, separators=(",", ":")))


def publish_display_text(client: mqtt.Client, action: dict[str, Any]) -> None:
    mode = action.get("mode", "render_text")
    if mode not in DISPLAY_MODES:
        return
    payload: dict[str, Any] = {"event": mode}
    stream = action.get("stream", "bottom") if mode != "fast_read" else "bottom"
    if mode == "clear":
        if stream in {"top", "bottom"}:
            payload["stream"] = stream
    elif mode == "fast_read":
        text = str(action.get("text", "")).strip()
        if not text:
            return
        payload["text"] = text[:160]
        payload["speed"] = int(action.get("speed", 240))
        payload["end_speed"] = int(action.get("end_speed", 120))
    else:
        text = str(action.get("text", "")).strip()
        if not text or text == "...":
            return
        payload["text"] = text[:64]
        payload["stream"] = stream
        payload["direction"] = action.get("direction", "left")
        payload["speed"] = int(action.get("speed", 30))
        payload["loop"] = bool(action.get("loop", False))
        if "color" in action:
            payload["color"] = str(action["color"])
        if action.get("static_left"):
            payload["static_left"] = True
    if not can_publish(DISPLAY_TOPIC, stream):
        return
    publish_json(client, DISPLAY_TOPIC, payload)


def publish_display_gimli(client: mqtt.Client, action: dict[str, Any]) -> None:
    mode = action.get("mode", "render_text")
    if mode not in GIMLI_MODES:
        return
    payload: dict[str, Any] = {"event": mode}
    if mode == "render_text":
        text = str(action.get("text", "")).strip()
        if not text or text == "...":
            return
        payload["text"] = text[:32]
        payload["direction"] = action.get("direction", "left")
        payload["speed"] = int(action.get("speed", 30))
    if not can_publish(GIMLI_TOPIC):
        return
    publish_json(client, GIMLI_TOPIC, payload)


def publish_skippy_control(client: mqtt.Client, action: dict[str, Any]) -> None:
    command = str(action.get("command", "")).strip().lower()
    if command not in SKIPPY_COMMANDS:
        return
    if not can_publish(SKIPPY_CONTROL_TOPIC):
        return
    client.publish(SKIPPY_CONTROL_TOPIC, command)


def dispatch_actions(client: mqtt.Client, actions: list[dict[str, Any]]) -> None:
    for action in actions:
        if not isinstance(action, dict):
            continue
        t = action.get("type")
        if t == "display_text":
            if action.get("mode") == "fast_read":
                # alert before fast_read: gimli flash + beep
                publish_json(client, GIMLI_TOPIC, {"event": "render_text", "text": ">>>", "direction": "left", "speed": 25})
                publish_skippy_control(client, {"command": "beep"})
                time.sleep(0.4)
            publish_display_text(client, action)
        elif t == "display_gimli":
            publish_display_gimli(client, action)
        elif t == "skippy_control":
            publish_skippy_control(client, action)


# ── event routing ─────────────────────────────────────────────────────────────

def enqueue_brain_call(client: mqtt.Client, event_label: str) -> None:
    prompt = build_prompt(event_label)
    record_event(event_label)

    with _lock:
        if _queue["processing"]:
            _queue["pending"] = prompt  # latest wins, drop stale
            return
        _queue["processing"] = True

    emit_thinking(client)

    def run() -> None:
        current = prompt
        while True:
            try:
                patch, actions = ask_brain(current)
                with _lock:
                    _state.update(patch)
                push_top_stream(client)
            except Exception as exc:
                print(f"Brain error: {exc}")
                actions = []
            dispatch_actions(client, actions)
            with _lock:
                next_prompt = _queue["pending"]
                if next_prompt is None:
                    _queue["processing"] = False
                    break
                _queue["pending"] = None
                current = next_prompt
            emit_thinking(client)

    brain_executor.submit(run)


def reset_presence_timer() -> None:
    global _presence_timer
    if _presence_timer is not None:
        _presence_timer.cancel()
    t = threading.Timer(PRESENCE_TIMEOUT, on_presence_lost)
    t.daemon = True
    _presence_timer = t
    t.start()


def on_presence_lost() -> None:
    global _current_proximity
    with _lock:
        _state["presence"] = "idle"
        _state["proximity"] = "unknown"
        _current_proximity = "unknown"
    label = "presence_lost"
    print(f"Presence timeout → {label}")
    if _mqtt_client is not None:
        push_top_stream(_mqtt_client)
        enqueue_brain_call(_mqtt_client, label)


# ── MQTT callbacks ────────────────────────────────────────────────────────────

def on_connect(client: mqtt.Client, _u: Any, _f: Any, reason_code: Any, _p: Any) -> None:
    if reason_code != 0:
        print(f"MQTT connect failed: {reason_code}")
        return
    for topic, qos in SUBSCRIPTIONS:
        client.subscribe(topic, qos=qos)
        print(f"Subscribed to {topic}")


def summarize_event(topic: str, payload: Any) -> str | None:
    global _current_proximity

    if topic == "meep/tracking":
        active = isinstance(payload, dict) and bool(payload.get("active"))
        if not active:
            return None  # spurious; timeout handles real departures

        dist = int(payload.get("dist", 0)) if isinstance(payload, dict) else 0
        new_proximity = classify_proximity(dist)

        reset_presence_timer()

        with _lock:
            was_idle = _state.get("presence") == "idle"
            old_proximity = _current_proximity

        if was_idle:
            with _lock:
                _state["presence"] = "person_detected"
                _state["proximity"] = new_proximity
                _current_proximity = new_proximity
            return f"appeared proximity={new_proximity}"

        if new_proximity != old_proximity:
            with _lock:
                _state["proximity"] = new_proximity
                _current_proximity = new_proximity
            return f"proximity {old_proximity}->{new_proximity}"

        return None

    if topic == "apps/skippy/events":
        event_name = payload.get("event", "unknown") if isinstance(payload, dict) else str(payload)
        return f"skippy:{event_name}"

    if topic == "apps/yodel/control":
        if not isinstance(payload, dict):
            return None  # ignore encoder strings (enc1-yodel-right etc.)
        return f"user:{json.dumps(payload, separators=(',', ':'))}"

    return f"{topic}:{payload}"


def on_message(client: mqtt.Client, _u: Any, msg: mqtt.MQTTMessage) -> None:
    payload = decode_payload(msg.payload)
    topic = msg.topic

    label = summarize_event(topic, payload)
    if label is None:
        return

    print(f"Event: {topic} -> {payload}")
    enqueue_brain_call(client, label)
    if label.startswith("appeared"):
        push_top_stream(client)


# ── main ──────────────────────────────────────────────────────────────────────

def build_model() -> None:
    modelfile = os.path.join(os.path.dirname(__file__) or ".", "mustard.mf")
    print(f"Building {OLLAMA_MODEL} from {modelfile}...")
    result = subprocess.run(
        ["ollama", "create", OLLAMA_MODEL, "-f", modelfile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ollama create failed:\n{result.stderr}")
    print("Model built.")


def warmup_model() -> None:
    print(f"Warming up {OLLAMA_MODEL}...")
    try:
        ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": '{"state":{"mood":"idle","presence":"idle","proximity":"unknown"},"event":"startup","history":[]}'},
            ],
            stream=False,
            keep_alive=-1,
            format="json",
        )
        print("Model ready.")
    except Exception as exc:
        print(f"Warmup failed: {exc}")


def main() -> None:
    global _mqtt_client
    build_model()
    warmup_model()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    _mqtt_client = client
    client.on_connect = on_connect
    client.on_message = on_message
    print(f"Connecting to MQTT broker {MQTT_BROKER}:{MQTT_PORT}")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    client.loop_forever()


if __name__ == "__main__":
    main()
