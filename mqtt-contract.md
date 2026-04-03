# MQTT Contract

Broker: `192.168.8.100` (also resolvable as `mose.local`) — port `1883`

---

## Published Topics

### `meep/tracking`
**Publisher:** Meep (Raspberry Pi, [headless-pef-mqtt-tracker.py](../../meep/headless-pef-mqtt-tracker.py))  
**Rate:** On face movement exceeding 5px threshold. QoS 0.

```json
{"x": 423, "y": 309, "dist": 171, "active": true}
```

| Field | Type | Notes |
|---|---|---|
| `x` | int | Nose tip x, 0–640 (camera pixel space) |
| `y` | int | Nose tip y, 0–480 |
| `dist` | int | Face bounding box width in pixels (proxy for subject size/distance) |
| `active` | bool | Always `true` from current code |

> **Note:** 8 captures of `{"active": false}` were observed in the live capture snapshot but no publisher for this shape exists in current meep source code. Treat it as potentially valid but unverified.

---

### `meep/telemetry`
**Publisher:** Meep  
**Rate:** Every 30 seconds. QoS 1.

```json
{"temp": 62.8, "uptime": 1710001234}
```

| Field | Type | Notes |
|---|---|---|
| `temp` | float | CPU temperature in Celsius |
| `uptime` | int | Unix timestamp (seconds) at time of publish |

---

### `apps/skippy/events`
**Publisher:** Skippy (Arduino Nano 33 IoT, [skippy.ino](../../skippy/skippy.ino))  
**Client ID:** `skippy`

Five distinct event types, all on the same topic:

#### `sound_triggered`
Fires on leading edge of sound sensor activation.
```json
{"event": "sound_triggered", "lid": 310, "rotation": 300}
```

#### `distance_reading`
Periodic proximity telemetry. Only published while lid is not fully closed. Throttled: minimum 750ms between publishes, minimum 3cm change required (or 5s max silence).
```json
{"event": "distance_reading", "distance_cm": 37, "lid": 310, "rotation": 300}
```

#### `distance_near`
Fires on leading edge of the "near" threshold (< 10 cm).
```json
{"event": "distance_near", "distance_cm": 8, "lid": 310, "rotation": 300}
```

#### `tracking_acquired`
Fires when Skippy's ultrasonic sensor detects a subject enter tracking range (< 50 cm, not also near).
```json
{"event": "tracking_acquired", "distance_cm": 34, "lid": 350, "rotation": 300}
```

#### `tracking_lost`
Fires when a tracked subject leaves tracking range (> 50 cm), confirmed after 650ms.
```json
{"event": "tracking_lost", "distance_cm": 55, "lid": 350, "rotation": 300}
```

**Field reference for all skippy events:**

| Field | Type | Notes |
|---|---|---|
| `event` | string | One of the five event names above |
| `distance_cm` | int | Rounded cm reading (not present in `sound_triggered`) |
| `lid` | int | Current lid servo position (150 = closed, 310 = mid, 350 = open) |
| `rotation` | int | Current rotation servo position (150–450, center = 300) |

---

## Subscribed Topics

### `apps/skippy/control`
**Subscriber:** Skippy  
**Publisher:** Noodles (when Skippy is the selected app)

Two payload formats are accepted on this topic:

**Plain text commands:**

| Payload | Effect |
|---|---|
| `open` or `enc2-skippy-right` or `up` or `lift` | Move lid to fully open |
| `close` or `enc2-skippy-left` or `down` or `lower` | Move lid to fully closed |
| `left` or `enc1-skippy-left` | Rotate left (partial) |
| `right` or `enc1-skippy-right` | Rotate right (partial) |
| `middle` | Rotate to center position |
| `beep` | Play a random joyful sound |

**JSON key events** (from Noodles trellis keypad):
```json
{"key": 14, "pressed": true}
```
```json
{"key": 15, "pressed": true}
```

| Key | Effect |
|---|---|
| `14` | Run full hardware test flow (servos + lights + sounds), then exit control mode |
| `15` | Exit MQTT control mode immediately |

> Control mode has a 10-second inactivity timeout — Skippy returns to autonomous behavior if no commands arrive.

---

### `apps/puddles/control`
**Subscriber:** Puddles (Arduino Nano 33 IoT)  
**Client ID:** `puddles2-servo`

**Encoder commands** (plain text):

| Payload | Effect |
|---|---|
| `enc1-puddles-right` | Move eye X servo +8° |
| `enc1-puddles-left` | Move eye X servo −8° |
| `enc2-puddles-right` | Move eye Y servo +8° |
| `enc2-puddles-left` | Move eye Y servo −8° |

**JSON key events:**

| Key | Effect |
|---|---|
| `14` | Run servo test sweep sequence, then exit control mode |
| `15` | Exit control mode immediately |

---

### `apps/nurbo/control`
**Subscriber:** Nurbo (Arduino Nano 33 IoT)  
**Client ID:** `nurbo-servo`

Same behavior as Puddles above, with `nurbo` substituted in payload strings:

| Payload | Effect |
|---|---|
| `enc1-nurbo-right` | Move all-eye X servos +8° |
| `enc1-nurbo-left` | Move all-eye X servos −8° |
| `enc2-nurbo-right` | Move all-eye Y servos +8° |
| `enc2-nurbo-left` | Move all-eye Y servos −8° |

