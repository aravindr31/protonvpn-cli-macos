import os
import logging
from logging.handlers import RotatingFileHandler

from .constants import CONFIG_DIR


def get_logger():
    """
    Create the logger.
    Always logs to file and to console when using PVPN_DEBUG=1
    """
    FORMATTER = logging.Formatter(
        "%(asctime)s — %(name)s — %(levelname)s — %(funcName)s:%(lineno)d — %(message)s" # noqa
    )
    LOGFILE = os.path.join(CONFIG_DIR, "pvpn-cli.log")

    # Create log directory if possible
    try:
        if not os.path.isdir(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        # Starts a new file at 3MB size limit
        file_handler = RotatingFileHandler(LOGFILE, maxBytes=3145728,
                                           backupCount=1)
        file_handler.setFormatter(FORMATTER)
        logger.addHandler(file_handler)
    except (PermissionError, OSError):
        pass

    logger = logging.getLogger("protonvpn-cli")
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(FORMATTER)
    # Only log to console when using PVPN_DEBUG=1
    if os.environ.get("PVPN_DEBUG", 0) == "1":
        logger.addHandler(console_handler)

    return logger


logger = get_logger()
