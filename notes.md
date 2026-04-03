# Mustard Notes

## Goal

Mustard runs as the local Pi-side brain for the robot cluster. It listens to MQTT events, sends compact state plus the latest event into a local Ollama model, then turns the model's JSON actions into MQTT outputs.

Primary outputs right now:

- `apps/eowyn/text` for expressive text on the matrix display
- `apps/gimli/text` for expressive text or test patterns on the 32x16 matrix
- `apps/skippy/control` for simple embodied reactions from Skippy

Broker for all MQTT work is `192.168.8.100:1883`.

## Restart Runbook

This section should be enough to recover the project after chat memory loss or a broken connection.

Assumptions:

- repo path: `/home/carol/dev/mustard`
- Python venv path: `/home/carol/dev/mustard/.venv`
- MQTT broker: `192.168.8.100:1883`
- Ollama model name: `meep-brain`
- main runtime entrypoint: `main.py`
- display topics: `apps/eowyn/text`, `apps/gimli/text`

If anything disagrees with the live machine, update this file first.

## Quick Start

From the repo root:

```bash
cd /home/carol/dev/mustard
source .venv/bin/activate
ollama create meep-brain -f mustard.mf
python main.py
```

That is the shortest known-good startup path.

Only run `pip install -r requirements.txt` when the venv is new, broken, or dependencies changed.

## Boot Checklist

Run these checks in order.

### 1. Confirm repo contents

```bash
cd /home/carol/dev/mustard
ls
```

Expected important files:

- `main.py`
- `mustard.mf`
- `requirements.txt`
- `mqtt-contract.md`
- `notes.md`

### 2. Confirm Python venv exists

```bash
cd /home/carol/dev/mustard
.venv/bin/python --version
```

If that fails:

```bash
cd /home/carol/dev/mustard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Confirm Ollama is installed

```bash
command -v ollama
```

If that prints nothing, install it:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 4. Confirm Ollama is responsive

```bash
ollama list
```

If `meep-brain` is missing, rebuild it:

```bash
cd /home/carol/dev/mustard
ollama pull gemma3:4b
ollama create meep-brain -f mustard.mf
```

### 5. Confirm MQTT broker is reachable

Use either of these if available on the Pi:

```bash
ping -c 1 192.168.8.100
```

```bash
mosquitto_sub -h 192.168.8.100 -p 1883 -t '#' -C 1
```

If `mosquitto_sub` is not installed, falling back to ping is acceptable.

## Current Runtime Shape

- [main.py](main.py) subscribes to `meep/tracking` and `apps/skippy/events`
- It keeps a small rolling state/history in memory
- Each event is sent to the local Ollama model `meep-brain`
- The model must return JSON with `state_patch` and `actions`
- Supported action types are:
  - `display_text`
  - `display_gimli`
  - `skippy_control`

This is the minimal loop needed to make the LLM feel embodied instead of chat-based.

## Exact Startup Commands

### First-time or recovery setup

```bash
cd /home/carol/dev/mustard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull gemma3:4b
ollama create meep-brain -f mustard.mf
python main.py
```

### Normal startup

```bash
cd /home/carol/dev/mustard
source .venv/bin/activate
python main.py
```

### Startup with explicit environment

```bash
cd /home/carol/dev/mustard
source .venv/bin/activate
export MQTT_BROKER=192.168.8.100
export MQTT_PORT=1883
export MQTT_CLIENT_ID=mustard-brain
export OLLAMA_MODEL=meep-brain
export DISPLAY_TOPIC=apps/eowyn/text
export GIMLI_TOPIC=apps/gimli/text
export SKIPPY_CONTROL_TOPIC=apps/skippy/control
python main.py
```

## One-Time Setup On The Raspberry Pi

### 1. Create or activate the project venv

```bash
cd /home/carol/dev/mustard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install and start Ollama

If Ollama is not already installed:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Then make sure the service is running.

### 3. Pull the base model and build the local brain model

```bash
ollama pull gemma3:4b
ollama create meep-brain -f mustard.mf
```

### 4. Run the brain process

```bash
source .venv/bin/activate
python main.py
```

Optional environment overrides:

```bash
export MQTT_BROKER=192.168.8.100
export MQTT_PORT=1883
export OLLAMA_MODEL=meep-brain
python main.py
```

## Verification

These checks confirm the stack is working, not just installed.

### 1. Verify the model exists

```bash
ollama list
```

Expected: `meep-brain` appears in the list.

### 2. Verify the model can answer in the required shape

```bash
ollama run meep-brain '{"state":{"presence":"idle"},"event":{"topic":"meep/tracking","payload":{"active":true,"x":320,"y":200,"dist":180}},"allowed_actions":{"display_text":{"target":["eowyn"],"mode":["render_text","fast_read","clear"],"stream":["top","bottom"]},"skippy_control":{"command":["open","close","left","right","middle","beep"]}}}'
```

Expected shape:

```json
{"state_patch":{},"actions":[...]}
```

No markdown and no plain English outside the JSON object.

### 3. Verify the Python runtime starts

```bash
cd /home/carol/dev/mustard
source .venv/bin/activate
python main.py
```

Expected startup logs:

- `Connecting to MQTT broker 192.168.8.100:1883`
- `Subscribed to meep/tracking`
- `Subscribed to apps/skippy/events`

### 4. Verify live event handling

When MQTT events arrive, expected logs look like:

```text
Event: meep/tracking -> {...}
Brain output: {...}
```

