# Distance Vector Routing (DVR) — sección para el reporte grupal

Laboratorio 3, CC3067 Redes. Implementación en `src/algorithms/dvr.py` y capa de
transporte XMPP en `src/transport/xmpp_transport.py`.

## 1. Descripción del algoritmo

Distance Vector Routing es el algoritmo de Bellman-Ford distribuido. A diferencia
de Link State Routing, ningún nodo llega a conocer la topología completa de la
red: cada uno solo conversa con sus vecinos directos y aprende el resto de la red
a partir de lo que ellos le cuentan.

Cada nodo mantiene un **vector de distancias**, un diccionario `{destino: costo}`
con lo que le cuesta alcanzar cada destino que conoce, y una **tabla de ruteo**
`{destino: siguiente salto}`. El ciclo del algoritmo es:

1. Cada nodo inicializa su vector con sus enlaces directos: costo 0 hacia sí
   mismo y costo 1 hacia cada vecino (el archivo de topología no trae pesos, así
   que la ruta más corta equivale a la de menor número de saltos).
2. Periódicamente (cada 5 s) le envía su vector a cada uno de sus vecinos en un
   paquete de tipo `info`.
3. Al recibir el vector de un vecino *v*, aplica la ecuación de Bellman-Ford:

   ```
   costo(destino) = min sobre los vecinos v de [ costo(v) + vector_v(destino) ]
   ```

   El vecino *v* que produce ese mínimo queda registrado como siguiente salto
   hacia ese destino.
4. Cuando llega un mensaje de datos que no es para él, lo reenvía únicamente al
   siguiente salto que indique su tabla.

La información se propaga un salto por ronda de intercambio, así que la red
converge en tantas rondas como el diámetro de la red.

## 2. Implementación

### 2.1 Estructura

El proyecto separa el algoritmo del motor del nodo y del medio de transmisión.
`DVR` es una subclase de `RoutingAlgorithm` y solo implementa cuatro métodos que
el motor (`src/node.py`) invoca desde sus dos hilos:

| Método | Hilo | Responsabilidad |
|---|---|---|
| `start()` | arranque | Inicializa el vector con los enlaces directos |
| `tick()` | routing | Cada 5 s: revisa vecinos, recalcula y difunde el vector |
| `on_control(pkt)` | forwarding | Procesa el vector recibido de un vecino |
| `next_hops(pkt)` | forwarding | Devuelve el único siguiente salto hacia el destino |

Del archivo de configuración solo se usa `self.node.neighbors`, es decir la lista
de vecinos directos del propio nodo; nunca la topología completa, como exige el
enunciado.

### 2.2 Estado que mantiene el nodo

| Estructura | Contenido |
|---|---|
| `cost` | `{destino: costo}` — el vector de distancias propio |
| `next_hop` | `{destino: vecino}` — la tabla de ruteo |
| `neighbor_vectors` | `{vecino: {destino: costo}}` — el último vector recibido de cada vecino |
| `neighbor_time` | `{vecino: timestamp}` — cuándo se supo por última vez de cada vecino |
| `link_cost` | `{vecino: costo del enlace}` — 1 por defecto |

### 2.3 Formato de los paquetes

Los vectores viajan en el mismo paquete JSON estándar del laboratorio, con
`type: "info"` y el vector de distancias como `payload`:

```json
{
  "proto": "dvr",
  "type": "info",
  "from": "A",
  "to": "B",
  "ttl": 1,
  "headers": [{"last_hop": "A"}],
  "payload": {"A": 0, "C": 1, "I": 1, "D": 2}
}
```

El `ttl` es 1 y el destino es el vecino concreto porque un vector es información
que se intercambia solo entre vecinos directos: nunca se reenvía más allá. El
header `last_hop` identifica de qué vecino vino el vector, que es el dato que se
usa para fijar el siguiente salto.

Al recibir un vector se acepta el `payload` tanto como diccionario como en forma
de cadena JSON, para poder interoperar con las implementaciones de otros grupos.

### 2.4 Decisiones de diseño

