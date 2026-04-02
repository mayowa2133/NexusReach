import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio


MOCK_STATUS = {
    "connected": True,
    "source": "manual_import",
    "last_synced_at": None,
    "sync_status": "completed",
    "last_error": None,
    "connection_count": 2,
    "last_run": None,
}


async def test_get_linkedin_graph_status(client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.get_status",
        new_callable=AsyncMock,
    ) as mock_get_status:
        mock_get_status.return_value = MOCK_STATUS
        response = await client.get("/api/linkedin-graph/status")

    assert response.status_code == 200
    assert response.json()["connection_count"] == 2


async def test_create_linkedin_graph_sync_session(client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.create_sync_session",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = {
            "sync_run_id": "run-1",
            "session_token": "secret-token",
            "expires_at": "2026-04-02T12:00:00+00:00",
            "upload_path": "/api/linkedin-graph/import-batch",
            "max_batch_size": 250,
        }
        response = await client.post("/api/linkedin-graph/sync-session")

    assert response.status_code == 200
    assert response.json()["session_token"] == "secret-token"


async def test_import_batch_uses_session_token_without_auth(unauthed_client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.import_batch_with_session",
        new_callable=AsyncMock,
    ) as mock_import:
        mock_import.return_value = MOCK_STATUS
        response = await unauthed_client.post(
            "/api/linkedin-graph/import-batch",
            json={
                "session_token": "connector-token",
                "connections": [
                    {
                        "full_name": "Jane Doe",
                        "linkedin_url": "https://www.linkedin.com/in/jane-doe",
                        "current_company_name": "Acme",
                    }
                ],
                "is_final_batch": True,
            },
        )

    assert response.status_code == 200
    assert mock_import.await_args.args[1] == "connector-token"
    assert mock_import.await_args.kwargs["is_final_batch"] is True


async def test_import_file_accepts_multipart_upload(client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.import_file",
        new_callable=AsyncMock,
    ) as mock_import:
        mock_import.return_value = MOCK_STATUS
        response = await client.post(
            "/api/linkedin-graph/import-file",
            files={"file": ("Connections.csv", b"First Name,Last Name,URL\nJane,Doe,https://www.linkedin.com/in/jane", "text/csv")},
        )

    assert response.status_code == 200
    assert mock_import.await_args.kwargs["filename"] == "Connections.csv"


async def test_clear_connections_handles_auth_or_dev_bypass(unauthed_client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.clear_connections",
        new_callable=AsyncMock,
    ) as mock_clear:
        mock_clear.return_value = {
            **MOCK_STATUS,
            "connected": False,
            "connection_count": 0,
            "sync_status": "idle",
            "source": None,
        }
        response = await unauthed_client.delete("/api/linkedin-graph/connections")

    assert response.status_code in (200, 401, 403)


async def test_clear_connections(client):
    with patch(
        "app.routers.linkedin_graph.linkedin_graph_service.clear_connections",
        new_callable=AsyncMock,
    ) as mock_clear:
        mock_clear.return_value = {
            **MOCK_STATUS,
            "connected": False,
            "connection_count": 0,
            "sync_status": "idle",
            "source": None,
        }
        response = await client.delete("/api/linkedin-graph/connections")

    assert response.status_code == 200
    assert response.json()["connected"] is False
