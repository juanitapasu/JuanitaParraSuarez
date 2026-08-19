"""Modelo del mundo: validador de referencia (dado por la cátedra) + modelo de
búsqueda del agente (State + get_successors) construido sobre las mismas reglas.

Dos capas conviven a propósito en este archivo:

1. **Validador de referencia** (`load_scenario`, `initial_state`, `apply_step`,
   `goal_satisfied`, `simulate`): re-implementa exactamente las reglas de
   `CONTRATO.md` §4, mutando un `dict` paso a paso y lanzando `AssertionError`
   ante cualquier violación — el mismo criterio que usará el banco de pruebas
   del frontend. `demo_plan.py` la usa como red de seguridad: antes de
   devolver un plan lo vuelve a ejecutar aquí para confirmar que es legal.
2. **Modelo de búsqueda** (`State`, `ScenarioIndex`, `get_successors`):
   representación inmutable y hasheable del mismo mundo, más un generador de
   sucesores que aplica la poda de `DROP`/`PICKUP` por relevancia (design.md).
   Es lo que consume `uniform_cost_search` en `demo_plan.py`.

Ver design.md, sección "Estado" y "Modelo de transición".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

SCENARIO_PATH = Path(__file__).resolve().parents[2] / "scenarios" / "scenario.json"


# ===========================================================================
# 1. VALIDADOR DE REFERENCIA (reglas de CONTRATO.md §4, estilo imperativo)
# ===========================================================================

def load_scenario(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path) if path else SCENARIO_PATH
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def initial_state(scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "zone": scenario["robot"]["start"],
        "battery": scenario["robot"]["battery_start"],
        "energy_spent": 0,
        "payload": [],
        "doors": {d["id"]: d["state"] for d in scenario["doors"]},
        "panels": {p["id"]: p["state"] for p in scenario["panels"]},
        "stations": {s["id"]: s["state"] for s in scenario["stations"]},
        "ground_keys": {k["id"]: k["zone"] for k in scenario["keys"]},
        "ground_tools": {t["id"]: t["zone"] for t in scenario["tools"]},
        "ground_materials": {
            m["type"]: {"type": m["type"], "count": m["count"], "zone": m["zone"]}
            for m in scenario["materials"]
        },
    }


def payload_weight(payload: List[Dict[str, Any]]) -> int:
    return sum(p.get("weight", 1) for p in payload)


def spend(state: Dict[str, Any], cost: int) -> None:
    if state["battery"] < cost:
        raise AssertionError(f"Insufficient battery: have {state['battery']}, need {cost}")
    state["battery"] -= cost
    state["energy_spent"] += cost


def find_corridor(scenario: Dict[str, Any], frm: str, to: str) -> Dict[str, Any]:
    for c in scenario["corridors"]:
        if c["from"] == frm and c["to"] == to:
            return c
    raise AssertionError(f"No corridor {frm}->{to}")


def apply_step(scenario: Dict[str, Any], state: Dict[str, Any], step: Dict[str, Any]) -> None:
    cap = scenario["robot"]["cargo_capacity"]
    op = step["op"]
    cost = int(step["cost"])

    if op == "MOVE":
        frm = step.get("from", state["zone"])
        to = step["to"]
        assert frm == state["zone"], f"MOVE from {frm} but robot in {state['zone']}"
        corr = find_corridor(scenario, frm, to)
        if corr.get("door"):
            assert state["doors"][corr["door"]] == "OPEN", f"Door {corr['door']} closed"
        spend(state, cost)
        state["zone"] = to
        return

    if op == "PICKUP":
        item = step["item"]
        assert payload_weight(state["payload"]) + 1 <= cap, "cargo full"
        if item in state["ground_keys"]:
            assert state["ground_keys"][item] == state["zone"]
            key = next(k for k in scenario["keys"] if k["id"] == item)
            spend(state, cost)
            del state["ground_keys"][item]
            state["payload"].append({"kind": "key", "id": item, "color": key["color"], "weight": key["weight"]})
            return
        if item in state["ground_tools"]:
            assert state["ground_tools"][item] == state["zone"]
            tool = next(t for t in scenario["tools"] if t["id"] == item)
            spend(state, cost)
            del state["ground_tools"][item]
            state["payload"].append({"kind": "tool", "id": item, "repairs": tool["repairs"], "weight": tool["weight"]})
            return
        if item in state["ground_materials"]:
            mat = state["ground_materials"][item]
            assert mat["zone"] == state["zone"] and mat["count"] > 0
            spend(state, cost)
            mat["count"] -= 1
            if mat["count"] <= 0:
                del state["ground_materials"][item]
            state["payload"].append({"kind": "material", "type": item, "weight": 1})
            return
        raise AssertionError(f"Item {item} not on ground in {state['zone']}")

    if op == "DROP":
        item = step["item"]
        idx = next((i for i, p in enumerate(state["payload"]) if p.get("id") == item or p.get("type") == item), None)
        assert idx is not None, f"{item} not in payload"
        spend(state, cost)
        obj = state["payload"].pop(idx)
        if obj["kind"] == "key":
            state["ground_keys"][obj["id"]] = state["zone"]
        elif obj["kind"] == "tool":
            state["ground_tools"][obj["id"]] = state["zone"]
        else:
            existing = state["ground_materials"].get(obj["type"])
            if existing and existing["zone"] == state["zone"]:
                existing["count"] += 1
            else:
                state["ground_materials"][obj["type"]] = {"type": obj["type"], "count": 1, "zone": state["zone"]}
        return

    if op == "INTERACT":
        target = step["target"]
        action = step["action"]

        if action == "OPEN_DOOR":
            door = next(d for d in scenario["doors"] if d["id"] == target)
            a, b = door["between"]
            assert state["zone"] in (a, b)
            assert state["doors"][target] == "CLOSED"
            assert any(p.get("id") == door["key"] for p in state["payload"])
            spend(state, cost)
            state["doors"][target] = "OPEN"
            return

        if action == "REPAIR":
            panel = next(p for p in scenario["panels"] if p["id"] == target)
            assert state["zone"] == panel["zone"]
            assert state["panels"][target] == "DAMAGED"
            assert any(p.get("id") == panel["requires"]["tool"] for p in state["payload"])
            mat = step.get("consumes", panel["requires"]["material"])
            assert mat == panel["requires"]["material"]
            midx = next(
                (i for i, p in enumerate(state["payload"]) if p.get("kind") == "material" and p.get("type") == mat),
                None,
            )
            assert midx is not None, f"missing material {mat}"
            spend(state, cost)
            state["payload"].pop(midx)
            state["panels"][target] = "OK"
            return

        if action == "ACTIVATE":
            station = next(s for s in scenario["stations"] if s["id"] == target)
            assert state["zone"] == station["zone"]
            assert state["stations"][target] == "OFFLINE"
            for pid in station["requires"].get("panels_ok", []):
                assert state["panels"][pid] == "OK", f"panel {pid} not OK"
            for sid in station["requires"].get("stations_online", []):
                assert state["stations"][sid] == "ONLINE", f"station {sid} offline"
            spend(state, cost)
            state["stations"][target] = "ONLINE"
            return

        if action == "RECHARGE":
            charger = next(c for c in scenario["chargers"] if c["id"] == target)
            assert state["zone"] == charger["zone"]
            assert state["battery"] < scenario["robot"]["battery_max"]
            spend(state, cost)
            state["battery"] = scenario["robot"]["battery_max"]
            return

        raise AssertionError(f"Unknown action {action}")

    raise AssertionError(f"Unknown op {op}")


def goal_satisfied(scenario: Dict[str, Any], state: Dict[str, Any]) -> bool:
    return all(state["stations"][sid] == "ONLINE" for sid in scenario["goal"]["stations_online"])


def simulate(scenario: Dict[str, Any], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Reproduce un plan completo desde el estado inicial. Lanza AssertionError
    ante el primer paso ilegal — usado como verificación posterior a la búsqueda."""
    state = initial_state(scenario)
    for i, step in enumerate(steps):
        try:
            apply_step(scenario, state, step)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Step {i} {step} failed: {exc}") from exc
    return state