**Recálculo completo en vez de actualización incremental.** La versión más
sencilla de DVR solo se queda con lo que mejora su costo actual
(`if nuevo < actual`). El problema es que así un nodo nunca puede *empeorar* un
costo, y por lo tanto jamás se entera de que una ruta se degradó o desapareció.
La implementación guarda el último vector de cada vecino y, ante cualquier
cambio, recalcula su vector desde cero a partir de esos vectores guardados. De
esa forma el nodo reacciona igual ante una mejora que ante la caída de un enlace,
que es lo que el laboratorio pide evaluar.

**Split horizon con poison reverse.** A un vecino no se le anuncian las rutas que
se aprendieron de él: se le anuncian con costo infinito. Si no se hiciera, el
vecino podría creer que existe un camino alterno cuando en realidad ese camino es
el suyo propio, que es exactamente el origen del problema de *count-to-infinity*.

**Infinito acotado a 16.** Siguiendo la convención de RIP, un costo mayor o igual
a 16 significa "inalcanzable". El split horizon elimina los lazos entre dos
nodos, pero no los de tres o más; el tope de 16 garantiza que cualquier lazo
residual termine en pocas rondas en vez de crecer indefinidamente.

**Envejecimiento de vecinos.** Los vectores periódicos funcionan como
*keepalive*: si un vecino deja de enviar el suyo durante 20 s (cuatro ticks), se
da el enlace por caído y se descarta su vector. El margen de cuatro ticks evita
tumbar un enlace solo porque se perdió un paquete. Cuando el vecino vuelve a
hablar, el enlace se restablece automáticamente.

**Triggered updates.** Si al recibir un vector cambia la tabla, el nodo difunde
su vector de inmediato en vez de esperar al siguiente tick. Esto acelera mucho la
convergencia; para que no se convierta en una tormenta de paquetes se exige un
mínimo de 1 s entre difusiones.

**Estabilidad de la tabla.** Cuando dos rutas empatan en costo se conserva el
siguiente salto que ya se estaba usando, para que la tabla no oscile entre dos
caminos equivalentes. Además, los vecinos se recorren en orden alfabético para
que el cálculo sea determinista.

**Concurrencia.** `on_control()` corre en los hilos del transporte y `tick()` en
el hilo de routing; ambos tocan las mismas estructuras, así que el estado
compartido se protege con un `threading.Lock`.

## 3. Capa de transporte XMPP (Fase 2)

El medio de la red está aislado detrás de la interfaz `Transport`, con dos
implementaciones intercambiables: `SocketTransport` (Fase 1) y `XMPPTransport`
(Fase 2). Ni el motor del nodo ni los algoritmos cambian entre una y otra; solo
se elige con el flag `--transport` de la línea de comandos.

En `XMPPTransport` cada nodo es un usuario del servidor XMPP y el paquete JSON de
la red viaja como el cuerpo de un mensaje de chat. El mapeo `id -> JID` sale del
archivo `names-*.txt`, igual que el mapeo `id -> host:port` de los sockets: es
información del medio, no de la topología.

El detalle técnico relevante es que la librería `slixmpp` trabaja sobre asyncio y
su *event loop* bloquea el hilo donde corre, mientras que el motor del nodo es
multihilo (forwarding y routing en paralelo). Por eso el cliente XMPP vive en su
propio hilo con su propio event loop, y `send()` le inyecta trabajo desde los
otros hilos con `call_soon_threadsafe`, que es la forma segura de comunicarse con
un event loop de asyncio desde fuera de él.

## 4. Resultados

Las pruebas se hicieron sobre la topología de ejemplo de nueve nodos
(`config/topo-example.txt`), levantando cada nodo como un proceso independiente.

**Tablas de ruteo.** Tras la convergencia se compararon las tablas de los nueve
nodos contra los caminos mínimos reales calculados por BFS: los costos y los
siguientes saltos coinciden en los nueve nodos. La tabla del nodo A quedó así:

```
[A] tabla de ruteo (DVR):
    B: via B  (costo 1)      E: via C  (costo 3)      H: via B  (costo 3)
    C: via C  (costo 1)      F: via B  (costo 2)      I: via I  (costo 1)
    D: via C  (costo 2)      G: via B  (costo 3)
```

