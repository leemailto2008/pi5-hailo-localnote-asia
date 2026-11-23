"""tests/_repo_side_effects：測試跑完只清「這次新建、仍是空的」import 時資料夾。"""
import os

import _repo_side_effects as rse

DIRS = ("a/cache", "b/data", "c/data")


def _mk(root, rel, with_file=False):
    p = root / rel
    p.mkdir(parents=True)
    if with_file:
        (p / "keep.txt").write_text("x")
    return p


def test_only_new_empty_dirs_are_removed(tmp_path):
    _mk(tmp_path, "a/cache")                       # 測試前就在：保留
    pre = rse.snapshot(str(tmp_path), DIRS)
    assert pre == {"a/cache"}
    _mk(tmp_path, "b/data")                        # 測試中新建、空：刪
    _mk(tmp_path, "c/data", with_file=True)        # 測試中新建、有檔案：保留
    removed = rse.remove_new_empty_dirs(pre, str(tmp_path), DIRS)
    assert removed == ["b/data"]
    assert (tmp_path / "a/cache").is_dir() and (tmp_path / "c/data/keep.txt").exists()
    assert not (tmp_path / "b/data").exists() and (tmp_path / "b").is_dir()   # 只刪最末層


def test_missing_dirs_and_symlinks_are_ignored(tmp_path):
    target = _mk(tmp_path, "elsewhere")
    (tmp_path / "a").mkdir()
    os.symlink(target, tmp_path / "a/cache")
    assert rse.remove_new_empty_dirs(set(), str(tmp_path), DIRS) == []
    assert target.is_dir() and (tmp_path / "a/cache").is_symlink()


def test_repo_dirs_list_matches_import_side_effects():
    """清單裡的資料夾要真的是那些模組在 import 時建的（模組改名或改路徑時這裡要跟著改）。"""
    src = {
        "code_dispatcher/voice_memory.py": 'os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_cache")',
        "code_dispatcher/bluetooth_manager.py": 'DATA_DIR = os.path.join(BASE_DIR, "data")',
        "telegram_agent/config.py": 'DATA_DIR = os.path.join(BASE_DIR, "data")',
    }
    for rel, needle in src.items():
        with open(os.path.join(rse.ROOT, rel), encoding="utf-8") as f:
            assert needle in f.read(), rel
    assert {d.replace(os.sep, "/") for d in rse.IMPORT_TIME_DIRS} == {
        "code_dispatcher/audio_cache", "code_dispatcher/data", "telegram_agent/data"}
