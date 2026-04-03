#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import signal
import sys
import time
from collections import Counter

import paho.mqtt.client as mqtt


DEFAULT_BROKER = "192.168.8.100"
DEFAULT_PORT = 1883


class CaptureState:
    def __init__(self, dedup_window: float, show_duplicates: bool, max_cache: int):
        self.dedup_window = dedup_window
        self.show_duplicates = show_duplicates
        self.max_cache = max_cache

        self.last_seen = {}
        self.topic_counts = Counter()
        self.unique_events = 0
        self.duplicate_events = 0
        self.filtered_events = 0
        self.last_emitted_by_topic = {}
        self.last_emitted_field_values = {}

    def is_duplicate(self, fingerprint: str, now: float) -> bool:
        last = self.last_seen.get(fingerprint)
        self.last_seen[fingerprint] = now

        if len(self.last_seen) > self.max_cache:
            # Drop stale entries to cap memory use while keeping recent events for de-dupe.
            cutoff = now - (self.dedup_window * 2)
            stale_keys = [k for k, ts in self.last_seen.items() if ts < cutoff]
            for key in stale_keys:
                self.last_seen.pop(key, None)

        return last is not None and (now - last) <= self.dedup_window


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture and de-duplicate MQTT events with optional noise filters."
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT broker port")
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="Topic filter(s) to subscribe to. Can be used multiple times. Default: #",
    )
    parser.add_argument(
        "--include-topic",
        action="append",
        default=[],
        help="Regex include filter for topic (can repeat).",
    )
    parser.add_argument(
        "--exclude-topic",
        action="append",
        default=[],
        help="Regex exclude filter for topic (can repeat).",
    )
    parser.add_argument(
        "--payload-contains",
        action="append",
        default=[],
        help="Only keep messages whose payload contains this substring (can repeat).",
    )
    parser.add_argument(
        "--dedup-window",
        type=float,
        default=2.0,
        help="Seconds in which identical event fingerprints are considered duplicates.",
    )
    parser.add_argument(
        "--show-duplicates",
        action="store_true",
        help="Print duplicate messages instead of suppressing them.",
    )
    parser.add_argument(
        "--max-cache",
        type=int,
        default=10000,
        help="Maximum dedupe fingerprint cache size.",
    )
    parser.add_argument(
        "--stats-interval",
        type=float,
        default=10.0,
        help="Print capture stats every N seconds. Set 0 to disable.",
    )
    parser.add_argument(
        "--max-runtime",
        type=float,
        default=0.0,
        help="Optional max runtime in seconds (0 means run forever).",
    )
    parser.add_argument(
        "--emit-min-interval",
        type=float,
        default=0.0,
        help="Suppress messages from the same topic if emitted too soon after the last emitted one.",
    )
    parser.add_argument(
        "--delta-field",
        action="append",
        default=[],
        help=(
            "Require a numeric JSON field to change by at least DELTA before emitting. "
            "Format: field:delta (can repeat)."
        ),
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Write emitted events to this JSONL file.",
    )
    parser.add_argument(
        "--append-log",
        action="store_true",
        help="Append to --log-file instead of overwriting it.",
    )
    parser.add_argument(
        "--log-duplicates",
        action="store_true",
        help="When --show-duplicates is enabled, also write duplicate events to the log.",
    )
    return parser.parse_args()


def compile_patterns(patterns):
    return [re.compile(p) for p in patterns]


def parse_delta_fields(specs):
    parsed = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(f"Invalid --delta-field '{spec}', expected field:delta")
        field, delta_text = spec.split(":", 1)
        field = field.strip()
        if not field:
            raise ValueError(f"Invalid --delta-field '{spec}', field cannot be empty")
        try:
            delta = float(delta_text)
        except ValueError as exc:
            raise ValueError(f"Invalid --delta-field '{spec}', delta must be numeric") from exc
        if delta < 0:
            raise ValueError(f"Invalid --delta-field '{spec}', delta must be >= 0")
        parsed.append((field, delta))
    return parsed


def decode_payload(payload_bytes: bytes) -> str:
    try:
        return payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return payload_bytes.hex()


def canonical_payload(payload_text: str) -> str:
    payload_text = payload_text.strip()
    if not payload_text:
        return ""

    try:
        obj = json.loads(payload_text)
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError:
        return payload_text


