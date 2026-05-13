import logging
import sys
from typing import Optional


def setup_logging(level: Optional[str] = None) -> None:
    """Configure root logger with structured format and severity level.

    Every log line includes: timestamp, level, module, and message.
    Failures include exception traceback when available.
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(level.upper()) if level else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove default handlers to avoid duplicate output
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)

    # Suppress noisy third-party logs
    for noisy in ("httpx", "urllib3", "apscheduler.scheduler", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class FailureLogger:
    """Utility for logging failures with structured context.

    Usage:
        logger = FailureLogger("my_module")
        logger.failure("API call failed", exc=e, context={"endpoint": "/foo"})
    """

    def __init__(self, name: str):
        self._log = logging.getLogger(name)

    def failure(self, message: str, exc: Optional[Exception] = None, context: Optional[dict] = None) -> None:
        parts = [f"[FAILURE] {message}"]
        if context:
            for k, v in context.items():
                parts.append(f"  {k}={v}")
        full = "\n".join(parts)
        if exc:
            self._log.exception(full)
        else:
            self._log.error(full)

    def recovery(self, message: str, context: Optional[dict] = None) -> None:
        parts = [f"[RECOVERY] {message}"]
        if context:
            for k, v in context.items():
                parts.append(f"  {k}={v}")
        self._log.warning("\n".join(parts))
