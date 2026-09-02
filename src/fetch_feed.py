"""Paso 1 del pipeline: obtener las entradas del feed RSS del blog de Power BI.

Descarga y procesa el feed oficial. Filtra las entradas para quedarse únicamente
con los resúmenes mensuales ("Feature Summary") recientes y con cuerpo completo,
descartando posts cuyo HTML ya fue colapsado por antigüedad.

Notas importantes:
- La URL "oficial" `https://powerbi.microsoft.com/en-us/blog/feed/` hace un 301
  y redirige al feed real de la comunidad (plataforma Khoros/Lithium):
  `https://community.fabric.microsoft.com/oxcrx34285/rss/board?board.id=fbc_pbiupdatesblog`
- Las PÁGINAS HTML del blog (tanto powerbi.microsoft.com como la del post en
  community.fabric.microsoft.com) devuelven 403 a los bots. Por eso NO fetcheamos
  la página del post: el propio `<description>` de cada entrada del feed ya trae el
  HTML completo del post, y de ahí extraemos los bullets (ver `parse_post.py`).
- El feed sí responde 200 siempre que se envíe un User-Agent de navegador.
- El feed trae el cuerpo completo del post SOLO durante unas semanas. Después lo
  colapsa al párrafo de presentación.el corte está entre los ~28 y los ~49 días. Un post viejo es IMPARSEABLE y
  no hay plan B, porque su página HTML devuelve 403
"""

from __future__ import annotations

import calendar
import logging
import re
import time

import feedparser
import requests

logger = logging.getLogger(__name__)

# El board publica varios tipos de post (deep dives, anuncios, etc.), pero al bot
# solo le interesan los resúmenes mensuales "Power BI <Mes> <Año> Feature Summary".
_FEATURE_SUMMARY = re.compile(r"feature\s+summary", re.IGNORECASE)

# Feed canónico. Se puede sobreescribir por variable de entorno FEED_URL (ver main.py).
DEFAULT_FEED_URL = (
    "https://community.fabric.microsoft.com/oxcrx34285/rss/board"
    "?board.id=fbc_pbiupdatesblog"
)

# Sin un UA de navegador la fuente responde 403.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30

# Antigüedad máxima de un post para considerarlo publicable (ver nota del módulo).
# 45 días: cómodamente por encima del ciclo mensual del blog, y por debajo del punto
# donde se observó que el feed ya había colapsado el cuerpo del post (49 días).
# Se puede sobreescribir por variable de entorno MAX_POST_AGE_DAYS (ver main.py).
MAX_AGE_DAYS = 45

# Tamaño mínimo del cuerpo para considerar que el feed todavía lo trae completo.
# Un Feature Summary completo mide decenas de miles de chars (42.600 el de julio
# 2026); una vez colapsado queda en ~318, apenas el párrafo de presentación. El
# umbral está lejos de ambos extremos a propósito: por debajo damos por colapsado
# el cuerpo (se saltea con WARNING, es esperable), y por encima el post SÍ se
# parsea, así un cambio real de estructura sigue fallando visible en parse_post.
MIN_BODY_CHARS = 2000


class FeedError(RuntimeError):
    """El feed no se pudo obtener o no se pudo parsear como RSS válido."""


def _antiguedad_en_dias(entry) -> float | None:
    """Días transcurridos desde la publicación de la entrada. None si no trae fecha."""
    fecha_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if fecha_struct is None:
        return None
    # feedparser entrega struct_time en UTC -> timegm (no mktime, que asume local).
    return (time.time() - calendar.timegm(fecha_struct)) / 86400


def get_body(entry) -> str:
    """HTML del post que trae la entrada del feed (`summary`, o `description` en su
    defecto). feedparser mapea `<description>` de RSS a `summary`, así que el
    segundo lookup casi nunca aporta — se mantiene solo como red de seguridad ante
    una entrada atípica. Compartido con `parse_post.parse()` para no duplicar el
    fallback en dos módulos.
    """
    return getattr(entry, "summary", None) or getattr(entry, "description", None) or ""


def _largo_cuerpo(entry) -> int:
    """Tamaño en chars del HTML del post que viene en la entrada del feed."""
    return len(get_body(entry))


