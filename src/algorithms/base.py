"""Interfaz comun para todos los algoritmos de enrutamiento.

Cada integrante implementa una subclase de `RoutingAlgorithm` en su propio
archivo (flooding.py, dijkstra.py, lsr.py, dvr.py) y rellena estos metodos. El
motor del nodo (node.py) no conoce los algoritmos concretos: solo llama a esta
interfaz, lo que mantiene todo modular (necesario, ya que LSR reutiliza Flooding
y Dijkstra).

Responsabilidades:
  - next_hops(pkt) -> lista de vecinos    [proceso de FORWARDING]
        A que vecino(s) reenviar un paquete de datos. Un solo salto en los
        algoritmos con tabla (Dijkstra/LSR/DVR); varios en Flooding.
  - on_control(pkt)                        [proceso de ROUTING]
        Procesar paquetes de control (hello/info) para armar/actualizar tablas.
  - tick()                                 [proceso de ROUTING]
        Tarea periodica: enviar hellos, difundir la tabla/LSP, etc.
  - start()
        Inicializacion (p. ej. tabla de ruteo) al levantar el nodo.
"""


class RoutingAlgorithm:
    name = "base"

    def __init__(self, node):
        self.node = node  # referencia al Node duenno (para acceder a vecinos, enviar, etc.)

    def start(self) -> None:
        """Inicializa el estado del algoritmo. Opcional."""

    def next_hops(self, pkt) -> list:
        """Vecinos a los que reenviar `pkt`. Por defecto no reenvia."""
        return []

    def on_control(self, pkt) -> None:
        """Procesa un paquete de control (hello/info). Opcional."""

    def tick(self) -> None:
        """Trabajo periodico del proceso de routing. Opcional."""
