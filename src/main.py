"""Orquestador del pipeline (pasos 1→7 del CLAUDE.md).

Dos ejes de configuración por variables de entorno:

  MODE      : "production" (default) | "test"
              - production: publica cada Feature Summary NUEVO (dedup contra
                processed_posts.json) y, solo en POST_MODE=webhook, registra su URL.
              - test: toma el Feature Summary más reciente, sin dedup ni registro.

  POST_MODE : "local" (default) | "webhook"
              - local: NO toca Slack. Guarda el JSON en output/last_block_kit.json
                y lo imprime, para validar en Block Kit Builder. No requiere Slack App.
              - webhook: POST real al Incoming Webhook (recién en la Fase Final).

Otras variables:
  SLACK_WEBHOOK_URL   : webhook de Slack (GitHub Secret). Solo se usa en POST_MODE=webhook.
  USE_LLM_SUMMARY     : "true"/"false" (default false). Flag de la fase LLM (no implementada).
  FEED_URL            : override opcional del feed.
  MAX_POST_AGE_DAYS   : antigüedad máxima de un post publicable (default 45; 0 desactiva).
                        El feed deja de traer el cuerpo de los posts viejos, así que
                        intentar procesarlos solo produce un ParseError. Ver fetch_feed.py.
  MIN_BODY_CHARS      : tamaño mínimo (chars) del cuerpo para considerarlo completo
                        (default 2000). Por debajo, el feed ya colapsó el post al
                        párrafo de presentación. Ver fetch_feed.py.
  PROCESSED_POSTS_FILE: override opcional de la ruta del registro.
  OUTPUT_FILE         : override opcional de la ruta del JSON local.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import fetch_feed
import format_slack
import parse_post
import post_to_slack

logger = logging.getLogger("powerbi_slack_bot")

# Archivos por defecto, relativos a la raíz del repo (un nivel arriba de src/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROCESSED = _REPO_ROOT / "processed_posts.json"
_DEFAULT_OUTPUT = _REPO_ROOT / "output" / "last_block_kit.json"


def _env_bool(nombre: str, default: bool = False) -> bool:
    val = os.environ.get(nombre)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_float(nombre: str, default: float) -> float:
    val = os.environ.get(nombre)
    if val is None or not val.strip():
        return default
    try:
        return float(val)
    except ValueError:
        logger.warning("%s=%r no es un número; se usa el default (%s).", nombre, val, default)
        return default


def _env_int(nombre: str, default: int) -> int:
    val = os.environ.get(nombre)
    if val is None or not val.strip():
        return default
    try:
        return int(val)
    except ValueError:
        logger.warning("%s=%r no es un entero; se usa el default (%s).", nombre, val, default)
        return default


def _cargar_procesados(path: Path) -> list[str]:
    if not path.exists():
        logger.info("No existe %s todavía; se asume lista vacía.", path.name)
        return []
    try:
        # utf-8-sig: el registro se edita a mano (ver README) y varios editores de
        # Windows guardan con BOM. Lee igual de bien los archivos sin BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig") or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} no es JSON válido: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"{path} debería contener una lista de URLs.")
    return data


def _guardar_procesados(path: Path, urls: list[str]) -> None:
    path.write_text(json.dumps(urls, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Registro actualizado (%d URLs) en %s.", len(urls), path.name)


def _aplicar_llm(post: parse_post.Post) -> parse_post.Post:
    """Punto de inserción de la fase LLM (resumen con IA). Aún NO implementado.

    Mantiene el flag USE_LLM_SUMMARY cableado sin construir la fase: si alguien lo
    activa antes de tiempo, falla de forma clara en vez de silenciosa.
    """
    try:
        import summarize_llm  # noqa: F401  (no existe hasta la fase LLM)
    except ImportError as exc:
        raise NotImplementedError(
            "USE_LLM_SUMMARY=true pero la fase LLM (summarize_llm.py) todavía no está "
            "implementada. Dejá el flag en false o pedí explícitamente iniciar esa fase."
        ) from exc
    return summarize_llm.summarize(post)  # pragma: no cover (fase LLM)


def _ruta_salida(base: Path, indice: int, total: int) -> Path:
    """Ruta del JSON local para el post `indice` de `total`.

    Con un solo post se usa `base` tal cual (el caso normal, y el que espera el
    README). Con varios hay que numerar: si no, cada post pisaría el JSON del
    anterior y solo sobreviviría el último, en silencio.
    """
    if total <= 1:
        return base
    return base.with_name(f"{base.stem}_{indice}{base.suffix}")


def _procesar_entrada(entry, *, use_llm: bool, post_mode: str,
                      webhook: str, output_path: Path) -> None:
    """Parsea una entrada, arma el mensaje y lo emite según POST_MODE."""
    post = parse_post.parse(entry)
    if use_llm:
        post = _aplicar_llm(post)

    payload = format_slack.build_message(
        post.titulo, post.fecha, post.bullets, post.url, post.secciones
    )
    post_to_slack.send(payload, mode=post_mode, webhook_url=webhook, output_path=output_path)


def main() -> int:
    # La consola de Windows por defecto usa cp1252 y rompe al imprimir "—"/emojis.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mode = os.environ.get("MODE", "production").strip().lower()
    post_mode = os.environ.get("POST_MODE", "local").strip().lower()
    use_llm = _env_bool("USE_LLM_SUMMARY", default=False)
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    feed_url = os.environ.get("FEED_URL", fetch_feed.DEFAULT_FEED_URL).strip()
    max_age = _env_float("MAX_POST_AGE_DAYS", fetch_feed.MAX_AGE_DAYS)
    min_body_chars = _env_int("MIN_BODY_CHARS", fetch_feed.MIN_BODY_CHARS)
    processed_path = Path(os.environ.get("PROCESSED_POSTS_FILE", str(_DEFAULT_PROCESSED)))
    output_path = Path(os.environ.get("OUTPUT_FILE", str(_DEFAULT_OUTPUT)))

    if post_mode not in {"local", "webhook"}:
        logger.error("POST_MODE inválido: %r (esperaba 'local' o 'webhook').", post_mode)
        return 2

    # MODE se valida igual de estricto que POST_MODE, y no por simetría: sin este
    # chequeo, cualquier valor distinto de "test" —un typo como "testing" o "tst"—
    # caía en producción y publicaba en el canal del equipo. El modo peligroso es el
    # default, así que un valor no reconocido tiene que frenar, no asumir.
    if mode not in {"production", "test"}:
        logger.error("MODE inválido: %r (esperaba 'production' o 'test').", mode)
        return 2

    logger.info("MODE=%s | POST_MODE=%s | USE_LLM_SUMMARY=%s", mode, post_mode, use_llm)

    # Solo nos interesan los resúmenes mensuales "Feature Summary", no los deep dives.
    # El filtro por antigüedad deja fuera los posts cuyo cuerpo el feed ya no trae.
    entries = fetch_feed.get_feature_summaries(
        feed_url, max_age_days=max_age, min_body_chars=min_body_chars,
    )

    if not entries:
        # Todos los Feature Summary del feed quedaron fuera, por antigüedad o porque
        # el feed ya colapsó su cuerpo. No es un error, pero sí es raro: el blog
        # publica todos los meses. Los WARNING de fetch_feed dicen cuál fue el motivo.
        logger.warning(
            "Ningún Feature Summary publicable (ventana de %.0f días / cuerpo mínimo "
            "%d chars). Nada que publicar. Si el blog realmente publicó algo reciente, "
            "revisar los WARNING de arriba y los umbrales MAX_POST_AGE_DAYS / MIN_BODY_CHARS.",
            max_age, min_body_chars,
        )
        return 0

    common = dict(use_llm=use_llm, post_mode=post_mode, webhook=webhook)

    if mode == "test":
        # Post más reciente, sin dedup ni escritura de registro.
        _procesar_entrada(entries[0], output_path=output_path, **common)
        logger.info("Modo test: no se toca processed_posts.json.")
        return 0

    # --- Modo producción ---
    procesados = _cargar_procesados(processed_path)
    nuevos = [e for e in entries if getattr(e, "link", "") not in procesados]

    if not nuevos:
        logger.info("Sin posts nuevos. Nada que publicar.")  # no es una falla
        return 0

    # Publicamos del más viejo al más nuevo para que queden en orden en el canal.
    logger.info("%d post(s) nuevo(s) para procesar.", len(nuevos))
    total = len(nuevos)
    for indice, entry in enumerate(reversed(nuevos), start=1):
        salida = _ruta_salida(output_path, indice, total)
        if post_mode == "local" and total > 1:
            logger.info("Post %d/%d -> %s", indice, total, salida.name)
        _procesar_entrada(entry, output_path=salida, **common)
        # El registro de duplicados SOLO se actualiza cuando hubo publicación real.
        # Se guarda post a post (no al final del loop) a propósito: si el siguiente
        # falla, lo ya publicado queda registrado y no se republica.
        if post_mode == "webhook":
            procesados.append(entry.link)
            _guardar_procesados(processed_path, procesados)

    if post_mode != "webhook":
        logger.info("POST_MODE=%s: no se modificó processed_posts.json.", post_mode)

    return 0


if __name__ == "__main__":
    sys.exit(main())
