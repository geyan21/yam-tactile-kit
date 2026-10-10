"""Shaded offscreen renders (VTK/EGL) of the tactile finger for the README / team review."""
import os
import sys
import numpy as np
import trimesh
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import yam_tactile_finger as F  # noqa: E402

OUT = os.path.join(F.OUT, "renders")
os.makedirs(OUT, exist_ok=True)
C = dict(socket=(0.36, 0.37, 0.40), cartridge=(0.16, 0.42, 0.72), skin=(0.96, 0.56, 0.17), ph_pad=(0.86, 0.70, 0.22),
         ph_finger_pcb=(0.10, 0.48, 0.22), ph_finger_pcb_parts=(0.15, 0.15, 0.15), ph_socket_pcb=(0.10, 0.48, 0.22),
         ph_pogo_pins=(0.85, 0.72, 0.25), ph_thumbscrews=(0.72, 0.72, 0.74), ph_dowels=(0.72, 0.72, 0.74),
         housing=(0.55, 0.57, 0.58), carriage=(0.72, 0.74, 0.76), taxel=(0.80, 0.42, 0.12))


def polydata(mesh):
    pts = vtk.vtkPoints(); pts.SetData(numpy_to_vtk(np.ascontiguousarray(mesh.vertices, float), deep=True))
    f = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).astype(np.int64).ravel()
    cells = vtk.vtkCellArray(); cells.ImportLegacyFormat(numpy_to_vtkIdTypeArray(f, deep=True))
    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(cells)
    return pd


def add(ren, mesh, color, opacity=1.0, edges=True):
    pd = polydata(mesh)
    nrm = vtk.vtkPolyDataNormals(); nrm.SetInputData(pd); nrm.SetFeatureAngle(35); nrm.SplittingOn(); nrm.Update()
    m = vtk.vtkPolyDataMapper(); m.SetInputConnection(nrm.GetOutputPort())
    a = vtk.vtkActor(); a.SetMapper(m)
    pr = a.GetProperty(); pr.SetColor(*color); pr.SetOpacity(opacity)
    pr.SetAmbient(0.18); pr.SetDiffuse(0.75); pr.SetSpecular(0.25); pr.SetSpecularPower(25)
    ren.AddActor(a)
    if edges and opacity > 0.6:
        fe = vtk.vtkFeatureEdges(); fe.SetInputData(pd); fe.BoundaryEdgesOn(); fe.FeatureEdgesOn()
        fe.SetFeatureAngle(40); fe.ManifoldEdgesOff(); fe.NonManifoldEdgesOff(); fe.Update()
        em = vtk.vtkPolyDataMapper(); em.SetInputConnection(fe.GetOutputPort()); em.ScalarVisibilityOff()
        ea = vtk.vtkActor(); ea.SetMapper(em)
        ea.GetProperty().SetColor(*(np.array(color) * 0.35)); ea.GetProperty().SetLineWidth(1.2)
        ren.AddActor(ea)


def taxel_tiles(side=1):
    """Thin tiles on the pad surface showing the 16 x 8 taxel overlaps."""
    P, D = F.P, F.DERIVED
    tiles = []
    for r in range(P["N_ROWS"]):
        for c in range(P["N_COLS"]):
            x = -D["ACT_W"] / 2 + P["PITCH"] * (c + 0.5)
            z = D["ACT_Z0"] + P["PITCH"] * (r + 0.5)
            b = trimesh.creation.box((1.5, 0.06, 1.5))
            b.apply_translation((x, D["Y_FACE"] - 0.03, z))
            tiles.append(b)
    t = trimesh.util.concatenate(tiles)
    if side < 0:
        t.apply_transform(np.diag([-1, -1, 1, 1.0]))
    return t


