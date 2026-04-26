from __future__ import annotations

from types import SimpleNamespace

from app.services.metadata import extract_m4b_metadata


class _FakeMP4:
    def __init__(self, _path: str):
        self.tags = {
            "\xa9nam": ["Story Title"],
            "\xa9alb": ["Series Name"],
            "\xa9ART": ["Author Name"],
            "\xa9gen": ["Audiobook"],
            "\xa9day": ["2022-10-01"],
            "trkn": [(7, 12)],
        }
        self.info = SimpleNamespace(length=120.6)


def test_extract_m4b_metadata_maps_common_fields(monkeypatch) -> None:
    monkeypatch.setattr("app.services.metadata.MP4", _FakeMP4)

    metadata = extract_m4b_metadata("/tmp/book.m4b")

    assert metadata.title == "Story Title"
    assert metadata.album == "Series Name"
    assert metadata.artist == "Author Name"
    assert metadata.genre == "Audiobook"
    assert metadata.track_number == 7
    assert metadata.year == 2022
    assert metadata.duration_seconds == 121
    assert metadata.raw is not None


class _FakeMP4NonJSON:
    def __init__(self, _path: str):
        self.tags = {
            "covr": [b"\x00\x01\x02"],
            "trkn": [(3, 9)],
        }
        self.info = SimpleNamespace(length=10)


def test_extract_m4b_metadata_normalizes_non_json_values(monkeypatch) -> None:
    monkeypatch.setattr("app.services.metadata.MP4", _FakeMP4NonJSON)

    metadata = extract_m4b_metadata("/tmp/book.m4b")

    assert metadata.raw == {"covr": ["000102"], "trkn": [[3, 9]]}
