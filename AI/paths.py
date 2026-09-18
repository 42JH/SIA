# -*- coding: utf-8 -*-
"""번들 자산과 사용자 데이터의 경로를 가른다.

지금까지는 둘 다 `HERE = Path(__file__).parent` 아래 `models/` 한 곳에 있었다. 소스로
돌릴 때는 같은 폴더라 문제가 없지만, PyInstaller 로 얼리면 갈라진다.

- onefile 로 얼리면 `__file__` 은 매 실행마다 새로 만들어지는 임시 추출 폴더
  (`sys._MEIPASS`)를 가리킨다. 읽기 전용 모델을 찾는 데는 그게 맞다 — 거기로 풀리니까.
- 그런데 온보딩이 새로 쓰는 사용자 데이터(wake·speaker·calib npz)도 같은 곳에 쓴다.
  그 폴더는 앱이 끝나면 지워진다. **켤 때마다 온보딩을 다시 해야 하는 상태**가 된다.

그래서 둘을 나눈다.

ASSET_DIR  코드와 함께 배포되는 읽기 전용 자산(.task/.onnx/.pth 66 MB).
           frozen 이면 _MEIPASS — 임시 폴더가 맞는 답이다.
DATA_DIR   런타임에 쓰는 사용자 데이터. frozen 이면 %APPDATA%\\SIA\\ai.

APPDATA 를 고른 이유:
- BE 가 이미 %APPDATA%\\SIA 를 데이터 루트로 쓴다. AI 는 거기서 runtime.json 을 읽는다
  (be_link.read_runtime). 한 제품의 두 프로세스가 같은 규약을 쓰는 게 맞다.
- `Path(sys.executable).parent`(설치 폴더)는 안 된다. Program Files 아래로 설치되면
  관리자 권한 없이 못 쓴다 — 온보딩이 조용히 실패한다.
- BE 가 이미 %APPDATA%\\SIA 밑에 models/·gestures/·previews/ 를 쓰고 있어서, 섞이지
  않게 `ai` 하위에 둔다.

SIA_DATA_DIR 로 덮어쓸 수 있다. 얼리지 않고도 frozen 경로를 밟아 볼 수 있어야 한다.
"""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

# PyInstaller 는 번들을 _MEIPASS 에 푼다. 소스 실행이면 이 파일 옆이 곧 자산 폴더다.
ASSET_DIR = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)


def resolve_data_dir():
    """사용자 데이터를 쓸 폴더. import 시 한 번 정해지고 DATA_DIR 에 담긴다.

    sys.frozen 을 그때그때 읽는다 — 모듈 상수로 굳히면 얼린 상태를 테스트할 수 없다.
    """
    override = os.environ.get("SIA_DATA_DIR")
    if override:
        return Path(override)
    if not getattr(sys, "frozen", False):
        # 소스로 돌릴 때는 지금까지와 똑같이 저장소 안에서 읽고 쓴다 — 개발 흐름을 바꾸지
        # 않는다(기존 models/*.npz 를 옮길 필요가 없다).
        return Path(__file__).resolve().parent
    base = os.environ.get("APPDATA") or Path.home()
    return Path(base) / "SIA" / "ai"


DATA_DIR = resolve_data_dir()


def data_path(*parts):
    """사용자 데이터 경로 — 상위 폴더까지 만들어 준다(첫 실행에 폴더가 없다)."""
    p = DATA_DIR.joinpath(*parts)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # 못 만들어도 경로는 돌려준다 — 실패는 실제로 쓸 때 드러나는 게 낫다
    return p


def asset_path(*parts):
    """코드와 함께 배포되는 읽기 전용 자산 경로."""
    return ASSET_DIR.joinpath(*parts)


def _selftest():
    import tempfile

    assert asset_path("models", "x.onnx").parent.name == "models"
    with tempfile.TemporaryDirectory() as d:
        os.environ["SIA_DATA_DIR"] = d
        try:
            assert resolve_data_dir() == Path(d)
        finally:
            del os.environ["SIA_DATA_DIR"]
    # 얼린 상태에서 사용자 데이터가 임시 추출 폴더로 가면 안 된다 — 매 실행 날아간다
    sys.frozen = True
    try:
        frozen_data = resolve_data_dir()
        assert "SIA" in str(frozen_data), frozen_data
        assert frozen_data != Path(__file__).resolve().parent
        assert not str(frozen_data).startswith(tempfile.gettempdir()), frozen_data
    finally:
        del sys.frozen
    assert resolve_data_dir() == Path(__file__).resolve().parent  # 원래대로
    print("selftest ok")


if __name__ == "__main__":
    _selftest()
