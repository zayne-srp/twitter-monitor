from unittest.mock import MagicMock, patch

import pytest

from src.reporter.report_generator import ReportGenerator


@pytest.fixture
def reporter():
    return ReportGenerator()


class TestSendReport:
    def test_send_via_webhook(self, reporter, monkeypatch):
        monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://hooks.feishu.cn/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("src.reporter.report_generator.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            result = reporter.send_report("test report content")

        assert result is True
        mock_requests.post.assert_called_once_with(
            "https://hooks.feishu.cn/test",
            json={"msg_type": "text", "content": {"text": "test report content"}},
        )
        mock_resp.raise_for_status.assert_called_once()

    def test_print_to_stdout_when_no_webhook(self, reporter, monkeypatch, capsys):
        monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
        result = reporter.send_report("stdout report content")

        assert result is False
        captured = capsys.readouterr()
        assert "stdout report content" in captured.out

    def test_webhook_error_raises(self, reporter, monkeypatch):
        monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://hooks.feishu.cn/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")

        with patch("src.reporter.report_generator.requests") as mock_requests:
            mock_requests.post.return_value = mock_resp
            with pytest.raises(Exception, match="HTTP 500"):
                reporter.send_report("test content")
