"""Paso 6 del pipeline: salida del mensaje, en uno de dos modos (POST_MODE).

- `local`: NO hace ningún request a Slack. Guarda el JSON de Block Kit en
  `output/last_block_kit.json` y lo imprime por consola, listo para pegar en
  https://app.slack.com/block-kit-builder y validar el formato visualmente.
- `webhook`: hace el POST real al Incoming Webhook.

Este módulo es el único punto que depende de si el webhook ya existe. El resto
del pipeline es idéntico en ambos modos.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# output/last_block_kit.json en la raíz del repo (un nivel arriba de src/).
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / "last_block_kit.json"


class SlackError(RuntimeError):
    """El POST al webhook de Slack falló."""


def _emitir_local(payload: dict, output_path: Path) -> None:
    """Guarda el JSON en disco y lo imprime, para Block Kit Builder."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(payload, indent=2, ensure_ascii=False)
    output_path.write_text(texto + "\n", encoding="utf-8")
    logger.info("POST_MODE=local: JSON guardado en %s", output_path)
    logger.info("Pegalo en https://app.slack.com/block-kit-builder para validar el formato.")
    print(texto)


def _emitir_webhook(payload: dict, webhook_url: str) -> None:
    """POST real al Incoming Webhook de Slack."""
    if not webhook_url:
        raise SlackError(
            "POST_MODE=webhook pero falta SLACK_WEBHOOK_URL. "
            "Configuralo como variable de entorno / GitHub Secret."
        )
    logger.info("POST_MODE=webhook: publicando en Slack (%d bloques)...", len(payload["blocks"]))
    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        # Solo el tipo de excepción, nunca el str: los errores de `requests` suelen
        # incluir la URL completa, y esa URL ES el secreto. En GitHub Actions el
        # secret queda enmascarado, pero una corrida local lo imprimiría en consola.
        # `from None` es deliberado: con `from exc` el traceback encadenado volvería
        # a imprimir el mensaje original —con la URL— al propagar.
        raise SlackError(
            f"No se pudo conectar con el webhook de Slack ({type(exc).__name__}). "
            "Revisar conectividad y que SLACK_WEBHOOK_URL siga siendo válido."
        ) from None

    if resp.status_code != 200 or resp.text.strip().lower() != "ok":
        raise SlackError(
            f"Slack rechazó el mensaje: HTTP {resp.status_code} — {resp.text[:300]!r}"
        )
    logger.info("Mensaje publicado en Slack correctamente.")


def send(payload: dict, mode: str = "local", *,
         webhook_url: str | None = None,
         output_path: Path | str = DEFAULT_OUTPUT_PATH) -> None:
    """Emite el mensaje según `mode` ("local" o "webhook").

    - `local`:   guarda/imprime el JSON (no toca la red).
    - `webhook`: hace el POST real usando `webhook_url`.

    `payload` es el mensaje completo de Slack (`format_slack.build_message()`), o sea
    `{"text": ..., "blocks": [...]}`. Se emite idéntico en ambos modos a propósito: lo
    que se valida en Block Kit Builder tiene que ser exactamente lo que se publica.
    """
    mode = (mode or "local").strip().lower()

    if mode == "webhook":
        _emitir_webhook(payload, webhook_url or "")
    elif mode == "local":
        _emitir_local(payload, Path(output_path))
    else:
        raise ValueError(f"POST_MODE desconocido: {mode!r} (esperaba 'local' o 'webhook').")
