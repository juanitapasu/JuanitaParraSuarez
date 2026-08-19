from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import Any


# ============================================================
# STATE
# ============================================================


@dataclass(frozen=True)
class State:
    """
    Estado completo del mundo.

    La estructura es inmutable para que cada transición
    produzca un nuevo estado y nunca modifique el padre.
    """

    zone: str
    battery: int

    payload: tuple[
        tuple[str, str, int],
        ...
    ]

    doors: tuple[
        tuple[str, str],
        ...
    ]

    panels: tuple[
        tuple[str, str],
        ...
    ]

    stations: tuple[
        tuple[str, str],
        ...
    ]

    ground_keys: tuple[
        tuple[str, str],
        ...
    ]

    ground_tools: tuple[
        tuple[str, str],
        ...
    ]

    ground_materials: tuple[
        tuple[str, int, str],
        ...
    ]


# ============================================================
# SEARCH NODE
# ============================================================


@dataclass
class Node:
    state: State
    parent: Node | None
    action: dict[str, Any] | None
    g: int


# ============================================================
# BASIC HELPERS
# ============================================================


def payload_weight(state: State) -> int:
    """Calcula el peso actual del robot."""

    return sum(
        weight
        for _, _, weight in state.payload
    )


def has_item(
    state: State,
    item_id: str,
) -> bool:
    """Indica si el robot tiene un objeto."""

    return any(
        obj_id == item_id
        for _, obj_id, _ in state.payload
    )


def payload_ids(
    state: State,
) -> set[str]:
    """Devuelve IDs/tipos presentes en el payload."""

    return {
        obj_id
        for _, obj_id, _ in state.payload
    }


# ============================================================
# INITIAL STATE
# ============================================================


def initial_state(
    scenario: dict[str, Any],
) -> State:
    """Construye el estado inicial."""

    doors = tuple(
        sorted(
            (
                d["id"],
                d["state"],
            )
            for d in scenario["doors"]
        )
    )

    panels = tuple(
        sorted(
            (
                p["id"],
                p["state"],
            )
            for p in scenario["panels"]
        )
    )

    stations = tuple(
        sorted(
            (
                s["id"],
                s["state"],
            )
            for s in scenario["stations"]
        )
    )

    ground_keys = tuple(
        sorted(
            (
                k["id"],
                k["zone"],
            )
            for k in scenario["keys"]
        )
    )

    ground_tools = tuple(
        sorted(
            (
                t["id"],
                t["zone"],
            )
            for t in scenario["tools"]
        )
    )

    ground_materials = tuple(
        sorted(
            (
                m["type"],
                int(m["count"]),
                m["zone"],
            )
            for m in scenario["materials"]
        )
    )

    return State(
        zone=scenario["robot"]["start"],
        battery=int(
            scenario["robot"]["battery_start"]
        ),
        payload=(),
        doors=doors,
        panels=panels,
        stations=stations,
        ground_keys=ground_keys,
        ground_tools=ground_tools,
        ground_materials=ground_materials,
    )


# ============================================================
# STATE KEY
# ============================================================


def state_key(
    state: State,
) -> tuple[Any, ...]:
    """
    Configuración física del mundo.

    La batería NO forma parte de esta clave porque
    la tratamos mediante dominancia.

    Dos estados con la misma configuración física
    pero diferente batería pueden compararse mediante
    Pareto.
    """

    return (
        state.zone,
        state.payload,
        state.doors,
        state.panels,
        state.stations,
        state.ground_keys,
        state.ground_tools,
        state.ground_materials,
    )


# ============================================================
# GOAL TEST
# ============================================================


def goal_test(
    scenario: dict[str, Any],
    state: State,
) -> bool:
    """Comprueba si todas las estaciones objetivo están ONLINE."""

    stations = dict(
        state.stations
    )

    for station_id in scenario["goal"][
        "stations_online"
    ]:

        if stations.get(
            station_id
        ) != "ONLINE":

            return False

    return True


# ============================================================
# USEFUL ITEMS
# ============================================================


