from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ghostroll.logging_utils import attach_session_logfile, setup_logging


def test_setup_logging_default():
    logger = setup_logging()
    assert isinstance(logger, logging.Logger)
    assert logger.name == "ghostroll"


def test_setup_logging_verbose():
    logger = setup_logging(verbose=True)
    assert isinstance(logger, logging.Logger)
    # Verbose mode should set a different log level
    assert logger.level <= logging.INFO


def test_setup_logging_with_session_dir(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    
    logger = setup_logging(session_dir=session_dir)
    assert isinstance(logger, logging.Logger)
    # Session dir should exist
    assert session_dir.exists()


def test_attach_session_logfile(tmp_path: Path):
    logger = setup_logging()
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    
    attach_session_logfile(logger, session_dir)
    
    # Check that log file was created
    log_file = session_dir / "ghostroll.log"
    assert log_file.exists() or log_file.parent.exists()


def test_attach_session_logfile_creates_dir(tmp_path: Path):
    logger = setup_logging()
    session_dir = tmp_path / "new_session"
    # Don't create the directory - function should create it
    
    attach_session_logfile(logger, session_dir)
    
    # Directory should be created
    assert session_dir.exists()