If the model emits a display action, Mustard should publish to `apps/eowyn/text`.

If the model emits a Gimli display action, Mustard should publish to `apps/gimli/text`.

If the model emits a skippy control action, Mustard should publish to `apps/skippy/control`.

## Gimli Output Notes

Gimli is available at `apps/gimli/text`.

Supported contract from `mqtt-contract.md`:

- `render_text`
- `clear`
- `test`
- `test2`
- `test3`
- `test4`

Example payloads:

```json
{"event":"render_text","text":"GIMLI","direction":"left","speed":30}
```

```json
{"event":"clear"}
```

This makes Gimli a good target for short expressive text, small debug/status messages, or visual test modes.

## Known-Good Model Output Examples

Display text only:

```json
{
  "state_patch": {"mood": "curious"},
  "actions": [
    {
      "type": "display_text",
      "target": "eowyn",
      "mode": "render_text",
      "text": "hello there",
      "stream": "bottom",
      "speed": 30
    }
  ]
}
```

Skippy reaction only:

```json
{
  "state_patch": {},
  "actions": [
    {
      "type": "skippy_control",
      "command": "beep"
    }
  ]
}
```

Do nothing:

```json
{
  "state_patch": {},
  "actions": []
}
```

## Output Contract Expected From The Model

The model should always return a JSON object shaped like:

```json
{
  "state_patch": {
    "mood": "curious"
  },
  "actions": [
    {
      "type": "display_text",
      "target": "eowyn",
      "mode": "render_text",
      "text": "I see you.",
      "stream": "bottom",
      "speed": 30
    },
    {
      "type": "skippy_control",
      "command": "beep"
    }
  ]
}
```

If nothing should happen, the model should return:

```json
{
  "state_patch": {},
  "actions": []
}
```

## Failure Modes

### Ollama missing

Symptom:

- `command -v ollama` returns nothing

Fix:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Model missing

Symptom:

- `ollama list` does not show `meep-brain`

Fix:

```bash
cd /home/carol/dev/mustard
ollama pull gemma3:4b
ollama create meep-brain -f mustard.mf
```

### Python deps missing

Symptom:

- `python main.py` fails on `ImportError` for `ollama` or `paho.mqtt`

Fix:

```bash
cd /home/carol/dev/mustard
source .venv/bin/activate
pip install -r requirements.txt
```

### MQTT broker unavailable

Symptom:

- startup hangs or fails connecting to `192.168.8.100:1883`

Fix:

- verify the broker host is up
- verify the Pi is on the expected network
- verify port `1883` is reachable

### Model returns non-JSON or bad JSON

Symptom:

- `Brain inference failed` appears in logs

Fix:

- rebuild the model: `ollama create meep-brain -f mustard.mf`
- tighten examples in `mustard.mf`
- test with `ollama run meep-brain` directly before restarting `main.py`

### Events arrive but nothing happens

Symptom:

- event logs appear, but there are no visible device/display reactions

Fix:

- inspect the logged `Brain output`
- confirm action `type` is supported by `main.py`
- confirm the output topic exists in `mqtt-contract.md`
- remember `main.py` has cooldowns for publish frequency

## Recovery Notes For Future Sessions

If a future chat/session starts cold, the minimum files to read first are:

1. `notes.md`
2. `mqtt-contract.md`
3. `main.py`
4. `mustard.mf`

That sequence should restore enough context to continue implementation safely.

## Personality Direction

Mustard should feel like a presence, not a chatbot.

- It should react through motion, timing, and short text bursts
- Display text should be brief and intentional, not verbose
- Robot actions should be sparse enough to feel deliberate
- Reactions should vary with proximity, motion, and repeated attention

Examples:

- A new face appears: glance with Skippy, then show a short greeting
- Repeated close presence: show playful or suspicious text
- Sound trigger without visible face: brief startled behavior

## Tuning Strategy

"Training" should happen in phases.

### Phase 1: Prompt and action-schema tuning

Fastest path and the right first step.

- Improve `mustard.mf`
- Tighten the JSON schema
- Add a few high-quality examples
- Evaluate live behavior in the room

### Phase 2: Capture real event-to-action examples

Create a dataset from actual room interactions.

Recommended JSONL shape:

```json
{"input":{"state":{},"event":{}},"output":{"state_patch":{},"actions":[]}}
```

Capture examples such as:

- person enters frame
- person stays near for several seconds
- sound event without face tracking
- tracking lost
- repeated button presses

This dataset becomes the source of truth for how Mustard should behave.

### Phase 3: Supervised tuning off-device

The Raspberry Pi should host inference, not heavy training.

- Do dataset creation and curation here
- Fine-tune or adapter-train on a stronger machine if needed
- Export/import the tuned model back into Ollama on the Pi

Realistically, the Pi is best used for:

- inference
- logging
- evaluation
- lightweight prompt iteration

## Next Useful Additions

- Add a JSONL logger for every input event and model output
- Add a systemd service so Mustard starts at boot
- Add a small replay harness to test old MQTT captures against new prompts/models
- Extend actions to support more devices such as Puddles and Nurbo

## Decision Log

- Mustard runs local inference on the Raspberry Pi
- MQTT is the only integration bus between Mustard and room devices
- The current broker address is `192.168.8.100`
- Display endpoints available to Mustard include Eowyn and Gimli
- The first implemented outputs in code are Eowyn text and Skippy control
- Heavier model tuning should happen off-device; the Pi is primarily for inference and evaluation