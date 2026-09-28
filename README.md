# Setas ibéricas — mapa de probabilidad de fructificación

Mapa interactivo que cada día calcula, para toda la península y Baleares, un índice
0-100 de probabilidad de encontrar 13 especies: *Boletus edulis*, *B. aereus*,
*B. pinophilus*, *Imleria badia*, *Neoboletus erythropus*, *Cantharellus cibarius*,
*Craterellus lutescens*, níscalo (*Lactarius deliciosus*), níscalo de sangre
(*L. sanguifluus*), pie azul, trompeta de la muerte, lengua de vaca y *Amanita caesarea*.

## Pestañas

| Pestaña | Qué hace |
|---|---|
| Fructificación | Probabilidad por especie para hoy y los 7 días siguientes, con las mejores zonas |
| Exploración | Mapa de encaje con tus criterios: lluvia, mínimas y máximas, rachas, altitud y bosque |
| Mis setales | Puntos guardados desde el mapa, con las setas más probables hoy y el mejor día |
| Clima | Precipitación, temperatura, humedad del suelo y viento de los últimos 7-30 días |
| Flora | Los 8 tipos de bosque del Mapa Forestal (o GBIF donde no hay MFE) |
| Setas | Fichas: temporada, altitud, lluvia, temperatura, árboles, probabilidad mensual y confusiones |

Las fichas se generan desde `config.SPECIES` (datos) y `species_info.py` (textos), así que
coinciden siempre con el modelo. Los setales se guardan en el navegador del usuario
(`localStorage`), con opción de descargar y cargar una copia.

**Fotos:** se cargan de iNaturalist con su autor y licencia. Muchas son CC BY-NC, que no
permite uso comercial. Si monetizas la app, filtra por `license_code` (cc0, cc-by, cc-by-sa)
o usa fotos propias.

## Cómo funciona

```
 Mapa Forestal de España ──► mfe_0.1.json ─┐  (1 vez, en tu ordenador)
 GBIF (árboles PT + citas) ─► habitat_gbif ─┤  (1 vez)
                                            ▼
 Open-Meteo 0,25º (35 días + 7) ──► corrección por altitud a 0,1º ──► model.py
                                            │
                          docs/data/latest.json ──► docs/index.html (Leaflet)
```

Para cada celda de 0,1º (≈ 10 km, unas 6.200 celdas) y cada día (hoy + 7):

| Factor | Fuente | Qué mide |
|---|---|---|
| Hábitat | Mapa Forestal de España; GBIF en Portugal y provincias sin MFE | Superficie de 8 tipos de bosque (pinar montano, negral, mediterráneo, abetal, hayedo, castañar, robledal, encinar/alcornocal) ponderada por cabida cubierta y ocupación de cada especie + citas de la seta |
| Altitud | Open-Meteo (MDT 90 m) | Rango altitudinal de la especie; corrige la temperatura (−0,65 ºC/100 m) |
| Estación | calendario | Peso mensual interpolado |
| Lluvia | Open-Meteo | Lluvia acumulada entre 8 y 22 días antes (según especie) |
| Temperatura | Open-Meteo | Media de 7 días dentro del óptimo |
| pH del suelo | SoilGrids 250 m (+ LUCAS opcional) | Rango de pH preferido; separa el níscalo (ácido) del de sangre (calizo) |
| Agua del suelo | Open-Meteo + SMAP (satélite, opcional) | Media geométrica del balance lluvia − evaporación a 30 días y la humedad 0-7 cm de la última semana |
| Helada / calor | Open-Meteo | Mínimas < −1 ºC o máximas > 30 ºC en 5 días |

## Puesta en marcha

```bash
pip install -r requirements.txt
python -m pipeline.run_daily --demo      # datos sintéticos, sin red
python -m http.server -d docs 8000       # abre http://localhost:8000
```

Con datos reales:

```bash
python -m pipeline.habitat      # una vez, 15-30 min (miles de consultas a GBIF)
python -m pipeline.run_daily    # cada día, ~10 min (pausas para respetar límites)
```

## pH del suelo

`python -m pipeline.soil` descarga una vez el pH de SoilGrids (28 recortes de 2º × 2º, media de
0-5 y 5-15 cm) y lo promedia por celda en `data/ph_0.1.json`. El workflow diario lo hace solo
la primera vez.

Para afinarlo con muestras de campo, pide gratis los datos **LUCAS Topsoil** en
https://esdac.jrc.ec.europa.eu/ (formulario, tardan unos días), deja el CSV en `data/lucas/`
y vuelve a ejecutar `python -m pipeline.soil`. Cada celda con muestras se corrige hacia su mediana.

## Humedad del suelo

- **Modelo (siempre):** Open-Meteo, capas 0-1, 1-3 y 3-9 cm combinadas en 0-7 cm, con previsión.
- **Satélite (opcional):** NASA SMAP L3 mejorado, 9 km, 1-2 días de retraso. Crea una cuenta
  gratuita en https://urs.earthdata.nasa.gov y añade en GitHub → Settings → Secrets and
  variables → Actions los secretos `EARTHDATA_USERNAME` y `EARTHDATA_PASSWORD`. El satélite
  corrige el sesgo del modelo en cada zona; si falla un día, la previsión sigue sin él.
- **ERA5-Land:** se usa en la calibración (meteo histórica de cada hallazgo), porque es la
  serie más coherente hacia atrás.

## Calibración con hallazgos

1. **Registra hallazgos** en la web: en el mapa o en un setal, «Registrar hallazgo aquí».
   Apunta también cuando vas y *no* hay nada: esas ausencias valen el triple.
