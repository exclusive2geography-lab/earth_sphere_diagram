import math, traceback
from qgis.PyQt.QtCore import QVariant, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QSpinBox, QGroupBox, QMessageBox
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsField, QgsSymbol, QgsFillSymbol, QgsGradientFillSymbolLayer, QgsLineSymbol, QgsSingleSymbolRenderer, QgsGeometry, QgsPointXY, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsMapLayerProxyModel, QgsFieldProxyModel

class SphereDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('3D Earth Globe Sphere Diagram')
        self.setMinimumWidth(360)
        lay = QVBoxLayout()
        lay.addWidget(QLabel('<b>Select Polygon Layer:</b>'))
        self.lyr_cb = QgsMapLayerComboBox(); self.lyr_cb.setFilters(QgsMapLayerProxyModel.PolygonLayer); lay.addWidget(self.lyr_cb)
        lay.addWidget(QLabel('<b>Select Numeric Field:</b>'))
        self.fld_cb = QgsFieldComboBox(); self.fld_cb.setFilters(QgsFieldProxyModel.Numeric)
        self.lyr_cb.layerChanged.connect(self.fld_cb.setLayer)
        if self.lyr_cb.currentLayer(): self.fld_cb.setLayer(self.lyr_cb.currentLayer())
        lay.addWidget(self.fld_cb)
        self.mm_lbl = QLabel('Data Min: - | Max: -'); self.mm_lbl.setStyleSheet('color: #004c99; font-weight: bold;'); lay.addWidget(self.mm_lbl)
        self.fld_cb.fieldChanged.connect(self.upd_mm)
        sz_lay = QHBoxLayout(); sz_lay.addWidget(QLabel('<b>Globe Size Multiplier:</b>'))
        self.sz_sp = QDoubleSpinBox(); self.sz_sp.setRange(0.1, 10.0); self.sz_sp.setSingleStep(0.1); self.sz_sp.setValue(1.0)
        sz_lay.addWidget(self.sz_sp); lay.addLayout(sz_lay)
        sg = QGroupBox('Graphical Scale Values (Large -> Mid -> Small)'); sgl = QHBoxLayout()
        self.v1, self.v2, self.v3 = QSpinBox(), QSpinBox(), QSpinBox()
        for sp, val in ((self.v1, 8000), (self.v2, 4000), (self.v3, 1000)):
            sp.setRange(1, 999999999); sp.setValue(val); sgl.addWidget(sp)
        sg.setLayout(sgl); lay.addWidget(sg)
        bl = QHBoxLayout(); self.run_btn = QPushButton('Generate Sphere Diagram')
        self.run_btn.setStyleSheet('background-color: #2b579a; color: white; font-weight: bold; padding: 6px;')
        self.cls_btn = QPushButton('Close'); bl.addWidget(self.run_btn); bl.addWidget(self.cls_btn); lay.addLayout(bl)
        self.setLayout(lay); self.cls_btn.clicked.connect(self.reject); self.upd_mm()
    def upd_mm(self):
        lyr, fld = self.lyr_cb.currentLayer(), self.fld_cb.currentField()
        if lyr and fld:
            vals = [float(ft[fld]) for ft in lyr.getFeatures() if ft[fld] is not None and float(ft[fld]) > 0]
            if vals:
                dmin, dmax = min(vals), max(vals)
                self.mm_lbl.setText(f'Data Min: {dmin:,.0f} | Max: {dmax:,.0f}')
                nr = lambda n: max(1, int(round(n / (10 ** (len(str(int(n))) - 1))) * (10 ** (len(str(int(n))) - 1))))
                rmax, rmin = nr(dmax), nr(dmin)
                self.v1.setValue(rmax); self.v2.setValue(nr((rmax + rmin) / 2.0)); self.v3.setValue(rmin)

