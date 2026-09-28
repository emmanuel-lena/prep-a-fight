import pytest

from paf.simc_install import latest_build, parse_nightly_index

INDEX = """
<a href="simc-1210-01-macos-4c7c736.dmg">x</a>
<a href="simc-1210.01.4c7c736-win64.7z">x</a>
<a href="simc-1210.01.4c7c736-winarm64.7z">x</a>
<a href="simc-1205.01.ac79c0f-win64.7z">x</a>
"""


def test_parse_keeps_windows_builds_in_order():
    builds = parse_nightly_index(INDEX)
    assert [b.filename for b in builds] == [
        "simc-1210.01.4c7c736-win64.7z",
        "simc-1210.01.4c7c736-winarm64.7z",
        "simc-1205.01.ac79c0f-win64.7z",
    ]


def test_latest_build_per_arch():
    builds = parse_nightly_index(INDEX)
    b = latest_build(builds, "win64")
    assert b.version == "1210.01.4c7c736"
    assert b.url.endswith("/nightly/simc-1210.01.4c7c736-win64.7z")
    assert latest_build(builds, "winarm64").arch == "winarm64"


def test_latest_build_missing_arch():
    with pytest.raises(LookupError):
        latest_build(parse_nightly_index(""), "win64")
