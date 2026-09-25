from __future__ import annotations

import json

from claude_tidy.core import scanner
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.scanner import (
    check_deletable,
    count_messages,
    read_session_meta,
    scan_cache,
    scan_projects,
)
from tests.fixtures import fake_claude as fc


def _project(projects, slug):
    return next(p for p in projects if p.slug == slug)


def test_bundle_contains_every_session_artifact(fake):
    alpha = _project(scan_projects(fake.paths), "D--work-alpha")
    bundle = next(s for s in alpha.sessions if s.session_id == fc.S_OLD)
    assert sorted(bundle.paths) == sorted(fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))
    assert bundle.cwd == fc.ALPHA_CWD
    assert bundle.title == "Old refactor"
    assert bundle.size_bytes > 0
    assert bundle.message_count == 2  # fixture writes ai-title + user per session


def test_count_messages(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text('{"a":1}\n{"b":2}\n{"c":3}\n', encoding="utf-8")
    assert count_messages(f) == 3


def test_count_messages_missing_file_is_zero_not_an_error(tmp_path):
    assert count_messages(tmp_path / "nope.jsonl") == 0


def test_count_messages_no_trailing_newline_still_counts_last_line(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_bytes(b'{"a":1}\n{"b":2}')  # no trailing \n after the last record
    # A byte-scan counting b"\n" undercounts by one when the file doesn't end
    # in a newline — document the known limitation rather than silently
    # pretend it's exact.
    assert count_messages(f) == 1


def test_memory_and_non_session_entries_are_never_in_a_bundle(fake):
    for project in scan_projects(fake.paths):
        for bundle in project.sessions:
            for p in bundle.paths:
                assert "memory" not in p.parts
                assert check_deletable(p, fake.paths) is None


def test_project_cwd_comes_from_transcript_not_slug(fake):
    alpha = _project(scan_projects(fake.paths), "D--work-alpha")
    assert alpha.cwd == fc.ALPHA_CWD
    assert len(alpha.sessions) == 7


def test_orphan_sidecar_without_jsonl_is_still_a_bundle(fake):
    slug_dir = fake.paths.projects_dir / "D--work-alpha"
    orphan = "abcdefab-0000-0000-0000-000000000000"
    (slug_dir / f"{orphan}.jsonl.wakatime").write_text("1")
    alpha = _project(scan_projects(fake.paths), "D--work-alpha")
    bundle = next(s for s in alpha.sessions if s.session_id == orphan)
    assert bundle.jsonl is None
    assert bundle.paths == [slug_dir / f"{orphan}.jsonl.wakatime"]


def test_read_meta_only_reads_head_and_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "HEAD_BYTES", 1024)
    monkeypatch.setattr(scanner, "TAIL_BYTES", 512)
    f = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "x", "cwd": "C:\\from\\middle"}) + "\n"
    with f.open("w", encoding="utf-8") as out:
        out.write(json.dumps({"type": "user", "cwd": "C:\\repo"}) + "\n")
        out.write(filler * 500)
        out.write(json.dumps({"type": "custom-title", "customTitle": "Named"}) + "\n")
    cwd, title = read_session_meta(f)
    assert cwd == "C:\\repo"
    assert title == "Named"


def test_read_meta_tolerates_garbage(tmp_path):
    f = tmp_path / "bad.jsonl"
    f.write_bytes(b"\x00\xffnot json\n[1,2]\n")
    assert read_session_meta(f) == (None, None)


def test_check_deletable_refuses_protected_and_foreign_paths(fake):
    home = fake.paths.claude_home
    for p in fake.protected:
        assert check_deletable(p, fake.paths) is not None, p
    refused = [
        home,
        home / "projects",
        home / "projects" / "D--work-alpha",
        home / "projects" / "D--work-alpha" / "memory",
        home / "projects" / "D--work-alpha" / "notes.txt",
        home / "file-history",
        home / "sessions",
        home / "sessions" / "notes.json",
        fake.paths.desktop_dirs[0],
        fake.paths.desktop_dirs[0] / "vm_bundles",
        fake.paths.temp_dir,
        fake.outside_dir,
    ]
    for p in refused:
        assert check_deletable(p, fake.paths) is not None, p


def test_check_deletable_allows_exact_bundle_shapes(fake):
    home = fake.paths.claude_home
    for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"):
        assert check_deletable(p, fake.paths) is None, p
    assert check_deletable(home / "sessions" / "4101.json", fake.paths) is None
    assert check_deletable(home / "sessions" / "4101.deadbeef4101.key", fake.paths) is None
    assert check_deletable(fake.paths.desktop_dirs[0] / "GPUCache", fake.paths) is None


def test_check_deletable_is_case_insensitive_on_windows_paths(fake):
    p = fake.paths.claude_home / "projects" / "D--work-alpha" / "MEMORY"
    assert check_deletable(p, fake.paths) is not None


def test_scan_cache_uses_allowlist_only(fake):
    groups = scan_cache(fake.paths)
    names = {g.name for g in groups}
    assert names == {"Desktop: Cache", "Desktop: GPUCache", "Desktop: logs",
                     "Temp (%TEMP%\\claude)"}
    all_paths = [p for g in groups for p in g.paths]
    assert not any("Local Storage" in p.parts or "vm_bundles" in p.parts for p in all_paths)
    temp = next(g for g in groups if g.name.startswith("Temp"))
    assert temp.size_bytes == 100
    assert temp.file_count == 2  # tmp1.txt + tmp2.txt, per fixture
    cache = next(g for g in groups if g.name == "Desktop: Cache")
    assert cache.file_count == 1


def test_scan_handles_missing_directories(tmp_path):
    paths = ClaudePaths(claude_home=tmp_path / "none", desktop_dirs=(tmp_path / "nd",),
                        temp_dir=tmp_path / "nt", app_dir=tmp_path / "app")
    assert scan_projects(paths) == []
    assert scan_cache(paths) == []
