"""Review builds cannot select a public version or use uncommitted inputs."""

import pytest
import build_review_snapshot as review


def test_review_rejects_public_version(monkeypatch):
    monkeypatch.setattr("sys.argv", ["build_review_snapshot.py", "--tiled-source", "."])
    monkeypatch.setenv("TRAME_VTKJS_RELEASE_VERSION", "1.2.3")
    with pytest.raises(ValueError, match="public release version"):
        review.main()


def test_review_rejects_uncommitted_inputs(monkeypatch):
    monkeypatch.setattr("sys.argv", ["build_review_snapshot.py", "--tiled-source", "."])
    monkeypatch.delenv("TRAME_VTKJS_RELEASE_VERSION", raising=False)
    monkeypatch.setattr(review.chain, "git_output", lambda *args: " M source.py")
    with pytest.raises(ValueError, match="Commit review inputs"):
        review.main()
