import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import ollama
import paho.mqtt.client as mqtt


MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.8.100")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mustard-brain")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

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
SKIPPY_COMMANDS = {"open", "close", "left", "right", "middle", "beep"}

SYSTEM_MESSAGE = (
    "You control robots and displays in a room. "
    "Output ONLY JSON: {\"actions\":[]}. "
    "Actions: "
    "{\"type\":\"display_text\",\"target\":\"eowyn\",\"mode\":\"render_text\",\"text\":\"...\",\"stream\":\"bottom\",\"speed\":30} "
    "{\"type\":\"display_gimli\",\"mode\":\"render_text\",\"text\":\"...\",\"direction\":\"left\",\"speed\":30} "
    "{\"type\":\"skippy_control\",\"command\":\"open|close|left|right|middle|beep\"} "
    "React with personality. Be sparse. Empty actions if nothing meaningful."
)

brain_executor = ThreadPoolExecutor(max_workers=1)
last_publish_at: dict[str, float] = {}
presence = "idle"  # tracks person_detected vs idle to avoid spamming meep events
ollama_client = ollama.Client()  # persistent — reuses HTTP connection to localhost:11434

_lock = threading.Lock()
_queue: dict[str, Any] = {"processing": False, "pending": None}


# ── helpers ───────────────────────────────────────────────────────────────────

def decode_payload(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def can_publish(topic: str) -> bool:
    cooldown = OUTPUT_COOLDOWNS.get(topic, 0.0)
    now = time.time()
    last = last_publish_at.get(topic)
    if last is not None and (now - last) < cooldown:
        return False
    last_publish_at[topic] = now
    return True


def emit_thinking(client: mqtt.Client) -> None:
    """Clear gimli and show processing indicator."""
    print(f"[emit_thinking] clearing gimli")
    publish_json(client, GIMLI_TOPIC, {"event": "clear"})
    print(f"[emit_thinking] showing ======= on gimli")
    publish_json(
        client,
        GIMLI_TOPIC,
        {"event": "render_text", "text": "=======", "direction": "left", "speed": 80},
    )


def extract_actions(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        obj = json.loads(text[start:end + 1])
        actions = obj.get("actions", [])
        if isinstance(actions, dict):
            return [actions]
        return actions if isinstance(actions, list) else []
    except json.JSONDecodeError:
        return []


# ── brain ─────────────────────────────────────────────────────────────────────

def ask_brain(event_summary: str) -> list[dict[str, Any]]:
    t0 = time.time()
    response = ollama_client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": event_summary},
        ],
        stream=False,
        keep_alive=-1,
        format="json",
    )
    elapsed = time.time() - t0
    content = response["message"]["content"]
    actions = extract_actions(content)
    print(f"[timing] ollama={elapsed:.2f}s actions={actions}")
    return actions


# ── publishers ────────────────────────────────────────────────────────────────

def publish_json(client: mqtt.Client, topic: str, payload: dict[str, Any]) -> None:
    client.publish(topic, json.dumps(payload, separators=(",", ":")))


def publish_display_text(client: mqtt.Client, action: dict[str, Any]) -> None:
    mode = action.get("mode", "render_text")
    if mode not in DISPLAY_MODES:
        return
    payload: dict[str, Any] = {"event": mode}
    if mode == "clear":
        if action.get("stream") in {"top", "bottom"}:
            payload["stream"] = action["stream"]
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
        payload["stream"] = action.get("stream", "bottom")
        payload["direction"] = action.get("direction", "left")
        payload["speed"] = int(action.get("speed", 30))
        payload["loop"] = bool(action.get("loop", True))
        if "color" in action:
            payload["color"] = str(action["color"])
    if not can_publish(DISPLAY_TOPIC):
        return
    publish_json(client, DISPLAY_TOPIC, payload)


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
            publish_display_text(client, action)
        # gimli is reserved for thinking markers; skip display_gimli from LLM
        elif t == "skippy_control":
            publish_skippy_control(client, action)


# ── MQTT callbacks ────────────────────────────────────────────────────────────

def on_connect(client: mqtt.Client, _u: Any, _f: Any, reason_code: Any, _p: Any) -> None:
    if reason_code != 0:
        print(f"MQTT connect failed: {reason_code}")
        return
    for topic, qos in SUBSCRIPTIONS:
        client.subscribe(topic, qos=qos)
        print(f"Subscribed to {topic}")


def summarize_event(topic: str, payload: Any) -> str | None:
    """Build the compact prompt string sent to the LLM."""
    global presence

    # meep/tracking fires constantly; only pass to brain on presence state change
    if topic == "meep/tracking":
        new_presence = "person_detected" if (
            isinstance(payload, dict) and payload.get("active")
        ) else "idle"
        if new_presence == presence:
            return None
        presence = new_presence
        return f"presence changed to {presence}"

    if topic == "apps/skippy/events":
        event_name = payload.get("event", "unknown") if isinstance(payload, dict) else payload
        return f"skippy:{event_name}"

    if topic == "apps/yodel/control":
        return f"user input:{json.dumps(payload, separators=(',', ':'))}"

    return f"{topic}:{payload}"


def on_message(client: mqtt.Client, _u: Any, msg: mqtt.MQTTMessage) -> None:
    payload = decode_payload(msg.payload)
    topic = msg.topic

    summary = summarize_event(topic, payload)
    if summary is None:
        return

    print(f"Event: {topic} -> {payload}")

    with _lock:
        if _queue["processing"]:
            _queue["pending"] = summary  # latest wins, drop stale
            return
        _queue["processing"] = True

    emit_thinking(client)

    def run() -> None:
        current = summary
        while True:
            try:
                actions = ask_brain(current)
            except Exception as exc:
                print(f"Brain error: {exc}")
                actions = []
            dispatch_actions(client, actions)
            with _lock:
                next_summary = _queue["pending"]
                if next_summary is None:
                    _queue["processing"] = False
                    break
                _queue["pending"] = None
                current = next_summary
            emit_thinking(client)

    brain_executor.submit(run)


# ── main ──────────────────────────────────────────────────────────────────────

def warmup_model() -> None:
    print(f"Warming up {OLLAMA_MODEL}...")
    try:
        ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": "idle"},
            ],
            stream=False,
            keep_alive=-1,
            format="json",
        )
        print("Model ready.")
    except Exception as exc:
        print(f"Warmup failed: {exc}")


def main() -> None:
    warmup_model()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message
    print(f"Connecting to MQTT broker {MQTT_BROKER}:{MQTT_PORT}")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    client.loop_forever()


if __name__ == "__main__":
    main()