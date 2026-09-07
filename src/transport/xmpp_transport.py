"""Transporte por XMPP para la Fase 2 (el medio es el servidor del curso).

Cada nodo de la red es un usuario del servidor XMPP: el paquete JSON viaja como
el cuerpo (`body`) de un mensaje de chat normal. El mapeo id -> JID sale del
archivo `names-*.txt` ({"A": "foo@bar.com"}), igual que el address book de
`SocketTransport` mapea id -> host:port; es informacion del medio, no la
topologia de la red.

Se respeta la misma interfaz `Transport`, asi que ni el nodo ni los algoritmos
cambian al pasar de sockets a XMPP: solo se elige otro transporte en main.py.

Detalle de implementacion: slixmpp trabaja sobre asyncio y su loop bloquea el
hilo donde corre, mientras que el motor del nodo es multihilo (forwarding +
routing). Por eso el cliente XMPP vive en su propio hilo con su propio event
loop y `send()` le inyecta trabajo con `call_soon_threadsafe`, que es la forma
segura de hablarle a un loop de asyncio desde otro hilo.
"""
import asyncio
import functools
import inspect
import ssl
import threading

from .base import Transport

try:
    from slixmpp import ClientXMPP
except ImportError:                            # Fase 1 no necesita la libreria
    ClientXMPP = None

# Segundos que se espera a que la sesion XMPP quede lista antes de seguir.
CONNECT_TIMEOUT = 15.0


class XMPPTransport(Transport):
    def __init__(self, node_id, on_receive, jid_book, password,
                 host=None, port=5222, insecure=False):
        super().__init__(node_id, on_receive)
        if ClientXMPP is None:
            raise RuntimeError(
                "El transporte XMPP necesita slixmpp: pip install -r requirements.txt")
        if node_id not in jid_book:
            raise RuntimeError(f"El nodo '{node_id}' no tiene JID en el archivo de nombres")
        self.jid_book = jid_book               # {id: jid}
        self.jid = jid_book[node_id]
        self.password = password
        self.address = (host, port) if host else None   # None: se resuelve por DNS
        self.insecure = insecure
        self._client = None
        self._loop = None
        self._ready = threading.Event()        # sesion iniciada
        self._running = False

    # --- Ciclo de vida ---
    def start(self):
        """Levanta el cliente XMPP en su propio hilo y espera a la sesion."""
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(timeout=CONNECT_TIMEOUT):
            print(f"[{self.node_id}] XMPP: la sesion no quedo lista en "
                  f"{CONNECT_TIMEOUT:.0f}s; se sigue reintentando en segundo plano")

    def _run(self):
        """Hilo del cliente: crea el loop de asyncio, conecta y lo corre."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._client = ClientXMPP(self.jid, self.password)
        self._client.register_plugin("xep_0030")   # Service Discovery
        self._client.register_plugin("xep_0199")   # XMPP Ping (mantiene viva la sesion)
        self._client.add_event_handler("session_start", self._on_session_start)
        self._client.add_event_handler("message", self._on_message)
        self._client.add_event_handler("failed_auth", self._on_failed_auth)
        self._client.add_event_handler("disconnected", self._on_disconnected)
        if self.insecure:
            # Los servidores de laboratorio suelen usar certificados autofirmados.
            self._client.ssl_context.check_hostname = False
            self._client.ssl_context.verify_mode = ssl.CERT_NONE

        # La conexion se lanza ya dentro del loop, que es donde slixmpp espera
        # correr; `run_forever` mantiene vivo al cliente hasta el stop().
        self._loop.call_soon(self._connect)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _connect(self):
        """Arranca la conexion (la firma de `connect` cambio entre versiones)."""
        try:
            if not self.address:
                self._client.connect()             # host y puerto por DNS
            elif "address" in inspect.signature(self._client.connect).parameters:
                self._client.connect(address=self.address)   # slixmpp 1.8
            else:
                self._client.connect(*self.address)          # slixmpp >= 1.9
        except Exception as e:                 # noqa: BLE001 - el nodo no debe morir por el medio
            print(f"[{self.node_id}] XMPP: error en la conexion: {e}")

    # --- Eventos del cliente XMPP ---
    def _on_session_start(self, event):
        """Sesion lista: hay que anunciarse para poder recibir mensajes."""
        self._client.send_presence()
        self._client.get_roster()
        print(f"[{self.node_id}] XMPP conectado como {self.jid}")
        self._ready.set()

    def _on_message(self, msg):
        """Cada mensaje de chat trae un paquete de la red en su body."""
        if msg["type"] not in ("chat", "normal"):
            return
        raw = str(msg["body"]).strip()
        if raw:
            self.on_receive(raw)               # se lo pasa al forwarding del nodo

    def _on_failed_auth(self, event):
        print(f"[{self.node_id}] XMPP: credenciales rechazadas para {self.jid}")

    def _on_disconnected(self, event):
        if self._running:
            self._ready.clear()
            print(f"[{self.node_id}] XMPP: desconectado, reintentando...")

    # --- Envio ---
    def send(self, dst_id, raw):
        """Manda `raw` al JID del nodo `dst_id`. False si no se pudo encolar."""
        jid = self.jid_book.get(dst_id)
        if not jid or not self._client or not self._loop or not self._loop.is_running():
            return False
        try:
            # send_message debe ejecutarse dentro del loop de slixmpp, no en el
            # hilo que llama (forwarding o routing).
            self._loop.call_soon_threadsafe(
                functools.partial(self._client.send_message,
                                  mto=jid, mbody=raw, mtype="chat"))
            return True
        except RuntimeError:
            return False                       # el loop se cerro mientras tanto

    def stop(self):
        self._running = False
        self._ready.clear()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._shutdown)

    def _shutdown(self):
        """Corre dentro del loop: cierra la sesion y luego detiene el loop."""
        try:
            self._client.disconnect()
        except Exception:                      # noqa: BLE001 - ya se esta cerrando
            pass
        self._loop.call_later(1.0, self._loop.stop)
