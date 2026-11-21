import paperless_win
import paperless_win.platform


def test_package_imports() -> None:
    assert paperless_win.__version__.endswith("-win.0")
    assert paperless_win.platform is not None
