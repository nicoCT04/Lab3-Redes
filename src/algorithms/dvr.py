"""Algoritmo de enrutamiento Distance Vector Routing (DVR).

DVR es Bellman-Ford distribuido: ningun nodo conoce la topologia completa, solo
habla con sus vecinos directos.

  1. Cada nodo mantiene un VECTOR DE DISTANCIAS {destino: costo}: lo que le
     cuesta llegar a cada destino que conoce.
  2. Cada ~5s le manda su vector a cada vecino (paquete "info", ttl=1: los
     vectores nunca se reenvian mas alla del vecino).
  3. Al recibir el vector de un vecino v aplica Bellman-Ford:
     costo(destino) = min sobre los vecinos v de [ costo(v) + vector_v(destino) ]
     y guarda como SIGUIENTE SALTO al vecino v que dio ese minimo.
  4. Los mensajes de datos se reenvian al siguiente salto de esa tabla.

Del archivo de configuracion solo se usan los vecinos directos
(`self.node.neighbors`); el resto de la red se aprende de los vectores que
llegan, como exige el laboratorio.

Decisiones de implementacion
----------------------------
* RECALCULO COMPLETO: se guarda el ultimo vector de cada vecino
  (`self.neighbor_vectors`) y ante cualquier cambio se recalcula el vector
  propio desde cero. La version "incremental" (quedarse solo con lo que mejora)
  nunca puede EMPEORAR un costo, asi que jamas se entera de que una ruta se
  degrado; con el recalculo completo el nodo reacciona igual a las mejoras que
  a las caidas de enlaces.
* SPLIT HORIZON CON POISON REVERSE: a un vecino no se le anuncian las rutas que
  se aprendieron de el (se le anuncian como INFINITY). Esto elimina el
  count-to-infinity entre dos nodos.
* INFINITY = 16 (convencion de RIP): un costo >= INFINITY significa
  "inalcanzable" y le pone tope a los lazos de tres o mas nodos, que el split
  horizon no cubre.
* ENVEJECIMIENTO DE VECINOS: si un vecino deja de mandar su vector durante
  NEIGHBOR_TIMEOUT segundos se da el enlace por caido y se descarta su vector
  (los vectores periodicos hacen de keepalive, igual que en RIP).
* TRIGGERED UPDATES: si la tabla cambia al recibir un vector, se difunde de
  inmediato en vez de esperar al siguiente tick (con un minimo de
  TRIGGERED_MIN_INTERVAL entre difusiones para no inundar la red).
"""
import json
import threading
import time

from ..protocol import TYPE_INFO, Packet, get_header
from .base import RoutingAlgorithm

# Costo "infinito": un destino con este costo (o mas) se considera inalcanzable.
# 16 es la convencion de RIP y basta de sobra para redes del tamano del lab.
INFINITY = 16

# El archivo de topologia no trae pesos, asi que cada enlace directo cuesta 1
# (la ruta mas corta es la de menos saltos).
LINK_COST = 1

# Segundos sin recibir el vector de un vecino antes de dar el enlace por caido.
# Debe ser varias veces el tick del nodo (5s) para no tumbar un enlace solo
# porque se perdio un paquete.
NEIGHBOR_TIMEOUT = 20.0

# Minimo entre difusiones del vector, para que los triggered updates no
# provoquen una tormenta de paquetes cuando la red se esta reacomodando.
TRIGGERED_MIN_INTERVAL = 1.0

# Split horizon: si es True las rutas aprendidas de un vecino se le anuncian de
# vuelta como INFINITY (poison reverse); si es False simplemente se omiten.
# Poison reverse corta el lazo mas rapido.
POISON_REVERSE = True


def _as_cost(value):
    """Normaliza un costo recibido a numero, o None si no es valido."""
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return int(cost) if cost == int(cost) else cost


