"""Algoritmo de enrutamiento Link State Routing (LSR).

LSR combina las dos ideas que ya existen en el laboratorio:

  1. FLOODING: cada nodo empaqueta su estado de enlace local (la lista de sus
     vecinos) en un LSP (Link State Packet) y lo inunda por toda la red.
  2. DIJKSTRA: con los LSP que recibe, cada nodo reconstruye la topologia
     completa (la LSDB) y corre Dijkstra sobre ella para armar su tabla
     {destino: siguiente_salto}.

A diferencia de Dijkstra puro, aqui la topologia NO se lee del archivo: se
descubre juntando los LSP que llegan. Del archivo solo se usan los vecinos
directos (`self.node.neighbors`), que es lo unico que permite el laboratorio.

Formato del LSP (va en el `payload` del paquete de tipo "info"):

    {"origin": "A", "seq": 3, "neighbors": ["B", "C", "I"]}

y en los headers viaja `lsp_id` = "<origin>:<seq>" para detectar duplicados y
`last_hop` para no devolver el LSP por donde vino.
"""
import heapq
import json
import threading
import time

from ..protocol import DEFAULT_TTL, TYPE_INFO, Packet, get_header, set_header
from .base import RoutingAlgorithm

# Segundos sin recibir un LSP de un nodo antes de darlo por caido y sacarlo de
# la LSDB. Debe ser varias veces el `tick_interval` del nodo (5s) para no
# borrar a un nodo solo porque se perdio un LSP.
LSP_MAX_AGE = 30.0


