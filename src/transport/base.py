"""Interfaz de la capa de transporte.

El transporte es el "medio" de la red. Aisla al nodo de COMO viajan los bytes:
en la Fase 1 es por sockets TCP locales y en la Fase 2 sera por XMPP. Mientras
se respete este contrato, el nodo funciona igual con cualquiera de los dos.

Contrato:
  - send(dst_id, raw) -> bool : entrega el string `raw` al nodo `dst_id`.
  - start()                   : comienza a recibir; por cada mensaje entrante
                                llama al callback `on_receive(raw)`.
  - stop()                    : detiene la recepcion y libera recursos.
"""
from abc import ABC, abstractmethod
from typing import Callable


class Transport(ABC):
    def __init__(self, node_id: str, on_receive: Callable[[str], None]):
        self.node_id = node_id
        self.on_receive = on_receive

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def send(self, dst_id: str, raw: str) -> bool:
        """Envia `raw` a `dst_id`. Devuelve False si el destino no esta disponible."""
        ...

    @abstractmethod
    def stop(self) -> None:
        ...
