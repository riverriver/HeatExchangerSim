import sys
from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def _setup_matplotlib_japanese() -> None:
    """Windows 環境で日本語フォントを設定する。"""
    import matplotlib
    from matplotlib import font_manager
    candidates = ["Yu Gothic", "Meiryo", "MS Gothic", "MS PGothic"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams["font.family"] = font
            break
    matplotlib.rcParams["axes.unicode_minus"] = False  # マイナス記号の文字化け防止


def main() -> None:
    _setup_matplotlib_japanese()
    app = QApplication(sys.argv)
    app.setApplicationName("熱交換器シミュレーター")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
