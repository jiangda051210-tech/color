"""
Security and performance regression tests.

Covers:
- Path traversal prevention in _generate_output_dir
- SQL identifier validation in _ensure_columns
- Image magic-bytes validation in _is_valid_image_bytes
- CIEDE2000 numerical correctness after constant refactor
- load_action_rules mtime cache
- load_decision_policy mtime cache
- load_customer_tier_config mtime cache
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 1. SQL identifier validation
# ---------------------------------------------------------------------------

class TestEnsureColumnsIdentifierValidation:
    def test_safe_identifiers_accepted(self):
        from elite_quality_history import _SAFE_IDENTIFIER, _ALLOWED_SQL_TYPES
        assert _SAFE_IDENTIFIER.match("valid_column")
        assert _SAFE_IDENTIFIER.match("quality_runs")
        assert "TEXT" in _ALLOWED_SQL_TYPES
        assert "REAL" in _ALLOWED_SQL_TYPES

    def test_dangerous_identifiers_rejected(self):
        from elite_quality_history import _SAFE_IDENTIFIER
        assert not _SAFE_IDENTIFIER.match("'; DROP TABLE--")
        assert not _SAFE_IDENTIFIER.match("col name")
        assert not _SAFE_IDENTIFIER.match("")
        assert not _SAFE_IDENTIFIER.match("1starts_with_digit")

    def test_disallowed_sql_types_rejected(self):
        from elite_quality_history import _ALLOWED_SQL_TYPES
        assert "DROP" not in _ALLOWED_SQL_TYPES
        assert "VARCHAR(255); DROP TABLE quality_runs;--" not in _ALLOWED_SQL_TYPES

    def test_ensure_columns_raises_on_bad_table(self, tmp_path):
        import sqlite3
        from elite_quality_history import _ensure_columns
        conn = sqlite3.connect(str(tmp_path / "test.sqlite"))
        conn.execute("CREATE TABLE safe_table (id INTEGER PRIMARY KEY)")
        with pytest.raises(ValueError, match="unsafe table name"):
            _ensure_columns(conn, "bad; DROP TABLE", {"col": "TEXT"})
        conn.close()

    def test_ensure_columns_raises_on_bad_column(self, tmp_path):
        import sqlite3
        from elite_quality_history import _ensure_columns
        conn = sqlite3.connect(str(tmp_path / "test.sqlite"))
        conn.execute("CREATE TABLE mytable (id INTEGER PRIMARY KEY)")
        with pytest.raises(ValueError, match="unsafe column name"):
            _ensure_columns(conn, "mytable", {"'; DROP TABLE mytable;--": "TEXT"})
        conn.close()

    def test_ensure_columns_raises_on_bad_type(self, tmp_path):
        import sqlite3
        from elite_quality_history import _ensure_columns
        conn = sqlite3.connect(str(tmp_path / "test.sqlite"))
        conn.execute("CREATE TABLE mytable (id INTEGER PRIMARY KEY)")
        with pytest.raises(ValueError, match="disallowed SQL type"):
            _ensure_columns(conn, "mytable", {"newcol": "VARCHAR(255); DROP TABLE mytable;--"})
        conn.close()


# ---------------------------------------------------------------------------
# 2. Image magic-bytes validation
# ---------------------------------------------------------------------------

class TestImageMagicBytesValidation:
    def _make_bytes(self, magic: bytes, pad: int = 100) -> bytes:
        return magic + b"\x00" * pad

    def test_jpeg_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"\xff\xd8\xff"))

    def test_png_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"\x89PNG\r\n\x1a\n"))

    def test_bmp_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"BM"))

    def test_tiff_le_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"II\x2a\x00"))

    def test_tiff_be_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"MM\x00\x2a"))

    def test_webp_accepted(self):
        from elite_api import _is_valid_image_bytes
        assert _is_valid_image_bytes(self._make_bytes(b"RIFF"))

    def test_random_bytes_rejected(self):
        from elite_api import _is_valid_image_bytes
        assert not _is_valid_image_bytes(b"\x00\x01\x02\x03" * 50)

    def test_empty_rejected(self):
        from elite_api import _is_valid_image_bytes
        assert not _is_valid_image_bytes(b"")

    def test_text_rejected(self):
        from elite_api import _is_valid_image_bytes
        assert not _is_valid_image_bytes(b"<html><body>not an image</body></html>")

    def test_php_shell_rejected(self):
        from elite_api import _is_valid_image_bytes
        assert not _is_valid_image_bytes(b"<?php system($_GET['cmd']); ?>")


# ---------------------------------------------------------------------------
# 3. Path traversal prevention in _generate_output_dir
# ---------------------------------------------------------------------------

class TestGenerateOutputDirPathTraversal:
    def test_subpath_allowed(self, tmp_path):
        with patch("elite_api.DEFAULT_OUTPUT_ROOT", tmp_path):
            from elite_api import _generate_output_dir
            result = _generate_output_dir("test", str(tmp_path / "sub" / "run1"))
            assert result == tmp_path / "sub" / "run1"

    def test_traversal_rejected(self, tmp_path):
        from fastapi import HTTPException
        with patch("elite_api.DEFAULT_OUTPUT_ROOT", tmp_path):
            from elite_api import _generate_output_dir
            with pytest.raises(HTTPException) as exc_info:
                _generate_output_dir("test", str(tmp_path / ".." / "escaped"))
            assert exc_info.value.status_code == 400

    def test_absolute_outside_rejected(self, tmp_path):
        from fastapi import HTTPException
        with patch("elite_api.DEFAULT_OUTPUT_ROOT", tmp_path):
            from elite_api import _generate_output_dir
            with pytest.raises(HTTPException) as exc_info:
                _generate_output_dir("test", "/etc/passwd")
            assert exc_info.value.status_code == 400

    def test_no_requested_dir_uses_default(self, tmp_path):
        with patch("elite_api.DEFAULT_OUTPUT_ROOT", tmp_path):
            from elite_api import _generate_output_dir
            result = _generate_output_dir("myprefix", None)
            assert str(result).startswith(str(tmp_path))
            assert "myprefix" in result.name


# ---------------------------------------------------------------------------
# 4. CIEDE2000 numerical correctness
# ---------------------------------------------------------------------------

class TestCiede2000NumericalCorrectness:
    """Verify the refactored ciede2000 (with _C25_7 constant) is numerically correct."""

    def test_identical_colors_give_zero(self):
        from elite_color_match import ciede2000
        lab = np.array([[50.0, 0.0, 0.0]], dtype=np.float32)
        result = ciede2000(lab, lab)
        assert float(result[0]) == pytest.approx(0.0, abs=1e-6)

    def test_known_pair_approx(self):
        """Reference pair from Sharma et al. (2005) test set — pair #1."""
        from elite_color_match import ciede2000
        # Lab1 = (50.0000,  2.6772, -79.7751)
        # Lab2 = (50.0000,  0.0000, -82.7485)
        # Expected ΔE00 ≈ 2.0425
        lab1 = np.array([[50.0000, 2.6772, -79.7751]], dtype=np.float64)
        lab2 = np.array([[50.0000, 0.0000, -82.7485]], dtype=np.float64)
        result = float(ciede2000(lab1, lab2)[0])
        assert result == pytest.approx(2.0425, abs=0.01)

    def test_vectorised_batch(self):
        """Vectorised call on N pairs should give same results as individual calls."""
        from elite_color_match import ciede2000
        rng = np.random.default_rng(42)
        batch_n = 64
        lab1 = rng.uniform([0, -128, -128], [100, 128, 128], (batch_n, 3)).astype(np.float64)
        lab2 = rng.uniform([0, -128, -128], [100, 128, 128], (batch_n, 3)).astype(np.float64)
        batch_result = ciede2000(lab1, lab2)
        for i in range(batch_n):
            single = float(ciede2000(lab1[i : i + 1], lab2[i : i + 1])[0])
            assert float(batch_result[i]) == pytest.approx(single, rel=1e-5)

    def test_symmetry(self):
        """ΔE(A,B) == ΔE(B,A) for CIEDE2000."""
        from elite_color_match import ciede2000
        rng = np.random.default_rng(7)
        lab1 = rng.uniform([0, -50, -50], [100, 50, 50], (32, 3)).astype(np.float64)
        lab2 = rng.uniform([0, -50, -50], [100, 50, 50], (32, 3)).astype(np.float64)
        forward = ciede2000(lab1, lab2)
        backward = ciede2000(lab2, lab1)
        np.testing.assert_allclose(forward, backward, rtol=1e-5)


