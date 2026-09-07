"""Algoritmo de enrutamiento Flooding.

Flooding no arma tabla de ruteo: cuando llega un mensaje que no es para este
nodo, se reenvia una copia a todos sus vecinos excepto al que se lo mando
(`last_hop`). Para no dar vueltas infinitas se descartan los mensajes ya vistos
(por su `mid`) y el motor descarta los paquetes con TTL agotado.

Solo necesita conocer a sus vecinos (`self.node.neighbors`); no usa la
topologia completa.
"""
from .base import RoutingAlgorithm
from ..protocol import get_header


class Flooding(RoutingAlgorithm):
    name = "flooding"

    def __init__(self, node):
        super().__init__(node)
        self.seen = set()   # mids ya reenviados

    def next_hops(self, pkt):
        mid = get_header(pkt, "mid")
        if mid in self.seen:
            return []                     # ya lo reenviamos: evitar loops
        self.seen.add(mid)
        last = get_header(pkt, "last_hop")
        return [n for n in self.node.neighbors if n != last]

    # Flooding no arma tablas, asi que on_control y tick quedan vacios.