# ===========================================================================
# 2. MODELO DE BÚSQUEDA (State inmutable/hasheable + Applicable(s)/Result(s,a))
# ===========================================================================

def _c(pairs) -> Tuple:
    return tuple(sorted(pairs))


@dataclass(frozen=True)
class State:
    """s = <P, B, C, E, M> aplicado a este dominio:
    P=zone, B=battery, C=payload_*, E=doors+panels+stations, M=ground_*.

    __hash__/__eq__ EXCLUYEN la batería (design.md, "Cuándo dos configuraciones
    son el mismo estado"): la dominancia por batería se resuelve en demo_plan.py.
    """

    zone: str
    battery: int
    payload_keys: Tuple[str, ...]
    payload_tools: Tuple[str, ...]
    payload_materials: Tuple[Tuple[str, int], ...]  # (type, count)
    doors: Tuple[Tuple[str, str], ...]
    panels: Tuple[Tuple[str, str], ...]
    stations: Tuple[Tuple[str, str], ...]
    ground_keys: Tuple[Tuple[str, str], ...]  # (id, zone) — solo las no cargadas
    ground_tools: Tuple[Tuple[str, str], ...]
    ground_materials: Tuple[Tuple[str, str, int], ...]  # (type, zone, count)

    def signature(self) -> Tuple:
        return (
            self.zone,
            self.payload_keys,
            self.payload_tools,
            self.payload_materials,
            self.doors,
            self.panels,
            self.stations,
            self.ground_keys,
            self.ground_tools,
            self.ground_materials,
        )

    def __eq__(self, other: object) -> bool:  # noqa: D105
        if not isinstance(other, State):
            return NotImplemented
        return self.signature() == other.signature()

    def __hash__(self) -> int:  # noqa: D105
        return hash(self.signature())

    # --- vistas convenientes ---
    def doors_map(self) -> Dict[str, str]:
        return dict(self.doors)

    def panels_map(self) -> Dict[str, str]:
        return dict(self.panels)

    def stations_map(self) -> Dict[str, str]:
        return dict(self.stations)

    def materials_map(self) -> Dict[str, int]:
        return dict(self.payload_materials)

    def payload_weight(self) -> int:
        return len(self.payload_keys) + len(self.payload_tools) + sum(q for _, q in self.payload_materials)


