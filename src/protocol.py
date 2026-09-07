"""Formato de protocolo de la red.

Todos los nodos (sin importar el algoritmo) intercambian paquetes con la misma
estructura JSON definida en el laboratorio:

    {
      "proto":   "dijkstra|flooding|lsr|dvr",
      "type":    "message|hello|echo|info",
      "from":    "<id/jid del nodo origen>",
      "to":      "<id/jid del nodo destino>",
      "ttl":     <entero>,
      "headers": [{"clave": "valor"}, ...],
      "payload": "<contenido segun el tipo>"
    }

Mantener este formato estable es lo que permite interoperar entre los codigos
de distintos grupos para un mismo algoritmo.
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

# --- Protocolos (algoritmo de la red) ---
PROTO_DIJKSTRA = "dijkstra"
PROTO_FLOODING = "flooding"
PROTO_LSR = "lsr"
PROTO_DVR = "dvr"

# --- Tipos de mensaje ---
TYPE_MESSAGE = "message"   # data de usuario: se reenvia o se imprime si es para nosotros
TYPE_HELLO = "hello"       # descubrimiento de vecinos / medicion de delay
TYPE_ECHO = "echo"         # respuesta a un hello
TYPE_INFO = "info"         # informacion de tablas / enlaces (DV, LSP, etc.)

DEFAULT_TTL = 10


@dataclass
class Packet:
    """Un paquete de la red. Se serializa a/desde JSON respetando el formato."""

    proto: str
    type: str
    src: str                                  # se serializa como "from"
    dst: str                                  # se serializa como "to"
    ttl: int = DEFAULT_TTL
    headers: list = field(default_factory=list)
    payload: Any = ""

    def to_dict(self) -> dict:
        return {
            "proto": self.proto,
            "type": self.type,
            "from": self.src,
            "to": self.dst,
            "ttl": self.ttl,
            "headers": self.headers,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Packet":
        return cls(
            proto=d.get("proto", ""),
            type=d.get("type", ""),
            src=d.get("from", ""),
            dst=d.get("to", ""),
            ttl=d.get("ttl", DEFAULT_TTL),
            headers=d.get("headers", []),
            payload=d.get("payload", ""),
        )

    @classmethod
    def from_json(cls, raw: str) -> "Packet":
        return cls.from_dict(json.loads(raw))


# --- Utilidades para trabajar con la lista de headers ---
# Los headers son una lista de diccionarios de un solo par clave/valor, tal como
# en el formato del laboratorio. Estas ayudas evitan repetir ese recorrido.

def get_header(pkt: Packet, key: str, default=None):
    """Devuelve el valor del header `key` o `default` si no existe."""
    for h in pkt.headers:
        if key in h:
            return h[key]
    return default


def set_header(pkt: Packet, key: str, value) -> None:
    """Fija (o crea) el header `key` con `value`."""
    for h in pkt.headers:
        if key in h:
            h[key] = value
            return
    pkt.headers.append({key: value})


def new_message_id() -> str:
    """ID unico de mensaje, util para detectar duplicados (p. ej. en flooding)."""
    return uuid.uuid4().hex
