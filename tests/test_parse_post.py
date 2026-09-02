import time

import pytest

import parse_post
from conftest import load_july_2026_entry, make_entry

_JULY_EXCLUDED = {"events and announcements", "third party custom visuals"}


def test_parse_fixture_extrae_titulo_y_fecha():
    post = parse_post.parse(load_july_2026_entry())

    assert post.titulo == "Power BI Updates Summary - July 2026"
    assert post.fecha == "July 22, 2026"
    assert post.url == (
        "https://community.fabric.microsoft.com/t5/Power-BI-Updates-Blog/"
        "Power-BI-July-2026-Feature-Summary/ba-p/5303533"
    )


def test_parse_fixture_excluye_secciones_no_core():
    post = parse_post.parse(load_july_2026_entry())

    categorias = {parse_post._clave_seccion(s.categoria) for s in post.secciones}
    assert categorias.isdisjoint(_JULY_EXCLUDED)
    # Las secciones core del post de julio siguen presentes.
    assert {"General", "Reporting", "Modeling", "Mobile"} <= {s.categoria for s in post.secciones}


def test_parse_fixture_bullets_plano_coincide_con_secciones():
    post = parse_post.parse(load_july_2026_entry())

    esperado = [feat for s in post.secciones for feat in s.features]
    assert post.bullets == esperado
    assert len(post.bullets) > 0
    assert "TMDL View on the Web" in post.bullets


def test_parse_cuerpo_colapsado_lanza_parse_error():
    entry = make_entry(
        title="Power BI June 2026 Feature Summary",
        summary="<p>Welcome to the June 2026 Power BI feature summary!</p>",
    )
    with pytest.raises(parse_post.ParseError, match="No se encontraron features"):
        parse_post.parse(entry)


def test_parse_sin_contenido_lanza_parse_error():
    entry = make_entry(title="Power BI August 2026 Feature Summary", summary="")
    with pytest.raises(parse_post.ParseError, match="no trae contenido"):
        parse_post.parse(entry)


def test_parse_solo_secciones_excluidas_lanza_parse_error():
    html = (
        "<h2>Events and Announcements</h2><h3>Meetup en Barcelona</h3>"
        "<h2>Third-party custom visuals</h2><h3>Gantt by Profitbase</h3>"
    )
    entry = make_entry(title="Power BI August 2026 Feature Summary", summary=html)
    with pytest.raises(parse_post.ParseError, match="no dejó ninguna sección"):
        parse_post.parse(entry)


def test_parse_feature_sin_h2_previo_cae_en_seccion_generica():
    html = "<h3>Feature suelta antes de cualquier categoría</h3><h2>Reporting</h2><h3>Otra feature</h3>"
    entry = make_entry(title="Power BI August 2026 Feature Summary", summary=html)

    post = parse_post.parse(entry)

    assert post.secciones[0].categoria == "Updates"
    assert post.secciones[0].features == ["Feature suelta antes de cualquier categoría"]


def test_titulo_encabezado_usa_mes_y_anio_del_titulo():
    fecha_struct = time.strptime("2026-01-15", "%Y-%m-%d")
    titulo = parse_post._titulo_encabezado("Power BI July 2026 Feature Summary", fecha_struct)
    assert titulo == "Power BI Updates Summary - July 2026"


def test_titulo_encabezado_cae_a_fecha_de_publicacion_sin_mes_en_titulo():
    fecha_struct = time.strptime("2026-08-01", "%Y-%m-%d")
    titulo = parse_post._titulo_encabezado("Power BI Feature Summary", fecha_struct)
    assert titulo == "Power BI Updates Summary - August 2026"


def test_titulo_encabezado_ultimo_recurso_sin_titulo_ni_fecha():
    assert parse_post._titulo_encabezado("", None) == "Power BI Updates Summary"
    assert parse_post._titulo_encabezado(None, None) == "Power BI Updates Summary"
