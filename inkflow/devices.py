"""出力先端末の解像度プリセット。

出力画像はここで定義した解像度ちょうどに正規化される。Kindle は固定レイアウト
EPUB の画像を等倍で表示するため、端末の実解像度と一致させるのが最も鮮明になる。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InkFlowError


@dataclass(frozen=True)
class Device:
    """出力先端末のプロファイル。"""

    id: str
    label: str
    width: int
    height: int

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def aspect(self) -> float:
        """幅 / 高さ。"""
        return self.width / self.height


DEVICES: tuple[Device, ...] = (
    Device("paperwhite_11", "Kindle Paperwhite 第11世代/第12世代 (1236x1648)", 1236, 1648),
    Device("paperwhite_10", "Kindle Paperwhite 第10世代以前 (1072x1448)", 1072, 1448),
    Device("kindle_11", "Kindle (2022/2024) (1072x1448)", 1072, 1448),
    Device("oasis", "Kindle Oasis (1264x1680)", 1264, 1680),
    Device("scribe", "Kindle Scribe (1860x2480)", 1860, 2480),
)

DEFAULT_DEVICE_ID = "paperwhite_11"

_BY_ID = {d.id: d for d in DEVICES}


def get_device(device_id: str) -> Device:
    """ID から端末プロファイルを取得する。

    ``custom:WxH`` 形式を渡すと任意解像度のプロファイルを生成する。
    """
    if device_id in _BY_ID:
        return _BY_ID[device_id]

    if device_id.startswith("custom:"):
        spec = device_id.split(":", 1)[1]
        try:
            w_text, h_text = spec.lower().split("x", 1)
            width, height = int(w_text), int(h_text)
        except ValueError as e:
            raise InkFlowError(
                f"カスタム解像度の指定が不正です: {device_id!r}（例: custom:1236x1648）"
            ) from e
        if width <= 0 or height <= 0:
            raise InkFlowError(f"カスタム解像度は正の整数で指定してください: {device_id!r}")
        return Device(device_id, f"カスタム ({width}x{height})", width, height)

    known = ", ".join(_BY_ID)
    raise InkFlowError(f"未知の端末IDです: {device_id!r}（利用可能: {known}, custom:WxH）")


def default_device() -> Device:
    return _BY_ID[DEFAULT_DEVICE_ID]
