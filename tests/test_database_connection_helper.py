import unittest
from unittest.mock import AsyncMock, patch

from backend.core.database import get_connection


class GetConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_settings_dsn_for_direct_connection(self) -> None:
        fake_connection = object()

        with patch("backend.core.database.get_settings") as mock_get_settings, patch(
            "backend.core.database.asyncpg.connect",
            new=AsyncMock(return_value=fake_connection),
        ) as mock_connect:
            mock_get_settings.return_value.database_dsn = "postgresql://example"

            result = await get_connection()

        self.assertIs(result, fake_connection)
        mock_connect.assert_awaited_once_with(dsn="postgresql://example")


if __name__ == "__main__":
    unittest.main()
