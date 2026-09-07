# Laboratorio 3 — Algoritmos de Enrutamiento

CC3067 Redes · Universidad del Valle de Guatemala

Simulacion de una red de nodos donde cada nodo es un proceso independiente que
descubre a sus vecinos, arma su tabla de ruteo y reenvia mensajes al destino
usando distintos algoritmos de enrutamiento.

## Algoritmos

| Algoritmo | Estado | Responsable |
|---|---|---|
| Dijkstra | ✅ listo | Integrante 1 |
| Flooding | ✅ listo | Integrante 2 |
| Link State Routing (LSR) | ⬜ pendiente | Integrante 3 |
| Distance Vector (DVR) | ⬜ pendiente | Integrante 4 |

## Estructura del proyecto

```
Lab3-Redes/
├── config/              # Archivos de topologia y nombres (ejemplos)
│   ├── topo-example.txt
│   └── names-example.txt
├── src/
│   ├── protocol.py      # Formato de paquete + serializacion JSON
│   ├── config.py        # Lectura de topo-*.txt / names-*.txt
│   ├── transport/       # Capa de transporte (sockets; XMPP en Fase 2)
│   ├── algorithms/      # Un archivo por algoritmo
│   ├── node.py          # Motor del nodo: hilos forwarding + routing
│   └── main.py          # CLI para levantar un nodo
├── requirements.txt
└── README.md
```

## Protocolo

Todos los nodos hablan el mismo formato JSON, lo que permite interoperar entre
grupos para un mismo algoritmo:

```json
{
  "proto":   "dijkstra|flooding|lsr|dvr",
  "type":    "message|hello|echo|info",
  "from":    "<nodo origen>",
  "to":      "<nodo destino>",
  "ttl":     10,
  "headers": [{"mid": "..."}],
  "payload": "contenido del paquete"
}
```

## Uso

Requiere Python 3 (Fase 1 usa solo la biblioteca estándar, sin dependencias).

Levantar un nodo por terminal, cada uno con su `--id`:

```bash
python -m src.main --algo dijkstra --id A --topo config/topo-example.txt --names config/names-example.txt
python -m src.main --algo dijkstra --id G --topo config/topo-example.txt --names config/names-example.txt
```

Al iniciar, cada nodo imprime su tabla de ruteo. En la consola de un nodo se
envían mensajes con el formato `<destino> <texto>`:

```
G hola desde A
```

El mensaje viaja por la ruta óptima hasta el nodo destino, que lo imprime.
Escribe `quit` para cerrar el nodo.

> Para agregar un algoritmo, crea `src/algorithms/<algo>.py` con una subclase de
> `RoutingAlgorithm` y regístralo en el diccionario `ALGORITHMS` de `src/main.py`.

## Notas de diseño

- Cada nodo corre dos responsabilidades en paralelo: **forwarding** (manejo de
  paquetes entrantes/salientes) y **routing** (armado y actualizacion de tablas).
- Los archivos `topo`/`names` solo se usan para configurar el propio nodo y
  descubrir vecinos, nunca para resolver la topologia completa de forma estatica.
- Fase 1 usa **sockets TCP** locales; la Fase 2 migrara a **XMPP** manteniendo la
  misma interfaz de transporte.