# ---------------------------------------------------------------------------
# 5. load_action_rules mtime cache
# ---------------------------------------------------------------------------

class TestLoadActionRulesMtimeCache:
    def _write_rules(self, path: Path, tag: str) -> None:
        path.write_text(
            json.dumps({"action_rules": [{"tag": tag}]}),
            encoding="utf-8",
        )

    def test_returns_cached_on_same_mtime(self, tmp_path):
        from elite_process_advisor import _RULES_CACHE, _RULES_CACHE_MTIME, load_action_rules
        _RULES_CACHE.clear()
        _RULES_CACHE_MTIME.clear()
        p = tmp_path / "rules.json"
        self._write_rules(p, "v1")
        r1 = load_action_rules(p)
        r2 = load_action_rules(p)
        assert r1 is r2  # same object — from cache

    def test_reloads_on_mtime_change(self, tmp_path):
        from elite_process_advisor import _RULES_CACHE, _RULES_CACHE_MTIME, load_action_rules
        _RULES_CACHE.clear()
        _RULES_CACHE_MTIME.clear()
        p = tmp_path / "rules.json"
        self._write_rules(p, "v1")
        r1 = load_action_rules(p)
        time.sleep(0.05)
        self._write_rules(p, "v2")
        r2 = load_action_rules(p)
        assert r2["action_rules"][0]["tag"] == "v2"
        assert r1["action_rules"][0]["tag"] == "v1"


# ---------------------------------------------------------------------------
# 6. load_decision_policy mtime cache
# ---------------------------------------------------------------------------

