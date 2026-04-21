import time

LOG_LEVEL = "INFO"  # DEBUG, INFO, ERROR

def log(msg, level="INFO"):
    levels = ["DEBUG", "INFO", "SIGNAL"]

    if levels.index(level) < levels.index(LOG_LEVEL):
        return

    return print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}", flush=True)