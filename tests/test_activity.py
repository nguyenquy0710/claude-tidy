from __future__ import annotations

import os

import psutil
import pytest

from claude_tidy.core.activity import (
    ActivityDetector,
    ProcessState,
    PsutilProbe,
    filetime_to_epoch,
    probe_process,
    read_index,
)
from claude_tidy.core.models import Activity
from claude_tidy.core.scanner import scan_projects
from tests.fixtures import fake_claude as fc


def _bundle(fake, sid):
    for project in scan_projects(fake.paths):
        for s in project.sessions:
            if s.session_id == sid:
                return s
    raise KeyError(sid)


def test_filetime_roundtrip():
    assert filetime_to_epoch(fc.to_filetime(1_790_309_512.244)) == pytest.approx(1_790_309_512.244)
    # Real sample from a live sessions/<pid>.json.
    assert filetime_to_epoch("134347831122444350") == pytest.approx(1790309512.244, abs=1e-3)


@pytest.mark.parametrize("value", [None, "", "abc", "1790309512244", 12345])
def test_filetime_rejects_other_units(value):
    assert filetime_to_epoch(value) is None


@pytest.mark.parametrize(
    ("sid", "expected"),
    [
        (fc.S_LIVE, Activity.ACTIVE),          # PID alive and start time matches
        (fc.S_REUSED, Activity.INACTIVE),      # PID alive but belongs to another process
        (fc.S_DEAD, Activity.INACTIVE),        # PID gone
        (fc.S_DENIED, Activity.MAYBE_ACTIVE),  # can't read process -> don't assume dead
        (fc.S_FRESH, Activity.MAYBE_ACTIVE),   # no index, but written 60s ago
        (fc.S_RECENT, Activity.INACTIVE),      # written 2h ago: beyond the 5 min window
        (fc.S_OLD, Activity.INACTIVE),
    ],
)
def test_activity_status(fake, detector, sid, expected):
    assert detector.status(_bundle(fake, sid)) is expected


def test_corrupt_index_is_flagged_not_fatal(fake):
    entries = {e.pid: e for e in read_index(fake.paths)}
    corrupt = entries[fc.PID_CORRUPT]
    assert corrupt.corrupt
    assert corrupt.session_id is None
    assert len(corrupt.key_files) == 1
    assert entries[fc.PID_LIVE].proc_start == pytest.approx(fc.PROC_START_LIVE, abs=1e-3)


def test_missing_sessions_dir(fake):
    for f in fake.paths.sessions_dir.iterdir():
        f.unlink()
    fake.paths.sessions_dir.rmdir()
    det = ActivityDetector(fake.paths, probe=fake.probe, clock=lambda: fc.NOW)
    assert det.index_entries() == []
    assert det.status(_bundle(fake, fc.S_OLD)) is Activity.INACTIVE


def test_orphans_are_dead_or_reused_pids(fake, detector):
    orphans = {e.pid for e in detector.orphan_entries()}
    # corrupt file's PID (from its filename) is not running either
    assert orphans == {fc.PID_REUSED, fc.PID_DEAD, fc.PID_CORRUPT}


def test_refresh_picks_up_new_state(fake, detector):
    bundle = _bundle(fake, fc.S_OLD)
    assert detector.status(bundle) is Activity.INACTIVE
    fc._index(fake.paths.claude_home, 4200, fc.S_OLD, fc.ALPHA_CWD, fc.NOW - 10)
    fake.probe.table[4200] = fc.NOW - 10
    detector.refresh()
    assert detector.status(bundle) is Activity.ACTIVE


# --- against the real OS process table, using this test process itself ---

def test_real_psutil_alive_pid_matches_own_start_time():
    me = psutil.Process(os.getpid()).create_time()
    assert probe_process(os.getpid(), me, PsutilProbe()) is ProcessState.MATCH


def test_real_psutil_reused_pid_detected():
    me = psutil.Process(os.getpid()).create_time()
    assert probe_process(os.getpid(), me - 3600, PsutilProbe()) is ProcessState.REUSED


def test_real_psutil_dead_pid():
    pid = max(psutil.pids()) + 100_000
    assert probe_process(pid, 1.0, PsutilProbe()) is ProcessState.GONE


def test_alive_pid_without_proc_start_is_unknown():
    assert probe_process(os.getpid(), None, PsutilProbe()) is ProcessState.UNKNOWN