**Reenvío de mensajes.** Los mensajes siguen efectivamente la ruta óptima:

| Mensaje | Ruta seguida | Saltos |
|---|---|---|
| A → G | A → B → F → G | 3 |
| H → I | H → F → D → I | 3 |

**Tiempos de convergencia** (tick de 5 s, timeout de vecino de 20 s):

| Escenario | Tiempo |
|---|---|
| Convergencia inicial de los 9 nodos | 5.0 s |
| Reconvergencia tras la caída de un nodo | 30.0 s |

**Caída y recuperación de un nodo.** Al matar el proceso del nodo D, sus cuatro
vecinos (C, E, F, I) reportaron el enlace caído al vencer el timeout y toda la
red recalculó sus tablas: el destino D desapareció de las tablas y las rutas que
pasaban por él se redirigieron. La ruta A → E, que originalmente era
A → C → D → E con costo 3, pasó a ser A → B → F → G → E con costo 4, y el mensaje
siguió llegando. Al volver a levantar D, los vecinos lo detectaron de nuevo y la
red regresó a las rutas óptimas originales.

## 5. Discusión

El comportamiento observado coincide con lo esperado teóricamente. La
convergencia inicial es muy rápida (una sola ronda de intercambio) gracias a los
*triggered updates*: como cada cambio se difunde de inmediato, la información
recorre el diámetro de la red sin esperar los ticks intermedios.

En cambio la reconvergencia ante la caída de un nodo es notablemente más lenta
(30 s frente a 5 s) y esa asimetría es inherente a DVR. Las buenas noticias
viajan rápido y las malas lento: una ruta nueva se anuncia en cuanto se conoce,
pero la desaparición de una ruta solo se detecta por ausencia, es decir cuando
vence el temporizador del vecino. Ese timeout es un compromiso: bajarlo acelera
la detección de fallas pero aumenta el riesgo de dar por caído un enlace que solo
perdió un paquete. Se fijó en cuatro veces el intervalo de tick.

El problema clásico de DVR es el *count-to-infinity*: cuando un enlace cae, dos
nodos pueden pasarse mutuamente rutas obsoletas e incrementar el costo de uno en
uno indefinidamente, convencidos de que el otro tiene un camino válido. En esta
implementación se atacó por tres vías complementarias: el split horizon con
poison reverse lo elimina entre pares de nodos, el recálculo completo evita
conservar rutas obsoletas cuando el vecino que las anunciaba las perdió, y el
tope de 16 acota los lazos que involucran a tres o más nodos. En las pruebas de
caída de nodo no se observó escalada de costos: el destino caído simplemente
desapareció de las tablas.

Comparado con Link State Routing, DVR intercambia mucha menos información —solo
con los vecinos y sin inundar la red— y su implementación es considerablemente
más simple, pero paga el precio de converger más lento ante fallas y de no poder
detectar lazos, porque ningún nodo tiene la vista completa de la topología para
verificar sus propias rutas.

## 6. Conclusiones

- DVR logra rutas óptimas sin que ningún nodo conozca la topología completa: la
  información se construye colectivamente a partir de intercambios locales.
- Las optimizaciones clásicas (split horizon con poison reverse, infinito
  acotado y triggered updates) no son opcionales en la práctica: sin ellas el
  algoritmo converge lento y es vulnerable al count-to-infinity.
- Aislar el medio detrás de una interfaz de transporte permitió desarrollar y
  probar todos los algoritmos con sockets locales y migrar a XMPP sin tocar ni el
  motor del nodo ni los algoritmos.

## 7. Referencias

- Kurose, J. y Ross, K. *Computer Networking: A Top-Down Approach*, capítulo 5:
  Distance-Vector (DV) Routing Algorithm.
- Tanenbaum, A. *Computer Networks*, sección 5.2.4: Distance Vector Routing y el
  problema de count-to-infinity.
- RFC 2453, *RIP Version 2* — infinito igual a 16, split horizon con poison
  reverse y triggered updates.
- Documentación de slixmpp: https://slixmpp.readthedocs.io
