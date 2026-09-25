from __future__ import annotations

import pytest

from claude_tidy.core.grouping import build_cache_plan, build_session_plan, group_projects
from claude_tidy.core.models import Activity, PlanMode, Project, RiskLevel
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.risk import classify
from claude_tidy.core.scanner import scan_cache, scan_projects
from claude_tidy.core.settings import Settings, load_settings, save_settings
from tests.fixtures import fake_claude as fc


def _top(fake):
    return {p.slug: p for p in group_projects(scan_projects(fake.paths))}


def test_worktree_nested_under_parent_by_cwd(fake):
    top = _top(fake)
    assert set(top) == {"D--work-alpha", "E--other-beta"}
    alpha = top["D--work-alpha"]
    assert [w.worktree_name for w in alpha.worktrees] == ["feat-x"]
    wt = alpha.worktrees[0]
    assert wt.parent_slug == "D--work-alpha"
    assert wt.worktree_exists is False  # D:\work\alpha\.claude\worktrees\feat-x doesn't exist


def test_worktree_slug_fallback_when_no_cwd(tmp_path):
    parent = Project(slug="C--repo", dir=tmp_path)
    wt = Project(slug="C--repo--claude-worktrees-bold-fox", dir=tmp_path)
    top = group_projects([parent, wt])
    assert top == [parent]
    assert parent.worktrees == [wt]
    assert wt.worktree_name == "bold-fox"


def test_plan_all_excludes_worktrees_by_default(fake):
    alpha = _top(fake)["D--work-alpha"]
    plan = build_session_plan(PlanMode.ALL, alpha)
    assert fc.S_WORKTREE not in {t.id for t in plan.targets}
    assert len(plan.targets) == 7
    with_wt = build_session_plan(PlanMode.ALL, alpha, include_worktrees=True)
    assert fc.S_WORKTREE in {t.id for t in with_wt.targets}


def test_plan_single_and_multi_validation(fake):
    alpha = _top(fake)["D--work-alpha"]
    single = build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD])
    assert [t.id for t in single.targets] == [fc.S_OLD]
    with pytest.raises(ValueError):
        build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD, fc.S_RECENT])
    with pytest.raises(ValueError):
        build_session_plan(PlanMode.MULTI, alpha, [])
    with pytest.raises(KeyError):
        build_session_plan(PlanMode.MULTI, alpha, [fc.S_BETA])
    with pytest.raises(ValueError):
        build_session_plan(PlanMode.CACHE, alpha)


def test_cache_plan(fake):
    plan = build_cache_plan(scan_cache(fake.paths))
    assert plan.mode is PlanMode.CACHE
    assert plan.size_bytes == 3 * 100 + 100


@pytest.mark.parametrize(
    ("activity", "age_h", "expected"),
    [
        (Activity.ACTIVE, 100, RiskLevel.DANGER),
        (Activity.MAYBE_ACTIVE, 100, RiskLevel.WARNING),
        (Activity.INACTIVE, 2, RiskLevel.WARNING),
        (Activity.INACTIVE, 25, RiskLevel.SAFE),
    ],
)
def test_risk(activity, age_h, expected):
    now = 1_000_000.0
    assert classify(activity, now - age_h * 3600, now, recent_hours=24) is expected


def test_settings_roundtrip_and_defaults(tmp_path):
    paths = ClaudePaths(claude_home=tmp_path, desktop_dirs=(), temp_dir=tmp_path,
                        app_dir=tmp_path / "app")
    s = load_settings(paths)
    assert s == Settings.defaults(paths)
    assert s.retention_days == 14 and s.maybe_active_minutes == 5 and s.recent_hours == 24
    s.retention_days = 3
    s.backup_dir = tmp_path / "bk"
    save_settings(paths, s)
    assert load_settings(paths) == s


def test_settings_corrupt_file_falls_back(tmp_path):
    paths = ClaudePaths(claude_home=tmp_path, desktop_dirs=(), temp_dir=tmp_path,
                        app_dir=tmp_path / "app")
    paths.app_dir.mkdir()
    paths.settings_file.write_text("{oops")
    assert load_settings(paths) == Settings.defaults(paths)
    paths.settings_file.write_text('{"retention_days": "abc", "unknown": 1}')
    assert load_settings(paths).retention_days == 14


def test_paths_from_env_discovers_msix_desktop(tmp_path):
    pkg = tmp_path / "local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    pkg.mkdir(parents=True)
    paths = ClaudePaths.from_env({"USERPROFILE": str(tmp_path), "APPDATA": str(tmp_path / "r"),
                                  "LOCALAPPDATA": str(tmp_path / "local"),
                                  "TEMP": str(tmp_path / "t")})
    assert paths.claude_home == tmp_path / ".claude"
    assert paths.desktop_dirs == (tmp_path / "r" / "Claude", pkg)
    assert paths.temp_dir == tmp_path / "t" / "claude"
    assert paths.app_dir == tmp_path / "local" / "ClaudeTidy"