def required_items(
    scenario: dict[str, Any],
    state: State,
) -> set[str]:
    """
    Objetos que todavía pueden contribuir a la solución.

    Se utilizan para evitar PICKUP/DROP inútiles.
    """

    needed: set[str] = set()

    doors = dict(state.doors)
    panels = dict(state.panels)

    # ========================================================
    # LLAVES DE PUERTAS TODAVÍA CERRADAS
    # ========================================================

    for door in scenario["doors"]:

        if doors.get(door["id"]) == "CLOSED":

            needed.add(
                door["key"]
            )

    # ========================================================
    # HERRAMIENTAS Y MATERIALES DE PANELES DAÑADOS
    # ========================================================

    for panel in scenario["panels"]:

        if panels.get(panel["id"]) != "DAMAGED":
            continue

        needed.add(
            panel["requires"]["tool"]
        )

        needed.add(
            panel["requires"]["material"]
        )

    return needed
# ==============================================
# APPLICABLE ACTIONS
# ============================================================


def applicable_actions(
    scenario: dict[str, Any],
    state: State,
) -> list[dict[str, Any]]:
    """
    Genera exclusivamente acciones legales.

    No modifica el estado.
    """

    actions: list[
        dict[str, Any]
    ] = []

    costs = scenario.get(
        "action_costs",
        {},
    )

    pickup_cost = int(
        costs.get("pickup", 1)
    )

    drop_cost = int(
        costs.get("drop", 1)
    )

    interact_cost = int(
        costs.get("interact", 2)
    )

    recharge_cost = int(
        costs.get("recharge", 3)
    )

    battery_max = int(
        scenario["robot"]["battery_max"]
    )

    capacity = int(
        scenario["robot"]["cargo_capacity"]
    )

    current_weight = payload_weight(
        state
    )

    # ========================================================
    # MOVE
    # ========================================================

    for corridor in scenario["corridors"]:

        if corridor["from"] != state.zone:
            continue

        cost = int(
            corridor["cost"]
        )

        if state.battery < cost:
            continue

        door_id = corridor.get(
            "door"
        )

        if door_id is not None:

            doors = dict(
                state.doors
            )

            if doors.get(
                door_id
            ) != "OPEN":

                continue

        actions.append(
            {
                "op": "MOVE",
                "from": state.zone,
                "to": corridor["to"],
                "cost": cost,
            }
        )

    # ========================================================
    # PICKUP
    # ========================================================

    if current_weight < capacity:

        needed = required_items(
            scenario,
            state,
        )

        already_have = payload_ids(
            state
        )

        # ----------------------------------------------------
        # KEYS
        # ----------------------------------------------------

        for item_id, zone in state.ground_keys:

            if zone != state.zone:
                continue

            if item_id not in needed:
                continue

            if item_id in already_have:
                continue

            actions.append(
                {
                    "op": "PICKUP",
                    "item": item_id,
                    "cost": pickup_cost,
                }
            )

        # ----------------------------------------------------
        # TOOLS
        # ----------------------------------------------------

        for item_id, zone in state.ground_tools:

            if zone != state.zone:
                continue

            if item_id not in needed:
                continue

            if item_id in already_have:
                continue

            actions.append(
                {
                    "op": "PICKUP",
                    "item": item_id,
                    "cost": pickup_cost,
                }
            )

        # ----------------------------------------------------
        # MATERIALS
        # ----------------------------------------------------

        for (
            material_type,
            amount,
            zone,
        ) in state.ground_materials:

            if zone != state.zone:
                continue

            if amount <= 0:
                continue

            if material_type not in needed:
                continue

            # Ya tenemos uno de este material.
            # Recoger otro no aporta nada porque cada
            # material se utiliza como requisito de un panel.
            if material_type in already_have:
                continue

            actions.append(
                {
                    "op": "PICKUP",
                    "item": material_type,
                    "cost": pickup_cost,
                }
            )

    # ========================================================
    # DROP
    # ========================================================

    # Solo consideramos DROP cuando realmente necesitamos
    # espacio.
    #
    # Además, nunca soltamos un objeto que actualmente
    # sabemos que puede ser necesario.

    if current_weight >= capacity:

        needed = required_items(
            scenario,
            state,
        )

        for (
            kind,
            item_id,
            weight,
        ) in state.payload:

            if item_id in needed:
                continue

            actions.append(
                {
                    "op": "DROP",
                    "item": item_id,
                    "cost": drop_cost,
                }
            )

    # ========================================================
    # OPEN DOORS
    # ========================================================

    doors = dict(
        state.doors
    )

    for door in scenario["doors"]:

        door_id = door["id"]

        if state.zone not in door["between"]:
            continue

        if doors.get(
            door_id
        ) != "CLOSED":

            continue

        key_id = door["key"]

        if not has_item(
            state,
            key_id,
        ):
            continue

        actions.append(
            {
                "op": "INTERACT",
                "target": door_id,
                "action": "OPEN_DOOR",
                "cost": interact_cost,
            }
        )

    # ========================================================
    # REPAIR
    # ========================================================

    panels = dict(
        state.panels
    )

    for panel in scenario["panels"]:

        panel_id = panel["id"]

        if panel["zone"] != state.zone:
            continue

        if panels.get(
            panel_id
        ) != "DAMAGED":

            continue

        tool_id = panel[
            "requires"
        ]["tool"]

        material_id = panel[
            "requires"
        ]["material"]

        if not has_item(
            state,
            tool_id,
        ):
            continue

        if not has_item(
            state,
            material_id,
        ):
            continue

        actions.append(
            {
                "op": "INTERACT",
                "target": panel_id,
                "action": "REPAIR",
                "consumes": material_id,
                "cost": interact_cost,
            }
        )

    # ========================================================
    # ACTIVATE
    # ========================================================

    stations = dict(
        state.stations
    )

    for station in scenario["stations"]:

        station_id = station["id"]

        if station["zone"] != state.zone:
            continue

        if stations.get(
            station_id
        ) != "OFFLINE":

            continue

        requirements = station.get(
            "requires",
            {},
        )

        # ----------------------------------------------------
        # Panels
        # ----------------------------------------------------

        valid = True

        for panel_id in requirements.get(
            "panels_ok",
            [],
        ):

            if panels.get(
                panel_id
            ) != "OK":

                valid = False
                break

        if not valid:
            continue

        # ----------------------------------------------------
        # Stations
        # ----------------------------------------------------

        for required_station in requirements.get(
            "stations_online",
            [],
        ):

            if stations.get(
                required_station
            ) != "ONLINE":

                valid = False
                break

        if not valid:
            continue

        actions.append(
            {
                "op": "INTERACT",
                "target": station_id,
                "action": "ACTIVATE",
                "cost": interact_cost,
            }
        )

    # ========================================================
    # RECHARGE
    # ========================================================

    if state.battery < battery_max:

        for charger in scenario.get(
            "chargers",
            [],
        ):

            if charger["zone"] != state.zone:
                continue

            actions.append(
                {
                    "op": "INTERACT",
                    "target": charger["id"],
                    "action": "RECHARGE",
                    "cost": recharge_cost,
                }
            )

            # Solo necesitamos una acción de recarga
            # por zona.
            break

    return actions


