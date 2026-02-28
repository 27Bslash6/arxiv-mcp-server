"""Tests for HTML download functionality."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from arxiv_mcp_server.tools.download import (
    conversion_statuses,
    fetch_html_as_markdown,
    get_paper_path,
    handle_download,
)


@pytest.fixture(autouse=True)
def _clean_conversion_statuses():
    """Clear conversion statuses between tests."""
    conversion_statuses.clear()
    yield
    conversion_statuses.clear()


# ---------------------------------------------------------------------------
# Unit tests for fetch_html_as_markdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_html_as_markdown_success(mocker, temp_storage_path):
    """Test fetch_html_as_markdown converts HTML to markdown and saves it."""
    paper_id = "2401.00001"
    sample_html = "<html><body><h1>Test Paper</h1><p>Abstract text.</p></body></html>"

    mock_response = MagicMock()
    mock_response.text = sample_html
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mocker.patch(
        "arxiv_mcp_server.tools.download.httpx.AsyncClient",
        return_value=mock_client,
    )

    md_path = await fetch_html_as_markdown(paper_id)

    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "Test Paper" in content
    assert "Abstract text" in content

    md_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_fetch_html_as_markdown_raises_on_404(mocker):
    """Test fetch_html_as_markdown raises HTTPStatusError on 404."""
    paper_id = "0901.00001"

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mocker.patch(
        "arxiv_mcp_server.tools.download.httpx.AsyncClient",
        return_value=mock_client,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_html_as_markdown(paper_id)


# ---------------------------------------------------------------------------
# Integration tests for handle_download with format parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_format_tries_html_first(mocker, temp_storage_path):
    """Auto format (default) tries HTML and succeeds without touching PDF."""
    paper_id = "2401.10001"

    async def fake_fetch(pid):
        p = get_paper_path(pid, ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# HTML Paper\nContent", encoding="utf-8")
        return p

    mock_fetch = mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=fake_fetch,
    )

    response = await handle_download({"paper_id": paper_id})
    status = json.loads(response[0].text)

    assert status["status"] == "success"
    assert "HTML" in status["message"]
    mock_fetch.assert_awaited_once_with(paper_id)

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_default_format_is_auto(mocker, temp_storage_path):
    """Omitting format parameter behaves as auto (tries HTML first)."""
    paper_id = "2401.10002"

    async def fake_fetch(pid):
        p = get_paper_path(pid, ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# HTML\nContent", encoding="utf-8")
        return p

    mock_fetch = mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=fake_fetch,
    )

    # No "format" key in arguments at all
    response = await handle_download({"paper_id": paper_id})
    status = json.loads(response[0].text)

    assert status["status"] == "success"
    assert "HTML" in status["message"]
    mock_fetch.assert_awaited_once()

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_html_format_success(mocker, temp_storage_path):
    """Explicit HTML format succeeds."""
    paper_id = "2401.10003"

    async def fake_fetch(pid):
        p = get_paper_path(pid, ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# HTML\nContent", encoding="utf-8")
        return p

    mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=fake_fetch,
    )

    response = await handle_download({"paper_id": paper_id, "format": "html"})
    status = json.loads(response[0].text)

    assert status["status"] == "success"
    assert "HTML" in status["message"]

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_auto_format_falls_back_to_pdf_on_404(mocker, temp_storage_path, mock_client, mock_paper):
    """Auto format falls back to PDF when HTML returns 404."""
    paper_id = "1501.10001"

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_resp),
    )

    mocker.patch(
        "arxiv_mcp_server.tools.download.get_arxiv_client",
        return_value=mock_client,
    )
    mock_paper.download_pdf = MagicMock()

    async def mock_convert(paper_id, pdf_path):
        md_path = get_paper_path(paper_id, ".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# PDF Fallback\nContent", encoding="utf-8")
        if paper_id in conversion_statuses:
            conversion_statuses[paper_id].status = "success"
            conversion_statuses[paper_id].completed_at = datetime.now()

    mocker.patch("asyncio.to_thread", side_effect=mock_convert)

    response = await handle_download({"paper_id": paper_id, "format": "auto"})
    status = json.loads(response[0].text)

    assert status["status"] in ["converting", "success"]

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_auto_format_falls_back_to_pdf_on_generic_error(mocker, temp_storage_path, mock_client, mock_paper):
    """Auto format falls back to PDF on non-HTTP errors (e.g. timeout)."""
    paper_id = "1501.10002"

    mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=httpx.ConnectError("Connection refused"),
    )

    mocker.patch(
        "arxiv_mcp_server.tools.download.get_arxiv_client",
        return_value=mock_client,
    )
    mock_paper.download_pdf = MagicMock()

    async def mock_convert(paper_id, pdf_path):
        md_path = get_paper_path(paper_id, ".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# PDF Fallback\nContent", encoding="utf-8")
        if paper_id in conversion_statuses:
            conversion_statuses[paper_id].status = "success"
            conversion_statuses[paper_id].completed_at = datetime.now()

    mocker.patch("asyncio.to_thread", side_effect=mock_convert)

    response = await handle_download({"paper_id": paper_id})
    status = json.loads(response[0].text)

    assert status["status"] in ["converting", "success"]

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_html_only_format_error_on_404(mocker):
    """HTML-only format returns error when HTML is unavailable (404)."""
    paper_id = "1501.10003"

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_resp),
    )

    response = await handle_download({"paper_id": paper_id, "format": "html"})
    status = json.loads(response[0].text)

    assert status["status"] == "error"
    assert "HTML version not available" in status["message"]
    assert "404" in status["message"]


@pytest.mark.asyncio
async def test_html_only_format_error_on_generic_failure(mocker):
    """HTML-only format returns error on network failure."""
    paper_id = "2401.10004"

    mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
        side_effect=httpx.ConnectError("Connection refused"),
    )

    response = await handle_download({"paper_id": paper_id, "format": "html"})
    status = json.loads(response[0].text)

    assert status["status"] == "error"
    assert "HTML download failed" in status["message"]


@pytest.mark.asyncio
async def test_pdf_format_skips_html(mocker, temp_storage_path, mock_client, mock_paper):
    """PDF format never attempts HTML download."""
    paper_id = "2401.10005"

    mock_fetch = mocker.patch(
        "arxiv_mcp_server.tools.download.fetch_html_as_markdown",
    )

    mocker.patch(
        "arxiv_mcp_server.tools.download.get_arxiv_client",
        return_value=mock_client,
    )
    mock_paper.download_pdf = MagicMock()

    async def mock_convert(paper_id, pdf_path):
        md_path = get_paper_path(paper_id, ".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# PDF Only\nContent", encoding="utf-8")
        if paper_id in conversion_statuses:
            conversion_statuses[paper_id].status = "success"
            conversion_statuses[paper_id].completed_at = datetime.now()

    mocker.patch("asyncio.to_thread", side_effect=mock_convert)

    response = await handle_download({"paper_id": paper_id, "format": "pdf"})
    status = json.loads(response[0].text)

    assert status["status"] in ["converting", "success"]
    mock_fetch.assert_not_awaited()

    get_paper_path(paper_id, ".md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_existing_paper_skips_html_and_pdf(temp_storage_path):
    """Already-downloaded paper is returned immediately regardless of format."""
    paper_id = "2401.10006"
    md_path = get_paper_path(paper_id, ".md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("# Existing\nContent", encoding="utf-8")

    for fmt in ("auto", "html", "pdf"):
        response = await handle_download({"paper_id": paper_id, "format": fmt})
        status = json.loads(response[0].text)
        assert status["status"] == "success"
        assert status["message"] == "Paper already available"

    md_path.unlink(missing_ok=True)
