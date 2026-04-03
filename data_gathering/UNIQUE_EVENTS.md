# MQTT Event Catalog (from capture_broad_long.jsonl)

Generated from `capture_broad_long.jsonl` snapshot on 2026-03-15.

## Capture Summary

- Total captured rows: 158
- Topics seen: 6
- Exact unique payloads (topic + full payload): 115
- Near-unique templates (topic + payload shape + event name): 9

## Unique Event Types

These are the unique event types present in the snapshot.

| Topic | Event Type | Notes |
|---|---|---|
| `meep/tracking` | `tracking_position` (inferred) | Payload has `active=true` with `x`, `y`, `dist` |
| `meep/tracking` | `tracking_inactive` (inferred) | Payload is only `{"active": false}` |
| `apps/skippy/events` | `distance_reading` | Payload includes `distance_cm`, `lid`, `rotation` |
| `apps/skippy/events` | `sound_triggered` | Payload includes `lid`, `rotation` |
| `apps/skippy/events` | `tracking_acquired` | Seen once; includes `distance_cm`, `lid`, `rotation` |
| `apps/yodel/control` | `key_pressed` (inferred) | Payload has `key`, `pressed=true` |
| `apps/pickles/control` | `key_pressed` (inferred) | Payload has `key`, `pressed=true` |
| `apps/puddles/control` | `key_pressed` (inferred) | Payload has `key`, `pressed=true` |
| `apps/skippy/control` | `key_pressed` (inferred) | Payload has `key`, `pressed=true` |

## Near-Unique Templates And Good Guesses

Nearly-unique streams are high-cardinality events where values vary per message, but structure is stable.

### 1) `meep/tracking` with `active=true`

- Seen: 59 messages
- Stable keys: `active`, `x`, `y`, `dist`
- Value ranges observed:
  - `x`: 82..582
  - `y`: 181..318
  - `dist`: 143..485

Good guess for what should be in this event:

```json
{
  "event": "tracking_position",
  "active": true,
  "x": 0,
  "y": 0,
  "dist": 0,
  "source": "meep"
}
```

Rationale: this looks like continuous position tracking for a detected subject in camera space, with `dist` as range/depth proxy.

### 2) `apps/skippy/events` `distance_reading`

- Seen: 60 messages
- Stable keys: `event`, `distance_cm`, `lid`, `rotation`
- Value ranges observed:
  - `distance_cm`: 13..77
  - `lid`: 310..350
  - `rotation`: 300..300

Good guess for what should be in this event:

```json
{
  "event": "distance_reading",
  "distance_cm": 0,
  "lid": 0,
  "rotation": 0,
  "source": "skippy"
}
```

Rationale: this appears to be a periodic proximity sensor stream with attached actuator state for context.

### 3) `apps/*/control` key presses (`yodel`, `pickles`, `puddles`, `skippy`) and more

- Seen: 28 messages total
- Stable keys: `key`, `pressed`
- Value ranges observed:
  - `key`: 1..15 (device-dependent subsets)
  - `pressed`: always `true` in this snapshot

Good guess for what should be in this event:

```json
{
  "event": "key_pressed",
  "key": 0,
  "pressed": true,
  "device": "yodel"
}
```

Rationale: these look like control/button matrix inputs, likely user or hardware interactions mapped to key IDs.

### 4) `meep/tracking` with `active=false`

- Seen: 8 messages
- Stable keys: `active`

Good guess for what should be in this event:

```json
{
  "event": "tracking_inactive",
  "active": false,
  "source": "meep"
}
```

Rationale: likely explicit "lost target/no person tracked" state transitions.

### 5) Rare skippy event variants (rareness is not really accurate)

- `sound_triggered` (2 messages)
- `tracking_acquired` (1 message)

Good guess for what should be in this event family:

```json
{
  "event": "sound_triggered",
  "lid": 0,
  "rotation": 0,
  "source": "skippy"
}
```

```json
{
  "event": "tracking_acquired",
  "distance_cm": 0,
  "lid": 0,
  "rotation": 0,
  "source": "skippy"
}
```

Rationale: these are low-frequency state/trigger events that likely mark behavior transitions.

## Topic Counts In Snapshot

- `meep/tracking`: 67
- `apps/skippy/events`: 63
- `apps/yodel/control`: 18
- `apps/pickles/control`: 5
- `apps/puddles/control`: 4
- `apps/skippy/control`: 1

## Suggested Normalized Event Contract

To make downstream de-dup/filter logic easier, every emitter could include:

```json
{
  "event": "string",
  "source": "string",
  "ts": "ISO-8601",
  "payload": {}
}
```

Where current fields (`x`, `y`, `dist`, `distance_cm`, `key`, `pressed`, `lid`, `rotation`) move under `payload`.


## Rotary encoder

sample of events that include a lot of rotary encoder events:
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-left
apps/skippy/control enc1-skippy-right
apps/skippy/control enc1-skippy-left
apps/skippy/control enc2-skippy-right
apps/skippy/control enc2-skippy-right
apps/skippy/control enc2-skippy-left
apps/skippy/control enc2-skippy-left
apps/skippy/control {"key":14,"pressed":true}
apps/skippy/control {"key":15,"pressed":true}
apps/pickles/control enc1-pickles-right
apps/pickles/control enc1-pickles-right
apps/pickles/control enc1-pickles-right
apps/pickles/control enc1-pickles-left
apps/pickles/control enc2-pickles-right
apps/pickles/control enc2-pickles-right
apps/pickles/control enc2-pickles-left
apps/puddles/control enc1-puddles-right
apps/puddles/control enc1-puddles-right
apps/puddles/control enc1-puddles-right
apps/puddles/control enc1-puddles-left
apps/puddles/control enc1-puddles-left
apps/puddles/control {"key":15,"pressed":true}
apps/puddles/control {"key":14,"pressed":true}
apps/yodel/control enc1-yodel-right
apps/yodel/control enc1-yodel-right
apps/yodel/control enc1-yodel-right
apps/yodel/control enc1-yodel-left
apps/yodel/control enc1-yodel-left
apps/yodel/control enc1-yodel-left
apps/yodel/control enc2-yodel-right
apps/yodel/control enc2-yodel-right
apps/yodel/control enc2-yodel-right
apps/yodel/control enc2-yodel-left
apps/yodel/control enc2-yodel-left

