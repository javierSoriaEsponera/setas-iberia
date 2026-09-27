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

SPECIES = {
    "boletus_edulis": {
        "name": "Boletus edulis", "common": "Boleto, calabaza",
        "gbif": ["Boletus edulis"],
        "hosts": {"haya": 1.0, "castano": 0.9, "pino_montano": 0.9, "abeto": 0.8, "roble": 0.7, "pino_negral": 0.5, "encina_alc": 0.2, "pino_medit": 0.1},
        "floor": 0.02, "elev": (200, 700, 1800, 2200),
        "season": [0, 0, 0, 0, .25, .35, .15, .3, .9, 1, .7, .15],
        "temp": (9, 17), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.3,
    },
    "boletus_aereus": {
        "name": "Boletus aereus", "common": "Boleto negro",
        "gbif": ["Boletus aereus"],
        "hosts": {"encina_alc": 1.0, "castano": 0.9, "roble": 0.8, "haya": 0.3, "pino_negral": 0.1},
        "floor": 0.02, "elev": (0, 300, 1100, 1500),
        "season": [0, 0, 0, 0, .4, .5, .2, .2, .8, 1, .6, .1],
        "temp": (13, 21), "rain_mm": 40, "lag": (7, 20), "frost_tol": 0.2,
    },
    "boletus_pinophilus": {
        "name": "Boletus pinophilus", "common": "Boleto de pino (pinicola)",
        "gbif": ["Boletus pinophilus"],
        "hosts": {"pino_montano": 1.0, "pino_negral": 0.7, "abeto": 0.6, "castano": 0.5, "haya": 0.4, "roble": 0.3},
        "floor": 0.02, "elev": (500, 1000, 1900, 2300),
        "season": [0, 0, 0, .1, .7, .8, .3, .3, .9, 1, .4, .05],
        "temp": (9, 17), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.3,
    },
    "imleria_badia": {
        "name": "Imleria badia", "common": "Boleto bayo, Boletus badius",
        "gbif": ["Imleria badia", "Boletus badius"],
        "hosts": {"pino_montano": 1.0, "pino_negral": 0.9, "abeto": 0.8, "haya": 0.5, "castano": 0.4, "roble": 0.3},
        "floor": 0.02, "elev": (0, 300, 1500, 2000),
        "season": [.1, 0, 0, 0, 0, .05, .05, .2, .7, 1, .9, .4],
        "temp": (8, 16), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.4,
    },
    "neoboletus_erythropus": {
        "name": "Neoboletus erythropus", "common": "Pie rojo, Boletus erythropus",
        "gbif": ["Neoboletus erythropus", "Boletus erythropus"],
        "hosts": {"haya": 0.9, "castano": 0.9, "pino_montano": 0.8, "abeto": 0.8, "roble": 0.8, "pino_negral": 0.6, "encina_alc": 0.3},
        "floor": 0.02, "elev": (100, 400, 1700, 2100),
        "season": [0, 0, 0, 0, .2, .5, .4, .4, .9, 1, .6, .1],
        "temp": (10, 19), "rain_mm": 45, "lag": (7, 20), "frost_tol": 0.3,
    },
    "cantharellus": {
        "name": "Cantharellus cibarius", "common": "Rebozuelo",
        "gbif": ["Cantharellus cibarius", "Cantharellus pallens", "Cantharellus"],
        "hosts": {"castano": 1.0, "roble": 0.9, "haya": 0.9, "pino_montano": 0.7, "pino_negral": 0.7, "encina_alc": 0.6, "abeto": 0.6},
        "floor": 0.02, "elev": (0, 300, 1600, 2000),
        "season": [0, 0, 0, 0, .2, .6, .5, .5, .9, 1, .6, .2],
        "temp": (12, 20), "rain_mm": 45, "lag": (5, 18), "frost_tol": 0.3,
    },
    "niscalos": {
        "name": "Lactarius deliciosus / sanguifluus", "common": "Níscalo, robellón",
        "gbif": ["Lactarius deliciosus", "Lactarius sanguifluus", "Lactarius vinosus"],
        "hosts": {"pino_negral": 1.0, "pino_montano": 1.0, "pino_medit": 0.9, "abeto": 0.2},
        "floor": 0.01, "elev": (0, 200, 1600, 2000),
        "season": [.2, .05, 0, 0, .1, 0, 0, 0, .4, 1, 1, .6],
        "temp": (8, 17), "rain_mm": 50, "lag": (8, 22), "frost_tol": 0.4,
    },
    "pie_azul": {
        "name": "Lepista nuda", "common": "Pie azul",
        "gbif": ["Lepista nuda", "Clitocybe nuda", "Lepista personata"],
        "hosts": {"pino_montano": 0.7, "pino_negral": 0.7, "pino_medit": 0.6, "roble": 0.7, "encina_alc": 0.6, "haya": 0.6, "castano": 0.6, "abeto": 0.6},
        "floor": 0.3, "elev": (0, 100, 1600, 2000),
        "season": [.6, .3, .2, .1, 0, 0, 0, 0, .2, .6, 1, 1],
        "temp": (4, 13), "rain_mm": 40, "lag": (7, 25), "frost_tol": 0.7,
    },
    "trompeta": {
        "name": "Craterellus cornucopioides", "common": "Trompeta de la muerte",
        "gbif": ["Craterellus cornucopioides"],
        "hosts": {"haya": 1.0, "roble": 0.8, "castano": 0.8, "abeto": 0.5, "encina_alc": 0.3, "pino_montano": 0.2},
        "floor": 0.02, "elev": (200, 500, 1500, 1900),
        "season": [0, 0, 0, 0, 0, 0, .05, .2, .7, 1, .9, .3],
        "temp": (10, 17), "rain_mm": 60, "lag": (8, 22), "frost_tol": 0.3,
    },
    "lengua_vaca": {
        "name": "Hydnum repandum", "common": "Lengua de vaca, gamuza",
        "gbif": ["Hydnum repandum", "Hydnum rufescens"],
        "hosts": {"roble": 0.9, "haya": 0.9, "castano": 0.8, "pino_montano": 0.8, "abeto": 0.8, "pino_negral": 0.7, "encina_alc": 0.6, "pino_medit": 0.4},
        "floor": 0.02, "elev": (0, 300, 1700, 2100),
        "season": [.3, .1, 0, 0, 0, 0, 0, .1, .5, 1, 1, .7],
        "temp": (7, 16), "rain_mm": 45, "lag": (8, 22), "frost_tol": 0.5,
    },
    "cantharellus_lutescens": {
        "name": "Craterellus lutescens", "common": "Angula de monte, trompeta amarilla",
        "gbif": ["Craterellus lutescens", "Cantharellus lutescens"],
        "hosts": {"pino_montano": 0.9, "pino_negral": 0.9, "abeto": 0.8, "haya": 0.6, "roble": 0.5, "castano": 0.5},
        "floor": 0.02, "elev": (0, 300, 1500, 1900),
        "season": [.4, .1, 0, 0, 0, 0, 0, 0, .2, .8, 1, .8],
        "temp": (6, 14), "rain_mm": 60, "lag": (8, 22), "frost_tol": 0.5,
    },
    "amanita_caesarea": {
        "name": "Amanita caesarea", "common": "Oronja, amanita de los césares",
        "gbif": ["Amanita caesarea"],
        "hosts": {"encina_alc": 1.0, "castano": 1.0, "roble": 0.9, "pino_negral": 0.4, "pino_medit": 0.3},
        "floor": 0.02, "elev": (0, 200, 1100, 1500),
        "season": [0, 0, 0, 0, 0, .3, .5, .8, 1, .8, .2, 0],
        "temp": (16, 24), "rain_mm": 35, "lag": (6, 18), "frost_tol": 0.1,
    },
}
