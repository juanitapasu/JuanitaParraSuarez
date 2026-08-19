from simulator import load_scenario
from solver import initial_state, applicable_actions, result, goal_test


scenario = load_scenario()
state = initial_state(scenario)


def apply(op, value):
    global state

    for action in applicable_actions(scenario, state):
        if op == "PICKUP" and action["op"] == "PICKUP":
            if action["item"] == value:
                state = result(scenario, state, action)
                print("OK:", action)
                return

        if op == "MOVE" and action["op"] == "MOVE":
            if action["to"] == value:
                state = result(scenario, state, action)
                print("OK:", action)
                return

        if op == "INTERACT" and action["op"] == "INTERACT":
            if action["target"] == value:
                state = result(scenario, state, action)
                print("OK:", action)
                return

    raise RuntimeError(
        f"No se encontró acción {op} {value} "
        f"desde {state.zone}"
    )


print("=== INICIO ===")
print(state.zone, state.battery, state.payload)


# Z1
apply("PICKUP", "KEY1")
apply("INTERACT", "DOOR1")
apply("MOVE", "Z2")


# En Z2 llevamos KEY1.
# Recogemos KEY2 y FUSE.
apply("PICKUP", "KEY2")
apply("PICKUP", "FUSE")


# Liberamos KEY1 para tener espacio.
# Esta parte la haremos manualmente después
# de comprobar DROP.


print("\n=== ESTADO ACTUAL ===")
print("Zona:", state.zone)
print("Batería:", state.battery)
print("Payload:", state.payload)
print("Puertas:", dict(state.doors))