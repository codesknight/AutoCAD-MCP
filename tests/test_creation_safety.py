"""Offline fault injection: dependency errors cannot create orphan entities."""
from types import SimpleNamespace

import pytest
from autocad_mcp.cad.controller import CADController


class Entity:
    def __init__(self, oid, fail=None, delete_fails=False):
        self.ObjectID = oid
        self.fail = fail
        self.delete_fails = delete_fails
        self.deleted = False

    def __setattr__(self, name, value):
        if name == self.__dict__.get("fail"):
            raise RuntimeError(f"setter failed: {name}")
        object.__setattr__(self, name, value)

    def Delete(self):
        if self.delete_fails:
            raise RuntimeError("cleanup refused")
        self.deleted = True

    def AppendOuterLoop(self, _boundary):
        pass

    def Evaluate(self):
        if self.fail == "Evaluate":
            raise RuntimeError("evaluate failed")


class ModelSpace:
    def __init__(self, fail=None, delete_fails=False):
        self.entities = []
        self.fail = fail
        self.delete_fails = delete_fails

    def __getattr__(self, method):
        if not method.startswith("Add") and method != "InsertBlock":
            raise AttributeError(method)

        def add(*_args):
            entity = Entity(len(self.entities) + 1, self.fail, self.delete_fails)
            self.entities.append(entity)
            return entity
        return add


def controller(*, missing=False, locked=False, frozen=False, fail=None, delete_fails=False):
    model = ModelSpace(fail, delete_fails)

    def item(_name):
        if missing:
            raise KeyError("missing layer")
        return SimpleNamespace(Lock=locked, Freeze=frozen)

    doc = SimpleNamespace(Layers=SimpleNamespace(Item=item))
    ctrl = CADController(SimpleNamespace(document=doc, model_space=model))
    ctrl._ensure_cjk_text_style = lambda: "fixture"
    return ctrl, model


DRAW = [
    lambda c: c.draw_line((0, 0, 0), (1, 1, 0), layer="fixture"),
    lambda c: c.draw_circle((0, 0, 0), 1, layer="fixture"),
    lambda c: c.draw_arc((0, 0, 0), 1, 0, 90, layer="fixture"),
    lambda c: c.draw_polyline([(0, 0, 0), (1, 1, 0)], layer="fixture"),
    lambda c: c.draw_rectangle((0, 0, 0), (1, 1, 0), layer="fixture"),
    lambda c: c.draw_text((0, 0, 0), "fixture", 1, layer="fixture"),
    lambda c: c.draw_mtext((0, 0, 0), "fixture", layer="fixture"),
    lambda c: c.insert_block("fixture", (0, 0, 0), layer="fixture"),
    lambda c: c.draw_hatch([(0, 0, 0), (1, 0, 0), (1, 1, 0)], layer="fixture"),
]


@pytest.mark.parametrize("draw", DRAW)
@pytest.mark.parametrize("state", ["missing", "locked", "frozen"])
def test_invalid_layer_precedes_all_creation(draw, state):
    ctrl, model = controller(**{state: True})
    with pytest.raises((KeyError, ValueError)):
        draw(ctrl)
    assert model.entities == []


@pytest.mark.parametrize("draw", DRAW)
def test_property_failure_cleans_only_objects_from_this_call(draw):
    ctrl, model = controller(fail="Layer")
    prior = Entity(999)
    with pytest.raises(RuntimeError, match="setter failed"):
        draw(ctrl)
    assert all(e.deleted for e in model.entities)
    assert not prior.deleted


def test_cleanup_failure_is_explicit_and_does_not_claim_rollback():
    ctrl, model = controller(fail="Layer", delete_fails=True)
    with pytest.raises(RuntimeError, match="CAD_PARTIAL_MUTATION.*cleanup_errors"):
        DRAW[3](ctrl)
    assert len(model.entities) == 1
    assert not model.entities[0].deleted


def test_closed_and_hatch_evaluation_failures_cleanup_created_geometry():
    ctrl, model = controller(fail="Closed")
    with pytest.raises(RuntimeError, match="Closed"):
        DRAW[3](ctrl)
    assert all(e.deleted for e in model.entities)
    ctrl, model = controller(fail="Evaluate")
    with pytest.raises(RuntimeError, match="evaluate failed"):
        DRAW[-1](ctrl)
    assert len(model.entities) == 2
    assert all(e.deleted for e in model.entities)