class EarthSphereDiagram:
    def __init__(self, iface): self.iface, self.action = iface, None
    def initGui(self):
        self.action = QAction(QIcon(':/images/themes/default/mActionAddOgrLayer.svg'), '3D Earth Sphere Diagram', self.iface.mainWindow())
        self.action.triggered.connect(self.run); self.iface.addToolBarIcon(self.action); self.iface.addPluginToMenu('&Sphere Diagram', self.action)
    def unload(self): self.iface.removePluginMenu('&Sphere Diagram', self.action); self.iface.removeToolBarIcon(self.action)
    def run(self):
        dlg = SphereDialog(self.iface.mainWindow()); dlg.run_btn.clicked.connect(lambda: self.make_map(dlg)); dlg.exec_()
    def make_map(self, dlg):
        try:
            lyr, fld, sc = dlg.lyr_cb.currentLayer(), dlg.fld_cb.currentField(), dlg.sz_sp.value()
            vals = [float(ft[fld]) for ft in lyr.getFeatures() if ft[fld] is not None and float(ft[fld]) > 0]
            if not vals: return
            for nm in ('Sphere_Base', 'Sphere_Grid', 'Sphere_Scale_Label'):
                for l in QgsProject.instance().mapLayersByName(nm): QgsProject.instance().removeMapLayer(l)
            sv_list = sorted((float(dlg.v1.value()), float(dlg.v2.value()), float(dlg.v3.value())), reverse=True)
            vl, vm, vs = sv_list.pop(0), sv_list.pop(0), sv_list.pop(0)
            ext = lyr.extent(); max_r = (ext.width() * 0.045) * sc; sf = max_r / (max(max(vals), vl) ** (1.0 / 3.0))
            crs = lyr.crs().authid()
            b_lyr = QgsVectorLayer('Polygon?crs=' + crs, 'Sphere_Base', 'memory')
            g_lyr = QgsVectorLayer('MultiLineString?crs=' + crs, 'Sphere_Grid', 'memory')
            g_lyr.dataProvider().addAttributes((QgsField('ltype', QVariant.String),)); g_lyr.updateFields()
            l_lyr = QgsVectorLayer('Point?crs=' + crs, 'Sphere_Scale_Label', 'memory')
            l_lyr.dataProvider().addAttributes((QgsField('scale_txt', QVariant.String),)); l_lyr.updateFields()
            bf, gf, lf = [], [], []
            roll, pitch = math.radians(-30.0), math.radians(23.5)
            def proj(x, y, z):
                yp, zp = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
                return x * math.cos(roll) - yp * math.sin(roll), x * math.sin(roll) + yp * math.cos(roll), zp
            def globe(c, r):
                cp = [QgsPointXY(c.x() + r * math.cos(math.radians(a)), c.y() + r * math.sin(math.radians(a))) for a in range(0, 365, 5)]
                lns = [cp]
                for ld in (-60, -30, 0, 30, 60):
                    lat, pts = math.radians(ld), []
                    for od in range(-180, 185, 5):
                        xr, yr, zr = proj(r * math.cos(lat) * math.sin(math.radians(od)), r * math.sin(lat), r * math.cos(lat) * math.cos(math.radians(od)))
                        if zr >= -0.02 * r: pts.append(QgsPointXY(c.x() + xr, c.y() + yr))
                        else:
                            if len(pts) > 1: lns.append(pts)
                            pts = []
                    if len(pts) > 1: lns.append(pts)
                for od in range(-150, 180, 30):
                    lon, pts = math.radians(od), []
                    for ld in range(-90, 95, 5):
                        xr, yr, zr = proj(r * math.cos(math.radians(ld)) * math.sin(lon), r * math.sin(math.radians(ld)), r * math.cos(math.radians(ld)) * math.cos(lon))
                        if zr >= -0.02 * r: pts.append(QgsPointXY(c.x() + xr, c.y() + yr))
                        else:
                            if len(pts) > 1: lns.append(pts)
                            pts = []
                    if len(pts) > 1: lns.append(pts)
                for s in (1, -1):
                    xi, yi, _ = proj(0, s * r, 0); xo, yo, _ = proj(0, s * r * 1.18, 0)
                    lns.append((QgsPointXY(c.x() + xi, c.y() + yi), QgsPointXY(c.x() + xo, c.y() + yo)))
                return QgsGeometry.fromPolygonXY([cp]), QgsGeometry.fromMultiPolylineXY(lns)
            for ft in lyr.getFeatures():
                if ft[fld] and float(ft[fld]) > 0:
                    pg, gg = globe(ft.geometry().centroid().asPoint(), (float(ft[fld]) ** (1.0 / 3.0)) * sf)
                    f1, f2 = QgsFeature(), QgsFeature(); f1.setGeometry(pg); f2.setGeometry(gg); f2.setAttributes(['solid']); bf.append(f1); gf.append(f2)
            rl, rm, rs = (vl**(1/3))*sf, (vm**(1/3))*sf, (vs**(1/3))*sf
            gap, by = max_r * 0.85, ext.yMinimum() - (max_r * 1.2)
            x1 = ext.xMinimum() + rl; x2 = x1 + rl + gap + rm; x3 = x2 + rm + gap + rs; tx = x3 + rs + (max_r * 0.9)
            for sv, sr, cx in ((vl, rl, x1), (vm, rm, x2), (vs, rs, x3)):
                pg, gg = globe(QgsPointXY(cx, by + sr), sr)
                f1, f2 = QgsFeature(), QgsFeature(); f1.setGeometry(pg); f2.setGeometry(gg); f2.setAttributes(['solid']); bf.append(f1); gf.append(f2)
                ty = by + 2.0 * sr
                df = QgsFeature(); df.setGeometry(QgsGeometry.fromMultiPolylineXY(list((list((QgsPointXY(cx, ty), QgsPointXY(tx, ty))),)))); df.setAttributes(['dotted']); gf.append(df)
                lt = QgsFeature(); lt.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(tx + max_r * 0.15, ty))); lt.setAttributes([f'  {int(round(sv)):,}']); lf.append(lt)
            bl = QgsFeature(); bl.setGeometry(QgsGeometry.fromMultiPolylineXY(list((list((QgsPointXY(x1 - rl*0.6, by), QgsPointXY(x3 + rs*0.6, by))),)))); bl.setAttributes(['solid']); gf.append(bl)
            tl = QgsFeature(); tl.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x1 - rl*0.4, by + rl*2.55))); tl.setAttributes(['Graphical Scale']); lf.append(tl)
            b_lyr.dataProvider().addFeatures(bf); b_lyr.updateExtents(); g_lyr.dataProvider().addFeatures(gf); g_lyr.updateExtents(); l_lyr.dataProvider().addFeatures(lf); l_lyr.updateExtents()
            fs = QgsFillSymbol(); fs.deleteSymbolLayer(0); gf_f = QgsGradientFillSymbolLayer(); gf_f.setColor(QColor('#ffffff')); gf_f.setColor2(QColor('#666666'))
            gf_f.setGradientType(QgsGradientFillSymbolLayer.Radial); gf_f.setCoordinateMode(QgsGradientFillSymbolLayer.Feature); gf_f.setReferencePoint1(QPointF(0.35, 0.3)); gf_f.setReferencePoint2(QPointF(0.5, 0.5))
            fs.appendSymbolLayer(gf_f); b_lyr.setRenderer(QgsSingleSymbolRenderer(fs))
            c1 = QgsRendererCategory('solid', QgsLineSymbol.createSimple({'color': '#111111', 'width': '0.25'}), 'Grid')
            c2 = QgsRendererCategory('dotted', QgsLineSymbol.createSimple({'color': '#111111', 'width': '0.3', 'line_style': 'dash'}), 'Leader')
            g_lyr.setRenderer(QgsCategorizedSymbolRenderer('ltype', (c1, c2)))
            ls = QgsPalLayerSettings(); ls.fieldName = 'scale_txt'; ls.enabled = True; ls.quadOffset = QgsPalLayerSettings.QuadrantRight
            tf = QgsTextFormat(); tf.setFont(QFont('Arial', 9, QFont.Bold)); tf.setColor(QColor('#000000')); ls.setFormat(tf); l_lyr.setLabeling(QgsVectorLayerSimpleLabeling(ls)); l_lyr.setLabelsEnabled(True)
            ps = QgsSymbol.defaultSymbol(l_lyr.geometryType()); ps.setOpacity(0); l_lyr.setRenderer(QgsSingleSymbolRenderer(ps))
            QgsProject.instance().addMapLayer(b_lyr); QgsProject.instance().addMapLayer(g_lyr); QgsProject.instance().addMapLayer(l_lyr)
            fe = lyr.extent(); fe.combineExtentWith(g_lyr.extent()); self.iface.mapCanvas().setExtent(fe); self.iface.mapCanvas().refresh(); dlg.accept()
        except Exception as e: QMessageBox.critical(dlg, 'Error', f'{e}\n{traceback.format_exc()}')
