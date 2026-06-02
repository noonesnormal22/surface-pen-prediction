#!/usr/bin/env python3
"""
Stylus event rate analyzer — polls cursor position via X11 to detect motion events.
Draw continuously with the pen for 15 seconds after the script starts.
"""

import time
import statistics
from Xlib import display

POLL_INTERVAL = 0.002   # poll every 2ms (500Hz) — faster than any stylus
DURATION = 15
MIN_MOVE_PX = 2         # ignore sub-pixel jitter

def main():
    print("Draw continuously with the pen for 15 seconds — anywhere on screen.\n")

    d = display.Display()
    root = d.screen().root

    motion_times = []
    gaps = []
    last_t = None
    last_pos = None

    deadline = time.monotonic() + DURATION
    print(f"Recording for {DURATION} seconds...")

    while time.monotonic() < deadline:
        t = time.monotonic()
        try:
            p = root.query_pointer()
            pos = (p.root_x, p.root_y)
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue

        if last_pos is not None:
            dx = abs(pos[0] - last_pos[0])
            dy = abs(pos[1] - last_pos[1])
            if dx + dy >= MIN_MOVE_PX:
                motion_times.append(t)
                if last_t is not None:
                    gaps.append((t - last_t) * 1000)
                last_t = t

        last_pos = pos
        time.sleep(POLL_INTERVAL)

    d.close()

    print("\n" + "=" * 52)
    print("RESULTS")
    print("=" * 52)

    if len(motion_times) < 10:
        print("Not enough motion detected. Make sure the pen was moving.")
        return

    duration = motion_times[-1] - motion_times[0]
    count = len(motion_times)
    avg_hz = count / duration if duration > 0 else 0

    print(f"Motion samples   : {count}")
    print(f"Duration         : {duration:.2f}s")
    print(f"Effective rate   : {avg_hz:.1f} Hz  ({1000/avg_hz:.1f} ms avg interval)")
    print(f"(Poll rate was 500Hz — captures true hardware event rate)")

    if gaps:
        s = sorted(gaps)
        p95 = s[int(len(s) * 0.95)]
        p99 = s[int(len(s) * 0.99)]

        print(f"\nGap between position updates (ms):")
        print(f"  Min            : {min(gaps):.1f}")
        print(f"  Median         : {statistics.median(gaps):.1f}")
        print(f"  Mean           : {statistics.mean(gaps):.1f}")
        print(f"  P95            : {p95:.1f}")
        print(f"  P99            : {p99:.1f}")
        print(f"  Max            : {max(gaps):.1f}  ← worst-case jump")

        big = [g for g in gaps if g > 40]
        print(f"\nGaps > 40ms      : {len(big)} / {len(gaps)}  ({100*len(big)/len(gaps):.1f}%)")
        print(f"  (these produce visible polygon corners in fast strokes)")

        spd = 150
        print(f"\nAt {spd} mm/s drawing speed:")
        print(f"  Avg interval → {statistics.mean(gaps)/1000*spd:.1f} mm between samples")
        print(f"  Max gap      → {max(gaps)/1000*spd:.1f} mm straight-line jump")

    print("=" * 52)

if __name__ == "__main__":
    main()