@dataclass(frozen=True)
class ActionRecord:
    """Sucesor de Applicable(s): ya trae el `step` en el formato exacto del contrato."""

    kind: str  # "MOVE" | "PICKUP" | "DROP" | "INTERACT"
    step: Dict[str, Any]
    cost: int


class ScenarioIndex:
    """Envuelve el scenario.json crudo con lookups precomputados (constantes Θ)."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.robot = raw["robot"]
        self.action_costs = raw["action_costs"]
        self.doors = {d["id"]: d for d in raw["doors"]}
        self.panels = {p["id"]: p for p in raw["panels"]}
        self.stations = {s["id"]: s for s in raw["stations"]}
        self.keys = {k["id"]: k for k in raw["keys"]}
        self.tools = {t["id"]: t for t in raw["tools"]}
        self.materials = {m["type"]: m for m in raw["materials"]}
        self.chargers = raw.get("chargers", [])
        self.goal = raw["goal"]

        self.corridors_from: Dict[str, List[Dict[str, Any]]] = {}
        for c in raw["corridors"]:
            self.corridors_from.setdefault(c["from"], []).append(c)

        self.door_by_key: Dict[str, str] = {d["key"]: d["id"] for d in raw["doors"] if "key" in d}
        self.panels_needing_tool: Dict[str, List[str]] = {}
        self.panels_needing_material: Dict[str, List[str]] = {}
        for p in raw["panels"]:
            req = p["requires"]
            self.panels_needing_tool.setdefault(req["tool"], []).append(p["id"])
            self.panels_needing_material.setdefault(req["material"], []).append(p["id"])

    def initial_state(self) -> State:
        return State(
            zone=self.robot["start"],
            battery=self.robot["battery_start"],
            payload_keys=(),
            payload_tools=(),
            payload_materials=(),
            doors=_c((d["id"], d["state"]) for d in self.raw["doors"]),
            panels=_c((p["id"], p["state"]) for p in self.raw["panels"]),
            stations=_c((s["id"], s["state"]) for s in self.raw["stations"]),
            ground_keys=_c((k["id"], k["zone"]) for k in self.raw["keys"]),
            ground_tools=_c((t["id"], t["zone"]) for t in self.raw["tools"]),
            ground_materials=_c((m["type"], m["zone"], m["count"]) for m in self.raw["materials"] if m["count"] > 0),
        )

    def is_goal(self, state: State) -> bool:
        stations = state.stations_map()
        return all(stations.get(sid) == "ONLINE" for sid in self.goal["stations_online"])

    # --- relevancia (design.md, "Relevancia: objetos que ya no cambian el futuro") ---
    def key_relevant(self, key_id: str, state: State) -> bool:
        door_id = self.door_by_key.get(key_id)
        return door_id is not None and state.doors_map().get(door_id) == "CLOSED"

    def tool_relevant(self, tool_id: str, state: State) -> bool:
        panels = state.panels_map()
        return any(panels.get(pid) == "DAMAGED" for pid in self.panels_needing_tool.get(tool_id, []))

    def material_relevant(self, mat_type: str, state: State) -> bool:
        panels = state.panels_map()
        return any(panels.get(pid) == "DAMAGED" for pid in self.panels_needing_material.get(mat_type, []))


def get_successors(idx: ScenarioIndex, state: State) -> List[Tuple[ActionRecord, State]]:
    """Applicable(s) + Result(s,a). Refleja exactamente las reglas de apply_step,
    pero de forma pura (sin mutar) y con la poda de DROP/PICKUP por relevancia."""
    out: List[Tuple[ActionRecord, State]] = []
    doors = state.doors_map()
    panels = state.panels_map()
    stations = state.stations_map()
    ground_keys = dict(state.ground_keys)
    ground_tools = dict(state.ground_tools)
    ground_materials = {t: (z, q) for t, z, q in state.ground_materials}
    weight = state.payload_weight()
    cap = idx.robot["cargo_capacity"]

    def mk(zone=None, battery=None, pk=None, pt=None, pm=None, dr=None, pn=None, st=None, gk=None, gt=None, gm=None) -> State:
        return State(
            zone=zone if zone is not None else state.zone,
            battery=battery if battery is not None else state.battery,
            payload_keys=pk if pk is not None else state.payload_keys,
            payload_tools=pt if pt is not None else state.payload_tools,
            payload_materials=pm if pm is not None else state.payload_materials,
            doors=dr if dr is not None else state.doors,
            panels=pn if pn is not None else state.panels,
            stations=st if st is not None else state.stations,
            ground_keys=gk if gk is not None else state.ground_keys,
            ground_tools=gt if gt is not None else state.ground_tools,
            ground_materials=gm if gm is not None else state.ground_materials,
        )

    # --- MOVE ---
    for corr in idx.corridors_from.get(state.zone, []):
        door_id = corr.get("door")
        if door_id and doors.get(door_id) != "OPEN":
            continue
        cost = corr["cost"]
        if state.battery < cost:
            continue
        step = {"op": "MOVE", "from": state.zone, "to": corr["to"], "cost": cost}
        out.append((ActionRecord("MOVE", step, cost), mk(zone=corr["to"], battery=state.battery - cost)))

    # --- RECHARGE (INTERACT especial) ---
    cost_recharge = idx.action_costs["recharge"]
    if state.battery < idx.robot["battery_max"] and state.battery >= cost_recharge:
        for charger in idx.chargers:
            if charger["zone"] == state.zone:
                step = {"op": "INTERACT", "target": charger["id"], "action": "RECHARGE", "cost": cost_recharge}
                out.append((ActionRecord("INTERACT", step, cost_recharge), mk(battery=idx.robot["battery_max"])))

    # --- PICKUP (solo relevante y que quepa) ---
    cost_pickup = idx.action_costs["pickup"]
    if weight < cap and state.battery >= cost_pickup:
        for key_id, zone in ground_keys.items():
            if zone == state.zone and idx.key_relevant(key_id, state):
                new_gk = tuple(sorted((k, z) for k, z in ground_keys.items() if k != key_id))
                step = {"op": "PICKUP", "item": key_id, "cost": cost_pickup}
                out.append((
                    ActionRecord("PICKUP", step, cost_pickup),
                    mk(battery=state.battery - cost_pickup, pk=tuple(sorted(state.payload_keys + (key_id,))), gk=new_gk),
                ))
        for tool_id, zone in ground_tools.items():
            if zone == state.zone and idx.tool_relevant(tool_id, state):
                new_gt = tuple(sorted((t, z) for t, z in ground_tools.items() if t != tool_id))
                step = {"op": "PICKUP", "item": tool_id, "cost": cost_pickup}
                out.append((
                    ActionRecord("PICKUP", step, cost_pickup),
                    mk(battery=state.battery - cost_pickup, pt=tuple(sorted(state.payload_tools + (tool_id,))), gt=new_gt),
                ))
        for mat_type, (zone, qty) in ground_materials.items():
            if zone == state.zone and qty > 0 and idx.material_relevant(mat_type, state):
                new_gm = tuple(sorted(
                    (t, z, (q - 1 if t == mat_type else q))
                    for t, (z, q) in ground_materials.items()
                    if not (t == mat_type and q - 1 <= 0)
                ))
                pm_map = dict(state.payload_materials)
                pm_map[mat_type] = pm_map.get(mat_type, 0) + 1
                step = {"op": "PICKUP", "item": mat_type, "cost": cost_pickup}
                out.append((
                    ActionRecord("PICKUP", step, cost_pickup),
                    mk(battery=state.battery - cost_pickup, pm=_c(pm_map.items()), gm=new_gm),
                ))

    # --- DROP (solo si la capacidad está llena y bloquea un PICKUP relevante) ---
    cost_drop = idx.action_costs["drop"]
    if weight >= cap and state.battery >= cost_drop:
        blocked = any(
            zone == state.zone and idx.key_relevant(k, state) for k, zone in ground_keys.items()
        ) or any(
            zone == state.zone and idx.tool_relevant(t, state) for t, zone in ground_tools.items()
        ) or any(
            zone == state.zone and qty > 0 and idx.material_relevant(t, state) for t, (zone, qty) in ground_materials.items()
        )
        if blocked:
            carried = (
                [("key", k) for k in state.payload_keys]
                + [("tool", t) for t in state.payload_tools]
                + [("material", t) for t, q in state.payload_materials if q > 0]
            )
            irrelevant = [
                (kind, ident)
                for kind, ident in carried
                if (kind == "key" and not idx.key_relevant(ident, state))
                or (kind == "tool" and not idx.tool_relevant(ident, state))
                or (kind == "material" and not idx.material_relevant(ident, state))
            ]
            candidates = irrelevant if irrelevant else carried
            for kind, ident in candidates:
                if kind == "key":
                    new_pk = tuple(x for x in state.payload_keys if x != ident)
                    new_gk = tuple(sorted(list(state.ground_keys) + [(ident, state.zone)]))
                    step = {"op": "DROP", "item": ident, "cost": cost_drop}
                    out.append((ActionRecord("DROP", step, cost_drop), mk(battery=state.battery - cost_drop, pk=new_pk, gk=new_gk)))
                elif kind == "tool":
                    new_pt = tuple(x for x in state.payload_tools if x != ident)
                    new_gt = tuple(sorted(list(state.ground_tools) + [(ident, state.zone)]))
                    step = {"op": "DROP", "item": ident, "cost": cost_drop}
                    out.append((ActionRecord("DROP", step, cost_drop), mk(battery=state.battery - cost_drop, pt=new_pt, gt=new_gt)))
                else:
                    pm_map = dict(state.payload_materials)
                    pm_map[ident] = pm_map.get(ident, 0) - 1
                    if pm_map[ident] <= 0:
                        del pm_map[ident]
                    existing = ground_materials.get(ident)
                    if existing and existing[0] == state.zone:
                        new_gm = tuple(sorted((t, z, (q + 1 if t == ident else q)) for t, (z, q) in ground_materials.items()))
                    else:
                        new_gm = tuple(sorted(list(state.ground_materials) + [(ident, state.zone, 1)]))
                    step = {"op": "DROP", "item": ident, "cost": cost_drop}
                    out.append((ActionRecord("DROP", step, cost_drop), mk(battery=state.battery - cost_drop, pm=_c(pm_map.items()), gm=new_gm)))

    # --- INTERACT: OPEN_DOOR / REPAIR / ACTIVATE ---
    cost_interact = idx.action_costs["interact"]
    if state.battery >= cost_interact:
        for door_id, door in idx.doors.items():
            a, b = door["between"]
            if state.zone not in (a, b):
                continue
            if doors.get(door_id) != "CLOSED":
                continue
            if door["key"] not in state.payload_keys:
                continue
            new_doors = tuple(sorted((did, ("OPEN" if did == door_id else st)) for did, st in state.doors))
            step = {"op": "INTERACT", "target": door_id, "action": "OPEN_DOOR", "cost": cost_interact}
            out.append((ActionRecord("INTERACT", step, cost_interact), mk(battery=state.battery - cost_interact, dr=new_doors)))

        for panel_id, panel in idx.panels.items():
            if panel["zone"] != state.zone or panels.get(panel_id) != "DAMAGED":
                continue
            req = panel["requires"]
            if req["tool"] not in state.payload_tools:
                continue
            pm_map = dict(state.payload_materials)
            if pm_map.get(req["material"], 0) < 1:
                continue
            pm_map[req["material"]] -= 1
            if pm_map[req["material"]] <= 0:
                del pm_map[req["material"]]
            new_panels = tuple(sorted((pid, ("OK" if pid == panel_id else st)) for pid, st in state.panels))
            step = {"op": "INTERACT", "target": panel_id, "action": "REPAIR", "consumes": req["material"], "cost": cost_interact}
            out.append((ActionRecord("INTERACT", step, cost_interact), mk(battery=state.battery - cost_interact, pm=_c(pm_map.items()), pn=new_panels)))

        for station_id, station in idx.stations.items():
            if station["zone"] != state.zone or stations.get(station_id) != "OFFLINE":
                continue
            req = station["requires"]
            if not all(panels.get(pid) == "OK" for pid in req.get("panels_ok", [])):
                continue
            if not all(stations.get(sid) == "ONLINE" for sid in req.get("stations_online", [])):
                continue
            new_stations = tuple(sorted((sid, ("ONLINE" if sid == station_id else st)) for sid, st in state.stations))
            step = {"op": "INTERACT", "target": station_id, "action": "ACTIVATE", "cost": cost_interact}
            out.append((ActionRecord("INTERACT", step, cost_interact), mk(battery=state.battery - cost_interact, st=new_stations)))

    return out
