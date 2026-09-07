"""CLI para levantar un nodo de la red.

Ejemplo:
    python -m src.main --algo dijkstra --id A \
        --topo config/topo-example.txt --names config/names-example.txt

Una vez arriba, se escriben mensajes en la consola con el formato
"<destino> <texto>" y el nodo los enruta segun su algoritmo.
"""
import argparse
import sys

from .algorithms.dijkstra import Dijkstra
from .algorithms.flooding import Flooding
from .algorithms.lsr import LSR
from .config import load_names, load_topology
from .node import Node
from .transport.socket_transport import SocketTransport

# Registro de algoritmos disponibles. Cada integrante agrega el suyo aqui.
ALGORITHMS = {
    "dijkstra": Dijkstra,
    "flooding": Flooding,
    "lsr": LSR,
    # "dvr": DVR,             # Integrante 4
}


def build_address_book(all_ids, names):
    """Mapa {id: (host, port)} para el transporte por sockets.

    Por defecto asigna puertos locales 5001, 5002, ... en orden alfabetico.
    Si el archivo `names` trae valores "host:port", esos tienen prioridad.
    """
    book = {}
    for i, nid in enumerate(sorted(all_ids), start=1):
        book[nid] = ("127.0.0.1", 5000 + i)
    for nid, val in (names or {}).items():
        if isinstance(val, str) and ":" in val and "@" not in val:
            host, _, port = val.rpartition(":")
            try:
                book[nid] = (host, int(port))
            except ValueError:
                pass
    return book


def main():
    parser = argparse.ArgumentParser(description="Nodo de la red - Lab 3 Redes")
    parser.add_argument("--algo", required=True, choices=sorted(ALGORITHMS),
                        help="algoritmo de enrutamiento")
    parser.add_argument("--id", required=True, help="ID de este nodo (p. ej. A)")
    parser.add_argument("--topo", required=True, help="archivo topo-*.txt")
    parser.add_argument("--names", help="archivo names-*.txt (direcciones)")
    args = parser.parse_args()

    topology = load_topology(args.topo)
    names = load_names(args.names) if args.names else {}
    if args.id not in topology:
        sys.exit(f"El nodo '{args.id}' no aparece en la topologia.")

    all_ids = set(topology) | set(names)
    for nbrs in topology.values():
        all_ids.update(nbrs)
    book = build_address_book(all_ids, names)

    def transport_factory(node_id, on_recv):
        return SocketTransport(node_id, on_recv, book)

    node = Node(args.id, topology, transport_factory, ALGORITHMS[args.algo])
    node.start()

    print("Escribe '<destino> <mensaje>' para enviar, o 'quit' para salir.")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            dst, _, text = line.partition(" ")
            if not text:
                print("Formato: <destino> <mensaje>")
                continue
            node.send_message(dst, text)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
