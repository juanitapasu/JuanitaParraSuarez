from simulator import load_scenario
from solver import initial_state, state_key, goal_test


scenario = load_scenario()

state = initial_state(scenario)

print("\n=== ESTADO INICIAL ===")
print("Zona:", state.zone)
print("Batería:", state.battery)
print("Payload:", state.payload)

print("\n=== ENTORNO ===")
print("Doors:", state.doors)
print("Panels:", state.panels)
print("Stations:", state.stations)

print("\n=== SUELO ===")
print("Keys:", state.ground_keys)
print("Tools:", state.ground_tools)
print("Materials:", state.ground_materials)

print("\n=== STATE KEY ===")
print(state_key(state))

print("\n=== GOAL ===")
print(goal_test(scenario, state))