class DVR(RoutingAlgorithm):
    name = "dvr"

    def __init__(self, node):
        super().__init__(node)
        self.link_cost = {}          # {vecino: costo del enlace directo}
        self.cost = {}               # {destino: costo} <- nuestro vector de distancias
        self.next_hop = {}           # {destino: siguiente salto} <- tabla de ruteo
        self.neighbor_vectors = {}   # {vecino: {destino: costo}} ultimo vector recibido
        self.neighbor_time = {}      # {vecino: momento del ultimo vector}
        self.down = set()            # vecinos que dejaron de responder
        self._last_broadcast = 0.0
        # on_control corre en los hilos del transporte y tick() en el hilo de
        # routing: ambos tocan los vectores, asi que se protegen con un lock.
        self._lock = threading.Lock()

    # --- Ciclo de vida ---
    def start(self):
        """Inicializa el vector con los enlaces directos a los vecinos."""
        now = time.time()
        with self._lock:
            for v in self.node.neighbors:
                self.link_cost[v] = LINK_COST
                # Periodo de gracia: se asume al vecino arriba y tiene
                # NEIGHBOR_TIMEOUT para mandar su primer vector.
                self.neighbor_time[v] = now
            self._recompute()
        print(f"[{self.node.id}] DVR iniciado. vecinos: {self.node.neighbors}")
        self._broadcast_vector()

    def tick(self):
        """Cada ~5s: revisa los vecinos, recalcula y difunde el vector."""
        with self._lock:
            self._check_neighbors()
            changed = self._recompute()
        self._broadcast_vector()
        if changed:
            self._print_table()

    # --- a) Difundir nuestro vector de distancias ---
    def _broadcast_vector(self):
        """Manda el vector a cada vecino (uno distinto por vecino: split horizon).

        Va con ttl=1 y `dst` es el vecino concreto: un vector es informacion
        entre vecinos directos, nunca se reenvia mas alla.
        """
        me = self.node.id
        with self._lock:
            self._last_broadcast = time.time()
            vectors = {v: self._vector_for(v) for v in self.node.neighbors}
        for v, vector in vectors.items():
            pkt = Packet(
                proto=self.name, type=TYPE_INFO, src=me, dst=v, ttl=1,
                headers=[{"last_hop": me}], payload=vector,
            )
            self.node.send_to(v, pkt)

    def _vector_for(self, neighbor):
        """Vector que se le anuncia a `neighbor` aplicando split horizon.

        No se le devuelven las rutas que pasan por el: si se las anunciaramos,
        el vecino podria creer que tenemos un camino alterno cuando en realidad
        ese camino es el suyo (eso es el count-to-infinity).
        """
        vector = {}
        for dest, cost in self.cost.items():
            if dest == neighbor:
                continue                     # el vecino ya sabe llegar a si mismo
            if self.next_hop.get(dest) == neighbor:
                if POISON_REVERSE:
                    vector[dest] = INFINITY  # "por mi no llegas a ese destino"
                continue
            vector[dest] = cost
        return vector

    # --- b) Recibir el vector de un vecino ---
    def on_control(self, pkt):
        if pkt.type != TYPE_INFO:
            return                            # hello/echo: DVR no los usa
        via = get_header(pkt, "last_hop") or pkt.src
        if via not in self.node.neighbors:
            return                            # solo se aceptan vectores de vecinos directos
        vector = self._parse_vector(pkt.payload)
        if vector is None:
            return                            # payload que no es un vector de distancias

        with self._lock:
            recovered = via in self.down
            self.down.discard(via)
            self.neighbor_time[via] = time.time()
            self.neighbor_vectors[via] = vector
            changed = self._recompute()
            # Triggered update: avisar del cambio sin esperar al siguiente tick.
            triggered = changed and (
                time.time() - self._last_broadcast >= TRIGGERED_MIN_INTERVAL)

        if recovered:
            print(f"[{self.node.id}] vecino {via} volvio a responder")
        if changed:
            self._print_table()
        if triggered:
            self._broadcast_vector()

    def _parse_vector(self, payload):
        """Saca el {destino: costo} del payload, o None si no es un vector.

        Se acepta el payload como dict o como string JSON: otros grupos pueden
        serializarlo de cualquiera de las dos formas.
        """
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
        if not isinstance(payload, dict):
            return None
        vector = {}
        for dest, raw_cost in payload.items():
            cost = _as_cost(raw_cost)
            if cost is not None:
                vector[str(dest)] = cost
        return vector

    # --- c) Bellman-Ford sobre los vectores de los vecinos ---
    def _recompute(self):
        """Recalcula vector y tabla desde cero. Devuelve True si algo cambio.

        Se llama con el lock ya tomado.
        """
        me = self.node.id
        alive = self._alive_neighbors()
        cost = {me: 0}
        next_hop = {}

        for v in alive:                       # enlaces directos
            cost[v] = self.link_cost.get(v, LINK_COST)
            next_hop[v] = v

        for v in alive:                       # rutas aprendidas de cada vecino
            link = self.link_cost.get(v, LINK_COST)
            for dest, advertised in self.neighbor_vectors.get(v, {}).items():
                if dest == me or advertised >= INFINITY:
                    continue                  # nosotros mismos / inalcanzable para el
                total = link + advertised
                if total >= INFINITY:
                    continue                  # tope: mas alla de INFINITY no hay ruta
                current = cost.get(dest)
                # Ante empate se conserva el siguiente salto que ya se usaba,
                # para que la tabla no oscile entre dos rutas del mismo costo.
                if current is None or total < current or (
                        total == current and self.next_hop.get(dest) == v):
                    cost[dest] = total
                    next_hop[dest] = v

        changed = cost != self.cost or next_hop != self.next_hop
        self.cost = cost
        self.next_hop = next_hop
        return changed

    def _alive_neighbors(self):
        """Vecinos que siguen respondiendo (en orden fijo, para un calculo estable)."""
        now = time.time()
        return [v for v in sorted(self.node.neighbors)
                if now - self.neighbor_time.get(v, 0.0) <= NEIGHBOR_TIMEOUT]

    def _check_neighbors(self):
        """Da por caidos a los vecinos que llevan NEIGHBOR_TIMEOUT sin hablar."""
        now = time.time()
        down = {v for v in self.node.neighbors
                if now - self.neighbor_time.get(v, 0.0) > NEIGHBOR_TIMEOUT}
        for v in down - self.down:
            print(f"[{self.node.id}] vecino {v} sin vector hace "
                  f"{NEIGHBOR_TIMEOUT:.0f}s: enlace caido")
            self.neighbor_vectors.pop(v, None)
        self.down = down

    # --- d) Forwarding de mensajes de datos ---
    def next_hops(self, pkt) -> list:
        """Un unico siguiente salto: el que diga la tabla de ruteo."""
        next_hop = self.next_hop.get(pkt.dst)
        if not next_hop:
            print(f"[{self.node.id}] sin ruta hacia {pkt.dst}: se descarta el mensaje")
            return []
        return [next_hop]

    def _print_table(self):
        # Se copia la tabla con el lock puesto: si se recalculara a medio
        # recorrido se imprimirian filas inconsistentes.
        with self._lock:
            rows = [(dest, self.next_hop[dest], self.cost[dest])
                    for dest in sorted(self.next_hop)]
        print(f"[{self.node.id}] tabla de ruteo (DVR):")
        for dest, hop, cost in rows:
            print(f"    {dest}: via {hop}  (costo {cost})")
