"""Tests for ivory_helm/config/book_config.py."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ivory_helm.config.book_config import (
    BookConfig,
    _dict_to_config,
    _merge_dict,
    list_book_configs,
    load_config,
)


class TestMergeDict:

    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        overlay = {"c": 3}
        assert _merge_dict(base, overlay) == {"a": 1, "b": 2, "c": 3}

    def test_overlay_wins_on_conflict(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 99}
        assert _merge_dict(base, overlay) == {"a": 1, "b": 99}

    def test_nested_override(self):
        base = {"x": {"a": 1, "b": 2}}
        overlay = {"x": {"b": 99}}
        result = _merge_dict(base, overlay)
        assert result == {"x": {"a": 1, "b": 99}}

    def test_deep_nesting(self):
        base = {"x": {"y": {"z": 1, "w": 2}}}
        overlay = {"x": {"y": {"z": 100}}}
        result = _merge_dict(base, overlay)
        assert result == {"x": {"y": {"z": 100, "w": 2}}}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        overlay = {"a": {"b": 2}}
        _merge_dict(base, overlay)
        assert base == {"a": {"b": 1}}


class TestDictToConfig:

    def test_full_dict(self):
        data = {
            "book_id": "test_book",
            "silver_gauge": {"dpi": 300, "smooth_k": 11},
            "bronze_mirror": {"ocr_lang": "en"},
            "platinum_scale": {"max_workers": 25},
            "ivory_helm": {"max_iterations": 5},
            "metadata": {"title": "Test Title"},
        }
        cfg = _dict_to_config(data)
        assert cfg.book_id == "test_book"
        assert cfg.silver_gauge.dpi == 300
        assert cfg.silver_gauge.smooth_k == 11
        assert cfg.bronze_mirror.ocr_lang == "en"
        assert cfg.platinum_scale.max_workers == 25
        assert cfg.ivory_helm.max_iterations == 5
        assert cfg.metadata.title == "Test Title"

    def test_partial_dict_uses_defaults(self):
        cfg = _dict_to_config({"silver_gauge": {"dpi": 200}})
        assert cfg.silver_gauge.dpi == 200
        assert cfg.silver_gauge.smooth_k == 15  # default
        assert cfg.bronze_mirror.ocr_lang == "ch"  # default
        assert cfg.book_id == ""

    def test_unknown_keys_ignored(self):
        data = {
            "silver_gauge": {"nonexistent_key": 42, "dpi": 200},
            "totally_unknown": {"x": 1},
        }
        cfg = _dict_to_config(data)
        assert cfg.silver_gauge.dpi == 200
        assert not hasattr(cfg.silver_gauge, "nonexistent_key")

    def test_empty_dict(self):
        cfg = _dict_to_config({})
        assert cfg.book_id == ""
        assert cfg.silver_gauge.dpi == 150  # all defaults


class TestLoadConfig:

    def test_load_none_returns_defaults(self, tmp_path, monkeypatch):
        # Create a minimal default.yaml
        books_dir = tmp_path / "books"
        books_dir.mkdir()
        default_yaml = books_dir / "default.yaml"
        default_yaml.write_text(yaml.dump({"silver_gauge": {"dpi": 200}}))

        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", books_dir)
        monkeypatch.setattr(mod, "DEFAULT_CONFIG", default_yaml)

        cfg = load_config(None)
        assert cfg.silver_gauge.dpi == 200
        assert cfg.book_id == ""

    def test_load_existing_book(self, tmp_path, monkeypatch):
        books_dir = tmp_path / "books"
        books_dir.mkdir()
        default_yaml = books_dir / "default.yaml"
        default_yaml.write_text(yaml.dump({
            "silver_gauge": {"dpi": 150, "smooth_k": 15},
        }))
        book_yaml = books_dir / "mybook.yaml"
        book_yaml.write_text(yaml.dump({
            "silver_gauge": {"smooth_k": 11},
            "metadata": {"title": "My Book"},
        }))

        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", books_dir)
        monkeypatch.setattr(mod, "DEFAULT_CONFIG", default_yaml)

        cfg = load_config("mybook")
        assert cfg.book_id == "mybook"
        assert cfg.silver_gauge.smooth_k == 11  # overridden
        assert cfg.silver_gauge.dpi == 150  # from default
        assert cfg.metadata.title == "My Book"

    def test_load_nonexistent_book(self, tmp_path, monkeypatch):
        books_dir = tmp_path / "books"
        books_dir.mkdir()
        default_yaml = books_dir / "default.yaml"
        default_yaml.write_text(yaml.dump({"silver_gauge": {"dpi": 150}}))

        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", books_dir)
        monkeypatch.setattr(mod, "DEFAULT_CONFIG", default_yaml)

        cfg = load_config("nonexistent")
        assert cfg.book_id == "nonexistent"
        assert cfg.silver_gauge.dpi == 150  # defaults apply


class TestListBookConfigs:

    def test_returns_sorted_stems_excluding_default(self, tmp_path, monkeypatch):
        books_dir = tmp_path / "books"
        books_dir.mkdir()
        (books_dir / "default.yaml").write_text("silver_gauge: {}")
        (books_dir / "zebra.yaml").write_text("silver_gauge: {}")
        (books_dir / "alpha.yaml").write_text("silver_gauge: {}")

        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", books_dir)

        result = list_book_configs()
        assert result == ["alpha", "zebra"]

    def test_empty_dir(self, tmp_path, monkeypatch):
        books_dir = tmp_path / "books"
        books_dir.mkdir()

        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", books_dir)

        assert list_book_configs() == []

    def test_nonexistent_dir(self, tmp_path, monkeypatch):
        import ivory_helm.config.book_config as mod
        monkeypatch.setattr(mod, "CONFIG_DIR", tmp_path / "nope")

        assert list_book_configs() == []
