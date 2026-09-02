import format_slack
import parse_post


def _secciones():
    return [
        parse_post.Seccion(categoria="Reporting", features=["Feature A", "Feature B"]),
        parse_post.Seccion(categoria="Modeling", features=["Feature C"]),
    ]


def test_build_message_devuelve_text_y_blocks():
    payload = format_slack.build_message(
        "Power BI Updates Summary - July 2026", "July 22, 2026",
        ["Feature A", "Feature B", "Feature C"],
        "https://example.com/post", _secciones(),
    )

    assert set(payload) == {"text", "blocks"}
    assert payload["text"]
    assert isinstance(payload["blocks"], list)


def test_build_blocks_estructura_header_fecha_secciones_link():
    blocks = format_slack.build_blocks(
        "Power BI Updates Summary - July 2026", "July 22, 2026",
        ["Feature A", "Feature B", "Feature C"],
        "https://example.com/post", _secciones(),
    )

    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "Power BI Updates Summary - July 2026"
    assert blocks[1]["type"] == "context"
    assert "July 22, 2026" in blocks[1]["elements"][0]["text"]

    section_texts = [b["text"]["text"] for b in blocks if b["type"] == "section"]
    assert any("*Reporting*" in t and "Feature A" in t and "Feature B" in t for t in section_texts)
    assert any("*Modeling*" in t and "Feature C" in t for t in section_texts)
    assert any("Read the original post" in t and "https://example.com/post" in t for t in section_texts)


def test_build_blocks_sin_secciones_usa_lista_plana():
    blocks = format_slack.build_blocks(
        "Titulo", "", ["Feature A", "Feature B"], "", secciones=None,
    )

    section = next(b for b in blocks if b["type"] == "section")
    assert "• Feature A" in section["text"]["text"]
    assert "• Feature B" in section["text"]["text"]
    # Sin fecha ni url: no hay bloque context ni el segundo divider/link.
    assert not any(b["type"] == "context" for b in blocks)


def test_build_fallback_text_pluraliza_segun_cantidad():
    uno = format_slack.build_fallback_text("Titulo", [], secciones=[
        parse_post.Seccion(categoria="Reporting", features=["Feature A"]),
    ])
    varios = format_slack.build_fallback_text("Titulo", [], secciones=_secciones())

    assert uno == "Titulo — 1 update"
    assert varios == "Titulo — 3 updates"


def test_truncar_no_toca_texto_corto():
    assert format_slack._truncar("hola", 10) == "hola"


def test_truncar_corta_y_agrega_elipsis():
    resultado = format_slack._truncar("a" * 20, 10)
    assert len(resultado) == 10
    assert resultado.endswith("…")


def test_escape_mrkdwn_escapa_ampersand_y_angulares():
    assert format_slack._escape_mrkdwn("Slicers & filters") == "Slicers &amp; filters"
    assert format_slack._escape_mrkdwn("a < b > c") == "a &lt; b &gt; c"


def test_build_blocks_loguea_warning_al_truncar_una_seccion(caplog):
    seccion_gigante = parse_post.Seccion(
        categoria="Reporting",
        features=[f"Feature número {i} con texto de relleno" for i in range(200)],
    )

    with caplog.at_level("WARNING", logger="format_slack"):
        blocks = format_slack.build_blocks("Titulo", "", [], "", [seccion_gigante])

    section = next(b for b in blocks if b["type"] == "section")
    assert len(section["text"]["text"]) <= format_slack._SECTION_TEXT_MAX
    assert section["text"]["text"].endswith("…")
    assert any("truncado" in r.message for r in caplog.records)
    assert any("Reporting" in r.message for r in caplog.records)


def test_build_blocks_no_loguea_cuando_no_hace_falta_truncar(caplog):
    with caplog.at_level("WARNING", logger="format_slack"):
        format_slack.build_blocks("Titulo", "", ["Feature A"], "", None)

    assert caplog.records == []


def test_build_blocks_escapa_categoria_y_features_con_caracteres_de_control():
    secciones = [
        parse_post.Seccion(categoria="Q&A", features=["<script>alert(1)</script>", "*bold* fake"]),
    ]
    blocks = format_slack.build_blocks("Titulo", "", [], "", secciones)

    section = next(b for b in blocks if b["type"] == "section")
    texto = section["text"]["text"]
    assert "*Q&amp;A*" in texto
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in texto
    assert "<script>" not in texto