# ============================================================
# RESULT
# ============================================================


def result(
    scenario: dict[str, Any],
    state: State,
    action: dict[str, Any],
) -> State:
    """
    Aplica una acción y devuelve un nuevo estado.

    El estado original NO se modifica.
    """

    zone = state.zone
    battery = state.battery

    payload = list(
        state.payload
    )

    doors = dict(
        state.doors
    )

    panels = dict(
        state.panels
    )

    stations = dict(
        state.stations
    )

    ground_keys = dict(
        state.ground_keys
    )

    ground_tools = dict(
        state.ground_tools
    )

    ground_materials = {
        material_type: {
            "count": count,
            "zone": zone,
        }
        for (
            material_type,
            count,
            zone,
        ) in state.ground_materials
    }

    op = action["op"]
    cost = int(
        action["cost"]
    )

    # ========================================================
    # MOVE
    # ========================================================

    if op == "MOVE":

        if battery < cost:
            raise ValueError(
                "Insufficient battery"
            )

        if action["from"] != zone:
            raise ValueError(
                "Invalid origin zone"
            )

        zone = action["to"]

        battery -= cost

    # ========================================================
    # PICKUP
    # ========================================================

    elif op == "PICKUP":

        if battery < cost:
            raise ValueError(
                "Insufficient battery"
            )

        item = action["item"]

        # ----------------------------------------------------
        # KEY
        # ----------------------------------------------------

        if item in ground_keys:

            if ground_keys[item] != zone:
                raise ValueError(
                    f"{item} not in current zone"
                )

            key_data = next(
                k
                for k in scenario["keys"]
                if k["id"] == item
            )

            payload.append(
                (
                    "key",
                    item,
                    int(
                        key_data["weight"]
                    ),
                )
            )

            del ground_keys[item]

        # ----------------------------------------------------
        # TOOL
        # ----------------------------------------------------

        elif item in ground_tools:

            if ground_tools[item] != zone:
                raise ValueError(
                    f"{item} not in current zone"
                )

            tool_data = next(
                t
                for t in scenario["tools"]
                if t["id"] == item
            )

            payload.append(
                (
                    "tool",
                    item,
                    int(
                        tool_data["weight"]
                    ),
                )
            )

            del ground_tools[item]

        # ----------------------------------------------------
        # MATERIAL
        # ----------------------------------------------------

        elif item in ground_materials:

            material = ground_materials[
                item
            ]

            if material["zone"] != zone:
                raise ValueError(
                    f"{item} not in current zone"
                )

            if material["count"] <= 0:
                raise ValueError(
                    f"No {item} remaining"
                )

            payload.append(
                (
                    "material",
                    item,
                    1,
                )
            )

            material["count"] -= 1

            if material["count"] <= 0:
                del ground_materials[item]

        else:

            raise ValueError(
                f"Unknown ground item: {item}"
            )

        battery -= cost

    # ========================================================
    # DROP
    # ========================================================

    elif op == "DROP":

        if battery < cost:
            raise ValueError(
                "Insufficient battery"
            )

        item = action["item"]

        index = None

        for i, obj in enumerate(
            payload
        ):

            if obj[1] == item:
                index = i
                break

        if index is None:
            raise ValueError(
                f"{item} not in payload"
            )

        dropped = payload.pop(
            index
        )

        kind = dropped[0]
        item_id = dropped[1]

        if kind == "key":

            ground_keys[item_id] = zone

        elif kind == "tool":

            ground_tools[item_id] = zone

        elif kind == "material":

            if item_id in ground_materials:

                material = ground_materials[
                    item_id
                ]

                if material["zone"] == zone:

                    material["count"] += 1

                else:

                    ground_materials[item_id] = {
                        "count": 1,
                        "zone": zone,
                    }

            else:

                ground_materials[item_id] = {
                    "count": 1,
                    "zone": zone,
                }

        else:

            raise ValueError(
                f"Unknown payload type: {kind}"
            )

        battery -= cost

    # ========================================================
    # INTERACT
    # ========================================================

    elif op == "INTERACT":

        action_type = action[
            "action"
        ]

        target = action[
            "target"
        ]

        if battery < cost:
            raise ValueError(
                "Insufficient battery"
            )

        # ----------------------------------------------------
        # OPEN DOOR
        # ----------------------------------------------------

        if action_type == "OPEN_DOOR":

            door = next(
                d
                for d in scenario["doors"]
                if d["id"] == target
            )

            if zone not in door["between"]:
                raise ValueError(
                    f"Not next to {target}"
                )

            if doors[target] != "CLOSED":
                raise ValueError(
                    f"{target} already open"
                )

            if not has_item(
                state,
                door["key"],
            ):
                raise ValueError(
                    f"Missing key {door['key']}"
                )

            doors[target] = "OPEN"

            battery -= cost

        # ----------------------------------------------------
        # REPAIR
        # ----------------------------------------------------

        elif action_type == "REPAIR":

            panel = next(
                p
                for p in scenario["panels"]
                if p["id"] == target
            )

            if panel["zone"] != zone:
                raise ValueError(
                    f"Not at {target}"
                )

            if panels[target] != "DAMAGED":
                raise ValueError(
                    f"{target} already repaired"
                )

            tool_id = panel[
                "requires"
            ]["tool"]

            material_id = panel[
                "requires"
            ]["material"]

            if not has_item(
                state,
                tool_id,
            ):
                raise ValueError(
                    f"Missing tool {tool_id}"
                )

            material_index = None

            for i, obj in enumerate(
                payload
            ):

                if (
                    obj[0] == "material"
                    and obj[1]
                    == material_id
                ):

                    material_index = i
                    break

            if material_index is None:
                raise ValueError(
                    f"Missing material {material_id}"
                )

            payload.pop(
                material_index
            )

            panels[target] = "OK"

            battery -= cost

        # ----------------------------------------------------
        # ACTIVATE
        # ----------------------------------------------------

        elif action_type == "ACTIVATE":

            station = next(
                s
                for s in scenario["stations"]
                if s["id"] == target
            )

            if station["zone"] != zone:
                raise ValueError(
                    f"Not at {target}"
                )

            if stations[target] != "OFFLINE":
                raise ValueError(
                    f"{target} already online"
                )

            requirements = station.get(
                "requires",
                {},
            )

            for panel_id in requirements.get(
                "panels_ok",
                [],
            ):

                if panels.get(
                    panel_id
                ) != "OK":

                    raise ValueError(
                        f"{panel_id} not repaired"
                    )

            for station_id in requirements.get(
                "stations_online",
                [],
            ):

                if stations.get(
                    station_id
                ) != "ONLINE":

                    raise ValueError(
                        f"{station_id} not online"
                    )

            stations[target] = "ONLINE"

            battery -= cost

        # ----------------------------------------------------
        # RECHARGE
        # ----------------------------------------------------

        elif action_type == "RECHARGE":

            charger = next(
                c
                for c in scenario.get(
                    "chargers",
                    [],
                )
                if c["id"] == target
            )

            if charger["zone"] != zone:
                raise ValueError(
                    f"Not at charger"
                )

            battery -= cost

            battery = int(
                scenario["robot"]["battery_max"]
            )

        else:

            raise ValueError(
                f"Unknown interaction: {action_type}"
            )

    else:

        raise ValueError(
            f"Unknown operation: {op}"
        )

    # ========================================================
    # NUEVO STATE
    # ========================================================

    return State(
        zone=zone,
        battery=battery,
        payload=tuple(
            sorted(payload)
        ),
        doors=tuple(
            sorted(
                doors.items()
            )
        ),
        panels=tuple(
            sorted(
                panels.items()
            )
        ),
        stations=tuple(
            sorted(
                stations.items()
            )
        ),
        ground_keys=tuple(
            sorted(
                ground_keys.items()
            )
        ),
        ground_tools=tuple(
            sorted(
                ground_tools.items()
            )
        ),
        ground_materials=tuple(
            sorted(
                (
                    material_type,
                    data["count"],
                    data["zone"],
                )
                for (
                    material_type,
                    data
                ) in ground_materials.items()
            )
        ),
    )


