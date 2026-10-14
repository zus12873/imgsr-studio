import pytest

from imgsr.config import Settings
from imgsr.config_store import SettingsError, SettingsProvider


def provider(sf):
    return SettingsProvider(Settings(_env_file=None), sf)


def test_update_persists_and_overrides(sf):
    p = provider(sf)
    assert p().image_model == "gpt-image-2.5"
    eff = p.update({"image_model": " gpt-image-2 ", "pixel_cap": "1200000"})
    assert eff.image_model == "gpt-image-2" and eff.pixel_cap == 1_200_000
    assert p.overrides() == {"image_model": "gpt-image-2", "pixel_cap": 1_200_000}
    assert p().image_model == "gpt-image-2"


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"open_api_key": "x"}, "不支持"),
        ({"pixel_cap": 10}, "之间"),
        ({"upstream_concurrency": "x"}, "整数"),
        ({"upstream_concurrency": True}, "整数"),
        ({"image_model": "  "}, "不能为空"),
    ],
)
def test_update_validation(sf, changes, message):
    with pytest.raises(SettingsError, match=message):
        provider(sf).update(changes)
