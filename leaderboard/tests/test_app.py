import pytest

from app import create_app


class TestCreateApp:
    def test_returns_gradio_blocks(self, sample_aggregated_dir):
        app = create_app(results_dir=sample_aggregated_dir)
        assert app is not None
        assert hasattr(app, "launch")

    def test_creates_with_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        app = create_app(results_dir=empty)
        assert app is not None
