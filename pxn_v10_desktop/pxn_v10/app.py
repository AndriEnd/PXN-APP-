"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pxn-v10", description="PXN V10 Desktop configurator")
    parser.add_argument("--simulator", action="store_true", help="start with the virtual wheel instead of Bluetooth")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from PySide6.QtWidgets import QApplication

    from . import __app_name__
    from .ui import theme
    from .ui.context import AppContext
    from .ui.main_window import MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(__app_name__)
    app.setStyle("Fusion")
    app.setFont(theme.app_font(10))
    app.setStyleSheet(theme.stylesheet())

    ctx = AppContext(simulator=args.simulator)
    window = MainWindow(ctx)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
