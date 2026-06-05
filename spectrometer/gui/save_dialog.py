"""Save / Record dialog -- configures a recording run (SaveOptions).

Lets the user choose folder, filename, file format (auto/CSV/HDF5), the
operation mode (repeat scans with a count/duration stop, or capture frames at
an Nth-frame / interval cadence), and metadata handling.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QRadioButton,
                             QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from ..core.storage import SaveOptions


def _seconds(edit: QTimeEdit) -> float:
    t = edit.time()
    return t.hour() * 3600 + t.minute() * 60 + t.second()


class SaveDialog(QDialog):
    def __init__(self, parent=None, *, wl_min: float = 350.0,
                 wl_max: float = 500.0, default_folder: str | None = None,
                 settings=None):
        super().__init__(parent)
        self.setWindowTitle("Save / Record")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)

        folder0 = (settings.save_folder if settings else default_folder
                   or os.path.join(os.path.expanduser("~"), "Documents"))

        # --- destination ------------------------------------------------
        dest = QFormLayout()
        self._folder = QLineEdit(folder0)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder)
        folder_row.addWidget(browse)
        folder_w = QWidget()
        folder_w.setLayout(folder_row)
        dest.addRow("Folder:", folder_w)

        self._filename = QLineEdit(settings.save_filename if settings else "spectrum")
        dest.addRow("File name:", self._filename)

        self._format = QComboBox()
        self._format.addItems(["auto (CSV single / HDF5 series)", "csv", "hdf5"])
        if settings:
            self._format.setCurrentIndex(
                {"auto": 0, "csv": 1, "hdf5": 2}.get(settings.save_format, 0))
        dest.addRow("Format:", self._format)
        layout.addLayout(dest)

        # --- what to save ----------------------------------------------
        content_box = QGroupBox("What to save")
        cl = QVBoxLayout(content_box)
        self._save_image = QCheckBox("Raw 2-D image per shot (forces HDF5)")
        self._save_spectrum = QCheckBox("Raw 1-D spectrum per shot")
        self._save_stitched = QCheckBox("Stitched 1-D spectrum per scan")
        self._save_image.setChecked(settings.save_image_2d if settings else False)
        self._save_spectrum.setChecked(settings.save_spectrum_1d if settings else False)
        self._save_stitched.setChecked(settings.save_stitched if settings else True)
        for w in (self._save_image, self._save_spectrum, self._save_stitched):
            cl.addWidget(w)
        self._save_image.toggled.connect(self._sync_format_constraint)
        self._sync_format_constraint()   # honour a prefilled 2-D selection
        layout.addWidget(content_box)

        # --- operation mode --------------------------------------------
        mode_box = QGroupBox("Operation mode")
        mb = QVBoxLayout(mode_box)
        self._type = QButtonGroup(self)
        self._scans_radio = QRadioButton("Repeat scans")
        self._frames_radio = QRadioButton("Capture frames")
        self._scans_radio.setChecked(True)
        self._type.addButton(self._scans_radio)
        self._type.addButton(self._frames_radio)
        mb.addWidget(self._scans_radio)

        # scan stop condition
        self._scan_panel = self._build_scan_panel(wl_min, wl_max)
        mb.addWidget(self._scan_panel)
        mb.addWidget(self._frames_radio)
        self._frame_panel = self._build_frame_panel()
        mb.addWidget(self._frame_panel)
        layout.addWidget(mode_box)

        self._scans_radio.toggled.connect(self._sync_enabled)
        self._sync_enabled()

        # --- metadata ---------------------------------------------------
        meta_box = QGroupBox("Metadata")
        ml = QVBoxLayout(meta_box)
        self._save_meta = QCheckBox("Save metadata")
        self._save_meta.setChecked(True)
        self._meta_separate = QCheckBox("In a separate info file")
        ml.addWidget(self._save_meta)
        ml.addWidget(self._meta_separate)
        self._save_meta.toggled.connect(self._meta_separate.setEnabled)
        layout.addWidget(meta_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- sub-panels ----------------------------------------------------
    def _build_scan_panel(self, wl_min, wl_max) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._wl_min = QDoubleSpinBox()
        self._wl_min.setRange(0.0, 2000.0)
        self._wl_min.setValue(wl_min)
        self._wl_min.setSuffix(" nm")
        self._wl_max = QDoubleSpinBox()
        self._wl_max.setRange(0.0, 2000.0)
        self._wl_max.setValue(wl_max)
        self._wl_max.setSuffix(" nm")
        rng = QHBoxLayout()
        rng.addWidget(self._wl_min)
        rng.addWidget(QLabel("to"))
        rng.addWidget(self._wl_max)
        rng_w = QWidget()
        rng_w.setLayout(rng)
        form.addRow("Scan range:", rng_w)

        self._stop = QButtonGroup(self)
        self._stop_count_radio = QRadioButton("Stop after N scans")
        self._stop_count_radio.setChecked(True)
        self._stop_count = QSpinBox()
        self._stop_count.setRange(1, 1_000_000)
        self._stop_count.setValue(1)
        self._stop_time_radio = QRadioButton("Stop after")
        self._stop_time = QTimeEdit(QTime(0, 1, 0))
        self._stop_time.setDisplayFormat("HH:mm:ss")
        self._stop.addButton(self._stop_count_radio)
        self._stop.addButton(self._stop_time_radio)
        row1 = QHBoxLayout()
        row1.addWidget(self._stop_count_radio)
        row1.addWidget(self._stop_count)
        form.addRow(row1)
        row2 = QHBoxLayout()
        row2.addWidget(self._stop_time_radio)
        row2.addWidget(self._stop_time)
        form.addRow(row2)
        return w

    def _build_frame_panel(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._cadence = QButtonGroup(self)
        self._cad_nth_radio = QRadioButton("Grab every Nth frame")
        self._cad_nth_radio.setChecked(True)
        self._cad_n = QSpinBox()
        self._cad_n.setRange(1, 1_000_000)
        self._cad_n.setValue(1)
        self._cad_int_radio = QRadioButton("Grab a frame every")
        self._cad_int = QTimeEdit(QTime(0, 0, 1))
        self._cad_int.setDisplayFormat("HH:mm:ss")
        self._cadence.addButton(self._cad_nth_radio)
        self._cadence.addButton(self._cad_int_radio)
        r1 = QHBoxLayout()
        r1.addWidget(self._cad_nth_radio)
        r1.addWidget(self._cad_n)
        form.addRow(r1)
        r2 = QHBoxLayout()
        r2.addWidget(self._cad_int_radio)
        r2.addWidget(self._cad_int)
        form.addRow(r2)
        form.addRow(QLabel("Runs until you press Abort."))
        return w

    def _sync_enabled(self) -> None:
        scans = self._scans_radio.isChecked()
        self._scan_panel.setEnabled(scans)
        self._frame_panel.setEnabled(not scans)
        # "stitched" only applies to scans.
        self._save_stitched.setEnabled(scans)

    def _sync_format_constraint(self) -> None:
        # 2-D images can't go in CSV -> force HDF5 and lock the selector.
        if self._save_image.isChecked():
            self._format.setCurrentIndex(2)   # hdf5
            self._format.setEnabled(False)
        else:
            self._format.setEnabled(True)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder",
                                                  self._folder.text())
        if folder:
            self._folder.setText(folder)

    def accept(self) -> None:  # noqa: N802 (Qt signature)
        scans = self._scans_radio.isChecked()
        picked = (self._save_image.isChecked() or self._save_spectrum.isChecked()
                  or (scans and self._save_stitched.isChecked()))
        if not picked:
            QMessageBox.warning(self, "Nothing to save",
                                "Select at least one of image / spectrum / "
                                "stitched to save.")
            return
        super().accept()

    # --- result --------------------------------------------------------
    def options(self) -> SaveOptions:
        fmt = ["auto", "csv", "hdf5"][self._format.currentIndex()]
        scans = self._scans_radio.isChecked()
        return SaveOptions(
            folder=self._folder.text(),
            filename=self._filename.text(),
            fmt=fmt,
            record_type="scans" if scans else "frames",
            stop_mode="count" if self._stop_count_radio.isChecked() else "duration",
            stop_count=self._stop_count.value(),
            stop_duration_s=_seconds(self._stop_time),
            cadence_mode="every_nth" if self._cad_nth_radio.isChecked() else "every_interval",
            cadence_n=self._cad_n.value(),
            cadence_interval_s=_seconds(self._cad_int),
            wl_min=self._wl_min.value(),
            wl_max=self._wl_max.value(),
            save_image_2d=self._save_image.isChecked(),
            save_spectrum_1d=self._save_spectrum.isChecked(),
            save_stitched=scans and self._save_stitched.isChecked(),
            save_metadata=self._save_meta.isChecked(),
            metadata_separate=self._meta_separate.isChecked(),
        )
