"""Punto de entrada: navegación lateral."""

from __future__ import annotations

import streamlit as st

# Tipografía del menú de páginas (sin iconos en st.Page): más grande; el texto puede partir en 2 líneas.
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] a,
    [data-testid="stSidebarNav"] a span,
    section[data-testid="stSidebar"] nav[aria-label="Page navigation"] a {
        font-size: 1.22rem !important;
        line-height: 1.48 !important;
        font-weight: 560 !important;
        white-space: normal !important;
    }
    [data-testid="stSidebarNav"] li {
        margin-bottom: 0.4rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

lista = st.Page(
    "pages/lista_contratos.py",
    title="Lista de Contratos",
    default=True,
)
reglas = st.Page(
    "pages/reglas_calidad.py",
    title="Reglas y coherencia",
)
exploracion = st.Page(
    "pages/exploracion_estadistica.py",
    title="Indicadores y patrones",
)
mapa = st.Page(
    "pages/mapa_territorial.py",
    title="Mapa territorial",
)
nav = st.navigation([lista, reglas, exploracion, mapa])
nav.run()
