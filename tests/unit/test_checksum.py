from unittest import mock

from checksum import PERCCLI_VERSION_INFOS, validate_checksum
from os_platform import OSPlatform


class TestCheckFileSum:
    @mock.patch(
        "checksum.get_os_platform",
        return_value=OSPlatform(
            system="ubuntu",
            release="20.04",
            machine="x86_64",
        ),
    )
    @mock.patch("checksum.hashlib.sha256")
    def test_validate_checksum(self, mock_sha256, mock_get_os_platform, tmp_path):
        mock_sha256.return_value = mock.Mock()
        mock_sha256.return_value.hexdigest.return_value = (
            "53c8ee43808779f8263c25b3cb975d816d207659684f3c7de1df4bbd2447ead4"
        )

        target = tmp_path / "perccli"
        target.write_text("fake file")

        ok = validate_checksum(PERCCLI_VERSION_INFOS, target)
        assert ok

    def test_validate_checksum_fail(self, tmp_path):
        target = tmp_path / "perccli"
        target.write_text("fake file")

        ok = validate_checksum(PERCCLI_VERSION_INFOS, target)
        assert not ok

    @mock.patch(
        "checksum.get_os_platform",
        return_value=OSPlatform(
            system="ubuntu",
            release="20.04",
            machine="fake machine architecture",
        ),
    )
    @mock.patch("checksum.hashlib.sha256")
    def test_validate_checksum_wrong_architecture(
        self, mock_sha256, mock_get_os_platform, tmp_path
    ):
        mock_sha256.return_value = mock.Mock()
        mock_sha256.return_value.hexdigest.return_value = (
            "53c8ee43808779f8263c25b3cb975d816d207659684f3c7de1df4bbd2447ead4"
        )

        target = tmp_path / "perccli"
        target.write_text("fake file")

        ok = validate_checksum(PERCCLI_VERSION_INFOS, target)
        assert not ok
