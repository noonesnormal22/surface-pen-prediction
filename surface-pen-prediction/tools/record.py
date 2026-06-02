#!/usr/bin/env python3
"""
Record a daemon trace (raw input vs emitted output) for offline analysis.

The daemon must be running. Use this to capture a stroke trace, then feed the
CSV to analyze-strokes.py to measure hooks, endpoint accuracy, and roundness.

Usage:
    tools/record.py start [path]     # begin recording (default: /tmp/trace.csv)
    tools/record.py stop             # stop recording
    tools/record.py status           # is it recording? how many events so far?

Typical workflow:
    tools/record.py start /tmp/test.csv
    # ... draw in Krita for a bit ...
    tools/record.py stop
    tools/analyze-strokes.py /tmp/test.csv
"""

import json
import os
import socket
import sys

SOCKET_PATH = os.path.expanduser('~/.local/share/ipts-predict.sock')


def send(cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCKET_PATH)
        s.send(json.dumps(cmd).encode())
        resp = json.loads(s.recv(4096).decode())
        s.close()
        return resp
    except FileNotFoundError:
        sys.exit("Daemon socket not found — is ipts-predict running?")
    except ConnectionRefusedError:
        sys.exit("Daemon not responding — is ipts-predict running?")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('start', 'stop', 'status'):
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action == 'start':
        path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/trace.csv'
        path = os.path.abspath(path)
        r = send({'record_start': path})
        if r.get('recording'):
            print(f"Recording to {path}")
            print("Draw in Krita, then run:  tools/record.py stop")
        else:
            print("Failed to start recording.")

    elif action == 'stop':
        r = send({'record_stop': True})
        print("Recording stopped." if not r.get('recording') else "Still recording?")

    elif action == 'status':
        r = send({'status': True})
        rec = r.get('recording')
        print(f"Recording: {'ON' if rec else 'off'}")
        print(f"Events seen: real={r.get('real_count')} synth={r.get('synth_count')}")


if __name__ == '__main__':
    main()