def get_latest_entries(feed_url: str = DEFAULT_FEED_URL) -> list:
    """Devuelve las entradas del feed ordenadas por fecha de publicación (desc)."""
    logger.info("Descargando feed RSS: %s", feed_url)
    try:
        resp = requests.get(
            feed_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FeedError(f"No se pudo descargar el feed {feed_url}: {exc}") from exc

    parsed = feedparser.parse(resp.content)

    # `bozo` indica XML mal formado. Si además no hay entradas, es un error real.
    if parsed.bozo and not parsed.entries:
        raise FeedError(
            f"El contenido de {feed_url} no es un feed RSS válido: "
            f"{parsed.get('bozo_exception')!r}"
        )

    if not parsed.entries:
        raise FeedError(f"El feed {feed_url} no contiene entradas.")

    # `time.gmtime(0)` como último recurso: una entrada sin ninguna de las dos fechas
    # daría clave None y rompería la comparación con los struct_time de las demás.
    # Con el epoch queda al final del orden, que es donde corresponde.
    entries = sorted(
        parsed.entries,
        key=lambda e: e.get("published_parsed") or e.get("updated_parsed") or time.gmtime(0),
        reverse=True,
    )
    logger.info("Feed OK: %d entradas.", len(entries))
    return entries


def is_feature_summary(entry) -> bool:
    """True si la entrada es un resumen mensual "... Feature Summary"."""
    return bool(_FEATURE_SUMMARY.search(getattr(entry, "title", "") or ""))


def get_feature_summaries(feed_url: str = DEFAULT_FEED_URL,
                          max_age_days: float = MAX_AGE_DAYS,
                          min_body_chars: int = MIN_BODY_CHARS) -> list:
    """Como get_latest_entries, pero solo los Feature Summary mensuales publicables.

    Ordenados por fecha de publicación (desc). Aplica tres filtros:

    1. Por título: solo los "... Feature Summary". Si no queda NINGUNO, falla
       visible: es el síntoma de que el blog cambió el nombre de sus resúmenes.
    2. Por antigüedad: descarta los más viejos que `max_age_days`.
    3. Por cuerpo colapsado: descarta los que traen menos de `min_body_chars`. Es
       la garantía real, porque el feed re-fecha entradas viejas y por fecha pueden
       parecer nuevas.

    Con `max_age_days=0` o negativo se desactiva el filtro por antigüedad. El
    filtro por cuerpo no se desactiva: sin cuerpo no hay nada que publicar.
    """
    entries = [e for e in get_latest_entries(feed_url) if is_feature_summary(e)]
    if not entries:
        raise FeedError(
            "El feed no contiene ningún post 'Feature Summary'. "
            "¿Cambió el título de los resúmenes mensuales? Revisar fetch_feed.py."
        )
    logger.info("Feature Summaries encontrados: %d.", len(entries))

    if max_age_days <= 0:
        logger.warning("Filtro por antigüedad DESACTIVADO (max_age_days=%s).", max_age_days)

    vigentes = []
    for e in entries:
        titulo = getattr(e, "title", "")
        dias = _antiguedad_en_dias(e)

        if max_age_days > 0 and dias is not None and dias > max_age_days:
            # Su cuerpo ya no está en el feed: intentarlo solo produciría un ParseError.
            logger.warning(
                "Descartado por antigüedad (%.0f días > %.0f): %r. "
                "El feed ya no trae el cuerpo de este post.",
                dias, max_age_days, titulo,
            )
            continue

        largo = _largo_cuerpo(e)
        if largo < min_body_chars:
            # Pasa cuando el feed re-fecha un post viejo: por fecha parece nuevo,
            # pero el cuerpo ya quedó colapsado al párrafo de presentación.
            logger.warning(
                "Descartado por cuerpo colapsado (%d chars < %d): %r. "
                "El feed ya no trae el cuerpo completo de este post "
                "(fecha del feed: %.0f días de antigüedad).",
                largo, min_body_chars, titulo, dias if dias is not None else -1,
            )
            continue

        vigentes.append(e)

    logger.info("Feature Summaries publicables: %d.", len(vigentes))
    return vigentes
