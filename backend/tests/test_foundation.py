from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.db.database import SQLiteDatabase


class SettingsTests(unittest.TestCase):
    def test_environment_overrides_are_applied(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPERLENS_ENVIRONMENT": "test",
                "PAPERLENS_DATABASE_URL": "sqlite:///:memory:",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.environment, "test")
        self.assertEqual(settings.database_url, "sqlite:///:memory:")


class SQLiteDatabaseTests(unittest.TestCase):
    def test_healthcheck_works_for_memory_database(self) -> None:
        self.assertTrue(SQLiteDatabase("sqlite:///:memory:").healthcheck())

    def test_non_sqlite_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SQLiteDatabase("postgresql://localhost/paperlens")


if __name__ == "__main__":
    unittest.main()