2. **Descarga el CSV** (Mis setales → Descargar hallazgos) y cópialo en `data/hallazgos/`.
   Puedes añadir CSV de otros usuarios con las mismas columnas:
   `species, date, lat, lon, found, count, source, notes`.
3. **Ejecuta** `pip install -r requirements-calib.txt` y `python -m pipeline.calibrate all`
   (o deja que lo haga el workflow semanal `calibrate.yml`).
   - `gbif` añade miles de citas fechadas de GBIF para empezar sin esperar a tus datos.
   - `dataset` cruza cada hallazgo con la meteo ERA5-Land de ese día y lugar, y añade celdas
     de «fondo» del mismo día como pseudo-ausencias. Descarga hasta 2.500 series por ejecución
     (límite gratuito); lo ya descargado se guarda y no se repite.
   - `train` entrena LightGBM con las mismas variables que el modelo ecológico (más su propio
     índice como variable) y lo **valida dejando fuera cada temporada completa**.
4. Lee `data/modelo/informe.md`. El modelo calibrado solo entra en la previsión si tiene al
   menos 200 presencias y mejora el AUC del modelo ecológico en 0,02 o más. Entonces se mezcla
   al 60 % con el ecológico (ajustable en `config.py`) y la web lo indica.

Prueba todo sin red con `python -m pipeline.calibrate all --demo` (borra después
`data/modelo/` y `data/hallazgos/demo.csv`).

## Mapa Forestal de España (una vez, en tu ordenador)

1. Descarga los .zip provinciales en
   https://www.miteco.gob.es/es/cartografia-y-sig/ide/descargas/biodiversidad/mfe.html
   (pincha cada provincia en el mapa). Puedes empezar solo por las provincias que te interesen:
   el resto usa GBIF automáticamente.
2. Déjalos sin descomprimir en `data/mfe/`.
3. Instala las dependencias geográficas: `pip install -r requirements-mfe.txt`
4. Revisa una provincia: `python -m pipeline.mfe --inspect data/mfe/<fichero>.zip`
   Muestra los campos y los km² asignados a cada tipo de bosque. Si un grupo sale a 0
   en una provincia donde abunda, revisa sus códigos en `config.HOST_GROUPS`.
5. Procesa todas: `python -m pipeline.mfe` → genera `data/mfe_0.1.json` (unos MB).
6. Sube solo `data/mfe_0.1.json` a GitHub. Los .zip están excluidos en `.gitignore`.

En el MFE25 el campo `FORARB` es un código numérico de formación arbolada. Su significado
está en el diccionario de datos oficial (`mfe25_dd.xlsx`), que `pipeline.mfe` descarga solo
de MITECO y guarda en `data/mfe/`. Con `python -m pipeline.mfe --codes` ves cada código, su
formación y a qué tipo de bosque se asigna. Si no puede descargarlo, bájalo de la página de
descargas del MFE o crea `data/mfe/forarb.csv` con las columnas `codigo,nombre`.

El lector entiende las dos estructuras del MFE: códigos de especie del IFN
(`SP1-SP3` con ocupación `O1-O3` y `FCCARB`) o el texto de la formación arbolada.
Cita la fuente: «Mapa Forestal de España, MITECO (CC BY 4.0)».

## Actualización diaria gratis (GitHub)

1. Sube el proyecto a un repositorio de GitHub.
2. Settings → Pages → rama `main`, carpeta `/docs`.
3. El workflow `.github/workflows/daily.yml` se ejecuta cada día a las 04:30 UTC,
   regenera `docs/data/latest.json` y lo publica. Puedes lanzarlo a mano en Actions.

## Licencias y límites

- **Open-Meteo**: gratis solo para uso no comercial (~10.000 llamadas/día). Si la app
  es comercial, plan de pago o AEMET OpenData (requiere API key gratuita).
- **GBIF**: datos CC0/CC-BY; cita GBIF y los conjuntos de datos en la web.
- **IGN / PNOA**: CC-BY 4.0, mantener la atribución.
- Mycora, Mapa de Setas o Esporas usan bases de datos propias; no las consultes ni las
  copies sin permiso. Este proyecto usa las mismas fuentes públicas en las que se basan.

## Mejoras recomendadas (por orden de impacto)

1. **COS (Portugal, DGT)** en lugar de GBIF para los árboles portugueses.
2. **Resolución 1 km** alrededor de zonas forestales, con **MDT 25 m del IGN** para
   orientación (umbrías) y pendiente.
3. **Hallazgos de usuarios centralizados**: un pequeño servidor (o formulario) que recoja
   los CSV sin tener que copiarlos a mano; llegará con la app móvil.
4. **Sentinel-1 (Copernicus, 1 km)** para humedad del suelo con más detalle que SMAP.
5. **App móvil**: el mismo `latest.json` sirve para una app en React Native o Flutter.

## Estructura

```
pipeline/config.py     parámetros de cada especie (edítalos para calibrar)
pipeline/grid.py       malla terrestre
pipeline/mfe.py        Mapa Forestal de España -> fracción de cada bosque por celda
pipeline/habitat.py    GBIF y combinación de capas de hábitat
pipeline/weather.py    meteorología diaria y humedad del suelo (Open-Meteo) + histórico ERA5-Land
pipeline/soil.py       pH del suelo (SoilGrids, LUCAS)
pipeline/satellite.py  humedad del suelo por satélite (SMAP)
pipeline/model.py      modelo ecológico de probabilidad
pipeline/features.py   variables comunes para entrenar y predecir
pipeline/calibrate.py  hallazgos, dataset, LightGBM y validación por temporadas
pipeline/species_info.py  textos de las fichas de la pestaña Setas
pipeline/run_daily.py  proceso diario -> docs/data/latest.json y species.json
docs/index.html        la web con las seis pestañas
```
