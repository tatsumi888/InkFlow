import pytest

from inkflow import devices
from inkflow.errors import InkFlowError


def test_default_device_is_paperwhite_11():
    device = devices.default_device()
    assert device.id == "paperwhite_11"
    assert device.size == (1236, 1648)


def test_all_presets_are_portrait_and_positive():
    for device in devices.DEVICES:
        assert device.width > 0 and device.height > 0
        assert device.height > device.width, f"{device.id} は縦長であるべき"


def test_get_device_by_id():
    assert devices.get_device("paperwhite_10").size == (1072, 1448)
    assert devices.get_device("scribe").size == (1860, 2480)


def test_get_device_custom_spec():
    device = devices.get_device("custom:800x1200")
    assert device.size == (800, 1200)
    assert device.id == "custom:800x1200"


@pytest.mark.parametrize("spec", ["custom:abc", "custom:800", "custom:0x100", "custom:-1x10"])
def test_get_device_invalid_custom_spec(spec):
    with pytest.raises(InkFlowError):
        devices.get_device(spec)


def test_get_device_unknown_id():
    with pytest.raises(InkFlowError, match="未知の端末ID"):
        devices.get_device("kobo")


def test_aspect_ratio():
    assert devices.get_device("paperwhite_11").aspect == pytest.approx(1236 / 1648)
