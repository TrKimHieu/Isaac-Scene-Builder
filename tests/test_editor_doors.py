"""Headless editor tests: painting doors, auto-fit against walls, hinge / swing keys."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

import architecture as arch  # noqa: E402
import scene_editor as se  # noqa: E402
from config import EDGE_DOOR, EDGE_WALL  # noqa: E402


@pytest.fixture
def ed():
    e = se.Editor()
    e.nx, e.ny = 6, 6
    e.cells = {(i, j): 1 for i in range(6) for j in range(6)}
    for j in range(6):                       # a wall along x = 3 ...
        e.vedges[(3, j)] = EDGE_WALL
    for i in range(3):                       # ... and one along y = 3 meeting it
        e.hedges[(i, 3)] = EDGE_WALL
    yield e
    pygame.quit()


def test_click_paints_and_selects_a_door(ed):
    ed.edge_type = EDGE_DOOR
    ed.click_edge("hedge", 2, 3)              # right beside the x = 3 wall
    assert ed.hedges[(2, 3)] == EDGE_DOOR and ed.sel_door == ("hedge", 2, 3)
    assert ("hedge", 2, 3) not in ed.door_issues()          # fitted on placement


def test_hinge_key_can_block_and_fit_repairs(ed):
    ed.edge_type = EDGE_DOOR
    ed.click_edge("hedge", 2, 3)
    blocked = []
    for _ in range(4):                        # walk through the 4 hinge / swing setups
        ed._door_op("hinge")
        blocked.append(("hedge", 2, 3) in ed.door_issues())
        ed._door_op("swing")
        blocked.append(("hedge", 2, 3) in ed.door_issues())
    assert any(blocked) and not all(blocked)
    ed._door_op("fit")
    assert ("hedge", 2, 3) not in ed.door_issues()


def test_click_again_toggles_off_a_wall(ed):
    ed.edge_type = EDGE_WALL
    ed.click_edge("vedge", 3, 0)
    assert (3, 0) not in ed.vedges


def test_hinge_saved_in_map(ed):
    ed.edge_type = EDGE_DOOR
    ed.click_edge("hedge", 1, 3)
    ed._door_op("hinge")
    md = ed.map_data()
    assert md["door_hinge"] == {"h:1,3": True}
    assert arch.door_mirrored(md, "h", 1, 3)
