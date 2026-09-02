
# Power BI Updates Slack Bot

Bot serverless que publica automáticamente un resumen de las novedades del blog oficial de actualizaciones de Power BI en un canal de Slack. Funciona de manera desatendida mediante GitHub Actions.

Cada publicación contiene:
* **Encabezado:** Indica el mes y año correspondiente (ej: `Power BI Updates Summary - July 2026`).
* **Novedades (Bullets):** Extraídas del post oficial y agrupadas por categoría funcional.
* **Enlace directo:** Redirección a la publicación original para ampliar detalles.

El contenido se formatea íntegramente en inglés, y las secciones que no corresponden a actualizaciones core del producto (como *Events and Announcements* o *Third-party custom visuals*) son excluidas automáticamente.

## Arquitectura y Flujo de Datos

```
[GitHub Actions: cron semanal | disparo manual]
        │
        ▼
[fetch_feed]  Descarga el feed RSS y filtra los posts "Feature Summary" mensuales
        │
        ▼
[parse_post]  Extrae título, fecha, features (bullets) y URL del HTML del post
        │
        ▼
[format_slack]  Arma el mensaje en Slack Block Kit
        │
        ▼
[post_to_slack]  POST_MODE=local  → guarda output/last_block_kit.json (Block Kit Builder)
                 POST_MODE=webhook → POST real al Incoming Webhook
        │
        ▼
[processed_posts.json]  Registra la URL publicada (solo en webhook+producción)
```

El pipeline no requiere bases de datos. Utiliza el archivo local `processed_posts.json` para registrar las URLs ya procesadas, garantizando que no se generen alertas duplicadas en el canal.

**Consideraciones sobre la fuente de datos:**
* El bot consume el feed RSS de la comunidad oficial (plataforma Fabric), ya que las páginas HTML web rechazan las peticiones automatizadas (HTTP 403).
* El feed RSS integra el cuerpo completo en HTML, de donde se extrae la jerarquía de `<h2>` y `<h3>`.
* Tras un período aproximado de 4-6 semanas, la fuente colapsa la estructura HTML del feed a un simple párrafo introductorio. Para asegurar la integridad del parseo, la herramienta descarta artículos con una antigüedad mayor a `MAX_POST_AGE_DAYS` (45 días) o cuyo tamaño sea inferior a `MIN_BODY_CHARS` (2000 caracteres).

## Estructura del repo

```
├── src/
│   ├── fetch_feed.py     # descarga y filtra el feed RSS
│   ├── parse_post.py     # extrae título, fecha, bullets y URL
│   ├── format_slack.py   # arma el JSON de Block Kit
│   ├── post_to_slack.py  # salida local (JSON) o webhook (POST real)
│   └── main.py           # orquesta todo (MODE + POST_MODE)
├── .github/workflows/run.yml
├── processed_posts.json        # registro de URLs ya publicadas (arranca en [])
├── requirements.txt
└── README.md
```

## Configuración y Variables de Entorno

El orquestador soporta las siguientes variables de entorno para modificar su ejecución en flujos CI/CD:

| Variable | Default | Descripción |
|---|---|---|
| `MODE` | `production` | `production` (deduplicación activa y registro de post) o `test` (procesa el resumen más reciente sin registrarlo). |
| `POST_MODE` | `local` | `local` (exporta JSON local sin consumir API de Slack) o `webhook` (realiza un POST real al canal). |
| `SLACK_WEBHOOK_URL` | — | URL del Incoming Webhook. Obligatorio si `POST_MODE=webhook`. |
| `MAX_POST_AGE_DAYS` | `45` | Filtro de descarte por antigüedad. |
| `USE_LLM_SUMMARY` | `false` | Flag estructural para futura fase de inteligencia artificial. |

## El registro de publicados (`processed_posts.json`)

Es la única memoria del bot: una lista de **URLs ya publicadas**.

**Regla de oro:** el registro **solo se escribe cuando `MODE=production` y
`POST_MODE=webhook`**, es decir, cuando hubo publicación real.

### Precargarlo a mano

Sirve para decirle al bot «este post ya lo doy por publicado, no lo mandes».

El archivo se lee con `utf-8-sig`, así que tolera que un editor de Windows lo guarde
con BOM. Si el JSON es inválido, el bot falla con un mensaje explícito en vez de
asumir que no hay nada publicado.

## Ejecución Local y Depuración

Para probar cambios sin el riesgo de enviar mensajes a Slack, el proyecto cuenta con un modo de ejecución seguro:

```bash
pip install -r requirements.txt
MODE=test POST_MODE=local python src/main.py
```

Este comando imprime la estructura completa y genera un archivo en `output/last_block_kit.json`. Copia el contenido de ese archivo en el [Block Kit Builder](https://app.slack.com/block-kit-builder) de Slack para validar visualmente la renderización de la interfaz.

## Despliegue en GitHub Actions

La automatización reside en `.github/workflows/run.yml`:
* **Automático (Cron):** Se dispara semanalmente. Detecta nuevos "Feature Summary" y los publica. 
* **Manual (Workflow Dispatch):** Habilita la selección explícita del modo de entorno y salida. En modo `local`, genera un artefacto (`block-kit-json`) descargable con la estructura del mensaje.

**Requisitos para el entorno corporativo:**
1. Crear una Slack App en el workspace y generar un **Incoming Webhook** asociado a un canal restrictivo (solo lectura).
2. Guardar la URL proporcionada como el secreto `SLACK_WEBHOOK_URL` en el repositorio.
3. Habilitar **Read and write permissions** en las opciones de Actions para autorizar el commit automático sobre `processed_posts.json`.

## Integración de IA Generativa (Pendiente)

El proyecto incluye el diseño de software necesario para integrar un modelo de lenguaje en el futuro (mediante `USE_LLM_SUMMARY=true`). Esta fase opcional procesará el array de *bullets* crudos mediante herramientas como Gemini para generar un nivel adicional de síntesis ejecutiva antes de inyectarlo en el formato Block Kit de Slack.