def render(actors_fn, fname, pos, focal, up=(0, 0, 1), size=(1400, 1100), parallel=None):
    ren = vtk.vtkRenderer(); ren.SetBackground(1, 1, 1)
    actors_fn(ren)
    lk = vtk.vtkLightKit(); lk.AddLightsToRenderer(ren)
    cam = ren.GetActiveCamera(); cam.SetPosition(*pos); cam.SetFocalPoint(*focal); cam.SetViewUp(*up)
    if parallel:
        cam.ParallelProjectionOn(); cam.SetParallelScale(parallel)
    else:
        cam.SetViewAngle(24)
    ren.ResetCameraClippingRange()
    ss = 2                                   # supersample, then downscale (FXAA is broken on EGL)
    rw = vtk.vtkRenderWindow(); rw.SetOffScreenRendering(1); rw.AddRenderer(ren); rw.SetSize(size[0] * ss, size[1] * ss)
    rw.Render()
    w2i = vtk.vtkWindowToImageFilter(); w2i.SetInput(rw); w2i.SetScale(1); w2i.Update()
    tmp = os.path.join(OUT, "_ss_" + fname)
    wr = vtk.vtkPNGWriter(); wr.SetFileName(tmp); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
    from PIL import Image
    Image.open(tmp).resize(size, Image.LANCZOS).save(os.path.join(OUT, fname)); os.remove(tmp)


def hero():
    q = 0.024
    G, CL, CR, _, _ = cf.yam_meshes(q)
    Rf, Lf = cf.finger(q, 1), cf.finger(q, -1)
    def fn(ren):
        add(ren, G, C["housing"]); add(ren, CL, C["carriage"]); add(ren, CR, C["carriage"])
        for f in (Rf, Lf):
            for k in ("socket", "cartridge", "skin", "ph_thumbscrews"):
                add(ren, f[k], C[k])
    render(fn, "hero.png", pos=(-260, -330, 40), focal=(0, 0, -75))


def finger_closeup():
    f = cf.finger(0.0, 1)
    tiles = taxel_tiles(1)
    def fn(ren):
        for k in ("socket", "cartridge", "ph_thumbscrews", "ph_pad"):
            add(ren, f[k], C[k])
        add(ren, tiles, C["taxel"], edges=False)
        add(ren, f["skin"], C["skin"], opacity=0.35, edges=False)
    render(fn, "finger_inner_face.png", pos=(-120, -210, -60), focal=(0, 10, -112))


def exploded():
    f = cf.finger(0.0, 1)
    off = dict(socket=(0, 0, 34), ph_socket_pcb=(0, 0, 24), ph_pogo_pins=(0, 0, 24), ph_dowels=(0, 0, 34),
               ph_finger_pcb=(0, 0, 12), ph_finger_pcb_parts=(0, 0, 12), cartridge=(0, 0, 0),
               ph_thumbscrews=(0, 0, -14), ph_pad=(0, -14, 0), skin=(0, -30, 0))
    tiles = taxel_tiles(1); tiles.apply_translation((0, -14, 0))
    def fn(ren):
        for k, m in f.items():
            mm = m.copy(); mm.apply_translation(off.get(k, (0, 0, 0)))
            add(ren, mm, C[k])
        add(ren, tiles, C["taxel"], edges=False)
    render(fn, "exploded.png", pos=(-230, -260, 40), focal=(0, -5, -100))


def back_view():
    f = cf.finger(0.0, 1)
    def fn(ren):
        for k in ("socket", "cartridge", "skin", "ph_thumbscrews"):
            add(ren, f[k], C[k])
    render(fn, "finger_back_below.png", pos=(160, 230, -230), focal=(0, 10, -105))


def contact_sheet():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg
    items = [("hero.png", "YAM Linear 4310 with two tactile cartridges (same part, rotated 180 deg)"),
             ("exploded.png", "socket (stays on robot) / pogo PCB / finger PCB / cartridge / pad / skin"),
             ("finger_inner_face.png", "inner face: 8 x 16 pad at 2 mm pitch under a 1.2 mm TPU skin"),
             ("finger_back_below.png", "two knurled M3 thumbscrews under the flange wings")]
    fig, axs = plt.subplots(2, 2, figsize=(16, 12.6))
    for ax, (fn, t) in zip(axs.ravel(), items):
        ax.imshow(mpimg.imread(os.path.join(OUT, fn))); ax.set_title(t, fontsize=12); ax.axis("off")
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "overview_sheet.png"), dpi=80); plt.close()


if __name__ == "__main__":
    hero(); exploded(); finger_closeup(); back_view(); contact_sheet()
    print("renders in", OUT)
