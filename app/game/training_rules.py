from dataclasses import dataclass

@dataclass
class TroopDef:
    name: str
    food: int
    wood: int
    stone: int
    iron: int
    seconds: int

TRAINABLE = {
    "t1_inf": TroopDef(
        name="Warrior",
        food=50,
        wood=20,
        stone=0,
        iron=0,
        seconds=5,
    ),
    "t1_archer": TroopDef(
        name="Archer",
        food=40,
        wood=40,
        stone=0,
        iron=0,
        seconds=6,
    ),
}
