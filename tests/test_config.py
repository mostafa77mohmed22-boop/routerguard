"""اختبارات تحميل الإعدادات."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config, masked_config


def test_load_example_config():
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.example.yaml")
    assert cfg["router"]["url"] == "http://192.168.1.1"
    assert "MyPhone" in cfg["devices"]["allowed"]
    assert cfg["scan"]["interval_seconds"] == 180


def test_env_ref_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_TEST_SECRET", "s3cr3t")
    p = tmp_path / "c.yaml"
    p.write_text("router:\n  password: env:RG_TEST_SECRET\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["router"]["password"] == "s3cr3t"


def test_env_override_prefix(tmp_path, monkeypatch):
    p = tmp_path / "c.yaml"
    p.write_text("scan:\n  interval_seconds: 180\n", encoding="utf-8")
    monkeypatch.setenv("ROUTERGUARD__SCAN__INTERVAL_SECONDS", "300")
    cfg = load_config(p)
    assert cfg["scan"]["interval_seconds"] == "300"


def test_masked_config_hides_secrets():
    cfg = {"router": {"username": "admin", "password": "x", "url": "http://a"}}
    masked = masked_config(cfg)
    assert masked["router"]["password"] == "***"
    assert masked["router"]["url"] == "http://a"
    # الأصل لم يتغير
    assert cfg["router"]["password"] == "x"
