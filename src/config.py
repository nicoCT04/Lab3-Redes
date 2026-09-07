"""Lectura de los archivos de configuracion `topo-*.txt` y `names-*.txt`.

IMPORTANTE (regla del laboratorio): estos archivos solo pueden usarse para
configurar el propio nodo y descubrir sus vecinos. No se debe usar la topologia
completa para resolver rutas de forma estatica (salvo Dijkstra puro). Por eso
`neighbors_of()` entrega unicamente la lista de vecinos del nodo indicado.
"""
import json


def _load_json_tolerant(path: str) -> dict:
    """Carga JSON. Tolera ejemplos escritos con comillas simples."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.replace("'", '"'))


def load_topology(path: str) -> dict:
    """Devuelve el mapa {nodo: [vecinos]} del archivo de topologia."""
    data = _load_json_tolerant(path)
    if data.get("type") != "topo":
        raise ValueError(f"{path}: no es un archivo de topologia (type != 'topo')")
    return data.get("config", {})


def load_names(path: str) -> dict:
    """Devuelve el mapa {nodo: direccion/jid} del archivo de nombres."""
    data = _load_json_tolerant(path)
    if data.get("type") != "names":
        raise ValueError(f"{path}: no es un archivo de nombres (type != 'names')")
    return data.get("config", {})


def neighbors_of(topology: dict, node_id: str) -> list:
    """Vecinos directos de `node_id` (unico uso permitido de la topologia)."""
    return list(topology.get(node_id, []))
