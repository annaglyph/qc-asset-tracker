import re
from qc_asset_crawler import __version__


def test_version_semver():
    assert re.match(r"^\d+\.\d+\.\d+$", __version__)
