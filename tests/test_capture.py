import frontmatter

from src.capture.capture import capture


def test_capture_writes_expected_frontmatter(tmp_path):
    path = capture("hello world", source="test", brain_root=tmp_path / "brain")

    assert path.exists()
    post = frontmatter.load(path)
    assert post.content == "hello world"
    assert post["source"] == "test"
    assert "id" in post
    assert "captured_at" in post


def test_capture_never_overwrites_prior_file(tmp_path):
    brain_root = tmp_path / "brain"
    p1 = capture("first", brain_root=brain_root)
    p2 = capture("second", brain_root=brain_root)

    assert p1 != p2
    assert p1.exists()
    assert p2.exists()
    assert frontmatter.load(p1).content == "first"
    assert frontmatter.load(p2).content == "second"


def test_capture_places_file_under_year_month(tmp_path):
    from datetime import datetime, timezone

    brain_root = tmp_path / "brain"
    path = capture("dated", brain_root=brain_root)
    now = datetime.now(timezone.utc)

    assert path.parent == brain_root / "episodic" / f"{now:%Y}" / f"{now:%m}"
