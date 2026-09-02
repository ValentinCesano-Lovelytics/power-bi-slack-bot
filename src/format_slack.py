"""Paso 5 del pipeline: armar el mensaje en formato Slack Block Kit.

Recibe los datos parseados y devuelve el payload listo para postear al webhook.

Formato del mensaje:
  - Header con el mes/año         -> "Power BI Updates Summary - July 2026"
  - Lista de bullets (features)   -> agrupados por categoría para legibilidad
  - Link a la publicación original

Nota sobre el campo `text` de nivel superior: Slack documenta que, cuando el payload
trae `blocks`, el `text` NO se renderiza en el mensaje pero es el fallback que usan
las notificaciones (push, desktop) y los lectores de pantalla. Por eso el payload
se arma acá, en `build_message()`.

Nota sobre jerarquía visual: Slack Block Kit no permite cambiar el tamaño de fuente.
Las categorías van en *negrita* para no competir con el `header` principal del mensaje.
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)

# Límites de Slack Block Kit que respetamos para no romper el POST.
_HEADER_MAX = 150       # plain_text de un header block
_SECTION_TEXT_MAX = 2900  # margen bajo el límite duro de 3000 de un section block
_FALLBACK_MAX = 300     # el fallback solo alimenta la notificación; no hace falta más


def _truncar(texto: str, limite: int, *, contexto: str | None = None) -> str:
    """Corta `texto` a `limite` chars. Si `contexto` viene, loguea un WARNING al
    truncar: el contenido que se pierde (ej. features de una sección) desaparece
    del mensaje en silencio si nadie lo nota.
    """
    if len(texto) <= limite:
        return texto
    if contexto:
        logger.warning(
            "%s truncado de %d a %d chars: el contenido excedente no llega al mensaje.",
            contexto, len(texto), limite,
        )
    return texto[: limite - 1].rstrip() + "…"


def _escape_mrkdwn(texto: str) -> str:
    """Escapa los caracteres de control que Slack interpreta en mrkdwn.

    Las categorías y features vienen de headings HTML vía `get_text()`, que ya
    decodificó entidades (`&amp;` -> `&`). Sin este escape, un heading como
    "Slicers & filters" llegaría con el `&` crudo, y uno con `<...>` rompería el
    mensaje en silencio. Nunca se aplica al markup que arma el propio
    `format_slack` (los `*` de negrita o el `<url|texto>` del link).
    """
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_blocks(titulo: str, fecha: str, bullets: Sequence[str], url: str,
                 secciones: Sequence | None = None) -> list[dict]:
    """Construye la lista de bloques de Slack.

    - `titulo`, `fecha`, `url`: strings.
    - `bullets`: lista plana de features.
    - `secciones`: opcional; si se pasa (lista de objetos con `.categoria` y
      `.features`), se agrupan los bullets por categoría. Si es None, se usa la
      lista plana `bullets`.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _truncar(titulo, _HEADER_MAX), "emoji": True},
        }
    ]

    if fecha:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🗓️ Update from {fecha}"}],
            }
        )

    blocks.append({"type": "divider"})

    if secciones:
        for sec in secciones:
            lineas = "\n".join(f"• {_escape_mrkdwn(feat)}" for feat in sec.features)
            texto = f"*{_escape_mrkdwn(sec.categoria)}*\n{lineas}"
            texto = _truncar(texto, _SECTION_TEXT_MAX, contexto=f"Sección {sec.categoria!r}")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": texto}})
    else:
        lineas = "\n".join(f"• {_escape_mrkdwn(b)}" for b in bullets)
        lineas = _truncar(lineas, _SECTION_TEXT_MAX, contexto="Lista de bullets")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lineas}})

    if url:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🔗 <{url}|Read the original post>"},
            }
        )

    return blocks


def build_fallback_text(titulo: str, bullets: Sequence[str],
                        secciones: Sequence | None = None) -> str:
    """Texto de notificación (campo `text` del payload). Ver nota del módulo.

    No se renderiza en el mensaje —los `blocks` mandan—, así que va en texto plano:
    sin mrkdwn, sin emojis, y corto, porque una notificación se lee de un vistazo.
    """
    if secciones:
        cantidad = sum(len(sec.features) for sec in secciones)
    else:
        cantidad = len(bullets)

    unidad = "update" if cantidad == 1 else "updates"
    return _truncar(f"{titulo} — {cantidad} {unidad}", _FALLBACK_MAX)


def build_message(titulo: str, fecha: str, bullets: Sequence[str], url: str,
                  secciones: Sequence | None = None) -> dict:
    """Payload completo del mensaje, listo para el webhook o para Block Kit Builder.

    Es `build_blocks()` más el campo `text` de nivel superior que Slack usa como
    fallback de notificaciones y accesibilidad (ver nota del módulo). Este es el
    punto de entrada que usa el pipeline; `build_blocks()` queda como API pública
    para quien solo quiera los bloques.
    """
    return {
        "text": build_fallback_text(titulo, bullets, secciones),
        "blocks": build_blocks(titulo, fecha, bullets, url, secciones),
    }
