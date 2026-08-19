"""Suite de validación del agente (5 casos obligatorios + verificaciones adicionales).

Ejecutar desde backend/:  python -m pytest tests/test_demo_plan.py -v
                     o:    python tests/test_demo_plan.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simulator import ScenarioIndex, State, get_successors, simulate
from demo_plan import uniform_cost_search


def _base_scenario_dict(**overrides):
    scenario = {
        "meta": {"description": "test scenario"},
        "zones": ["A", "B", "C", "D"],
        "robot": {"start": "A", "battery_start": 50, "battery_max": 50, "cargo_capacity": 2},
        "action_costs": {"pickup": 1, "drop": 1, "interact": 2, "recharge": 3},
        "corridors": [
            {"from": "A", "to": "D", "cost": 20},
            {"from": "A", "to": "B", "cost": 4},
            {"from": "B", "to": "D", "cost": 4},
        ],
        "doors": [],
        "keys": [],
        "tools": [],
        "materials": [],
        "panels": [],
        "stations": [
            {"id": "STATION1", "zone": "D", "state": "OFFLINE", "requires": {"panels_ok": [], "stations_online": []}}
        ],
        "chargers": [],
        "goal": {"stations_online": ["STATION1"]},
    }
    scenario.update(overrides)
    return scenario


class TestEstadosEquivalentes(unittest.TestCase):
    """Caso 1: dos configuraciones físicamente iguales -> mismo hash/eq, aunque
    la historia (orden de construcción, batería) sea distinta."""

    def test_mismo_hash_y_eq_pese_a_distinta_bateria_y_orden(self):
        s1 = State(
            zone="STORAGE",
            battery=17,
            payload_keys=("KEY_A",),
            payload_tools=("WRENCH",),
            payload_materials=(("FUSE", 1),),
            doors=(("DOOR1", "OPEN"),),
            panels=(),
            stations=(),
            ground_keys=(),
            ground_tools=(),
            ground_materials=(),
        )
        s2 = State(
            zone="STORAGE",
            battery=3,  # distinta batería, distinta "historia"
            payload_keys=("KEY_A",),
            payload_tools=("WRENCH",),
            payload_materials=(("FUSE", 1),),
            doors=(("DOOR1", "OPEN"),),
            panels=(),
            stations=(),
            ground_keys=(),
            ground_tools=(),
            ground_materials=(),
        )
        self.assertEqual(s1, s2)
        self.assertEqual(hash(s1), hash(s2))


class TestInformacionRelevante(unittest.TestCase):
    """Caso 2: diferir en E (puertas/paneles/estaciones) o en C/M debe producir
    estados distintos, porque cambia qué acciones son legales a futuro."""

    def test_distinta_puerta_produce_distinto_hash(self):
        base = dict(
            zone="Z", battery=10, payload_keys=(), payload_tools=(), payload_materials=(),
            panels=(), stations=(), ground_keys=(), ground_tools=(), ground_materials=(),
        )
        s1 = State(doors=(("DOOR1", "CLOSED"),), **base)
        s2 = State(doors=(("DOOR1", "OPEN"),), **base)
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(hash(s1), hash(s2))

    def test_distinto_payload_produce_distinto_hash(self):
        base = dict(
            zone="Z", battery=10, payload_tools=(), payload_materials=(),
            doors=(), panels=(), stations=(), ground_keys=(), ground_tools=(), ground_materials=(),
        )
        s1 = State(payload_keys=("KEY_A",), **base)
        s2 = State(payload_keys=(), **base)
        self.assertNotEqual(s1, s2)


class TestCostosDiferentes(unittest.TestCase):
    """Caso 3: la ruta con MÁS pasos pero MENOR costo debe ser la elegida por
    UCS, no la de menos acciones (A->D directo cuesta 20; A->B->D cuesta 4+4=8;
    +2 de ACTIVATE en ambos casos)."""

    def test_ucs_prefiere_mas_pasos_menor_costo(self):
        idx = ScenarioIndex(_base_scenario_dict())
        result = uniform_cost_search(idx)
        self.assertTrue(result.success)
        moves = [a.step for a in result.plan if a.kind == "MOVE"]
        self.assertEqual([m["to"] for m in moves], ["B", "D"])
        self.assertEqual(result.cost, 4 + 4 + 2)  # dos MOVE + ACTIVATE


class TestSinSolucion(unittest.TestCase):
    """Caso 4: si la misión es físicamente imposible, el agente debe terminar
    y retornar sin éxito, no colgarse explorando indefinidamente."""

    def test_sin_bateria_suficiente_retorna_failure(self):
        idx = ScenarioIndex(_base_scenario_dict(robot={"start": "A", "battery_start": 2, "battery_max": 2, "cargo_capacity": 2}))
        result = uniform_cost_search(idx)
        self.assertFalse(result.success)
        self.assertEqual(result.plan, [])
        self.assertIsNotNone(result.reason)

    def test_meta_inalcanzable_por_dependencia_faltante_retorna_failure(self):
        scenario_dict = _base_scenario_dict(
            stations=[
                {
                    "id": "STATION1",
                    "zone": "D",
                    "state": "OFFLINE",
                    "requires": {"panels_ok": ["PANEL_GHOST"], "stations_online": []},
                }
            ]
        )  # PANEL_GHOST no existe en "panels": nunca puede quedar "OK"
        idx = ScenarioIndex(scenario_dict)
        result = uniform_cost_search(idx)
        self.assertFalse(result.success)


class TestRutasAlternativas(unittest.TestCase):
    """Caso 5: dos caminos distintos alcanzan el mismo mundo; UCS debe manejar
    el grafo (no árbol) sin ciclos infinitos y quedarse con el óptimo."""

    def test_rutas_de_igual_costo_ambas_optimas(self):
        scenario_dict = _base_scenario_dict(
            corridors=[
                {"from": "A", "to": "B", "cost": 5},
                {"from": "A", "to": "C", "cost": 5},
                {"from": "B", "to": "D", "cost": 5},
                {"from": "C", "to": "D", "cost": 5},
            ]
        )
        idx = ScenarioIndex(scenario_dict)
        result = uniform_cost_search(idx)
        self.assertTrue(result.success)
        self.assertEqual(result.cost, 5 + 5 + 2)  # sin importar cuál rama simétrica se tome

    def test_graph_search_no_diverge_con_ciclos(self):
        """A<->B<->C<->D con ida y vuelta posibles: debe terminar rápido gracias
        al control de dominancia en CLOSED, no reexplorar infinitamente."""
        scenario_dict = _base_scenario_dict(
            corridors=[
                {"from": "A", "to": "B", "cost": 3},
                {"from": "B", "to": "A", "cost": 3},
                {"from": "B", "to": "C", "cost": 3},
                {"from": "C", "to": "B", "cost": 3},
                {"from": "C", "to": "D", "cost": 3},
                {"from": "D", "to": "C", "cost": 3},
            ]
        )
        idx = ScenarioIndex(scenario_dict)
        result = uniform_cost_search(idx)
        self.assertTrue(result.success)
        self.assertLess(result.expanded, 200)  # cota generosa: si divergiera, sería enorme


class TestPodaDropPickup(unittest.TestCase):
    """Verificación adicional: la poda de DROP/PICKUP no genera ramas para
    ítems irrelevantes ni DROP fuera de la condición de capacidad llena."""

    def test_pickup_irrelevante_no_se_genera(self):
        # Una llave cuya puerta ya está abierta no es relevante.
        scenario_dict = _base_scenario_dict(
            doors=[{"id": "DOOR1", "state": "OPEN", "between": ["A", "B"], "key": "KEY1"}],
            keys=[{"id": "KEY1", "zone": "A", "color": "cyan", "weight": 1}],
        )
        idx = ScenarioIndex(scenario_dict)
        state = idx.initial_state()
        successors = get_successors(idx, state)
        pickups = [a for a, _ in successors if a.kind == "PICKUP"]
        self.assertEqual(pickups, [])

    def test_drop_no_se_genera_si_hay_espacio_libre(self):
        scenario_dict = _base_scenario_dict(
            doors=[{"id": "DOOR1", "state": "CLOSED", "between": ["A", "B"], "key": "KEY1"}],
            keys=[{"id": "KEY1", "zone": "A", "color": "cyan", "weight": 1}],
        )
        idx = ScenarioIndex(scenario_dict)
        state = idx.initial_state()
        pickup_state = [s for a, s in get_successors(idx, state) if a.kind == "PICKUP"][0]
        drops = [a for a, _ in get_successors(idx, pickup_state) if a.kind == "DROP"]
        self.assertEqual(drops, [])  # capacidad=2, cargo=1: no hace falta soltar nada


class TestPlanValidoContraSimulador(unittest.TestCase):
    """El plan que arma UCS debe pasar el validador de referencia (simulate)
    sin lanzar AssertionError, y dejar el mundo en un estado que satisface Goal."""

    def test_plan_del_escenario_base_es_legal(self):
        raw = _base_scenario_dict()
        idx = ScenarioIndex(raw)
        result = uniform_cost_search(idx)
        self.assertTrue(result.success)
        steps = [a.step for a in result.plan]
        final_state = simulate(raw, steps)
        self.assertEqual(final_state["stations"]["STATION1"], "ONLINE")


if __name__ == "__main__":
    unittest.main()
