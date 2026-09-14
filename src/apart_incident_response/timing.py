"""Bounded controller waits. Heartbeats show waiting, never hidden model progress."""
import os
import queue
import socket
import threading
import time
import uuid


def worker_identity():
    return {'worker_id': uuid.uuid4().hex, 'pid': os.getpid(), 'host': socket.gethostname(),
            'identity_scope': 'controller_process_and_invocation', 'started_at_unix': time.time()}


def timed_generate(model, messages, seed, max_output_tokens, choices, timeout_seconds,
                   heartbeat=None, heartbeat_seconds=5):
    result_queue = queue.Queue(maxsize=1)
    def worker():
        try:
            if hasattr(model, 'generate_bounded'):
                result = model.generate_bounded(messages, seed, max_output_tokens, choices, timeout_seconds)
            else:
                result = model.generate(messages, seed, max_output_tokens, choices)
            result_queue.put(('ok', result))
        except Exception as exc:
            result_queue.put(('error', exc))
    started = time.monotonic()
    threading.Thread(target=worker, daemon=True).start()
    while True:
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            return None, (time.monotonic()-started)*1000, TimeoutError('controller generation deadline exceeded')
        try:
            kind, value = result_queue.get(timeout=min(remaining, heartbeat_seconds))
        except queue.Empty:
            if heartbeat:
                heartbeat(time.monotonic() - started)
            continue
        elapsed = (time.monotonic()-started)*1000
        if kind == 'error':
            return None, elapsed, value
        return value, elapsed, None
