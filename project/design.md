**# Diseño del agente**

Este documento debe completarse **\*\*antes\*\*** de la implementación principal del agente.

Use sus propias palabras y notación. No reemplace este archivo por una transcripción

del enunciado. Las subsecciones existen para que no se le olvide una decisión;

usted decide el contenido.

El entorno, según las propiedades vistas en clase, es totalmente observable,

determinista, secuencial, estático, discreto y de agente único. Bajo esas

condiciones la solución es un **\*\*plan completo\*\*** y el marco correcto es la

búsqueda clásica. Justifique cada componente con ese marco (AIMA, cap. 3).

\---

**## Estado**

**### Definición formal**

\`\`\`text

s = ⟨ P, B, C, E, M ⟩

\`\`\`

\- **\*\*P (posición):\*\*** la zona donde está el robot en este momento. Es un solo valor, por ejemplo \`"Z2"\`.

\- **\*\*B (batería):\*\*** un número entero entre 0 y la batería máxima del escenario.

\- **\*\*C (carga / cargo):\*\*** lo que el robot lleva encima en este momento, contado por tipo de ítem (no por objeto individual). Por ejemplo \`{wrench: 1, fuse\_box: 1}\`.

\- **\*\*E (entorno):\*\*** el estado de todo lo que es "permanente" en la instalación: puertas (\`LOCKED\`/\`UNLOCKED\`), paneles (\`PENDING\`/\`RESTORED\`), generadores (\`PENDING\`/\`ACTIVATED\`), etc.

\- **\*\*M (mapa de ítems en el piso):\*\*** cuántas unidades de cada tipo de ítem quedan tiradas en cada zona en este momento. Por ejemplo \`{(Z2, fuse\_box): 1}\`.

Este estado es lo que el robot necesita mirar para saber, en cualquier instante, qué puede hacer a continuación. No incluye nada de "cómo llegó hasta aquí" — eso vive en el Nodo (ver más abajo).

**### Por qué cada variable es necesaria**

El criterio que usamos es el mismo que da la guía: **\*\*una variable pertenece al estado si y solo si dos configuraciones que difieran solo en ella pueden diferir en las acciones legales futuras o en su resultado.\*\***

\- **\*\*P\*\*** es necesaria porque \`MOVE\` y \`INTERACT\` solo son legales desde ciertas zonas. Sin P no sabríamos ni siquiera qué acciones están al alcance del robot.

\- **\*\*B\*\*** es necesaria porque una \`MOVE\` cara puede volverse ilegal si no queda batería suficiente. Dos estados iguales en todo lo demás pero con distinta batería pueden tener distinto futuro: uno puede llegar a la próxima zona y el otro no. Por eso la batería es parte de la *\*situación física\** del robot, tal como dice el enunciado en 2.1, y no solo un dato de historial.

\- **\*\*C\*\*** es necesaria porque las operaciones (\`INTERACT\`) exigen tener ciertas herramientas o materiales encima. Sin C no sabríamos si el robot puede instalar un fusible o reparar el sistema de enfriamiento. También determina cuánto espacio libre queda para recoger algo nuevo.

\- **\*\*E\*\*** es necesaria porque ahí viven las dependencias entre operaciones (por ejemplo, no se puede instalar el fusible si la puerta sigue cerrada) y porque la meta de la misión se verifica sobre E.

\- **\*\*M\*\*** es necesaria porque, si el robot puede soltar objetos (\`DROP\`, sección 2.2 del enunciado), la posición de los ítems **\*\*no\*\*** se puede deducir del escenario inicial: un ítem puede terminar en una zona distinta a la que empezó. Sin M el agente no sabría qué hay disponible para recoger en cada zona.

**### Qué información se deriva y NO se almacena**

Todo lo que es una **\*\*constante del escenario\*\*** (no cambia mientras el robot actúa) se queda fuera del estado y se consulta directamente del archivo \`scenario.json\`:

\- el peso y tipo (herramienta/material) de cada ítem,

\- el grafo de corredores y sus costos,

\- la capacidad máxima de carga,

\- la batería máxima,

\- las precondiciones y efectos de cada operación.

Si un dato se puede calcular a partir del estado actual más estas constantes (por ejemplo, "cuánto peso llevo encima" se calcula sumando pesos según C), tampoco se guarda por separado.

**### Qué pertenece al historial de búsqueda y no al estado físico**

El **\*\*costo acumulado\*\*** \`g(n)\`, el **\*\*puntero al nodo padre\*\*** y la **\*\*acción que trajo hasta aquí\*\*** describen *\*cómo llegó el robot a esta situación\**, no *\*en qué situación está\**. Esa información vive en el **\*\*Nodo de búsqueda\*\***, no en el estado:

\`\`\`text

Nodo = ⟨ estado, padre, acción, g ⟩

\`\`\`

Esto importa porque dos caminos de acciones completamente distintos pueden terminar exactamente en el mismo mundo físico (mismo P, C, E, M). Si mezcláramos \`g\` o el padre dentro del estado, esos dos caminos nunca se reconocerían como "el mismo lugar" y CLOSED no podría fusionarlos — la búsqueda trataría el grafo como si fuera un árbol y reexploraría el mismo mundo una y otra vez.

**### Cuándo dos configuraciones son el mismo estado**

Dos configuraciones son el mismo estado si tienen el mismo P, el mismo C, el mismo E y el mismo M.

Dos detalles de implementación son clave para que esta igualdad funcione bien:

1\. **\*\*Los ítems del mismo tipo no llevan identificador individual\*\*** (sección 2.2 del enunciado). C y M se representan como *\*contadores por tipo\** (por ejemplo, "2 fusibles", no "fusible #1" y "fusible #2"). Así, dos formas distintas de llegar a "tengo 2 fusibles" son el mismo estado, en vez de ser tratadas como situaciones distintas.

2\. **\*\*Las estructuras se guardan en una forma canónica\*\*** (tuplas ordenadas, no diccionarios con orden arbitrario), para que dos estados físicamente iguales produzcan siempre el mismo \`hash\` y pasen la comparación \`==\`, sin importar en qué orden se insertaron los datos. Sin esto, Graph Search no reconoce estados repetidos y el espacio de búsqueda se dispara.

**\*\*Sobre la batería:\*\*** B forma parte de la situación física del robot y puede cambiar qué acciones futuras son posibles. Sin embargo, para evitar explorar por separado todas las cantidades posibles de batería, la búsqueda agrupa los nodos por la configuración del mundo **\`⟨P, C, E, M⟩\`** y mantiene para cada configuración los pares **\`(g, B)\` que no están dominados**. Por tanto, dos nodos con distinta batería no se consideran automáticamente intercambiables: se comparan mediante la regla de dominancia de la sección "Batería como recurso". Solo se descarta un nodo cuando existe otro que llega a la misma configuración del mundo con costo menor o igual y batería mayor o igual. Así se conserva la información de batería necesaria para no perder un plan óptimo, sin convertir cada nivel de batería en un estado independiente.

**### Relevancia: objetos que ya no cambian el futuro**

Los cambios en E son **\*\*monótonos\*\***: una puerta que ya se abrió no se vuelve a cerrar, un panel restaurado no vuelve a \`PENDING\`. Esto tiene una consecuencia directa sobre los objetos: **\*\*una vez que un ítem cumplió la función para la que servía, ya no puede habilitar ninguna acción futura\*\***.

Ejemplo: una tarjeta de acceso (\`keycard\`) que ya abrió la puerta que tenía que abrir. Da igual si esa tarjeta queda en el inventario del robot o tirada en cualquier zona — ninguna operación pendiente la necesita, así que su ubicación exacta ya no distingue estados relevantes para el plan. Si el agente sigue generando \`PICKUP\`/\`DROP\` para ese tipo de ítem, lo único que logra es multiplicar el número de estados con permutaciones de "dónde quedó el objeto muerto", sin acercarse nunca a la meta (que se define solo sobre E, nunca sobre C o M).

Por eso el agente clasifica cada ítem como **\*\*relevante\*\*** o **\*\*irrelevante\*\*** en cada estado:

\`\`\`text

un ítem i es relevante en el estado s

  si y solo si

existe una operación pendiente (no cumplida todavía en E)

que necesita ese ítem como herramienta o como material

\`\`\`

Un ítem que deja de ser relevante nunca se vuelve a generar como \`PICKUP\`, y es el primer candidato para \`DROP\` cuando hace falta liberar espacio (ver sección de Acciones). Ignorarlo no pierde el plan óptimo: cualquier plan que cargue o suelte un ítem irrelevante se puede acortar quitando esas dos acciones, sin romper ninguna precondición futura, y el plan resultante cuesta menos o igual. Es decir, esas acciones nunca pueden ser parte de un plan de costo mínimo.

\---

**## Acciones**

\`\`\`text

Acción            | Precondiciones                                                        | Efectos                                    | Costo

\------------------|------------------------------------------------------------------------|---------------------------------------------|------------------------

MOVE(p → p')       | robot en p; existe corredor (p,p'); entorno cumple los requisitos       | posición pasa a p';                         | costo\_energía(p,p') + 1

                    | del corredor (si los hay); batería ≥ costo\_energía(p,p')                | batería -= costo\_energía(p,p')              |

\------------------|------------------------------------------------------------------------|---------------------------------------------|------------------------

PICKUP(i)          | hay al menos 1 unidad de i en la zona actual;                          | +1 unidad de i en la carga;                 | 1

                    | cabe en la capacidad restante; i es relevante                          | -1 unidad de i en el piso de esa zona       |

\------------------|------------------------------------------------------------------------|---------------------------------------------|------------------------

DROP(i)             | el robot carga al menos 1 unidad de i;                                 | -1 unidad de i en la carga;                 | 1

                    | se cumple la regla de poda (ver abajo)                                  | +1 unidad de i en el piso de la zona actual |

\------------------|------------------------------------------------------------------------|---------------------------------------------|------------------------

INTERACT(op)        | robot en la zona de la operación; tiene las herramientas requeridas    | el entorno cambia según lo que defina la    | energía(op) + 1

                    | (no se consumen); tiene los materiales requeridos (sí se consumen);    | operación; se descuentan los materiales     |

                    | se cumplen las dependencias de entorno; la operación aún no está hecha | consumidos de la carga                      |

\------------------|------------------------------------------------------------------------|---------------------------------------------|------------------------

RECHARGE            | robot está en una zona de recarga; batería < batería máxima            | batería = batería máxima                    | 1

\`\`\`

\`INTERACT(op)\` es una acción genérica que representa cualquier operación concreta del escenario: abrir una puerta, instalar un fusible, reparar el sistema de enfriamiento, activar el generador, etc. Cada operación trae su propia lista de herramientas, materiales, dependencias de entorno y efectos, definidos en \`scenario.json\`.

**### \`Applicable\` interno vs legalidad del contrato**

El simulador (contrato) dice cuándo un paso es **\*\*legal\*\***: por ejemplo, permite hacer \`DROP\` de cualquier ítem cargado en cualquier zona, en cualquier momento. Pero el generador de sucesores del agente no tiene que ofrecer todas las acciones legales — solo las que un plan **\*\*óptimo\*\*** podría llegar a necesitar. Esa es la diferencia entre "legal" y "relevante para buscar".

**\*\*Por qué no se genera \`DROP\` en cada estado con carga.\*\*** Si el agente generara un \`DROP\` por cada ítem cargado en cada estado, el problema dejaría de ser "5 zonas y unas tareas" para convertirse en "en cuál de las 5 zonas quedó cada unidad de cada objeto en cada momento posible". Eso es una explosión combinatoria del número de sucesores por estado (el factor de ramificación \`b\`), y además crea ciclos inútiles del tipo \`DROP → PICKUP → DROP → …\` que la búsqueda tendría que detectar en tiempo de ejecución en vez de evitar por diseño.

**\*\*La regla que sí se usa:\*\***

1\. \`PICKUP(i)\` solo se genera si \`i\` es relevante en ese estado (sección anterior) y si cabe en la capacidad libre. Recoger algo que ninguna operación pendiente necesita no puede ayudar a llegar a la meta.

2\. \`DROP(i)\` solo se genera cuando la capacidad está llena **\*\*y\*\*** hay en la zona actual un ítem relevante que el robot necesita recoger pero no le cabe. Es decir, \`DROP\` siempre es un paso para habilitar un \`PICKUP\` importante, nunca un fin en sí mismo. Entre los ítems cargados, primero se ofrece soltar los que ya son irrelevantes (ya cumplieron su función); solo si todos los ítems cargados siguen siendo relevantes se ofrece \`DROP\` para cada uno de ellos como última opción, y ahí el número de alternativas está acotado por la capacidad máxima, no por la cantidad de zonas ni de tipos de ítem.

**\*\*Por qué esta restricción no pierde el plan óptimo.\*\*** Cualquier plan que use un \`PICKUP\`/\`DROP\` de un ítem irrelevante en ese momento se puede acortar quitando ese par de acciones: como ninguna operación pendiente lo necesita, quitar esas acciones no rompe ninguna precondición futura, y el plan resultante cuesta al menos 2 unidades menos. Así que un plan que use acciones irrelevantes nunca puede ser el de menor costo — el agente puede ignorarlas con total seguridad.

\---

**## Modelo de transición**

\`\`\`text

s  --a-->  s'     solo si a ∈ Applicable(s)

\`\`\`

\`Result(s, a)\` es una función determinista y parcial: dado un estado y una acción aplicable, produce exactamente un estado nuevo (nunca modifica el estado recibido, siempre construye uno nuevo).

Lo que puede cambiar según el tipo de acción:

\- **\*\*MOVE:\*\*** cambia P (nueva zona) y B (se descuenta el costo del corredor). C, E, M quedan igual.

\- **\*\*PICKUP:\*\*** cambia C (+1 del ítem) y M (-1 del ítem en esa zona). P, B, E quedan igual.

\- **\*\*DROP:\*\*** cambia C (-1 del ítem) y M (+1 del ítem en esa zona). P, B, E quedan igual.

\- **\*\*INTERACT:\*\*** cambia E (según los efectos de la operación) y, si la operación consume materiales, también cambia C. Si la operación tiene costo de energía, también cambia B. P y M quedan igual.

Todo lo que una acción no menciona explícitamente se conserva sin cambios (nada se pierde "por accidente"). Después de cada transición, el estado nuevo se vuelve a poner en su forma canónica (tuplas ordenadas, sin ceros) para que la comparación de igualdad y el hash sigan funcionando correctamente contra CLOSED.

\---

**## Prueba de meta**

\`\`\`text

Goal(s) ⟺ todos los sistemas críticos en E están en "RESTORED" o "ACTIVATED"

\`\`\`

La meta se revisa **\*\*únicamente sobre E\*\*** (el entorno). No exige nada sobre en qué zona terminó el robot, cuánta batería le queda, ni qué lleva o dejó de llevar cargado. Las puertas, paneles y demás elementos de E son en su mayoría **\*\*medios\*\*** para llegar a la meta (por ejemplo, la puerta debe abrirse porque bloquea el camino hacia el panel), salvo los que el escenario marca explícitamente como parte de la misión (los sistemas críticos que deben quedar \`RESTORED\`/\`ACTIVATED\`).

Esto es intencional: la misión se verifica contra el estado final del mundo, no contra si se ejecutó una lista de pasos predefinida. Dos planes con secuencias de acciones completamente distintas son igual de válidos si ambos dejan a E cumpliendo la condición anterior.

\---

**## Función de costo**

\`\`\`text

g(n) = Σ costo(acción\_k)   para cada acción en el camino desde la raíz hasta n

costo(a) = energía(a) + 1

\`\`\`

El costo de un plan es la suma de los costos **\*\*oficiales\*\*** de cada acción, no el número de pasos. \`energía(a)\` es lo que la acción gasta de batería (0 para la mayoría de \`PICKUP\`/\`DROP\`/\`INTERACT\`, variable para cada \`MOVE\` según el corredor). El \`+1\` fijo se suma en todas las acciones para romper empates a favor de planes con menos pasos cuando dos caminos gastan la misma energía — sin él, un plan de 3 acciones y uno de 30 acciones que consuman la misma batería total serían indistinguibles para el algoritmo, y eso no es lo que "mejor plan" significa en la práctica (más pasos = más tiempo de misión y más puntos donde algo puede salir mal).

Minimizar pasos **\*\*no\*\*** es lo mismo que minimizar costo en este mundo: los corredores tienen costos distintos, así que una ruta con más saltos puede terminar siendo más barata en batería que un atajo de un solo salto caro. \`g(n)\` captura eso; contar pasos no.

\---

**## Estrategia de búsqueda**

Se elige **\*\*Uniform Cost Search (UCS) con Graph Search\*\*** (lista CLOSED), vista en clase.

**\*\*Por qué no BFS.\*\*** BFS encuentra la solución con menos aristas (menos acciones), no la de menor costo. Como los corredores tienen costos distintos, la solución con menos pasos puede no ser la más barata en energía — BFS solo es óptimo cuando todas las acciones cuestan lo mismo, y aquí no es el caso.

**\*\*Por qué no DFS.\*\*** DFS no garantiza ni completitud (puede quedarse dando vueltas en un ciclo de corredores de ida y vuelta si no se controla explícitamente) ni optimalidad (se compromete con la primera solución que encuentra, sin comparar costos entre ramas).

**\*\*Por qué UCS funciona aquí:\*\***

\- **\*\*Completitud:\*\*** sí, porque el factor de ramificación es finito y todo costo de acción es ≥ 1 (nunca 0 ni negativo).

\- **\*\*Optimalidad:\*\*** sí, porque UCS siempre expande el nodo de frontera con menor \`g\` (usando una cola de prioridad) y **\*\*comprueba la meta al extraer el nodo de la frontera, no al generarlo\*\***. Si se comprobara al generar, se podría aceptar un camino a la meta que no es el más barato, porque en ese momento todavía podría haber otro nodo en la frontera con menor \`g\` que también llegue a la meta.

\- **\*\*Costo de camino:\*\*** garantizado óptimo por la razón anterior.

\- **\*\*Tiempo y espacio:\*\*** en el peor caso son exponenciales en la profundidad de la solución, pero el factor de ramificación real \`b\` **\*\*no depende del tamaño del mapa\*\*** — depende de cuántos sucesores genera \`Applicable(s)\` en cada estado. El peligro real no es el número de zonas, es cuántos \`PICKUP\`/\`DROP\` se generan por estado. Con la poda descrita en la sección de Acciones, \`b\` queda acotado por: los corredores que salen de la zona actual, las operaciones aplicables en esa zona, y como mucho la capacidad de carga (para el caso límite de \`DROP\`) — nunca por la cantidad de objetos del escenario multiplicada por la cantidad de zonas.

\- **\*\*Cuándo se rompen las garantías:\*\*** si apareciera algún costo 0 o negativo, UCS podría dejar de ser óptimo o incluso no terminar (necesitaría un algoritmo tipo Bellman-Ford); si los estados no se canonicalizan bien (por ejemplo, si el orden de inserción de un diccionario cambiara el hash), CLOSED no reconocería estados repetidos y la búsqueda podría no terminar nunca en la práctica; si la frontera (OPEN) no se vaciara correctamente o se dejaran nodos sin marcar como cerrados, se podría reexpandir indefinidamente el mismo estado.

Graph Search mantiene una estructura CLOSED indexada por la configuración canónica del mundo **\`⟨P,C,E,M⟩\`**. Para cada configuración se conserva la frontera de pares **\`(g,B)\` no dominados**. Así, si dos caminos llegan al mismo mundo físico, no se exploran ambos automáticamente: el nuevo nodo se descarta si ya existe otro camino que lo domina; si no hay dominancia, se conservan ambos porque pueden tener posibilidades futuras diferentes debido a su batería. Esta regla permite controlar los ciclos y estados repetidos sin perder una alternativa que pueda ser necesaria para completar la misión.

**### Batería como recurso**

La batería sí es parte del estado físico (sección 2.1 del enunciado), pero eso **\*\*no\*\*** obliga a tratar cada nivel de batería como si fuera un mundo distinto — si se hiciera así, UCS podría intentar explorar todos los "paseos" posibles que solo gastan y recargan batería sin llegar a ningún lado nuevo, hasta agotar memoria.

La solución es una regla de **\*\*dominancia\*\***: si dos caminos llegan a la **\*\*misma\*\*** configuración del mundo (misma zona, misma carga, mismo entorno, mismo mapa de ítems en el piso) y uno de ellos lo logra con **\*\*costo acumulado menor o igual\*\*** y **\*\*batería restante mayor o igual\*\***, el segundo camino nunca puede producir una continuación mejor que el primero — está dominado y se puede descartar sin riesgo de perder el plan óptimo.

\`\`\`text

camino 1 domina a camino 2 (misma configuración del mundo)

  si y solo si

g1 ≤ g2   y   batería1 ≥ batería2

\`\`\`

Si ninguno domina al otro (por ejemplo, un camino es más barato pero deja menos batería que el otro), **\*\*se conservan los dos\*\***, porque el más caro podría ser el único que deja batería suficiente para terminar la misión. Por eso CLOSED no guarda un solo "mejor" registro por configuración del mundo, sino la lista de puntos (costo, batería) que no están dominados entre sí para esa configuración, y cualquier nodo nuevo se compara contra esa lista antes de decidir si se descarta o se explora.

**Regla de implementación:** al insertar un nodo en CLOSED, primero se compara su par **\`(g,B)\`** con los pares no dominados de la misma configuración **\`⟨P,C,E,M⟩\`**. Si existe un par **\`(g₁,B₁)\`** con `g₁ ≤ g` y `B₁ ≥ B`, el nodo nuevo se descarta. Si no existe, se eliminan de CLOSED los pares que el nuevo nodo domine (`g ≤ gᵢ` y `B ≥ Bᵢ`) y se conserva el nuevo. De esta manera, CLOSED representa únicamente los caminos que todavía pueden aportar una ventaja real a la búsqueda.

\---

**## Formulación y tamaño del espacio (obligatorio)**

**\*\*1. ¿Por qué «5 zonas, \~10 objetos, capacidad 3» puede generar millones de nodos en un UCS ingenuo?\*\***

Porque el tamaño del espacio de estados no depende solo del número de zonas, sino de todas las combinaciones posibles de "quién lleva qué" y "qué quedó tirado dónde". Si el agente permite \`DROP\` de cualquier objeto en cualquier momento, cada uno de los \~10 objetos puede terminar en cualquiera de las 5 zonas o dentro de la carga del robot — eso son del orden de 6 posiciones posibles por objeto (5 zonas + "cargado"), elevado a la cantidad de objetos. Con 10 objetos eso ya son del orden de 6¹⁰ (más de 60 millones) combinaciones de "dónde está cada cosa", multiplicado además por las combinaciones de posición del robot, batería y entorno. El mapa sigue siendo pequeño; el espacio de estados que un agente mal formulado terminaría explorando no lo es.

**\*\*2. ¿Qué papel tiene \`DROP\` en esa explosión?\*\***

\`DROP\` es la acción que introduce esa combinatoria: es la única forma en que un objeto puede "moverse" a una zona distinta de donde empezó o de donde lo llevó el robot. Si se genera sin restricciones, por cada estado con carga se abren tantas ramas como objetos cargados, y como \`PICKUP\` puede deshacer un \`DROP\` (y viceversa), también aparecen ciclos \`DROP ↔ PICKUP\` que obligan a Graph Search a hacer trabajo extra solo para descartarlos, en vez de que esas ramas nunca se generen.

**\*\*3. ¿Qué podas o abstracciones aplicó y por qué no pierden el óptimo (sound)?\*\***

Se aplicaron dos podas, ambas descritas en la sección de Acciones:

\- \`PICKUP(i)\` solo se genera si \`i\` es relevante (alguna operación pendiente lo necesita).

\- \`DROP(i)\` solo se genera cuando la capacidad está llena y hace falta espacio para recoger algo relevante; entre los cargados, se prioriza soltar los que ya son irrelevantes.

Ambas son *\*sound\** (no pierden el óptimo) por el mismo argumento: cualquier plan que use un \`PICKUP\`/\`DROP\` de un ítem irrelevante en ese momento se puede acortar quitando ese par de acciones sin romper ninguna precondición futura y sin aumentar el costo — así que un plan de costo mínimo nunca las necesita, y el agente puede dejar de generarlas sin arriesgar la optimalidad.

**\*\*4. ¿Por qué no es solución subir la capacidad, bajar las estaciones o ignorar la batería?\*\***

Porque esos valores son **\*\*parámetros del escenario\*\*** (\`scenario.json\`), no parte del diseño del agente. Subir la capacidad de carga solo pospone el problema a una instancia con más objetos o menos capacidad; bajar el número de estaciones de recarga o quitar restricciones de batería cambia las reglas del mundo, no la formulación de la búsqueda. El profesor probará el agente con **\*\*otras instancias\*\*** del mismo tipo de escenario, con distintos mapas, capacidades y niveles de batería — si la solución dependiera de los números concretos de \`scenario.json\` en vez de depender de cómo se define \`Applicable(s)\`, dejaría de funcionar apenas cambiara la instancia. La poda de \`DROP\`/\`PICKUP\` por relevancia, en cambio, funciona igual sin importar cuántas zonas, objetos o cuánta batería tenga el escenario, porque no depende de esos números: depende de si un ítem todavía puede habilitar alguna operación pendiente.