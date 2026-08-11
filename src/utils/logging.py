"""
Logging setup.

Rule: never log secrets (Telegram token, AI API key). We enforce this with a
logging Filter that redacts any configured secret values before they hit the
log stream, as a safety net in addition to just not logging them directly.
"""
import logging
import sys


class RedactSecretsFilter(logging.Filter):
    def __init__(self, secrets):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for secret in self._secrets:
            if secret in msg:
                msg = msg.replace(secret, "***REDACTED***")
        record.msg = msg
        record.args = ()
        return True


def setup_logging(secrets=None, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger("dealfinder")
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RedactSecretsFilter(secrets or []))
    logger.addHandler(handler)
    return logger


logger = setup_logging()