# ============================================================
# PLAN RECONSTRUCTION
# ============================================================


def reconstruct_plan(
    node: Node,
) -> list[dict[str, Any]]:
    """Reconstruye la secuencia de acciones."""

    actions: list[
        dict[str, Any]
    ] = []

    current = node

    while current.parent is not None:

        if current.action is not None:

            actions.append(
                current.action
            )

        current = current.parent

    actions.reverse()

    return actions


# ============================================================
# UCS
# ============================================================


def solve_ucs(
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """
    Uniform Cost Search.

    La prioridad principal es el costo acumulado g.
    Para una misma configuración física se usa dominancia Pareto:
    un estado con menor/igual costo y mayor/igual batería domina al otro.
    """

    initial = initial_state(scenario)

    root = Node(
        state=initial,
        parent=None,
        action=None,
        g=0,
    )

    frontier: list[tuple[int, int, Node]] = []
    counter = count()

    heappush(
        frontier,
        (0, next(counter), root),
    )

    pareto: dict[
        tuple[Any, ...],
        list[tuple[int, int]],
    ] = {
        state_key(initial): [
            (0, initial.battery)
        ]
    }

    expanded = 0
    generated = 1

    while frontier:

        g, _, node = heappop(frontier)
        state = node.state
        key = state_key(state)

        # El nodo puede haber quedado dominado mientras
        # esperaba en la frontera.
        points = pareto.get(key, [])

        valid = any(
            saved_cost == g
            and saved_battery == state.battery
            for saved_cost, saved_battery in points
        )

        if not valid:
            continue

        # ----------------------------------------------------
        # META
        # ----------------------------------------------------

        if goal_test(scenario, state):
            steps = reconstruct_plan(node)

            print()
            print("======================================")
            print("SOLUCIÓN ENCONTRADA")
            print("======================================")
            print("COSTO:", g)
            print("PASOS:", len(steps))
            print("EXPANDED:", expanded)
            print("GENERATED:", generated)
            print()
            print("PLAN:")
            print("--------------------------------------")

            for i, step in enumerate(steps):
                print(f"{i + 1:02d}. {step}")

            print("--------------------------------------")
            print()

            return {
                "solution_found": True,
                "total_cost": g,
                "steps": steps,
                "message": "UCS solution",
                "expanded_nodes": expanded,
                "generated_nodes": generated,
            }

        expanded += 1

        # ----------------------------------------------------
        # ACCIONES
        # ----------------------------------------------------

        actions = applicable_actions(
            scenario,
            state,
        )

        # Esto solo desempata acciones dentro del mismo costo g.
        # UCS sigue priorizando siempre el menor costo acumulado.
        def action_priority(
            action: dict[str, Any],
        ) -> int:

            if action["op"] == "INTERACT":

                action_type = action.get("action")

                if action_type == "ACTIVATE":
                    return 0

                if action_type == "REPAIR":
                    return 1

                if action_type == "OPEN_DOOR":
                    return 2

                if action_type == "RECHARGE":
                    return 5

            if action["op"] == "PICKUP":
                return 3

            if action["op"] == "MOVE":
                return 4

            if action["op"] == "DROP":
                return 6

            return 10

        actions.sort(
            key=action_priority
        )

        # ----------------------------------------------------
        # GENERAR HIJOS
        # ----------------------------------------------------

        for action in actions:

            action_cost = int(
                action["cost"]
            )

            try:
                child_state = result(
                    scenario,
                    state,
                    action,
                )
            except Exception:
                continue

            child_g = g + action_cost
            child_key = state_key(child_state)
            child_battery = child_state.battery

            # ------------------------------------------------
            # DOMINANCIA
            # ------------------------------------------------

            existing = pareto.setdefault(
                child_key,
                [],
            )

            dominated = any(
                old_cost <= child_g
                and old_battery >= child_battery
                for old_cost, old_battery in existing
            )

            if dominated:
                continue

            # Eliminar puntos que ahora son dominados.
            existing[:] = [
                (old_cost, old_battery)
                for old_cost, old_battery in existing
                if not (
                    child_g <= old_cost
                    and child_battery >= old_battery
                )
            ]

            existing.append(
                (child_g, child_battery)
            )

            child = Node(
                state=child_state,
                parent=node,
                action=action,
                g=child_g,
            )

            heappush(
                frontier,
                (
                    child_g,
                    next(counter),
                    child,
                ),
            )

            generated += 1





    return {
        "solution_found": False,
        "total_cost": None,
        "steps": [],
        "message": "No solution found",
        "expanded_nodes": expanded,
        "generated_nodes": generated,
    }


# ============================================================
# LOCAL TEST
# ============================================================


if __name__ == "__main__":

    import json
    from pathlib import Path

    scenario_path = (
        Path(__file__).resolve()
        .parents[2]
        / "scenarios"
        / "scenario.json"
    )

    with scenario_path.open(
        encoding="utf-8"
    ) as f:

        scenario = json.load(f)

    print(
        "======================================"
    )

    print(
        "Emergency Control — UCS"
    )

    print(
        "======================================"
    )

    solution = solve_ucs(
        scenario
    )

    print(
        "FOUND:",
        solution["solution_found"],
    )

    print(
        "MESSAGE:",
        solution["message"],
    )

    print(
        "COST:",
        solution["total_cost"],
    )

    print(
        "STEPS:",
        len(
            solution["steps"]
        ),
    )

    print(
        "EXPANDED:",
        solution["expanded_nodes"],
    )

    print(
        "GENERATED:",
        solution["generated_nodes"],
    )