import time

def get_continuous_time() -> float:
    # CLOCK_MONOTONIC_RAW on macOS maps to mach_continuous_time (includes sleep time)
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
