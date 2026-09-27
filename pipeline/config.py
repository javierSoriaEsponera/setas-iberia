"""Configuración general y parámetros ecológicos por especie.

Los valores son un punto de partida razonable basado en la bibliografía
micológica ibérica. Están pensados para calibrarse con tus propios hallazgos.

Campos:
  hosts      -> peso de cada grupo forestal (HOST_GROUPS) como hospedador (0-1)
  floor      -> hábitat mínimo aunque no haya hospedadores (saprófitas > 0)
  elev       -> trapecio de altitud (m): (mín, óptimo bajo, óptimo alto, máx)
  season     -> peso mensual ene..dic (0-1)
  temp       -> rango óptimo de temperatura media de los últimos 7 días (ºC)
  rain_mm    -> lluvia acumulada que satura el factor lluvia
  lag        -> ventana (días antes) en la que cuenta esa lluvia (mín, máx)
  frost_tol  -> multiplicador si ha helado en los últimos 5 días
  ph         -> rango óptimo de pH del suelo (en agua); fuera de él la probabilidad baja poco a poco
  tmax_limit -> máxima (ºC) de los últimos 5 días a partir de la cual el calor frena la fructificación
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PUBLIC_DATA_DIR = ROOT / "docs" / "data"

# Península + Baleares (sin Canarias)
BBOX = (-9.6, 35.9, 3.4, 43.9)  # lon_min, lat_min, lon_max, lat_max
GRID_STEP = 0.1                 # malla del mapa y del hábitat (~10 km)
WEATHER_STEP = 0.25             # malla meteorológica (~25 km); se reparte a la fina con corrección por altitud
LAPSE_RATE = -0.0065            # ºC por metro de desnivel
MFE_DIR = DATA_DIR / "mfe"      # aquí van los .zip provinciales del Mapa Forestal de España
FINDINGS_DIR = DATA_DIR / "hallazgos"   # CSV de hallazgos (propios, de usuarios, GBIF)
MODEL_DIR = DATA_DIR / "modelo"         # modelo calibrado (LightGBM) y su informe
MODEL_MIN_PRESENCES = 200       # hallazgos positivos mínimos para usar el modelo calibrado
MODEL_MIN_GAIN = 0.02           # mejora mínima de AUC frente al modelo heurístico
MODEL_WEIGHT = 0.6              # peso del modelo calibrado en la mezcla final

PAST_DAYS = 35                  # historial meteo necesario para las ventanas de lluvia
FORECAST_DAYS = 8               # hoy + 7 días de previsión

HOST_GENERA = ["Pinus", "Quercus", "Fagus", "Castanea", "Abies"]  # GBIF (respaldo: Portugal y provincias sin MFE)

# Grupos forestales. "codes" = códigos de especie del Inventario Forestal Nacional
# (campos SP1-SP3 del MFE); "latin" = nombres que se buscan si la capa trae texto.
# "gbif" = género de respaldo y factor con que se reparte cuando no hay MFE.
HOST_GROUPS = {
    "pino_montano":  {"name": "Pinar de silvestre, negro o laricio", "codes": [21, 22, 25],
                      "latin": ["Pinus sylvestris", "Pinus uncinata", "Pinus nigra"], "gbif": ("Pinus", 0.6)},
    "pino_negral":   {"name": "Pinar de pino negral o radiata", "codes": [26, 28],
                      "latin": ["Pinus pinaster", "Pinus radiata"], "gbif": ("Pinus", 0.6)},
    "pino_medit":    {"name": "Pinar de carrasco o piñonero", "codes": [23, 24],
                      "latin": ["Pinus pinea", "Pinus halepensis"], "gbif": ("Pinus", 0.5)},
    "abeto":         {"name": "Abetal o pinsapar", "codes": [31, 32, 33],
                      "latin": ["Abies alba", "Abies pinsapo", "Picea abies"], "gbif": ("Abies", 1.0)},
    "haya":          {"name": "Hayedo", "codes": [71],
                      "latin": ["Fagus sylvatica"], "gbif": ("Fagus", 1.0)},
    "castano":       {"name": "Castañar", "codes": [72],
                      "latin": ["Castanea sativa"], "gbif": ("Castanea", 1.0)},
    "roble":         {"name": "Robledal, melojar o quejigar", "codes": [41, 42, 43, 44, 47],
                      "latin": ["Quercus robur", "Quercus petraea", "Quercus pyrenaica", "Quercus faginea",
                                "Quercus canariensis", "Quercus humilis", "Quercus pubescens"], "gbif": ("Quercus", 0.6)},
    "encina_alc":    {"name": "Encinar, alcornocal o dehesa", "codes": [45, 46],
                      "latin": ["Quercus ilex", "Quercus rotundifolia", "Quercus suber"], "gbif": ("Quercus", 0.6)},
}

# ---------------------------------------------------------------------------
# Parámetros revisados con bibliografía (sept. 2026). Fuentes principales:
#  [A] Alonso Ponce et al. 2011, Fungal Ecology 4:224-232 (B. edulis-Cistus en España)
#  [B] Monitorización diaria de B. edulis 2015-2024, hayedos de Alemania (bioRxiv 2025)
#  [C] Taye et al. 2016, Fungal Ecology (P. pinaster, Centro de España)
#  [D] Karavani et al. 2018, Agric. For. Meteorol. (humedad del suelo, Poblet)
#  [E] Salerni et al. 2002 y 2023 (lluvia y picos de calor en B. edulis, Italia)
#  [F] Estudios de C. cibarius en Canadá (Can. J. Bot. 2011; Can. J. Plant Sci. 2021)
#  [G] Fichas de sociedades micológicas: Barakaldo, MicoAragón, Aranzadi, Guía de Navarra
# Valores de partida: la calibración con hallazgos (pipeline.calibrate) los afina.
# ---------------------------------------------------------------------------
SPECIES = {
    "boletus_edulis": {
        # Otoño tras lluvias de final de verano; pico con ~13 ºC de media en los 20 días
        # previos y lluvia acumulada en ~26 días [B]; suelos silíceos y ácidos, >600 mm/año [A][G].
        # También fructifica con jara (Cistus ladanifer/laurifolius), grupo aún no modelizado; en el
        # suroeste y oeste puede alargarse hasta diciembre-enero.
        "name": "Boletus edulis", "common": "Boleto, calabaza",
        "gbif": ["Boletus edulis"],
        "hosts": {"haya": 1.0, "pino_montano": 0.9, "castano": 0.9, "abeto": 0.8, "roble": 0.8,
                  "pino_negral": 0.5, "encina_alc": 0.3, "pino_medit": 0.1},
        "floor": 0.02, "elev": (100, 500, 1800, 2200),
        "season": [.05, 0, 0, 0, .1, .2, .1, .3, .9, 1, .7, .2],
        "temp": (10, 16), "rain_mm": 70, "lag": (6, 26), "frost_tol": 0.3, "ph": (4.0, 6.0),
        "tmax_limit": 28,
    },
    "boletus_aereus": {
        # Termófilo: final de primavera a otoño y deja de salir cuando baja la temperatura; Quercus,
        # castaño y jaras del SO; suelos preferentemente ácidos, a veces algo básicos [G].
        "name": "Boletus aereus", "common": "Boleto negro",
        "gbif": ["Boletus aereus"],
        "hosts": {"encina_alc": 1.0, "castano": 1.0, "roble": 0.9, "haya": 0.3, "pino_negral": 0.1},
        "floor": 0.02, "elev": (0, 200, 1200, 1500),
        "season": [0, 0, 0, 0, .3, .6, .5, .4, .9, 1, .6, .2],
        "temp": (14, 22), "rain_mm": 40, "lag": (7, 20), "frost_tol": 0.2, "ph": (4.0, 7.0),
        "tmax_limit": 33,
    },
    "boletus_pinophilus": {
        # Dos oleadas: primavera (marzo-julio, antes en cotas bajas) y otoño (sept.-dic.);
        # pinares y hayedos maduros (>50 años) de media montaña, suelos ácidos [G].
        "name": "Boletus pinophilus", "common": "Boleto de pino (pinicola)",
        "gbif": ["Boletus pinophilus", "Boletus pinicola"],
        "hosts": {"pino_montano": 1.0, "abeto": 0.7, "haya": 0.5, "castano": 0.5, "pino_negral": 0.5, "roble": 0.4},
        "floor": 0.02, "elev": (400, 900, 1900, 2300),
        "season": [0, 0, .1, .3, .7, .8, .4, .2, .8, 1, .6, .2],
        "temp": (9, 17), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.3, "ph": (4.0, 6.0),
        "tmax_limit": 28,
    },
    "imleria_badia": {
        # Coníferas de montaña, menos bajo frondosas; ausente en suelos calizos; aguanta las
        # primeras heladas; final de verano a final de otoño [G].
        "name": "Imleria badia", "common": "Boleto bayo, Boletus badius",
        "gbif": ["Imleria badia", "Boletus badius", "Xerocomus badius"],
        "hosts": {"pino_montano": 1.0, "pino_negral": 0.9, "abeto": 0.8, "haya": 0.5, "castano": 0.4, "roble": 0.3},
        "floor": 0.02, "elev": (0, 300, 1600, 2000),
        "season": [.1, 0, 0, 0, 0, 0, .05, .2, .7, 1, .9, .4],
        "temp": (7, 16), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.5, "ph": (3.5, 6.0),
        "tmax_limit": 27,
    },
    "neoboletus_erythropus": {
        # Nombre válido actual: Neoboletus luridiformis ("Boletus erythropus" es un nombre ambiguo).
        # Primavera a otoño bajo frondosas y coníferas (abeto, pino albar) de suelos ácidos [G].
        "name": "Neoboletus luridiformis", "common": "Pie rojo, Boletus erythropus",
        "gbif": ["Neoboletus luridiformis", "Neoboletus erythropus", "Boletus luridiformis", "Boletus erythropus"],
        "hosts": {"haya": 0.9, "abeto": 0.9, "pino_montano": 0.9, "castano": 0.8, "roble": 0.8,
                  "pino_negral": 0.6, "encina_alc": 0.3},
        "floor": 0.02, "elev": (100, 400, 1700, 2100),
        "season": [0, 0, 0, .1, .4, .6, .5, .5, .9, 1, .6, .1],
        "temp": (10, 19), "rain_mm": 45, "lag": (7, 20), "frost_tol": 0.3, "ph": (3.8, 6.0),
        "tmax_limit": 29,
    },
    "cantharellus": {
        # Responde rápido: lluvia de la semana previa y temperatura de 2 semanas antes [F];
        # veranos cálidos y húmedos lo favorecen; suelos ácidos de frondosas y pinares [G].
        "name": "Cantharellus cibarius", "common": "Rebozuelo",
        "gbif": ["Cantharellus cibarius", "Cantharellus pallens", "Cantharellus"],
        "hosts": {"castano": 1.0, "roble": 0.9, "haya": 0.9, "pino_montano": 0.7, "pino_negral": 0.7,
                  "encina_alc": 0.6, "abeto": 0.6},
        "floor": 0.02, "elev": (0, 300, 1600, 2000),
        "season": [0, 0, 0, 0, .2, .6, .5, .5, .9, 1, .6, .2],
        "temp": (12, 20), "rain_mm": 45, "lag": (4, 15), "frost_tol": 0.3, "ph": (4.0, 6.5),
        "tmax_limit": 31,
    },
    "cantharellus_lutescens": {
        # Calcícola: pinares de pino albar y laricio con musgo, umbrías; agosto a febrero con
        # máximo en octubre-noviembre; sale incluso tras heladas [G].
        "name": "Craterellus lutescens", "common": "Angula de monte, trompeta amarilla",
        "gbif": ["Craterellus lutescens", "Cantharellus lutescens"],
        "hosts": {"pino_montano": 1.0, "pino_negral": 0.5, "abeto": 0.5, "pino_medit": 0.4, "roble": 0.3, "haya": 0.3},
        "floor": 0.02, "elev": (0, 300, 1600, 1900),
        "season": [.4, .2, 0, 0, 0, 0, 0, .1, .3, .8, 1, .7],
        "temp": (5, 13), "rain_mm": 60, "lag": (8, 24), "frost_tol": 0.7, "ph": (6.5, 8.5),
        "tmax_limit": 27,
    },
    "lactarius_deliciosus": {
        # Pinares de suelo ácido o neutro: la acidez aumenta su producción [C]; la humedad del
        # suelo es el mejor predictor [D]; sale unas 3 semanas tras lluvias abundantes, con el
        # suelo por encima de ~9 ºC y sin viento que lo reseque [G]. L. vinosus (silíceo, litoral) incluido.
        "name": "Lactarius deliciosus", "common": "Níscalo, robellón",
        "gbif": ["Lactarius deliciosus", "Lactarius vinosus"],
        "hosts": {"pino_negral": 1.0, "pino_montano": 1.0, "pino_medit": 0.7, "abeto": 0.2},
        "floor": 0.01, "elev": (0, 200, 1600, 2000),
        "season": [.3, .1, 0, 0, .05, 0, 0, .05, .3, .9, 1, .6],
        "temp": (8, 16), "rain_mm": 50, "lag": (10, 28), "frost_tol": 0.4, "ph": (4.5, 7.0),
        "tmax_limit": 28,
    },
    "lactarius_sanguifluus": {
        # Solo en suelos calizos; pino carrasco en llano y rodeno, laricio o albar en montaña;
        # climas cálidos y se enrarece con la altitud [G].
        "name": "Lactarius sanguifluus", "common": "Níscalo de sangre, rovellón vinoso",
        "gbif": ["Lactarius sanguifluus"],
        "hosts": {"pino_medit": 1.0, "pino_negral": 0.7, "pino_montano": 0.7},
        "floor": 0.01, "elev": (0, 100, 1200, 1700),
        "season": [.3, .1, 0, 0, .05, 0, 0, 0, .3, .9, 1, .6],
        "temp": (9, 18), "rain_mm": 45, "lag": (10, 28), "frost_tol": 0.4, "ph": (7.0, 8.5),
        "tmax_limit": 30,
    },
    "pie_azul": {
        # Saprófita de hojarasca, indiferente al pH; necesita frío (las heladas inducen su
        # fructificación); de las más tardías, con alguna salida en primavera [G].
        # L. personata se excluye: es de prados, no de bosque.
        "name": "Lepista nuda", "common": "Pie azul",
        "gbif": ["Lepista nuda", "Clitocybe nuda"],
        "hosts": {"pino_montano": 0.7, "pino_negral": 0.7, "pino_medit": 0.7, "roble": 0.7, "encina_alc": 0.7,
                  "haya": 0.6, "castano": 0.6, "abeto": 0.6},
        "floor": 0.3, "elev": (0, 100, 1600, 2000),
        "season": [.6, .4, .2, .2, .05, 0, 0, 0, .1, .5, 1, 1],
        "temp": (3, 12), "rain_mm": 40, "lag": (7, 25), "frost_tol": 0.9, "ph": (4.0, 8.5),
        "tmax_limit": 25,
    },
    "trompeta": {
        # Umbrófila: hojarasca de hayedos y robledales húmedos, rara en carrascales; de 0 a
        # 1.500 m; agosto a enero con máximo en septiembre-noviembre; suelos frescos, profundos,
        # a menudo neutros o calizos [G].
        "name": "Craterellus cornucopioides", "common": "Trompeta de la muerte",
        "gbif": ["Craterellus cornucopioides"],
        "hosts": {"haya": 1.0, "roble": 0.8, "castano": 0.7, "abeto": 0.4, "encina_alc": 0.2, "pino_montano": 0.1},
        "floor": 0.02, "elev": (0, 300, 1400, 1700),
        "season": [.1, 0, 0, 0, 0, 0, .05, .3, .8, 1, .8, .3],
        "temp": (9, 16), "rain_mm": 60, "lag": (8, 24), "frost_tol": 0.4, "ph": (5.0, 8.0),
        "tmax_limit": 27,
    },
    "lengua_vaca": {
        # Frondosas y coníferas de suelo ácido o mixto; muy resistente al frío, primero en
        # frondosas y después en pinares, hasta diciembre-enero [G].
        "name": "Hydnum repandum", "common": "Lengua de vaca, gamuza",
        "gbif": ["Hydnum repandum", "Hydnum rufescens"],
        "hosts": {"roble": 0.9, "haya": 0.9, "castano": 0.8, "pino_montano": 0.8, "abeto": 0.8, "pino_negral": 0.7,
                  "encina_alc": 0.6, "pino_medit": 0.4},
        "floor": 0.02, "elev": (0, 300, 1700, 2100),
        "season": [.4, .1, 0, 0, 0, 0, 0, .1, .4, .9, 1, .8],
        "temp": (6, 15), "rain_mm": 45, "lag": (8, 22), "frost_tol": 0.7, "ph": (4.0, 7.2),
        "tmax_limit": 27,
    },
    "amanita_caesarea": {
        # Termófila de claros soleados; sale unos 18-22 días después de lluvias de 15-20 mm
        # repetidas; silíceo y bien drenado; hasta 1.000-1.200 m [G]. Su micelio crece mejor a
        # 24-28 ºC (Wikipedia, estudio de aislados).
        "name": "Amanita caesarea", "common": "Oronja, amanita de los césares",
        "gbif": ["Amanita caesarea"],
        "hosts": {"encina_alc": 1.0, "castano": 1.0, "roble": 0.9, "haya": 0.3, "pino_negral": 0.2, "pino_medit": 0.2},
        "floor": 0.02, "elev": (0, 300, 1000, 1300),
        "season": [0, 0, 0, 0, 0, .2, .5, .8, 1, .8, .2, 0],
        "temp": (17, 25), "rain_mm": 40, "lag": (12, 24), "frost_tol": 0.1, "ph": (4.0, 6.5),
        "tmax_limit": 35,
    },
}

# Factores comunes (bibliografía general):
WIND_GUST_KMH = 50        # rachas que resecan el suelo y frenan la fructificación
WIND_PENALTY_PER_DAY = 0.07   # -7 % por cada día con rachas fuertes en la última semana (mín. 0,6)
