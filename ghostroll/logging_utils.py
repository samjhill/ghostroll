from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(*, session_dir: Path | None = None, verbose: bool = True) -> logging.Logger:
    """
    Set up logging for GhostRoll.
    
    Args:
        session_dir: Optional session directory to write log file to
        verbose: If True (default), show DEBUG level logs. If False, only show INFO and above.
    """
    logger = logging.getLogger("ghostroll")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if session_dir is not None:
        session_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(session_dir / "ghostroll.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.propagate = False
    return logger


def attach_session_logfile(logger: logging.Logger, session_dir: Path) -> None:
    """
    Adds a session logfile handler if one is not already present.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    logfile = session_dir / "ghostroll.log"
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == logfile:
            return

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(logfile)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)


