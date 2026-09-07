"""Algoritmo de enrutamiento de Dijkstra.

Dijkstra puro es estatico: recibe la topologia completa (nodos y aristas) y
calcula el camino mas corto desde este nodo hacia todos los demas. Con esos
caminos arma una tabla {destino: siguiente_salto} que el forwarding consulta.

Es la unica excepcion del laboratorio en la que se permite usar la topologia
completa (por eso lee `self.node.topology`). Los demas algoritmos deben
descubrir la red dinamicamente.

La topologia estandar (`topo-*.txt`) es una lista de adyacencia sin pesos, por
lo que cada arista cuesta 1 (camino mas corto = menor numero de saltos). Si un
nodo trae sus vecinos como diccionario {vecino: costo}, se respetan esos pesos.
"""
import heapq

from .base import RoutingAlgorithm


class Dijkstra(RoutingAlgorithm):
    name = "dijkstra"

    def __init__(self, node):
        super().__init__(node)
        self.table = {}        # {destino: siguiente_salto}
        self.distances = {}    # {destino: costo total}

    def start(self):
        self._compute()
        self._print_table()

    def _build_graph(self) -> dict:
        """Normaliza la topologia a {u: {v: costo}} (costo 1 si no hay pesos)."""
        graph = {}
        for u, nbrs in self.node.topology.items():
            graph.setdefault(u, {})
            items = nbrs.items() if isinstance(nbrs, dict) else ((v, 1) for v in nbrs)
            for v, cost in items:
                graph[u][v] = cost
                graph.setdefault(v, {})
        return graph

    def _compute(self):
        """Dijkstra clasico con cola de prioridad desde este nodo."""
        graph = self._build_graph()
        src = self.node.id
        dist = {src: 0}
        prev = {}
        visited = set()
        pq = [(0, src)]

        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            for v, cost in graph.get(u, {}).items():
                nd = d + cost
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        # Para cada destino, retrocedemos por `prev` hasta el vecino directo de
        # `src`: ese es el siguiente salto que debe guardar la tabla de ruteo.
        self.distances = dist
        self.table = {}
        for dest in dist:
            if dest == src:
                continue
            hop = dest
            while hop in prev and prev[hop] != src:
                hop = prev[hop]
            if prev.get(hop) == src:
                self.table[dest] = hop

    def next_hops(self, pkt) -> list:
        next_hop = self.table.get(pkt.dst)
        return [next_hop] if next_hop else []

    def _print_table(self):
        print(f"[{self.node.id}] tabla de ruteo (Dijkstra):")
        for dest in sorted(self.table):
            print(f"    {dest}: via {self.table[dest]}  (costo {self.distances[dest]})")
