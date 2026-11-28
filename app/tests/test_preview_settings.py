from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.preview_settings import (
    DEFAULT_PREVIEW_SETTINGS,
    PREVIEW_SETTINGS_SETTING,
    PreviewSettingsError,
    validate_preview_settings,
)
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


class PreviewSettingsTests(unittest.TestCase):
    def test_defaults_and_validation(self) -> None:
        self.assertEqual(validate_preview_settings({}), DEFAULT_PREVIEW_SETTINGS)
        self.assertEqual(
            validate_preview_settings({"thumbnails_enabled": False}),
            {"thumbnails_enabled": False, "realtime_limit": 50},
        )
        self.assertEqual(
            validate_preview_settings(
                {"thumbnails_enabled": True, "realtime_limit": 137}
            ),
            {"thumbnails_enabled": True, "realtime_limit": 137},
        )
        for limit in (10, 200):
            self.assertEqual(
                validate_preview_settings({"realtime_limit": limit})["realtime_limit"],
                limit,
            )
        for limit in (9, 201, 0, -1, True, "50", 50.0, None):
            with self.subTest(limit=limit), self.assertRaises(PreviewSettingsError):
                validate_preview_settings({"realtime_limit": limit})
        with self.assertRaises(PreviewSettingsError):
            validate_preview_settings({"thumbnails_enabled": "no"})
        with self.assertRaises(PreviewSettingsError):
            validate_preview_settings({"unexpected": True})


class PreviewSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "tasks.db"
        self.out_root = root / "tasks"
        self.client = TestClient(
            create_app(self.db_path, self.out_root),
            headers=HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preview_settings_round_trip_and_validation(self) -> None:
        self.assertEqual(
            self.client.get("/api/system/preview-settings").json(),
            {"thumbnails_enabled": True, "realtime_limit": 50},
        )
        saved = self.client.put(
            "/api/system/preview-settings",
            json={"thumbnails_enabled": False, "realtime_limit": 137},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(
            saved.json(),
            {"thumbnails_enabled": False, "realtime_limit": 137},
        )
        self.assertEqual(
            self.client.get("/api/system/preview-settings").json(),
            {"thumbnails_enabled": False, "realtime_limit": 137},
        )
        for payload in (
            {"thumbnails_enabled": "no", "realtime_limit": 50},
            {"thumbnails_enabled": True, "realtime_limit": 9},
            {"thumbnails_enabled": True, "realtime_limit": 201},
            {"thumbnails_enabled": True, "realtime_limit": True},
            {"thumbnails_enabled": True, "realtime_limit": "50"},
            {"thumbnails_enabled": True, "realtime_limit": 50.5},
        ):
            with self.subTest(payload=payload):
                rejected = self.client.put(
                    "/api/system/preview-settings",
                    json=payload,
                )
                self.assertEqual(rejected.status_code, 422)
        unknown = self.client.put(
            "/api/system/preview-settings",
            json={
                "thumbnails_enabled": True,
                "realtime_limit": 50,
                "unexpected": 1,
            },
        )
        self.assertEqual(unknown.status_code, 422)

    def test_legacy_stored_value_keeps_default_limit(self) -> None:
        TaskStore(self.db_path).set_setting(
            PREVIEW_SETTINGS_SETTING,
            '{"thumbnails_enabled": false}',
        )
        self.assertEqual(
            self.client.get("/api/system/preview-settings").json(),
            {"thumbnails_enabled": False, "realtime_limit": 50},
        )

    def test_corrupt_stored_value_falls_back_to_default(self) -> None:
        TaskStore(self.db_path).set_setting(PREVIEW_SETTINGS_SETTING, "{not-json")
        self.assertEqual(
            self.client.get("/api/system/preview-settings").json(),
            DEFAULT_PREVIEW_SETTINGS,
        )