JSON key events `14` and `15` behave identically to Puddles.

---

### `apps/yodel/control`, `apps/pickles/control`, `apps/jibbers/control`
**Publisher:** Noodles  
No subscriber project exists in this workspace for these apps. Noodles publishes to them when selected; payloads follow the same format as other apps (JSON key presses and plain-text encoder strings).

---

### `apps/eowyn/text`
**Subscriber:** Eowyn (Adafruit MatrixPortal S3, [main.cpp](../../eowyn/src/main.cpp))  
**Client ID:** `eowyn-matrixportal`

Three distinct event types on this topic:

#### `render_text`
Renders scrolling or pinned text to the top or bottom lane of the 64×32 LED matrix.
```json
{"event": "render_text", "stream": "bottom", "text": "HELLO WORLD", "direction": "left", "speed": 30}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | `render_text` |
| `text` | string | Required. Text to display. |
| `stream` | string | `top` or `bottom`. Defaults to `bottom`. |
| `direction` | string | `left` or `right`. Defaults to `left`. |
| `speed` | int | Frame delay in ms. Clamped 10–200. Defaults to `30`. |
| `color` | string | Optional RGB565 hex color (e.g. `"F800"` for red, `"07E0"` for green). Defaults to white. |
| `loop` | bool | If `true`, text wraps at edge. If `false`, stops at edge. Defaults to `true`. |
| `static_left` | bool | If `true`, text is pinned at left edge (1px padding) with no scroll. Defaults to `false`. |

#### `fast_read`
Displays text one word at a time with speed ramping. Bottom stream only. The pivot (middle) letter of each word is highlighted. Words wider than the panel pause, scroll across, then resume.
```json
{"event": "fast_read", "text": "ONE WORD AT A TIME", "speed": 240, "end_speed": 90}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | `fast_read` |
| `text` | string | Required. Full passage to display word by word. |
| `speed` | int | Starting delay in ms per word. Defaults to `240`. |
| `end_speed` | int | Ending delay in ms per word. Defaults to `150`. |

#### `clear`
Clears one or both text lanes.
```json
{"event": "clear"}
```
```json
{"event": "clear", "stream": "top"}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | `clear` |
| `stream` | string | Optional. `top` or `bottom`. Omit to clear both. |

---

### `apps/gimli/text`
**Subscriber:** Gimli (Adafruit Protomatter 32×16 LED matrix, [main.cpp](../../gimli/src/main.cpp))  
**Client ID:** `gimli-matrixportal`

Five distinct event types on this topic:

#### `render_text`
Renders scrolling or pinned text to the 32×16 LED matrix. Supports left/right scroll directions.
```json
{"event": "render_text", "text": "GIMLI", "direction": "left", "speed": 30}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | `render_text` |
| `text` | string | Required. Text to display. |
| `direction` | string | `left` or `right`. Defaults to `left`. |
| `speed` | int | Frame delay in ms. Clamped 10–200. Defaults to `30`. |

#### `clear`
Clears the display.
```json
{"event": "clear"}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | `clear` |

#### `test`
Runs a 30-second animated color bar test (columns for first 15s, rows for next 15s).
```json
{"event": "test"}
```

#### `test2`
Runs a 30-second sparse pseudo-random pixel pattern with animated diagonals.
```json
{"event": "test2"}
```

#### `test3`
Runs a 30-second physics simulation with colored blocks that fall and bounce in response to accelerometer input. Requires LIS3DH accelerometer to be present; without it, animation remains static.
```json
{"event": "test3"}
```

#### `test4`
Runs a 30-second tiling pattern with motion in response to accelerometer impulses and tilt. Pattern scrolls and wraps in both X and Y with physics-based decay.
```json
{"event": "test4"}
```

---

### `meep/tracking` (subscribed)
**Subscribers:** Puddles, Nurbo

Both consume the same tracking payload from Meep to drive face-following servo behavior. See the `meep/tracking` publisher entry above for the payload schema.

---

## How Noodles Publishes

**Source:** [InputHandler.cpp](lib/InputHandler/InputHandler.cpp), [main.cpp](src/main.cpp)  
**Client ID:** not set in secrets (uses PubSubClient default)

Noodles is the only publisher to `apps/*/control` topics. It publishes two formats depending on input type:

**Trellis keypad** (keys 0–15, only `pressed: true` is emitted):
```json
{"key": 3, "pressed": true}
```

**Rotary encoder** (plain text, not JSON):
```
enc{channel}-{app}-{direction}
```
- `channel`: `1` or `2`
- `app`: lowercase app name — `yodel`, `skippy`, `jibbers`, `pickles`, `puddles`, `nurbo`
- `direction`: `right` or `left`

Example: `enc1-skippy-right`

Both formats are published to the same `apps/{app}/control` topic for whichever app is currently selected.

---

## Passive Listeners

### Butter (ESP32-C6)
**Client ID:** `butter-lcd`  
**Subscription:** `#` (all topics)  
Displays incoming MQTT messages on a 16×2 LCD. Publishes nothing.
