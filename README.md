# Mustard

This is a WIP

ollama with Gemma 3 4B-it-QAT running on a Raspberry Pi 5, 8gb

Not a chat bot. This agent is the brain of a set of networked devices. It provides personality and interactivity.

Inputs and outputs are all handled over MQTT

Available inputs include:
- x,y coordinates of people (likely users) who are infront of the a camera in the same room (Meeps)
- distance sensor from skippy. Requires close proximity
- sound sensor from skippy. Boolean - sound heard or not
- button presses on Noodle


We have two LED matrix display available:
 - Eowyn: 64x32
 - Gimli: 32x16


# Dev
ollama create mustard-brain -f mustard.mf


# Run On Boot (Raspberry Pi 5)

Best practice is to run this as a `systemd` service under a dedicated non-root user.

Why this is preferred:
- automatic startup after boot
- automatic restart on crash
- centralized logs in `journalctl`
- clean dependency ordering with network and Ollama

## 1) One-time host setup

From repo root:

```bash
cd /home/carol/dev/mustard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Make sure Ollama is installed and enabled:

```bash
sudo systemctl enable --now ollama
ollama pull qwen2.5:0.5b
ollama create mustard-brain -f mustard.mf
```

## 2) Install the service

The repo includes a service file at `deploy/systemd/mustard.service`.

Update `User`, `Group`, `WorkingDirectory`, and `ExecStart` if your username/path is not `carol` and `/home/carol/dev/mustard`.

Then install it:

```bash
cd /home/carol/dev/mustard
sudo cp deploy/systemd/mustard.service /etc/systemd/system/mustard.service
sudo systemctl daemon-reload
sudo systemctl enable --now mustard
```

## 3) Verify it

```bash
systemctl status mustard --no-pager
journalctl -u mustard -f
```

## 4) Typical operations

```bash
sudo systemctl restart mustard
sudo systemctl stop mustard
sudo systemctl start mustard
```

## Notes on startup behavior

`main.py` now does hash-based rebuild checks:
- if `mustard.mf` changed since last build, it rebuilds automatically
- if the model is missing, it rebuilds automatically
- if `MUSTARD_FORCE_MODEL_REBUILD=1`, it always rebuilds

The last successful build state is stored in `.mustard_model_build.json` in the repo root.

If you intentionally want to force a model rebuild for one run:

```bash
cd /home/carol/dev/mustard
MUSTARD_FORCE_MODEL_REBUILD=1 .venv/bin/python main.py
```

For a long-term non-default setup on this one Pi, just edit values directly in `main.py` or add `Environment=` lines in your systemd service file.