def make_fingerprint(topic: str, payload_text: str) -> str:
    canonical = canonical_payload(payload_text)
    raw = f"{topic}\0{canonical}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def should_filter(topic: str, payload_text: str, include_topic, exclude_topic, payload_contains) -> bool:
    if include_topic and not any(rx.search(topic) for rx in include_topic):
        return True

    if exclude_topic and any(rx.search(topic) for rx in exclude_topic):
        return True

    if payload_contains and not any(s in payload_text for s in payload_contains):
        return True

    return False


def print_stats(state: CaptureState):
    total_seen = state.unique_events + state.duplicate_events + state.filtered_events
    print("\n===== MQTT Capture Stats =====")
    print(f"Total seen:            {total_seen}")
    print(f"Unique captured:       {state.unique_events}")
    print(f"Duplicates suppressed: {state.duplicate_events}")
    print(f"Filtered out:          {state.filtered_events}")
    if state.topic_counts:
        print("Top topics:")
        for topic, count in state.topic_counts.most_common(10):
            print(f"  {count:5d}  {topic}")
    print("==============================\n")


def run_capture(args: argparse.Namespace):
    include_topic = compile_patterns(args.include_topic)
    exclude_topic = compile_patterns(args.exclude_topic)
    payload_contains = args.payload_contains
    topics = args.topic if args.topic else ["#"]
    delta_filters = parse_delta_fields(args.delta_field)

    state = CaptureState(
        dedup_window=args.dedup_window,
        show_duplicates=args.show_duplicates,
        max_cache=args.max_cache,
    )

    start_time = time.time()
    last_stats = start_time
    stop_requested = False

    def request_stop(*_):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    log_handle = None

    if args.log_file:
        mode = "a" if args.append_log else "w"
        log_handle = open(args.log_file, mode, encoding="utf-8")
        print(f"Logging emitted events to: {args.log_file}")

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"Connect failed with reason code: {reason_code}")
            return
        for topic in topics:
            _client.subscribe(topic)
            print(f"Subscribed to: {topic}")

    def on_message(_client, _userdata, msg):
        now = time.time()
        payload_text = decode_payload(msg.payload)

        if should_filter(msg.topic, payload_text, include_topic, exclude_topic, payload_contains):
            state.filtered_events += 1
            return

        if args.emit_min_interval > 0:
            last_emit = state.last_emitted_by_topic.get(msg.topic)
            if last_emit is not None and (now - last_emit) < args.emit_min_interval:
                state.filtered_events += 1
                return

        parsed_json = None
        if delta_filters:
            try:
                parsed_json = json.loads(payload_text)
            except json.JSONDecodeError:
                state.filtered_events += 1
                return

            if not isinstance(parsed_json, dict):
                state.filtered_events += 1
                return

            for field, delta in delta_filters:
                value = parsed_json.get(field)
                if not isinstance(value, (int, float)):
                    state.filtered_events += 1
                    return

                key = (msg.topic, field)
                previous = state.last_emitted_field_values.get(key)
                if previous is not None and abs(float(value) - previous) < delta:
                    state.filtered_events += 1
                    return

        fingerprint = make_fingerprint(msg.topic, payload_text)
        duplicate = state.is_duplicate(fingerprint, now)

        if duplicate:
            state.duplicate_events += 1
            if not state.show_duplicates:
                return
            marker = "DUP"
        else:
            state.unique_events += 1
            state.topic_counts[msg.topic] += 1
            state.last_emitted_by_topic[msg.topic] = now
            if delta_filters and isinstance(parsed_json, dict):
                for field, _delta in delta_filters:
                    state.last_emitted_field_values[(msg.topic, field)] = float(parsed_json[field])
            marker = "NEW"

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        print(f"[{ts}] [{marker}] {msg.topic} | {payload_text}")

        if log_handle and (marker == "NEW" or args.log_duplicates):
            event = {
                "ts": ts,
                "epoch": now,
                "marker": marker,
                "topic": msg.topic,
                "payload": payload_text,
            }
            log_handle.write(json.dumps(event, separators=(",", ":")) + "\n")
            log_handle.flush()

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to MQTT broker {args.broker}:{args.port} ...")
    client.connect(args.broker, args.port, keepalive=30)
    client.loop_start()

    try:
        while not stop_requested:
            now = time.time()
            if args.max_runtime > 0 and (now - start_time) >= args.max_runtime:
                break
            if args.stats_interval > 0 and (now - last_stats) >= args.stats_interval:
                print_stats(state)
                last_stats = now
            time.sleep(0.1)
    finally:
        client.loop_stop()
        client.disconnect()
        if log_handle:
            log_handle.close()
        print_stats(state)


def main():
    args = parse_args()
    try:
        run_capture(args)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()