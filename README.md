# SADAI — Auditoría y análisis de contratos SECOP II (local)

Este repo deja una app en **Streamlit** para explorar y auditar contratos de SECOP II desde un **`export.csv` local** (grande), usando **DuckDB** para consultar el CSV sin cargarlo completo a memoria.

## Cómo ejecutar

Desde la raíz del repo:

```bash
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run streamlit_app/app.py
```

La app usa variables del archivo `.env` (ver `.env.example`). Para el catálogo geográfico (depto/ciudad) se consulta la API de datos.gov.co con App Token.

## Datos de entrada

- **`export.csv`**: export local (no se comitea; está en `.gitignore`).
- **Catálogo depto/ciudad**: **siempre viene de la API** (no se usa JSON local como fallback para los selects).

## Vistas (front)

La navegación está en `streamlit_app/app.py` (multipage con `st.navigation`).

- **Lista de Contratos** (`streamlit_app/lista_contratos.py`)
  - Filtros: departamento, ciudad (opcional), año (según “Fecha de Inicio del Contrato”).
  - Tabla paginada desde `export.csv` usando DuckDB.

- **Reglas y coherencia** (`streamlit_app/reglas_calidad.py`)
  - Reglas determinísticas (auditoría de coherencia temporal, valor, texto).
  - KPIs + gráfico de distribución de alertas + tabla enriquecida (muestra) y descarga CSV.

- **Indicadores y patrones** (`streamlit_app/exploracion_estadistica.py`)
  - Dispersión valor vs duración.
  - Histograma de costo por día.
  - Top modalidades y mediana de valor.
  - Serie mensual de contratos.
  - Concentración proveedor–entidad.

- **Mapa territorial** (`streamlit_app/mapa_territorial.py`)
  - **Mapa 1**: Colombia completa (coroplética por departamento) para el año seleccionado.
  - **Mapa 2**: zoom al departamento del filtro y, si hay ciudad elegida, se resalta el **municipio** (capa encima).
  - Incluye ranking (barras) + descarga del agregado por departamento.

## “Análisis” implementado (resumen)

### Variables del export usadas

Las columnas vienen del `export.csv` (nombres con espacios). Ejemplos:

- Fechas: `Fecha de Firma`, `Fecha de Inicio del Contrato`, `Fecha de Fin del Contrato`
- Texto: `Objeto del Contrato`
- Ubicación: `Departamento`, `Ciudad`
- Monto: `Valor del Contrato` (se parsea a número limpiando `$`, comas y espacios)
- Claves para concentración: `Nit Entidad`, `Documento Proveedor`, `Proveedor Adjudicado`

### Derivadas

En `src/sadai/analitica_local.py`:

- **`duracion_dias`**: `date_diff('day', inicio, fin)` (si existen ambas fechas)
- **`longitud_objeto`**: `length(trim(objeto))`
- **`costo_por_dia`**: `valor_num / duracion_dias` (solo si ambos son > 0)
- **`indice_concentracion`**: \(\#contratos\_entidad\_proveedor / \#contratos\_entidad\) en el filtro

### Reglas determinísticas (ejemplos)

Se exponen como flags (0/1):

- **Fin antes de inicio**
- **Firma después de inicio**
- **Valor inválido** (no parseable o ≤ 0)
- **Objeto muy corto** (< 30 caracteres)
- **Duración negativa** (consistencia con fechas)

> Nota: “antigüedad del contratista” no está implementada todavía porque requiere un dataset externo (p.ej. RUES) para enlazar por NIT.

## Estructura relevante

- `src/sadai/export_csv_duckdb.py`: conteo / paginación desde `export.csv`
- `src/sadai/analitica_local.py`: reglas + métricas + agregados
- `src/sadai/geo_catalog.py`: cliente API para depto/ciudad (catálogo)
- `src/sadai/colombia_geo.py`: GeoJSON departamentos (DANE) + homologación
- `src/sadai/colombia_municipios.py`: GeoJSON municipios (DANE) + match municipio dentro del depto
- `streamlit_app/`: UI multipágina

## GeoJSON (sin red / performance)

La app puede descargar GeoJSON públicos (DANE 2018). Si prefieres no depender de internet, guarda:

- Departamentos: `data/geo/departamentos.geojson`
- Municipios: `data/geo/municipios.geojson`

## Notas de rendimiento

- `export.csv` puede ser muy grande; DuckDB leerá el archivo en cada consulta (con caché de Streamlit por parámetro).
- Para acelerar a futuro: convertir a **Parquet** o persistir a una DB local (DuckDB `.duckdb`) y apuntar la app a eso.

