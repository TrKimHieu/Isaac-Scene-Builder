"""
Procedural scene generator cho thu vien props Office (Isaac Sim / OpenUSD).

Sinh ra mot phong hinh chu nhat (san + tran + tuong ghep tu module 3m),
rai noi that ngau nhien ben trong, va gan den tran da bat san.

- Don vi: 1 unit = 1 met, truc len = Z (giong office.usd goc).
- Scene.usd chi tham chieu (reference) toi assets/office/Props/*.usd -> file rat nhe.

Chay:
    python src/generate_scene.py                  # dung tham so mac dinh
    python src/generate_scene.py --cells-x 5 --cells-y 4 --seed 7 --furniture 40
"""
import argparse
import random
import os

from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf

from config import (CELL, WALL_H, FLOOR, CEILING, WALL, WALL_DOOR,
                    LIGHT_MESH, PROPS_REL, SCENES_DIR)
from scene_builder import (place, asset_exists, check_required,
                           available_furniture, asset_path)


def build_shell(stage, root, nx, ny, door_cell):
    """San + tran + 4 buc tuong bao quanh phong nx*ny o (moi o = 3m)."""
    W, D = nx * CELL, ny * CELL

    # San + tran
    for i in range(nx):
        for j in range(ny):
            place(stage, f"{root}/Structure/Floor_{i}_{j}", FLOOR,
                  (i * CELL, j * CELL, 0.0))
            place(stage, f"{root}/Structure/Ceiling_{i}_{j}", CEILING,
                  (i * CELL, j * CELL, WALL_H))

    # Tuong West (X=0, chay +Y) -> khong xoay
    for j in range(ny):
        place(stage, f"{root}/Structure/WallW_{j}", WALL,
              (0.0, j * CELL, 0.0), rot_z=0)
    # East (X=W) -> xoay 180
    for j in range(ny):
        place(stage, f"{root}/Structure/WallE_{j}", WALL,
              (W, (j + 1) * CELL, 0.0), rot_z=180)
    # South (Y=0, chay +X) -> xoay -90. O door_cell dung module co cua.
    for i in range(nx):
        a = WALL_DOOR if i == door_cell else WALL
        place(stage, f"{root}/Structure/WallS_{i}", a,
              (i * CELL, 0.0, 0.0), rot_z=-90)
    # North (Y=D) -> xoay +90
    for i in range(nx):
        place(stage, f"{root}/Structure/WallN_{i}", WALL,
              ((i + 1) * CELL, D, 0.0), rot_z=90)


def scatter_furniture(stage, root, nx, ny, count, furniture, rng):
    """Rai noi that ngau nhien, tranh chong lan bang kiem tra khoang cach toi thieu."""
    W, D = nx * CELL, ny * CELL
    margin = 0.7
    placed = []
    n = 0
    tries = 0
    while n < count and tries < count * 60:
        tries += 1
        name, r = rng.choice(furniture)
        x = rng.uniform(margin + r, W - margin - r)
        y = rng.uniform(margin + r, D - margin - r)
        if any((x - px) ** 2 + (y - py) ** 2 < (r + pr) ** 2
               for px, py, pr in placed):
            continue
        yaw = rng.choice([0, 90, 180, 270]) + rng.uniform(-12, 12)
        place(stage, f"{root}/Furniture/{name}_{n}", name, (x, y, 0.0), rot_z=yaw)
        placed.append((x, y, r))
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=os.path.join(SCENES_DIR, "Scene.usd"))
    ap.add_argument("--cells-x", type=int, default=5)
    ap.add_argument("--cells-y", type=int, default=4)
    ap.add_argument("--furniture", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    furniture = available_furniture()
    if not furniture:
        raise SystemExit("Khong co prop nao trong %s" % str(furniture))
    rng = random.Random(args.seed)
    nx, ny = args.cells_x, args.cells_y

    stage = Usd.Stage.CreateNew(args.out)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = "/World"
    world = UsdGeom.Xform.Define(stage, root)
    stage.SetDefaultPrim(world.GetPrim())

    UsdGeom.Scope.Define(stage, root + "/Structure")
    UsdGeom.Scope.Define(stage, root + "/Lights")

    door_cell = rng.randrange(nx)
    build_shell(stage, root, nx, ny, door_cell)

    # Den tran: 1 den moi o
    for i in range(nx):
        for j in range(ny):
            cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
            from scene_builder import add_light
            add_light(stage, f"{root}/Lights/Lamp_{i}_{j}", cx, cy)

    nf = scatter_furniture(stage, root, nx, ny, args.furniture, furniture, rng)

    stage.GetRootLayer().Save()
    print(f"Da tao: {args.out}")
    print(f"  Phong: {nx*CELL:.0f} x {ny*CELL:.0f} m ({nx}x{ny} o), cao {WALL_H:.0f} m")
    print(f"  Den tran: {nx*ny}, noi that: {nf}, cua o o so {door_cell} (tuong South)")


if __name__ == "__main__":
    main()
