"""El planificador: Nodo de búsqueda, Uniform Cost Search y construcción del plan.

Consume el modelo de búsqueda de simulator.py (State, ScenarioIndex,
get_successors) y produce un plan óptimo ya traducido al contrato
(CONTRATO.md). Aquí vive todo lo que es "historial de búsqueda" (g, padre,
acción) y NO el estado físico — ver design.md, "Nodo vs. Estado".

Ejecutar directo:  python demo_plan.py   (imprime el plan para scenario.json)
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from simulator import ActionRecord, ScenarioIndex, State, get_successors, load_scenario, simulate


@dataclass
class Node:
    """Nodo de búsqueda: contabilidad de UCS. NO es el estado físico."""

    state: State
    parent: Optional["Node"]
    action: Optional[ActionRecord]
    g: int
    depth: int = field(default=0)

    def path(self) -> List[ActionRecord]:
        actions: List[ActionRecord] = []
        node: Optional[Node] = self
        while node is not None and node.action is not None:
            actions.append(node.action)
            node = node.parent
        actions.reverse()
        return actions


@dataclass
class SearchResult:
    success: bool
    plan: List[ActionRecord]
    cost: int
    expanded: int
    reason: Optional[str] = None


def _dominates(g1: int, b1: int, g2: int, b2: int) -> bool:
    """design.md "Batería como recurso": (g1,B1) domina a (g2,B2) sii g1<=g2 y B1>=B2."""
    return g1 <= g2 and b1 >= b2


def uniform_cost_search(idx: ScenarioIndex) -> SearchResult:
    """UCS sobre Graph-Search con control de dominancia por batería en CLOSED."""
    start = idx.initial_state()
    counter = itertools.count()
    root = Node(state=start, parent=None, action=None, g=0, depth=0)

    frontier: List[Tuple[int, int, Node]] = [(0, next(counter), root)]
    # CLOSED: firma lógica <P,C,E,M> -> lista de puntos Pareto (g, battery) ya resueltos
    closed: Dict[Tuple, List[Tuple[int, int]]] = {}
    expanded = 0

    def is_dominated(sig: Tuple, g: int, battery: int) -> bool:
        return any(_dominates(g2, b2, g, battery) for g2, b2 in closed.get(sig, []))

    def register(sig: Tuple, g: int, battery: int) -> None:
        points = closed.setdefault(sig, [])
        points[:] = [(g2, b2) for g2, b2 in points if not _dominates(g, battery, g2, b2)]
        points.append((g, battery))

    while frontier:
        g, _, node = heapq.heappop(frontier)
        sig = node.state.signature()

        if is_dominated(sig, node.g, node.state.battery):
            continue  # llegó un camino mejor (o igual) antes: descartar sin perder optimalidad

        if idx.is_goal(node.state):
            return SearchResult(success=True, plan=node.path(), cost=node.g, expanded=expanded)

        register(sig, node.g, node.state.battery)
        expanded += 1

        for action, succ_state in get_successors(idx, node.state):
            new_g = node.g + action.cost
            succ_sig = succ_state.signature()
            if is_dominated(succ_sig, new_g, succ_state.battery):
                continue
            child = Node(state=succ_state, parent=node, action=action, g=new_g, depth=node.depth + 1)
            heapq.heappush(frontier, (new_g, next(counter), child))

    return SearchResult(success=False, plan=[], cost=0, expanded=expanded, reason="FAILURE: no existe plan que satisfaga Goal(s)")


def build_plan(scenario_path: Optional[str] = None, scenario_raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Función usada por main.py: carga el escenario, busca con UCS, valida
    el plan contra el simulador de referencia y arma la respuesta del contrato."""
    raw = scenario_raw if scenario_raw is not None else load_scenario(scenario_path)
    idx = ScenarioIndex(raw)
    result = uniform_cost_search(idx)

    if not result.success:
        return {"solution_found": False, "total_cost": 0, "steps": [], "message": result.reason}

    steps = [a.step for a in result.plan]

    # Red de seguridad: el plan que UCS cree óptimo debe ser legal según el
    # validador de referencia (mismas reglas que usará el banco de pruebas).
    try:
        final_state = simulate(raw, steps)
        assert final_state["battery"] >= 0
        assert all(
            final_state["stations"][sid] == "ONLINE" for sid in raw["goal"]["stations_online"]
        ), "goal no satisfecho tras simular el plan"
        message = f"Plan óptimo (UCS): {len(steps)} pasos, costo {result.cost}."
    except AssertionError as exc:  # pragma: no cover - señal de bug en get_successors
        return {
            "solution_found": False,
            "total_cost": 0,
            "steps": [],
            "message": f"El plan encontrado no pasó la verificación de legalidad: {exc}",
        }

    return {
        "solution_found": True,
        "total_cost": result.cost,
        "steps": steps,
        "message": message,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(build_plan(), indent=2, ensure_ascii=False))
