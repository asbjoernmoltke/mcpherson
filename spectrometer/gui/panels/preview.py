"""Live data preview: 2-D detector image + 1-D spectrum (pyqtgraph)."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget


class PreviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        pg.setConfigOptions(imageAxisOrder="row-major", antialias=True)

        layout = QVBoxLayout(self)

        # 2-D frame
        self._image_view = pg.ImageView()
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        layout.addWidget(self._image_view, stretch=2)

        # 1-D spectrum
        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "Wavelength", units="nm")
        self._plot.setLabel("left", "Intensity", units="counts")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self._plot.plot([], [], pen=pg.mkPen("#3aa0ff", width=1))
        layout.addWidget(self._plot, stretch=1)

    def update_frame(self, frame: np.ndarray) -> None:
        if frame is None:
            return
        arr = np.asarray(frame)
        if arr.ndim == 3:
            arr = arr[-1]
        # autoLevels only on the first frame to avoid flicker
        self._image_view.setImage(arr, autoLevels=self._image_view.image is None,
                                  autoRange=False)

    def update_spectrum(self, wavelength: np.ndarray, intensity: np.ndarray) -> None:
        self._curve.setData(np.asarray(wavelength), np.asarray(intensity))
