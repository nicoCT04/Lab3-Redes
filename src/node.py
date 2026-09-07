"""Motor del nodo: conecta transporte + algoritmo y corre los dos procesos.

Un nodo corre en paralelo:
  - FORWARDING: maneja los paquetes entrantes. Si un mensaje de datos es para
    nosotros lo imprime; si no, le pide al algoritmo a que vecino reenviarlo.
    Los paquetes de control (hello/info) se pasan al proceso de routing.
  - ROUTING: tarea periodica del algoritmo (armar/difundir tablas, hellos, etc.).

El motor no conoce ningun algoritmo concreto: solo usa la interfaz
`RoutingAlgorithm`, por lo que sirve igual para Dijkstra, Flooding, LSR o DVR.
"""
import threading
import time

from .protocol import (DEFAULT_TTL, TYPE_MESSAGE, Packet, new_message_id,
                       set_header)


class Node:
    def __init__(self, node_id, topology, transport_factory, algo_cls,
                 tick_interval=5.0):
        self.id = node_id
        # Topologia completa: SOLO Dijkstra puro puede usarla (excepcion del lab).
        # El resto de algoritmos debe limitarse a `self.neighbors`.
        self.topology = topology
        self.neighbors = list(topology.get(node_id, []))
        self.transport = transport_factory(self.id, self._on_receive)
        self.algo = algo_cls(self)
        self.tick_interval = tick_interval
        self._running = False

    # --- Ciclo de vida ---
    def start(self):
        self._running = True
        self.transport.start()
        self.algo.start()
        threading.Thread(target=self._routing_loop, daemon=True).start()
        print(f"[{self.id}] nodo iniciado ({self.algo.name}). vecinos: {self.neighbors}")

    def stop(self):
        self._running = False
        self.transport.stop()

    # --- Proceso de ROUTING (periodico) ---
    def _routing_loop(self):
        while self._running:
            try:
                self.algo.tick()
            except Exception as e:
                print(f"[{self.id}] error en routing: {e}")
            time.sleep(self.tick_interval)

    # --- Proceso de FORWARDING (paquetes entrantes) ---
    def _on_receive(self, raw):
        try:
            pkt = Packet.from_json(raw)
        except Exception:
            return  # paquete malformado: se ignora
        if pkt.type == TYPE_MESSAGE:
            if pkt.dst == self.id:
                print(f"[{self.id}] MENSAJE de {pkt.src}: {pkt.payload}")
            else:
                self._route(pkt)
        else:
            self.algo.on_control(pkt)  # hello/info -> proceso de routing

    def _route(self, pkt):
        """Reenvia un paquete de datos segun lo que decida el algoritmo."""
        if pkt.ttl <= 0:
            return  # TTL agotado: se descarta (corta loops)
        for next_hop in self.algo.next_hops(pkt):
            fwd = Packet.from_dict(pkt.to_dict())  # copia independiente
            fwd.ttl = pkt.ttl - 1
            set_header(fwd, "last_hop", self.id)
            self.transport.send(next_hop, fwd.to_json())

    # --- API de usuario ---
    def send_message(self, dst, text):
        """Crea y envia un mensaje de datos nuevo desde este nodo."""
        if dst == self.id:
            print(f"[{self.id}] MENSAJE para mi mismo: {text}")
            return
        pkt = Packet(
            proto=self.algo.name, type=TYPE_MESSAGE,
            src=self.id, dst=dst, ttl=DEFAULT_TTL,
            headers=[{"mid": new_message_id()}, {"last_hop": self.id}],
            payload=text,
        )
        self._route(pkt)

    def send_to(self, dst_id, pkt):
        """Ayuda para que los algoritmos envien un paquete ya armado a un nodo."""
        return self.transport.send(dst_id, pkt.to_json())
