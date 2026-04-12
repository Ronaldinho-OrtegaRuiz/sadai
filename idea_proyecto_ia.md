1. Resumen Ejecutivo.

   1. Propósito del proyecto.

      El presente proyecto desarrolla e implementa un Sistema de Detección de Anomalías automatizado, enfocado en la fiscalización preventiva de la contratación pública en Colombia. Utilizando los datos abiertos de la plataforma SECOP II, el sistema emplea algoritmos de Aprendizaje no Supervisado para identificar registros contractuales que presentan comportamientos atípicos o desviaciones estadísticas significativas respecto a patrones normales de contratación en el departamento de Bolívar.

   2. Justificación técnica.

      La complejidad y el masivo volumen de datos registrados en la contratación estatal hacen que la supervisión manual sea ineficiente y propensa a errores. Este sistema aborda dicha problemática mediante una arquitectura de dos capas:

      1. Capa 1 (Reglas de negocio): Filtros determinísticos basados en umbrales estadísticos y desviaciones estándar.

      2. Capa 2 (Inteligencia Artificial): Implementación del algoritmo Isolation Forest, seleccionado por su capacidad superior para aislar observaciones anómalas en espacios multidimensionales sin requerir datos previamente etiquetados.

   3. Alcance y objetivos.

      El alcance se limita a los procesos contractuales registrados entre 2024 y 2026 en la jurisdicción de Bolívar. El objetivo principal no es emitir juicios de valor sobre la legalidad de los contratos, sino proveer a las entidades de control y a la ciudadanía una herramienta de auditoría inteligente que priorice casos de alta sospecha casos con alta sospecha (outliers) basados en variables críticas como el valor del contrato, la modalidad de selección, el objeto contractual y el tiempo de ejecución.

   4. Impacto esperado.

      Se espera que la implementación de este prototipo reduzca el tiempo de respuesta en la detección de posibles irregularidades, permitiendo una transición de una vigilancia reactiva a un monitoreo proactivo basado en evidencia de datos, fortaleciendo la transparencia en el uso de recursos públicos.

2. Definición del Problema

   1. Contexto.  
      La plataforma SECOP II representa el salto de Colombia hacia la contratación pública electrónica. Sin embargo, esta digitalización ha generado un ecosistema de Big Data gubernamental que crece de forma exponencial. Diariamente se registran miles de procesos que incluyen contratos de obra, prestación de servicios, suministros y consultorías. Para un departamento como Bolívar, con una dinámica administrativa compleja que abarca desde la Alcaldía de Cartagena hasta municipios   
   2. Brecha: Las entidades de control suelen actuar *post-mortem*. Se necesita una detección de "señales de alerta" en tiempo real.

   3. Alcance: Contratación pública en el departamento de Bolívar (2024-2026).

3. Marco Técnico.

   1. Lenguaje: Python 3.12 (por su ecosistema maduro en Ciencia de Datos).

   2. Adquisición de Datos: Socrata Open Data API (SODA) con sodapy.

   3. Algoritmo Principal: Isolation Forest.  
      Justificación: A diferencia de otros algoritmos, Isolation Forest no intenta modelar los puntos "normales", sino que "aísla" las anomalías, lo cual es más eficiente en datasets de alta dimensionalidad como los contratos estatales.

4. Solución.

   1. Arquitectura de la solución:

      El proyecto se divide en dos fases críticas que actúan sobre los datos obtenidos de SODA:

      1. Capa 1 (Reglas de Negocio): Filtros determinísticos: esta capa actúa como primer tamiz de sentido común, estadístico y legal. El sistema ejecuta:

         1. Detección de valores extremos: Identificación de contratos cuento valor\_del\_contrato supere en 3 desviaciones estándar la media de su categoría.

         2. Validación de Consistencia: Marcado automático de registros con duraciones de ejecución iguales a cero, negativas, o donde la fecha de firma es incoherente con el inicio del contrato.

         3. Alertas de Concentración: Identificación nit\_contratista que acumulen múltiples adjudicaciones por “Contratación Directa” en ventanas de tiempo inferiores a 30 días.

      2. Capa 2 (Detección multivariable): este motor busca combinaciones inusuales que individualmente podrían parecer normales:

         1. Entrada (Features): Se alimenta de un vector compuesto por valor\_normalizado, plazo\_ejecucion, puntuacion\_modalidad y la métrica calculada costo\_por\_dia.

         2. Lógica de aislamiento: El algoritmo particiona los datos hasta aislar cada observación. Los contratos que requieren menos particiones para ser aislados reciben un Anomaly Score más alto, indicando que su estructura es atípica comparada con la masa de datos de Bolívar. 

   2. Flujo de Operación:

      1. Ingesta: Conexión segura a SODA API con App Token.

      2. Transformación: Limpieza y creación de nuevas variables.

      3. Detección: Ejecución secuencial de Capa 1 y Capa 2\.

      4. Carga: Guardado de resultados en la base de datos local.

      5. Consulta: Despliegue de alertas en la interfaz gráfica.

   3. Procedimiento:

      1. Configuración de Acceso: Obtención del App Token en el portal de Datos Abiertos de Colombia y configuración de variables de entorno (`.env`).

      2. Extracción con SoQL: Consulta filtrada a la API de SECOP II (`jbjy-vk9h`) limitando los resultados al departamento de Bolívar y años 2024-2026.

      3. Pipeline de Procesamiento: Ejecución secuencial de los scripts de limpieza, aplicación de la Capa 1 (Reglas) y entrenamiento del modelo de la Capa 2 (IA).

           
5. Ingeniería de Características (Feature Engineering).

   1. Métricas de Tiempo y Costo:

      1. costo\_por\_dia: (Valor del contrato / Duración en días). Permite identificar contratos inflados con duraciones artificialmente cortas.

      2. `desviacion_canon_sector`: Diferencia porcentual entre el valor del contrato y la mediana de contratos del mismo sector (ej. papelería vs. infraestructura).

   2. Métricas de Riesgo y Perfilamiento:

      1. `indice_concentracion_proveedor`: Porcentaje de contratos que un mismo NIT ha ganado dentro de una sola entidad territorial en el último año.

      2. `antiguedad_relacion_contractual`: Días transcurridos entre la creación de la empresa (o su primer contrato en SECOP) y la adjudicación del contrato actual.

   3. Métricas de Modalidad y Competencia:

      1. `puntuacion_riesgo_modalidad`: Peso numérico asignado según la transparencia.

         1. Licitación Pública: 1 (Bajo riesgo).

         2. Selección Abreviada: 5 (Riesgo medio).

         3. Contratación Directa: 10 (Riesgo alto).

      2. `ratio_adjudicacion_directa`: Relación entre el valor total contratado directamente vs. mediante concurso público por una misma entidad.

   4. Análisis de Objeto: 

      1. `longitud_objeto_contractual`: extensión de objetos de contratos extremadamente cortos o ambiguos (ej. “Suministros varios”).

6. Entregables del sistema:

   1. Ranking de Sospecha: Un listado priorizado por el Anomaly Score, permitiendo que el auditor se enfoque en los datos con mayor riesgo.

   2. Justificación de Alerta: Por cada registro marcado, el sistema adjunta una "razón de sospecha".

   3. Persistencia y Dashboard: Almacenamiento indexado en PostgreSQL  y representación gráfica en Dash/Plotly para visualizar la dispersión (Valor vs. Tiempo) y la concentración geográfica de alertas.

7. Resultados y Hallazgos (En progreso).

