"""CLI para levantar un nodo de la red.

Ejemplo (Fase 1, sockets):
    python -m src.main --algo dijkstra --id A \
        --topo config/topo-example.txt --names config/names-example.txt

Ejemplo (Fase 2, XMPP: el `names` trae los JID de cada nodo):
    python -m src.main --algo dvr --id A --transport xmpp \
        --topo config/topo-example.txt --names config/names-xmpp.txt

Una vez arriba, se escriben mensajes en la consola con el formato
"<destino> <texto>" y el nodo los enruta segun su algoritmo.
"""
import argparse
import os
import sys
from getpass import getpass

from .algorithms.dijkstra import Dijkstra
from .algorithms.dvr import DVR
from .algorithms.flooding import Flooding
from .algorithms.lsr import LSR
from .config import load_names, load_topology
from .node import Node
from .transport.socket_transport import SocketTransport
from .transport.xmpp_transport import XMPPTransport

# Registro de algoritmos disponibles. Cada integrante agrega el suyo aqui.
ALGORITHMS = {
    "dijkstra": Dijkstra,
    "flooding": Flooding,
    "lsr": LSR,
    "dvr": DVR,
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


def build_jid_book(names):
    """Mapa {id: jid} para el transporte XMPP (las entradas con '@')."""
    return {nid: val for nid, val in (names or {}).items()
            if isinstance(val, str) and "@" in val}


def make_transport_factory(args, names, book):
    """Devuelve la fabrica de transporte segun el flag `--transport`.

    El nodo y los algoritmos no cambian entre Fase 1 y Fase 2: ambos
    transportes cumplen la misma interfaz `Transport`.
    """
    if args.transport == "socket":
        return lambda node_id, on_recv: SocketTransport(node_id, on_recv, book)

    jid_book = build_jid_book(names)
    if args.id not in jid_book:
        sys.exit(f"El nodo '{args.id}' no tiene JID en {args.names} "
                 f"(se espera algo como \"{args.id}\": \"usuario@servidor\").")
    password = args.password or os.environ.get("XMPP_PASSWORD")
    if not password:
        password = getpass(f"Password XMPP de {jid_book[args.id]}: ")
    return lambda node_id, on_recv: XMPPTransport(
        node_id, on_recv, jid_book, password,
        host=args.xmpp_host, port=args.xmpp_port, insecure=args.xmpp_insecure)


def main():
    parser = argparse.ArgumentParser(description="Nodo de la red - Lab 3 Redes")
    parser.add_argument("--algo", required=True, choices=sorted(ALGORITHMS),
                        help="algoritmo de enrutamiento")
    parser.add_argument("--id", required=True, help="ID de este nodo (p. ej. A)")
    parser.add_argument("--topo", required=True, help="archivo topo-*.txt")
    parser.add_argument("--names", help="archivo names-*.txt (direcciones)")
    parser.add_argument("--transport", choices=["socket", "xmpp"], default="socket",
                        help="medio de la red: sockets locales (Fase 1) o XMPP (Fase 2)")
    parser.add_argument("--password", help="password XMPP (si no, se usa "
                                           "XMPP_PASSWORD o se pregunta)")
    parser.add_argument("--xmpp-host", help="host del servidor XMPP si no se "
                                            "resuelve por DNS")
    parser.add_argument("--xmpp-port", type=int, default=5222, help="puerto XMPP")
    parser.add_argument("--xmpp-insecure", action="store_true",
                        help="no validar el certificado TLS del servidor")
    args = parser.parse_args()

    topology = load_topology(args.topo)
    names = load_names(args.names) if args.names else {}
    if args.id not in topology:
        sys.exit(f"El nodo '{args.id}' no aparece en la topologia.")

    all_ids = set(topology) | set(names)
    for nbrs in topology.values():
        all_ids.update(nbrs)
    book = build_address_book(all_ids, names)
    transport_factory = make_transport_factory(args, names, book)

    try:
        node = Node(args.id, topology, transport_factory, ALGORITHMS[args.algo])
        node.start()
    except RuntimeError as e:
        sys.exit(f"No se pudo levantar el transporte: {e}")

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
