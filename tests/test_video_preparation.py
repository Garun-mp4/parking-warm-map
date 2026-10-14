from urllib.parse import parse_qs, urlparse

import pytest

from scripts.prepare_parking_video import fragment_url, walltime


def test_sequence_selection_preserves_other_url_parameters():
    url = fragment_url("https://example.test/video?itag=136&sq=4&value=a%2Bb", 120)
    assert parse_qs(urlparse(url).query) == {
        "itag": ["136"],
        "sq": ["120"],
        "value": ["a+b"],
    }


def test_source_timestamp_is_read_from_the_video_segment():
    segment = b"\x00\x00\x00\x1cftypdash" + b"First-Frame-Time-Us: 1791948176241045\r\n"
    assert walltime(segment) == pytest.approx(1791948176.241045, rel=0, abs=0.000001)


@pytest.mark.parametrize("body", [b"<html>sign in</html>", b"\x00\x00\x00\x1cftypdash"])
def test_nonvideo_or_untimestamped_download_is_rejected(body):
    with pytest.raises(ValueError, match="timestamped"):
        walltime(body)
