"""Frame caption from visible equipment and structures. Not a schedule verdict."""

from __future__ import annotations

_GEAR_RU = {
    "excavator": ("экскаватор", "экскаватора", "экскаваторов"),
    "bulldozer": ("бульдозер", "бульдозера", "бульдозеров"),
    "loader": ("погрузчик", "погрузчика", "погрузчиков"),
    "dump_truck": ("самосвал", "самосвала", "самосвалов"),
    "truck": ("грузовик", "грузовика", "грузовиков"),
    "concrete_mixer": ("бетоносмеситель", "бетоносмесителя", "бетоносмесителей"),
    "concrete_pump": ("бетононасос", "бетононасоса", "бетононасосов"),
    "mobile_crane": ("автокран", "автокрана", "автокранов"),
    "tower_crane": ("башенный кран", "башенных крана", "башенных кранов"),
    "road_roller": ("каток", "катка", "катков"),
}

_EARTH = {"excavator", "bulldozer", "loader", "dump_truck"}
_LIFT = {"tower_crane", "mobile_crane"}
_CONCRETE = {"concrete_mixer", "concrete_pump"}


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    n_abs = abs(n) % 100
    tail = n_abs % 10
    if 11 <= n_abs <= 14:
        word = forms[2]
    elif tail == 1:
        word = forms[0]
    elif 2 <= tail <= 4:
        word = forms[1]
    else:
        word = forms[2]
    return f"{n} {word}"


def describe_visible_work(
    *,
    equipment: dict[str, int],
    structures_present: set[str],
) -> str:
    """What is on the frame and which work the visible signs suggest.

    Wording stays observational: признаки, видно. No claim that a stage is finished
    or that construction has stopped.
    """
    present = {key: count for key, count in equipment.items() if count > 0}
    gear_bits = [
        _plural(present[key], _GEAR_RU[key])
        for key in _GEAR_RU
        if key in present
    ]
    if gear_bits:
        seen = "На кадре видно: " + ", ".join(gear_bits) + "."
    else:
        seen = "Строительной техники на кадре не отмечено."

    works: list[str] = []
    if present.keys() & _EARTH:
        works.append("признаки земляных работ и перемещения грунта")
    if present.keys() & _CONCRETE:
        works.append("признаки бетонных работ")
    if "tower_crane" in present:
        works.append("признаки монтажных работ башенным краном")
    elif present.keys() & _LIFT:
        works.append("признаки подъёмных работ")

    envelope = {"facade", "roof", "window_opening", "window"} & structures_present
    frame = {"column", "beam", "floor_slab", "slab"} & structures_present
    busy = bool(present.keys() & (_EARTH | _LIFT | _CONCRETE))
    if envelope and not busy:
        works.append("виден корпус с фасадом или кровлей, признаки отделочных работ")
    elif frame and "tower_crane" in present:
        works.append("видны элементы каркаса")
    elif {"foundation", "formwork"} & structures_present and "tower_crane" not in present:
        works.append("видны признаки фундаментных работ")

    if not works:
        return seen
    return seen + " По видимым признакам: " + "; ".join(works) + "."