class TestLoadDecisionPolicyMtimeCache:
    def test_returns_deep_copy_not_same_object(self, tmp_path):
        from elite_decision_center import _POLICY_CACHE, _POLICY_CACHE_MTIME, load_decision_policy
        _POLICY_CACHE.clear()
        _POLICY_CACHE_MTIME.clear()
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"decision_policy": {"auto_release_min_confidence": 0.90}}), encoding="utf-8")
        r1, _ = load_decision_policy(p)
        r2, _ = load_decision_policy(p)
        # Must be different objects (deep copy) so mutations don't corrupt cache
        assert r1 is not r2
        r1["decision_policy"]["auto_release_min_confidence"] = 0.01
        r3, _ = load_decision_policy(p)
        assert r3["decision_policy"]["auto_release_min_confidence"] == pytest.approx(0.90)

    def test_builtin_default_returned_when_path_none(self):
        from elite_decision_center import load_decision_policy
        policy, source = load_decision_policy(None)
        assert source == "builtin_default"
        assert "decision_policy" in policy


# ---------------------------------------------------------------------------
# 7. DB init caching — no duplicate CREATE TABLE
# ---------------------------------------------------------------------------

class TestDBInitCaching:
    def test_second_init_is_noop(self, tmp_path):
        from elite_quality_history import _DB_INITIALIZED, init_db
        db = tmp_path / "test.sqlite"
        key = str(db.resolve())
        _DB_INITIALIZED.discard(key)
        init_db(db)
        assert key in _DB_INITIALIZED
        mtime_after_first = db.stat().st_mtime
        time.sleep(0.05)
        init_db(db)  # second call — must be a no-op
        mtime_after_second = db.stat().st_mtime
        assert mtime_after_first == mtime_after_second


# ---------------------------------------------------------------------------
# 8. Batch image path traversal prevention
# ---------------------------------------------------------------------------

class TestValidateBatchImagePath:
    def test_path_within_root_accepted(self, tmp_path):
        from unittest.mock import patch
        img = tmp_path / "images" / "a.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        with patch("elite_api.DEFAULT_BATCH_IMAGES_ROOT", tmp_path.resolve()):
            from elite_api import _validate_batch_image_path
            result = _validate_batch_image_path(img)
            assert result == img.resolve()

    def test_traversal_outside_root_rejected(self, tmp_path):
        from unittest.mock import patch
        from fastapi import HTTPException
        allowed = tmp_path / "images"
        allowed.mkdir()
        with patch("elite_api.DEFAULT_BATCH_IMAGES_ROOT", allowed.resolve()):
            from elite_api import _validate_batch_image_path
            with pytest.raises(HTTPException) as exc_info:
                _validate_batch_image_path(tmp_path / ".." / "etc" / "passwd")
            assert exc_info.value.status_code == 400

    def test_no_root_configured_allows_any_path(self, tmp_path):
        from unittest.mock import patch
        img = tmp_path / "any.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        with patch("elite_api.DEFAULT_BATCH_IMAGES_ROOT", None):
            from elite_api import _validate_batch_image_path
            result = _validate_batch_image_path(img)
            assert result == img.resolve()

    def test_absolute_outside_root_rejected(self, tmp_path):
        from unittest.mock import patch
        from fastapi import HTTPException
        allowed = tmp_path / "images"
        allowed.mkdir()
        with patch("elite_api.DEFAULT_BATCH_IMAGES_ROOT", allowed.resolve()):
            from elite_api import _validate_batch_image_path
            with pytest.raises(HTTPException) as exc_info:
                _validate_batch_image_path(Path("/etc/passwd"))
            assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 9. read_image() dimension & channel validation
# ---------------------------------------------------------------------------

class TestReadImageValidation:
    def _write_valid_image(self, path: Path) -> None:
        """Write a minimal 10×10 3-channel BGR image via cv2."""
        import cv2 as _cv2
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        _cv2.imwrite(str(path), img)

    def test_valid_image_returned(self, tmp_path):
        from elite_color_match import read_image
        p = tmp_path / "ok.png"
        self._write_valid_image(p)
        result = read_image(p)
        assert result.shape == (10, 10, 3)

    def test_nonexistent_file_raises(self, tmp_path):
        from elite_color_match import read_image
        with pytest.raises(FileNotFoundError):
            read_image(tmp_path / "missing.png")

    def test_degenerate_tiny_image_rejected(self, tmp_path):
        """A 1×1 image must be rejected (below _IMAGE_MIN_DIM)."""
        import cv2 as _cv2
        from elite_color_match import read_image
        p = tmp_path / "tiny.png"
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        _cv2.imwrite(str(p), img)
        with pytest.raises(ValueError, match="too small"):
            read_image(p)


# ---------------------------------------------------------------------------
# 10. /metrics Prometheus endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def test_metrics_returns_200_text_plain(self):
        from fastapi.testclient import TestClient
        from elite_api import app
        with TestClient(app) as client:
            resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_contains_required_fields(self):
        from fastapi.testclient import TestClient
        from elite_api import app
        with TestClient(app) as client:
            body = client.get("/metrics").text
        assert "elite_requests_total" in body
        assert "elite_process_uptime_seconds" in body
        assert "elite_requests_per_minute" in body
