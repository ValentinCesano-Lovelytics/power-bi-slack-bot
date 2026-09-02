"""Paso 3 del pipeline: parseo estructural del post.

Extrae la estructura del post parseando directamente el HTML que viene
dentro de la entrada del feed (`entry.summary`). 
Identifica los `H2` como categorías y los `H3` como las features individuales.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

import fetch_feed

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """El HTML del post no tiene la estructura esperada (fallo visible, no silencioso)."""


# El mensaje de Slack va íntegramente en inglés.
_MESES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# En el título del post: "Power BI July 2026 Feature Summary"
_TITULO_MES_ANIO = re.compile(
    r"(" + "|".join(_MESES) + r")\s+(\d{4})",
    re.IGNORECASE,
)

# Secciones que NO interesan: solo publicamos updates core del producto.
# Se comparan normalizadas (minúsculas, sin puntuación) para tolerar variaciones
# de wording entre posts ("Third-party custom visuals" / "Third party visuals").
_SECCIONES_EXCLUIDAS = {
    "events and announcements",
    "third party custom visuals",
}


def _clave_seccion(categoria: str) -> str:
    """Normaliza el nombre de una categoría para compararlo con la lista de exclusión."""
    return re.sub(r"[^a-z0-9]+", " ", categoria.lower()).strip()


@dataclass
class Seccion:
    """Una categoría del post (H2) con sus features (H3)."""

    categoria: str
    features: list[str] = field(default_factory=list)


@dataclass
class Post:
    """Resultado del parseo, listo para formatear a Slack."""

    titulo: str          # encabezado ya formateado, ej: "Power BI Updates Summary - July 2026"
    fecha: str           # fecha legible, ej: "July 22, 2026"
    url: str             # link a la publicación original
    bullets: list[str]   # lista plana de features
    secciones: list[Seccion] = field(default_factory=list)  # agrupadas por categoría


def _mes_por_numero(numero: int) -> str:
    """Nombre del mes en inglés a partir de su número (1-12); '' si está fuera de rango."""
    if 1 <= numero <= 12:
        return _MESES[numero - 1]
    return ""


def _titulo_encabezado(titulo_original: str, fecha_struct) -> str:
    """Construye "Power BI Updates Summary - <Month> <Year>" a partir del título del post.

    Usa el mes/año del título (que es el mes de la actualización). Si no se puede
    extraer, cae a la fecha de publicación del feed.
    """
    m = _TITULO_MES_ANIO.search(titulo_original or "")
    if m:
        mes = m.group(1).capitalize()
        anio = m.group(2)
        return f"Power BI Updates Summary - {mes} {anio}"

    if fecha_struct is not None:
        # Fallback a la fecha de publicación del feed.
        mes = _mes_por_numero(fecha_struct.tm_mon)
        return f"Power BI Updates Summary - {mes} {fecha_struct.tm_year}"

    # Último recurso: el título original, para no fallar por un cambio de wording.
    logger.warning("No se pudo extraer mes/año del título %r; se usa tal cual.", titulo_original)
    return titulo_original or "Power BI Updates Summary"


def _fecha_legible(fecha_struct) -> str:
    """'July 22, 2026' a partir del struct_time del feed."""
    if fecha_struct is None:
        return ""
    mes = _mes_por_numero(fecha_struct.tm_mon)
    return f"{mes} {fecha_struct.tm_mday}, {fecha_struct.tm_year}"


def _limpiar(texto: str) -> str:
    """Colapsa espacios y saca saltos de línea de un heading."""
    return re.sub(r"\s+", " ", texto).strip()


def parse(entry) -> Post:
    """Parsea una entrada del feed y devuelve un `Post`.

    `entry` es un objeto de feedparser (ver fetch_feed.get_latest_entries).
    Lanza `ParseError` si no encuentra la estructura de features esperada.
    """
    titulo_original = getattr(entry, "title", "") or ""
    url = getattr(entry, "link", "") or ""
    fecha_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)

    html = fetch_feed.get_body(entry)
    if not html:
        raise ParseError(
            f"La entrada {url!r} no trae contenido HTML (summary/description vacío)."
        )

    soup = BeautifulSoup(html, "html.parser")

    secciones: list[Seccion] = []
    seccion_actual: Seccion | None = None

    # Recorremos los headings en orden de documento. H2 abre categoría, H3 es feature.
    for h in soup.find_all(["h2", "h3"]):
        texto = _limpiar(h.get_text())
        if not texto:
            continue
        if h.name == "h2":
            seccion_actual = Seccion(categoria=texto)
            secciones.append(seccion_actual)
        else:  # h3
            if seccion_actual is None:
                # Feature sin H2 previo: la agrupamos en una sección genérica.
                seccion_actual = Seccion(categoria="Updates")
                secciones.append(seccion_actual)
            seccion_actual.features.append(texto)

    # Descartamos categorías sin features (ej. el "Until next month" de cierre).
    secciones = [s for s in secciones if s.features]

    if not secciones:
        raise ParseError(
            f"No se encontraron features (H3) en el post {url!r}. "
            "¿Cambió la estructura HTML del blog? Revisar parse_post.py."
        )

    # Nos quedamos solo con los updates core del producto.
    descartadas = [s.categoria for s in secciones if _clave_seccion(s.categoria) in _SECCIONES_EXCLUIDAS]
    if descartadas:
        logger.info("Secciones excluidas del resumen: %s.", ", ".join(descartadas))
    secciones = [s for s in secciones if _clave_seccion(s.categoria) not in _SECCIONES_EXCLUIDAS]

    bullets = [feat for s in secciones for feat in s.features]

    if not bullets:
        raise ParseError(
            f"El post {url!r} no dejó ninguna sección después de filtrar las excluidas "
            f"({', '.join(sorted(_SECCIONES_EXCLUIDAS))}). "
            "¿Cambiaron los nombres de las categorías? Revisar _SECCIONES_EXCLUIDAS en parse_post.py."
        )

    post = Post(
        titulo=_titulo_encabezado(titulo_original, fecha_struct),
        fecha=_fecha_legible(fecha_struct),
        url=url,
        bullets=bullets,
        secciones=secciones,
    )
    logger.info(
        "Post parseado: %r — %d features en %d secciones.",
        post.titulo, len(bullets), len(secciones),
    )
    return post
