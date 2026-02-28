"""Tests for paper download functionality."""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from arxiv_mcp_server.tools.download import (
    conversion_statuses,
    get_paper_path,
    handle_download,
)


@pytest.mark.asyncio
async def test_download_paper_lifecycle(mocker, temp_storage_path, mock_client, mock_paper):
    """Test the complete lifecycle of downloading and converting a paper."""
    paper_id = "2103.12345"
    mocker.patch(
        "arxiv_mcp_server.tools.download.get_arxiv_client",
        return_value=mock_client,
    )

    mock_paper.download_pdf = MagicMock()

    # Mock conversion to write markdown via subprocess mock
    async def mock_convert(paper_id, pdf_path):
        md_path = get_paper_path(paper_id, ".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# Test Paper\nConverted content")
        if paper_id in conversion_statuses:
            status = conversion_statuses[paper_id]
            status.status = "success"
            status.completed_at = datetime.now()

    mocker.patch("asyncio.to_thread", side_effect=mock_convert)

    # Initial download request
    response = await handle_download({"paper_id": paper_id})
    status = json.loads(response[0].text)
    assert status["status"] in ["converting", "success"]

    # Check final status
    response = await handle_download({"paper_id": paper_id, "check_status": True})
    final_status = json.loads(response[0].text)
    assert final_status["status"] in ["success", "converting"]

    # Verify markdown file exists
    if final_status["status"] == "success":
        assert get_paper_path(paper_id, ".md").exists()


@pytest.mark.asyncio
async def test_download_existing_paper(temp_storage_path):
    """Test downloading a paper that's already available."""
    paper_id = "2103.12345"
    md_path = get_paper_path(paper_id, ".md")

    # Create test markdown file
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Existing Paper\nTest content")

    response = await handle_download({"paper_id": paper_id})
    status = json.loads(response[0].text)
    assert status["status"] == "success"


@pytest.mark.asyncio
async def test_download_nonexistent_paper(mocker, mock_client):
    """Test downloading a paper that doesn't exist."""
    mock_client.results.side_effect = lambda *args, **kwargs: iter([])
    mocker.patch(
        "arxiv_mcp_server.tools.download.get_arxiv_client",
        return_value=mock_client,
    )

    response = await handle_download({"paper_id": "invalid.12345"})
    status = json.loads(response[0].text)
    assert status["status"] == "error"


@pytest.mark.asyncio
async def test_check_unknown_status():
    """Test checking status of unknown paper."""
    response = await handle_download({"paper_id": "2103.99999", "check_status": True})
    status = json.loads(response[0].text)
    assert status["status"] == "unknown"


@pytest.mark.asyncio
async def test_convert_pdf_calls_unpdf(mocker, temp_storage_path):
    """Test that convert_pdf_to_markdown shells out to the unpdf binary."""
    from arxiv_mcp_server.tools.download import convert_pdf_to_markdown

    paper_id = "2103.12345"
    pdf_path = get_paper_path(paper_id, ".pdf")
    md_path = get_paper_path(paper_id, ".md")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_text("fake pdf")

    # Mock shutil.which to find the binary
    mocker.patch("arxiv_mcp_server.tools.download.shutil.which", return_value="/usr/local/bin/unpdf")

    # Mock subprocess.run to simulate successful conversion
    def fake_run(cmd, **kwargs):
        md_path.write_text("# Converted\nContent from unpdf")
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    mocker.patch("arxiv_mcp_server.tools.download.subprocess.run", side_effect=fake_run)

    convert_pdf_to_markdown(paper_id, pdf_path)

    assert md_path.exists()
    assert "Converted" in md_path.read_text()
    assert not pdf_path.exists()  # PDF cleaned up


@pytest.mark.asyncio
async def test_convert_pdf_handles_missing_binary(mocker, temp_storage_path):
    """Test graceful failure when unpdf binary is not found."""
    from arxiv_mcp_server.tools.download import convert_pdf_to_markdown

    paper_id = "2103.12345"
    pdf_path = get_paper_path(paper_id, ".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_text("fake pdf")

    mocker.patch("arxiv_mcp_server.tools.download.shutil.which", return_value=None)

    # Set up conversion status to verify error handling
    conversion_statuses[paper_id] = MagicMock()
    conversion_statuses[paper_id].status = "converting"

    convert_pdf_to_markdown(paper_id, pdf_path)

    # Status should not remain in the dict (finally block cleans up)
    assert paper_id not in conversion_statuses
