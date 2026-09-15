import os
import sys
import numpy as np
import pydicom
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.path import Path
import matplotlib.patches as patches
from scipy.interpolate import RegularGridInterpolator
from PyQt6.QtWidgets import QDialog, QTextEdit, QTabWidget

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QListWidget,
    QListWidgetItem, QCheckBox, QComboBox, QLineEdit, QGroupBox,
    QSplitter, QStatusBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QAction, QColor

from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.collections import LineCollection
from PyQt6.QtWidgets import QToolTip
from PyQt6.QtCore import QPoint


class RTViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSTRUCT & RTDOSE DICOM Inspector")
        self.resize(1300, 850)

        self.ct_volume = None
        self.slice_z = []
        self.ct_origin = None
        self.ct_spacing = None
        self.slice_thickness = 2.5
        self.current_slice_idx = 0

        self.structures = {}  # {roi_name: {'color': [r,g,b], 'visible': bool, 'contours': {slice_idx: [np.ndarray]}}}
        self.dose_interp = None
        self.dose_max = 0.0

        # DICOM datasets
        self.ds_ct = None
        self.ds_struct = None
        self.ds_dose = None

        self.ct_volume = None

        self.init_ui()

    def init_ui(self):
        # 1. Native Menu Bar
        menu_bar = self.menuBar()
        
        # File Menu
        file_menu = menu_bar.addMenu("File")
        action_headers = QAction("View DICOM Headers", self)
        action_headers.triggered.connect(self.show_dicom_headers)
        file_menu.addAction(action_headers)
        
        # RTSTRUCT Menu
        rt_menu = menu_bar.addMenu("RTSTRUCT")
        action_show_all = QAction("Show All Structures", self)
        action_show_all.triggered.connect(self.show_all_structs)
        rt_menu.addAction(action_show_all)

        # Info button
        action_struct_info = QAction("View RTSTRUCT Info", self)
        action_struct_info.triggered.connect(self.show_rtstruct_info)
        rt_menu.addAction(action_struct_info)
        
        action_hide_all = QAction("Hide All Structures", self)
        action_hide_all.triggered.connect(self.hide_all_structs)
        rt_menu.addAction(action_hide_all)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # 2. Top Bar (Keep the 3 big buttons, remove header button)
        top_bar = QHBoxLayout()
        self.btn_ct = QPushButton("Load CT Directory")
        self.btn_ct.clicked.connect(self.load_ct_dir)
        self.btn_struct = QPushButton("Load RTSTRUCT (.dcm)")
        self.btn_struct.clicked.connect(self.load_rtstruct)
        self.btn_dose = QPushButton("Load RTDOSE (.dcm)")
        self.btn_dose.clicked.connect(self.load_rtdose)

        top_bar.addWidget(self.btn_ct)
        top_bar.addWidget(self.btn_struct)
        top_bar.addWidget(self.btn_dose)
        main_layout.addLayout(top_bar)

        # Splitter: Canvas vs Controls
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas Area
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        self.figure = Figure(facecolor="#1e1e1e")
        self.canvas = FigureCanvasQTAgg(self.figure)
        
        # Add Navigation Toolbar for Pan/Zoom
        self.toolbar = NavigationToolbar2QT(self.canvas, canvas_container)
        canvas_layout.addWidget(self.toolbar)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.axis("off")
        canvas_layout.addWidget(self.canvas)

        self.img_ct = None
        self.img_dose = None
        self.dose_contours = None
        self.dose_clabels = []
        self.struct_collection = LineCollection([], linewidths=1.5)
        self.ax.add_collection(self.struct_collection)

        # Slice Scroll Controls
        slice_bar = QHBoxLayout()
        self.lbl_slice = QLabel("Slice: 0 / 0 (Z: 0.0 mm)")
        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.setEnabled(False)
        self.slice_slider.valueChanged.connect(self.on_slice_change)
        slice_bar.addWidget(self.lbl_slice)
        slice_bar.addWidget(self.slice_slider)
        canvas_layout.addLayout(slice_bar)

        splitter.addWidget(canvas_container)

        # Right Panel: Controls and Structure List
        control_panel = QWidget()
        panel_layout = QVBoxLayout(control_panel)

        # W/L Group
        wl_group = QGroupBox("CT Window / Level")
        wl_layout = QVBoxLayout(wl_group)
        self.combo_wl = QComboBox()
        self.combo_wl.addItems(["Soft Tissue (W: 400, L: 40)", "Lung (W: 1500, L: -600)", "Bone (W: 1800, L: 400)", "Brain (W: 80, L: 40)"])
        self.combo_wl.currentIndexChanged.connect(self.apply_wl_preset)
        
        self.slider_w = QSlider(Qt.Orientation.Horizontal)
        self.slider_w.setRange(1, 3000)
        self.slider_w.setValue(400)
        self.slider_w.valueChanged.connect(self.update_view)
        
        self.slider_l = QSlider(Qt.Orientation.Horizontal)
        self.slider_l.setRange(-1000, 2000)
        self.slider_l.setValue(40)
        self.slider_l.valueChanged.connect(self.update_view)

        wl_layout.addWidget(self.combo_wl)
        wl_layout.addWidget(QLabel("Window Width:"))
        wl_layout.addWidget(self.slider_w)
        wl_layout.addWidget(QLabel("Window Level:"))
        wl_layout.addWidget(self.slider_l)
        panel_layout.addWidget(wl_group)

        # Dose Display Group
        dose_group = QGroupBox("RTDOSE Options")
        dose_layout = QVBoxLayout(dose_group)
        self.chk_colorwash = QCheckBox("Show Color Wash")
        self.chk_colorwash.setChecked(True)
        self.chk_colorwash.stateChanged.connect(self.update_view)
        
        self.chk_isodose = QCheckBox("Show Isodose Lines")
        self.chk_isodose.setChecked(True)
        self.chk_isodose.stateChanged.connect(self.update_view)

        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(40)
        self.alpha_slider.valueChanged.connect(self.update_view)

        self.txt_iso_levels = QLineEdit("30, 50, 70, 80, 90, 95, 100")
        self.txt_iso_levels.setPlaceholderText("Levels in % (e.g. 50, 80, 95)")
        self.txt_iso_levels.returnPressed.connect(self.update_view)

        dose_layout.addWidget(self.chk_colorwash)
        dose_layout.addWidget(self.chk_isodose)
        dose_layout.addWidget(QLabel("Wash Opacity:"))
        dose_layout.addWidget(self.alpha_slider)
        dose_layout.addWidget(QLabel("Isodose Levels (% max):"))
        dose_layout.addWidget(self.txt_iso_levels)
        panel_layout.addWidget(dose_group)

        # RTSTRUCT List Group
        struct_group = QGroupBox("Structures")
        struct_layout = QVBoxLayout(struct_group)
        self.struct_list = QListWidget()
        self.struct_list.itemChanged.connect(self.on_struct_item_changed)
        struct_layout.addWidget(self.struct_list)
        panel_layout.addWidget(struct_group)

        splitter.addWidget(control_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Canvas Events
        self.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.canvas.mpl_connect("button_press_event", self.on_click)

    def show_dicom_headers(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("DICOM Headers")
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        
        if getattr(self, 'ds_ct', None):
            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setPlainText(str(self.ds_ct[self.current_slice_idx]))
            tabs.addTab(txt, f"CT (Slice {self.current_slice_idx + 1})")
            
        if getattr(self, 'ds_struct', None):
            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setPlainText(str(self.ds_struct))
            tabs.addTab(txt, "RTSTRUCT")
            
        if getattr(self, 'ds_dose', None):
            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setPlainText(str(self.ds_dose))
            tabs.addTab(txt, "RTDOSE")
            
        if tabs.count() == 0:
            layout.addWidget(QLabel("No DICOM files loaded."))
        else:
            layout.addWidget(tabs)
        
        dialog.exec()

    def show_rtstruct_info(self):
        if getattr(self, 'ds_struct', None) is None:
            self.status_bar.showMessage("No RTSTRUCT loaded.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("RTSTRUCT Summary")
        dialog.resize(600, 400)
        layout = QVBoxLayout(dialog)
        
        txt = QTextEdit()
        txt.setReadOnly(True)
        
        ds = self.ds_struct
        info = [
            f"Patient Name: {getattr(ds, 'PatientName', 'Unknown')}",
            f"Structure Set Name: {getattr(ds, 'StructureSetName', 'Unknown')}",
            f"Structure Set Date: {getattr(ds, 'StructureSetDate', 'Unknown')}",
            "-" * 40
        ]
        
        rois = {r.ROINumber: r.ROIName for r in getattr(ds, 'StructureSetROISequence', [])}
        types = {obs.ReferencedROINumber: getattr(obs, 'RTROIInterpretedType', 'Unknown') 
                 for obs in getattr(ds, 'RTROIObservationsSequence', [])}
        counts = {rc.ReferencedROINumber: len(getattr(rc, 'ContourSequence', [])) 
                  for rc in getattr(ds, 'ROIContourSequence', [])}
            
        for num, name in sorted(rois.items()):
            roi_type = types.get(num, 'Unknown')
            count = counts.get(num, 0)
            info.append(f"ROI {num}: {name} | Type: {roi_type} | Contours: {count}")
            
        txt.setPlainText("\n".join(info))
        layout.addWidget(txt)
        dialog.exec()

    def load_ct_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select CT Directory")
        if not dir_path:
            return

        dicom_files = []
        for root, _, files in os.walk(dir_path):
            for f in files:
                full_path = os.path.join(root, f)
                try:
                    ds = pydicom.dcmread(full_path, stop_before_pixels=True)
                    if getattr(ds, "Modality", "") == "CT":
                        dicom_files.append(full_path)
                except Exception:
                    continue

        if not dicom_files:
            self.status_bar.showMessage("No valid CT DICOM slices found.")
            return

        slices = [pydicom.dcmread(f) for f in dicom_files]
        slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))

        self.ds_ct = slices

        self.slice_z = [float(s.ImagePositionPatient[2]) for s in slices]
        self.ct_origin = [float(x) for x in slices[0].ImagePositionPatient]
        self.ct_spacing = [float(x) for x in slices[0].PixelSpacing]

        if len(self.slice_z) > 1:
            self.slice_thickness = abs(self.slice_z[1] - self.slice_z[0])

        arrays = []
        for s in slices:
            raw = s.pixel_array.astype(np.float32)
            slope = getattr(s, "RescaleSlope", 1.0)
            intercept = getattr(s, "RescaleIntercept", 0.0)
            arrays.append(raw * slope + intercept)

        self.ct_volume = np.stack(arrays, axis=0)

        self.slice_slider.setEnabled(True)
        self.slice_slider.setRange(0, len(slices) - 1)
        self.slice_slider.setValue(len(slices) // 2)
        self.current_slice_idx = self.slice_slider.value()
        self.update_view()

    def on_click(self, event):
        if event.button != 3 or event.xdata is None or event.ydata is None:
            return  # 3 is Right Click

        x, y = int(event.xdata), int(event.ydata)
        slice_idx = self.current_slice_idx
        info = []

        if 0 <= y < self.ct_volume.shape[1] and 0 <= x < self.ct_volume.shape[2]:
            hu = self.ct_volume[slice_idx, y, x]
            info.append(f"CT: {hu:.1f} HU")

        if hasattr(self, 'current_dose_slice') and self.current_dose_slice is not None:
            dose = self.current_dose_slice[y, x]
            info.append(f"Dose: {dose:.2f} Gy")

        structs = []
        for name, data in self.structures.items():
            if not data["visible"]:
                continue
            for item in data["contours"].get(slice_idx, []):
                if item["path"].contains_point((event.xdata, event.ydata)):
                    structs.append(name)
                    break

        if structs:
            info.append("Structures:\n- " + "\n- ".join(structs))

        # Show floating tooltip at mouse location
        global_pos = self.canvas.mapToGlobal(QPoint(int(event.x), int(self.canvas.height() - event.y)))
        QToolTip.showText(global_pos, "\n".join(info), self.canvas)

    def show_all_structs(self):
        self._set_all_structs_state(True)

    def hide_all_structs(self):
        self._set_all_structs_state(False)

    def _set_all_structs_state(self, visible):
        # Block signals temporarily to prevent updating the canvas on every single checkbox change
        self.struct_list.blockSignals(True)
        
        state = Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
        for i in range(self.struct_list.count()):
            item = self.struct_list.item(i)
            item.setCheckState(state)
            
            # Manually update the data dictionary
            name = item.text()
            if name in self.structures:
                self.structures[name]["visible"] = visible
                
        self.struct_list.blockSignals(False)
        self.update_view()

    def load_rtstruct(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select RTSTRUCT File", "", "DICOM Files (*.dcm)")
        if not file_path or self.ct_volume is None:
            return

        ds = pydicom.dcmread(file_path)
        if getattr(ds, "Modality", "") != "RTSTRUCT":
            self.status_bar.showMessage("File is not a valid RTSTRUCT.")
            return

        self.ds_struct = ds

        self.structures.clear()
        self.struct_list.clear()

        roi_names = {roi.ROINumber: roi.ROIName for roi in getattr(ds, "StructureSetROISequence", [])}
        colors = {}
        for contour in getattr(ds, "ROIContourSequence", []):
            num = contour.ReferencedROINumber
            if hasattr(contour, "ROIDisplayColor"):
                colors[num] = [v / 255.0 for v in contour.ROIDisplayColor]
            else:
                colors[num] = list(np.random.rand(3))

        for contour_roi in getattr(ds, "ROIContourSequence", []):
            roi_num = contour_roi.ReferencedROINumber
            roi_name = roi_names.get(roi_num, f"ROI_{roi_num}")
            color = colors.get(roi_num, [1.0, 0.0, 0.0])

            # 1. Group raw RTSTRUCT contours by their exact Z-coordinate
            z_to_contours = {}
            if hasattr(contour_roi, "ContourSequence"):
                for cs in contour_roi.ContourSequence:
                    c_data = getattr(cs, "ContourData", [])
                    if c_data is None or len(c_data) < 3 or len(c_data) % 3 != 0:
                        continue
                        
                    data = np.array(c_data).reshape(-1, 3)
                    z_val = data[0, 2]
                    
                    cols = (data[:, 0] - self.ct_origin[0]) / self.ct_spacing[1]
                    rows = (data[:, 1] - self.ct_origin[1]) / self.ct_spacing[0]
                    poly = np.column_stack([cols, rows])

                    if z_val not in z_to_contours:
                        z_to_contours[z_val] = []
                    # Cache the Path object once during load
                    z_to_contours[z_val].append({
                        "poly": poly,
                        "path": Path(poly)
                    })

            # 2. Map every CT slice to the nearest RTSTRUCT Z-plane (Nearest Neighbor)
            slice_dict = {}
            if z_to_contours:
                rt_z_vals = np.array(list(z_to_contours.keys()))
                for ct_idx, ct_z in enumerate(self.slice_z):
                    z_diff = np.abs(rt_z_vals - ct_z)
                    best_rt_idx = int(np.argmin(z_diff))
                    
                    # Tolerance: allow mapping if within 1.5x CT slice thickness (max 3mm)
                    if z_diff[best_rt_idx] <= max(self.slice_thickness * 1.5, 3.0):
                        best_z = rt_z_vals[best_rt_idx]
                        slice_dict[ct_idx] = z_to_contours[best_z]

            self.structures[roi_name] = {
                "color": color,
                "visible": True,
                "contours": slice_dict
            }

            item = QListWidgetItem(roi_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            qcol = QColor(int(color[0]*255), int(color[1]*255), int(color[2]*255))
            item.setForeground(qcol)
            self.struct_list.addItem(item)

        self.update_view()

    def load_rtdose(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select RTDOSE File", "", "DICOM Files (*.dcm)")
        if not file_path or self.ct_volume is None:
            return

        ds = pydicom.dcmread(file_path)
        if getattr(ds, "Modality", "") != "RTDOSE":
            self.status_bar.showMessage("File is not a valid RTDOSE.")
            return

        self.ds_dose = ds

        scaling = getattr(ds, "DoseGridScaling", 1.0)
        dose_arr = ds.pixel_array.astype(np.float32) * scaling
        self.dose_max = float(np.max(dose_arr))

        dose_origin = [float(x) for x in ds.ImagePositionPatient]
        dose_spacing = [float(x) for x in ds.PixelSpacing]
        offsets = getattr(ds, "GridFrameOffsetVector", [0.0])
        dose_z = dose_origin[2] + np.array(offsets, dtype=np.float32)

        dose_y = dose_origin[1] + np.arange(dose_arr.shape[1]) * dose_spacing[0]
        dose_x = dose_origin[0] + np.arange(dose_arr.shape[2]) * dose_spacing[1]

        if len(dose_z) > 1 and dose_z[1] < dose_z[0]:
            dose_z = dose_z[::-1]
            dose_arr = dose_arr[::-1, :, :]

        self.dose_interp = RegularGridInterpolator(
            (dose_z, dose_y, dose_x),
            dose_arr,
            bounds_error=False,
            fill_value=0.0
        )

        ny, nx = self.ct_volume.shape[1], self.ct_volume.shape[2]
        ct_y = self.ct_origin[1] + np.arange(ny) * self.ct_spacing[0]
        ct_x = self.ct_origin[0] + np.arange(nx) * self.ct_spacing[1]
        
        # Cache 2D grid coordinates once
        self.dose_grid_y, self.dose_grid_x = np.meshgrid(ct_y, ct_x, indexing="ij")
        self.cached_dose_idx = -1
        self.current_dose_slice = None
        
        self.update_view()

    def on_slice_change(self, value):
        self.current_slice_idx = value
        z_pos = self.slice_z[value] if self.slice_z else 0.0
        self.lbl_slice.setText(f"Slice: {value + 1} / {len(self.slice_z)} (Z: {z_pos:.1f} mm)")
        self.update_view()

    def on_scroll(self, event):
        if not self.slice_z:
            return
        if event.button == "up" and self.current_slice_idx < len(self.slice_z) - 1:
            self.slice_slider.setValue(self.current_slice_idx + 1)
        elif event.button == "down" and self.current_slice_idx > 0:
            self.slice_slider.setValue(self.current_slice_idx - 1)

    def apply_wl_preset(self, index):
        presets = [(400, 40), (1500, -600), (1800, 400), (80, 40)]
        w, l = presets[index]
        self.slider_w.blockSignals(True)
        self.slider_l.blockSignals(True)
        self.slider_w.setValue(w)
        self.slider_l.setValue(l)
        self.slider_w.blockSignals(False)
        self.slider_l.blockSignals(False)
        self.update_view()

    def on_struct_item_changed(self, item):
        name = item.text()
        if name in self.structures:
            self.structures[name]["visible"] = (item.checkState() == Qt.CheckState.Checked)
            self.update_view()

    def on_mouse_move(self, event):
        if event.xdata is None or event.ydata is None or not self.structures:
            return

        x, y = event.xdata, event.ydata
        matched_roi = None

        for name, data in self.structures.items():
            if not data["visible"]:
                continue
            contours = data["contours"].get(self.current_slice_idx, [])
            for item in contours:
                if item["path"].contains_point((x, y)):
                    matched_roi = name
                    break
            if matched_roi:
                break

        if matched_roi:
            self.status_bar.showMessage(f"Structure: {matched_roi} | Cursor: X={x:.1f}, Y={y:.1f}")
            for i in range(self.struct_list.count()):
                list_item = self.struct_list.item(i)
                if list_item.text() == matched_roi:
                    self.struct_list.setCurrentItem(list_item)
                    break
        else:
            self.status_bar.showMessage(f"Cursor: X={x:.1f}, Y={y:.1f}")

    def update_view(self):
        if self.ct_volume is None:
            return

        # 1. Base CT Update
        img = self.ct_volume[self.current_slice_idx]
        w = self.slider_w.value()
        l = self.slider_l.value()
        vmin = l - (w / 2.0)
        vmax = l + (w / 2.0)
        
        if self.img_ct is None:
            self.img_ct = self.ax.imshow(img, cmap="gray", vmin=vmin, vmax=vmax)
        else:
            self.img_ct.set_data(img)
            self.img_ct.set_clim(vmin, vmax)

        # 2. Dose Wash Update
        if self.dose_interp is not None:
            # Lazy evaluation: Only calculate dose for the current slice
            if getattr(self, 'cached_dose_idx', -1) != self.current_slice_idx:
                z_val = self.slice_z[self.current_slice_idx]
                pts = np.stack([np.full_like(self.dose_grid_y, z_val), self.dose_grid_y, self.dose_grid_x], axis=-1)
                self.current_dose_slice = self.dose_interp(pts)
                self.cached_dose_idx = self.current_slice_idx

            dose_slice = self.current_dose_slice
            
            if self.chk_colorwash.isChecked() and self.dose_max > 0:
                alpha = self.alpha_slider.value() / 100.0
                
                # Use np.where with np.nan for faster rendering than MaskedArrays
                masked_dose = np.where(dose_slice < 0.05 * self.dose_max, np.nan, dose_slice)
                
                if self.img_dose is None:
                    self.img_dose = self.ax.imshow(masked_dose, cmap="jet", alpha=alpha, vmin=0, vmax=self.dose_max)
                else:
                    self.img_dose.set_data(masked_dose)
                    self.img_dose.set_alpha(alpha)
                    self.img_dose.set_visible(True)
            elif self.img_dose is not None:
                self.img_dose.set_visible(False)

            # 3. Isodose Line Update
            if self.dose_contours:
                try:
                    self.dose_contours.remove()
                except Exception:
                    pass
                
                for t in self.dose_clabels:
                    try:
                        t.remove()
                    except ValueError:
                        pass  # Label was already automatically removed by Matplotlib
                        
                self.dose_contours = None
                self.dose_clabels = []

            if self.chk_isodose.isChecked() and self.dose_max > 0:
                try:
                    pct_levels = [float(v.strip()) for v in self.txt_iso_levels.text().split(",") if v.strip()]
                    abs_levels = sorted([p * self.dose_max / 100.0 for p in pct_levels if p > 0])
                    if abs_levels:
                        self.dose_contours = self.ax.contour(dose_slice, levels=abs_levels, cmap="hsv", linewidths=1.2)
                        self.dose_clabels = self.ax.clabel(self.dose_contours, inline=True, fontsize=7, fmt="%.1f Gy")
                except ValueError:
                    pass

        # 4. Fast RTSTRUCT Update 
        segments = []
        colors = []
        for name, data in self.structures.items():
            if not data["visible"]: 
                continue
            for item in data["contours"].get(self.current_slice_idx, []):
                poly = item["poly"]
                segments.append(np.vstack([poly, poly[0]]))
                colors.append(data["color"])

        self.struct_collection.set_segments(segments)
        self.struct_collection.set_colors(colors)

        self.canvas.draw_idle()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = RTViewer()
    viewer.show()
    sys.exit(app.exec())