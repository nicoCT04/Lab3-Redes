"""Transporte por sockets TCP para la Fase 1 (pruebas locales).

Cada nodo escucha en su propia direccion `host:port` y, para enviar, abre una
conexion breve al destino. Abrir una conexion por mensaje mantiene el codigo
simple y hace que la red tolere nodos que se caen o que aun no han arrancado:
si el destino no responde, `send` devuelve False en vez de romper el nodo.

El "address book" (id -> host:port) es informacion del medio, equivalente a que
el servidor XMPP sepa las direcciones de todos los usuarios; no es la topologia.
"""
import socket
import threading

from .base import Transport


class SocketTransport(Transport):
    def __init__(self, node_id, on_receive, address_book):
        super().__init__(node_id, on_receive)
        self.address_book = address_book          # {id: (host, port)}
        self.host, self.port = address_book[node_id]
        self._server = None
        self._running = False

    def start(self):
        self._running = True
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                break  # el socket se cerro en stop()
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn):
        # Cada mensaje es una linea JSON terminada en '\n'.
        with conn, conn.makefile("r", encoding="utf-8") as reader:
            for line in reader:
                line = line.strip()
                if line:
                    self.on_receive(line)

    def send(self, dst_id, raw):
        addr = self.address_book.get(dst_id)
        if not addr:
            return False
        try:
            with socket.create_connection(addr, timeout=2) as s:
                s.sendall((raw + "\n").encode("utf-8"))
            return True
        except OSError:
            return False  # nodo caido o no disponible

    def stop(self):
        self._running = False
        if self._server:
            self._server.close()
