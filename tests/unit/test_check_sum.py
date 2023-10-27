from unittest import mock

from check_sum import PERCCLI_SUPPORT_INFOS, check_file_sum
from os_platform import OSPlatform


class TestCheckFileSum:
    @mock.patch(
        "check_sum.get_os_platform",
        return_value=OSPlatform(
            system="ubuntu",
            release="20.04",
            machine="x86_64",
        ),
    )
    @mock.patch("check_sum.hashlib.sha256")
    def test_check_file_sum(self, mock_sha256, mock_get_os_platform, tmp_path):
        mock_sha256.return_value = mock.Mock()
        mock_sha256.return_value.hexdigest.return_value = (
            "53c8ee43808779f8263c25b3cb975d816d207659684f3c7de1df4bbd2447ead4"
        )

        target = tmp_path / "perccli"
        target.write_text("fake file")

        ok = check_file_sum(PERCCLI_SUPPORT_INFOS, target)
        assert ok

    def test_check_file_sum_fail(self, tmp_path):
        target = tmp_path / "perccli"
        target.write_text("fake file")

        ok = check_file_sum(PERCCLI_SUPPORT_INFOS, target)
        assert not ok
