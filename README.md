# Auditor de posicionamiento para clínicas y laboratorios dentales

Herramienta del curso de Vertical AI. El cursillista escribe su web, su ciudad y un tratamiento, y recibe un informe con dos vías separadas:

1. **Búsqueda en Google**: en cuántas búsquedas sale su web y en qué puesto.
2. **Pregunta a una IA**: en cuántas de 20 preguntas reales la IA recomienda su clínica.

En cada vía muestra el ranking real, las búsquedas y respuestas literales de las que sale cada porcentaje, las tres que más salen, qué tienen sus webs que a la del cursillista le falta, y qué hacer (con instrucciones según la web esté hecha con WordPress, Wix u otro gestor). El informe se guarda en PDF desde el navegador.

## Archivos

| Archivo | Qué es |
|---|---|
| `audit.py` | Todo el análisis. Solo usa la biblioteca estándar de Python 3. |
| `server.py` | Servidor HTTP y cola de análisis. |
| `index.html` | La pantalla (una sola página, sin dependencias). |
| `google_safari.applescript` | Búsqueda en Google mediante Safari. Solo para uso local en Mac. |
| `Abrir auditor.command` | Lanzador de doble clic para Mac. |
| `render.yaml` | Definición del servicio para Render. |

## De dónde salen los datos

| Dato | Uso local (Mac) | Servidor |
|---|---|---|
| Resultados de Google | Abre Safari y lee los resultados (sin clave) | Serper.dev con `SERPER_API_KEY` |
| Respuestas de la IA | ChatGPT instalado en el Mac, con su sesión | API de OpenAI con `OPENAI_API_KEY` |
| Si falta la fuente de Google | — | Usa DuckDuckGo y el informe avisa de que no es Google |
| Si falta la fuente de IA | — | La vía de IA muestra una estimación y lo avisa |

El servidor no puede usar Safari ni la aplicación de ChatGPT: **sin las dos claves, la versión desplegada no da datos reales de Google ni de IA.**

## Variables de entorno

| Variable | Para qué | Obligatoria en servidor |
|---|---|---|
| `PORT` | Puerto (Render la define sola) | Sí |
| `HOST` | Dirección de escucha. En Render se pone sola a `0.0.0.0` | No |
| `CLAVE_ACCESO` | Contraseña que pide la pantalla. Sin ella, cualquiera con el enlace gasta el saldo de las APIs | Sí |
| `OPENAI_API_KEY` | Consultas a la IA con búsqueda web | Sí |
| `OPENAI_MODEL` | Modelo de OpenAI que se usa (por defecto `gpt-5`). Debe admitir la herramienta `web_search` | Revisar |
| `SERPER_API_KEY` | Resultados reales de Google (google.serper.dev) | Sí |
| `N_PREGUNTAS_IA` | Preguntas a la IA por análisis (por defecto 20). Menos preguntas = menos coste y porcentaje menos estable | No |
| `ANALISIS_SIMULTANEOS` | Análisis en paralelo (por defecto 2) | No |

## Arrancar en local

```bash
python3 server.py
```

Abre http://localhost:4274. En Mac, la primera vez hay que aceptar que Terminal controle Safari.

## Desplegar en Render

1. New → Blueprint → elegir este repositorio (lee `render.yaml`).
2. Rellenar en el panel las variables marcadas como secretas (`CLAVE_ACCESO`, `OPENAI_API_KEY`, `SERPER_API_KEY`).
3. Desplegar. La pantalla indica bajo el formulario qué fuentes ha detectado.

## API (para integrarlo en la plataforma del curso)

Todas las llamadas llevan la cabecera `X-Clave: <CLAVE_ACCESO>` si hay contraseña.

- `GET /api/config` → fuentes disponibles y si hace falta contraseña.
- `GET /api/audit?url=&ciudad=&tratamiento=&negocio=&modo=` → `{"id": "..."}`. `negocio`: `clínica dental` o `laboratorio dental`. `modo`: `ambos`, `google` o `ia`.
- `GET /api/estado?id=...` → `{"estado": "en_cola|en_marcha|hecho", "resultado": {...}}`. Consultar cada pocos segundos; un análisis completo tarda entre 1 y 4 minutos.

## Estado de las pruebas

Probado con datos reales (noviembre de 2026, Madrid; implantes, carillas y prótesis de zirconio):

- Uso local completo: Google mediante Safari, IA mediante ChatGPT instalado, informe en pantalla.
- Acceso con contraseña, cola de análisis y bloqueo de direcciones internas.

**Sin probar** (no había claves al escribirlo):

- `pedir_openai_api` (API de OpenAI con `web_search` y salida con esquema JSON). Revisar el nombre del modelo y el formato de la respuesta.
- `buscar_google` (Serper.dev).

## Limitaciones conocidas

- El porcentaje de la IA varía entre dos análisis iguales (hasta unos 20 puntos con 20 preguntas). El orden entre clínicas es estable; la cifra exacta no.
- Google: solo resultados orgánicos. No lee el bloque del mapa ni los anuncios, y el orden depende de la ubicación desde la que se consulta.
- Las señales de la web se detectan por código y palabras clave; pueden fallar con webs poco habituales. Las webs que se dibujan con JavaScript no se pueden leer y el informe lo indica.
- A veces un directorio se cuela como si fuera una clínica entre las primeras de Google.
- Los trabajos se guardan en memoria: se pierden al reiniciar y no sirven con más de una instancia.
- El bloqueo de direcciones internas comprueba la dirección pedida, no cada redirección.
- El informe dice qué tienen las webs que más salen; no demuestra que eso sea la causa ni garantiza una posición.