class LSR(RoutingAlgorithm):
    name = "lsr"

    def __init__(self, node):
        super().__init__(node)
        self.lsdb = {}         # {origen: [vecinos]} -> topologia reconstruida
        self.lsp_seq = {}      # {origen: ultimo seq aceptado}
        self.lsp_time = {}     # {origen: momento del ultimo LSP recibido}
        self.seen_lsp = set()  # {"origen:seq"} ya procesados (corta los loops)
        self.table = {}        # {destino: siguiente_salto}
        self.distances = {}    # {destino: costo total}
        self.seq = 0           # numero de secuencia de NUESTRO LSP
        # on_control corre en los hilos del transporte y tick() en el hilo de
        # routing: los dos tocan la LSDB, asi que se protege con un lock.
        self._lock = threading.Lock()

    # --- Ciclo de vida ---
    def start(self):
        with self._lock:
            self._record_own_lsp()
            self._compute()
        print(f"[{self.node.id}] LSR iniciado. vecinos: {self.node.neighbors}")

    def tick(self):
        """Cada ~5s: refresca nuestro LSP, envejece la LSDB y lo inunda."""
        with self._lock:
            self._record_own_lsp()
            changed = self._age_out()
            changed = self._compute() or changed
        self._flood_own_lsp()
        if changed:
            self._print_table()

    # --- a) Difundir nuestro propio LSP ---
    def _record_own_lsp(self):
        """Mete (o actualiza) nuestro estado de enlace en la LSDB."""
        me = self.node.id
        self.lsdb[me] = list(self.node.neighbors)
        self.lsp_seq[me] = self.seq
        self.lsp_time[me] = time.time()

    def _flood_own_lsp(self):
        """Envia nuestro LSP a todos los vecinos (arranque del flooding)."""
        me = self.node.id
        lsp_id = f"{me}:{self.seq}"
        lsp = {"origin": me, "seq": self.seq, "neighbors": list(self.node.neighbors)}
        pkt = Packet(
            proto=self.name, type=TYPE_INFO, src=me, dst="*", ttl=DEFAULT_TTL,
            headers=[{"lsp_id": lsp_id}, {"last_hop": me}],
            payload=lsp,
        )
        with self._lock:
            self.seen_lsp.add(lsp_id)
            self._forget_old_ids(me, lsp_id)
        for v in self.node.neighbors:
            self.node.send_to(v, pkt)
        self.seq += 1

    # --- b) Recibir LSP ajenos ---
    def on_control(self, pkt):
        if pkt.type != TYPE_INFO:
            return  # hello/echo: LSR no los usa
        parsed = self._parse_lsp(pkt)
        if parsed is None:
            return  # payload que no es un LSP valido
        origin, seq, neighbors = parsed
        if origin == self.node.id:
            return  # nuestro propio LSP que dio la vuelta por la red

        lsp_id = get_header(pkt, "lsp_id") or f"{origin}:{seq}"
        with self._lock:
            if lsp_id in self.seen_lsp:
                return  # duplicado: ni se reprocesa ni se reinunda
            known = self.lsp_seq.get(origin)
            if known is not None and seq <= known:
                return  # LSP viejo: nos quedamos con el seq mas alto
            self.seen_lsp.add(lsp_id)
            self._forget_old_ids(origin, lsp_id)
            self.lsdb[origin] = neighbors
            self.lsp_seq[origin] = seq
            self.lsp_time[origin] = time.time()
            changed = self._compute()

        self._reflood(pkt)
        if changed:
            self._print_table()

    def _parse_lsp(self, pkt):
        """Saca (origin, seq, neighbors) del payload, o None si no es un LSP.

        Se acepta el payload como dict o como string JSON: otros grupos pueden
        serializarlo de cualquiera de las dos formas.
        """
        payload = pkt.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
        if not isinstance(payload, dict):
            return None
        neighbors = payload.get("neighbors")
        if not isinstance(neighbors, (list, dict)):
            return None
        origin = payload.get("origin") or pkt.src
        if not origin:
            return None
        try:
            seq = int(payload.get("seq", 0))
        except (TypeError, ValueError):
            return None
        return origin, seq, neighbors

    def _reflood(self, pkt):
        """Reenvia el LSP a los vecinos, menos por donde vino."""
        if pkt.ttl <= 1:
            return  # TTL agotado: se descarta
        last_hop = get_header(pkt, "last_hop")
        fwd = Packet.from_dict(pkt.to_dict())
        fwd.headers = [dict(h) for h in pkt.headers]  # copia propia de headers
        fwd.ttl = pkt.ttl - 1
        set_header(fwd, "last_hop", self.node.id)
        for v in self.node.neighbors:
            if v != last_hop and v != pkt.src:
                self.node.send_to(v, fwd)

    def _forget_old_ids(self, origin, keep_id):
        """Limpia los lsp_id viejos de `origin` para que `seen_lsp` no crezca."""
        prefix = origin + ":"
        self.seen_lsp = {i for i in self.seen_lsp
                         if i == keep_id or not i.startswith(prefix)}

    def _age_out(self):
        """Saca de la LSDB a los nodos que llevan mucho sin mandar su LSP."""
        now = time.time()
        stale = [n for n, t in self.lsp_time.items()
                 if n != self.node.id and now - t > LSP_MAX_AGE]
        for n in stale:
            print(f"[{self.node.id}] sin LSP de {n} hace {LSP_MAX_AGE:.0f}s: "
                  f"lo saco de la LSDB")
            self.lsdb.pop(n, None)
            self.lsp_seq.pop(n, None)
            self.lsp_time.pop(n, None)
            self._forget_old_ids(n, None)
        return bool(stale)

    # --- c) Dijkstra sobre la LSDB ---
    def _build_graph(self):
        """Normaliza la LSDB a {u: {v: costo}} (costo 1 si no vienen pesos).

        Un enlace u-v solo se considera valido si AMBOS extremos lo declaran en
        su LSP. Asi, cuando un nodo se cae y su LSP envejece, los enlaces hacia
        el desaparecen aunque sus vecinos todavia lo mencionen.
        """
        graph = {u: {} for u in self.lsdb}
        for u, nbrs in self.lsdb.items():
            items = nbrs.items() if isinstance(nbrs, dict) else ((v, 1) for v in nbrs)
            for v, cost in items:
                if v in self.lsdb and u in (self.lsdb.get(v) or []):
                    graph[u][v] = cost
        return graph

    def _compute(self):
        """Dijkstra desde este nodo. Devuelve True si la tabla cambio."""
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

        # Para cada destino retrocedemos por `prev` hasta el vecino directo de
        # `src`: ese es el siguiente salto que debe guardar la tabla de ruteo.
        table = {}
        for dest in dist:
            if dest == src:
                continue
            hop = dest
            while hop in prev and prev[hop] != src:
                hop = prev[hop]
            if prev.get(hop) == src:
                table[dest] = hop

        changed = table != self.table
        self.table = table
        self.distances = dist
        return changed

    # --- d) Forwarding de mensajes de datos ---
    def next_hops(self, pkt) -> list:
        next_hop = self.table.get(pkt.dst)
        if not next_hop:
            print(f"[{self.node.id}] sin ruta hacia {pkt.dst}: se descarta el mensaje")
            return []
        return [next_hop]

    def _print_table(self):
        print(f"[{self.node.id}] tabla de ruteo (LSR):")
        for dest in sorted(self.table):
            print(f"    {dest}: via {self.table[dest]}  (costo {self.distances[dest]})")
