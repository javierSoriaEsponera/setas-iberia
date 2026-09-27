"""Textos de las fichas de la pestaña «Setas» (contenido propio del proyecto).

La temporada, la altitud, la lluvia, la temperatura y los árboles de cada ficha
no se escriben aquí: se generan desde config.SPECIES, así la ficha y el mapa
usan siempre los mismos datos.
"""

INFO = {
    "boletus_edulis": {
        "desc": "Sombrero de avellana a pardo con el margen más claro y pie abombado con un retículo blanco "
                "en la parte alta. Vive asociado a hayas, castaños, robles y pinos de montaña, y sale en "
                "oleadas dos o tres semanas después de lluvias generosas si las noches refrescan sin helar.",
        "confusion": "Tylopilus felleus: retículo oscuro y poros que se vuelven rosados. No es tóxico, "
                     "pero su amargor estropea cualquier guiso.",
    },
    "boletus_aereus": {
        "desc": "Sombrero pardo muy oscuro, casi negro, a menudo con tacto de terciopelo, y carne blanca que no "
                "cambia de color. Es el boleto más amante del calor: encinares, alcornocales, rebollares y "
                "castañares de baja y media altitud, en otoños templados y también a final de primavera.",
        "confusion": "Boletus reticulatus, también comestible. Descarta cualquier boleto con poros rojos "
                     "o carne que azulea con fuerza si no lo conoces bien.",
    },
    "boletus_pinophilus": {
        "desc": "Sombrero rojizo a granate y pie con tonos rosados. Muy ligado al pino silvestre en montaña, "
                "con dos salidas: una a final de primavera y otra en el otoño clásico.",
        "confusion": "Tylopilus felleus y los boletos de poros rojos, como Rubroboletus satanas, tóxico, "
                     "más propio de suelos calizos.",
    },
    "imleria_badia": {
        "desc": "Sombrero castaño, viscoso con la humedad, y poros amarillentos que azulean al presionarlos. "
                "Frecuente en pinares sobre suelo ácido, incluso a baja altitud y hasta entrado el invierno.",
        "confusion": "Otros boletos de carne azulante; algunos provocan trastornos digestivos.",
    },
    "neoboletus_erythropus": {
        "desc": "Poros rojos y pie punteado de rojo; su carne amarilla se vuelve azul oscuro al instante al "
                "cortarla. Aparece en bosques de suelo ácido de todo tipo. Solo es comestible bien cocinado.",
        "confusion": "Rubroboletus satanas y otros boletos de poros rojos, tóxicos, sobre todo en suelos calizos.",
    },
    "cantharellus": {
        "desc": "Color yema de huevo, pliegues que bajan por el pie en lugar de láminas verdaderas y olor "
                "afrutado a albaricoque. Sale en grupos en castañares, robledales y hayedos ácidos desde el "
                "final de la primavera.",
        "confusion": "Hygrophoropsis aurantiaca, con láminas verdaderas y naranja intenso, y Omphalotus "
                     "olearius, tóxico, que crece en matas sobre madera de olivo o encina.",
    },
    "cantharellus_lutescens": {
        "desc": "Sombrero pardo sobre un pie hueco amarillo anaranjado y parte inferior casi lisa. Forma "
                "colonias numerosas en el musgo húmedo de pinares y bosques mixtos, ya bien avanzado el otoño.",
        "confusion": "Craterellus tubaeformis, también comestible, con pliegues grisáceos bajo el sombrero.",
    },
    "niscalos": {
        "desc": "Láminas y látex anaranjados en L. deliciosus o rojo vino en L. sanguifluus; las zonas "
                "rozadas se manchan de verde. Siempre bajo pinos, y de las setas más abundantes del otoño.",
        "confusion": "Lactarius torminosus, tóxico: sombrero con pelos en el borde y látex blanco.",
    },
    "pie_azul": {
        "desc": "Sombrero y láminas lila violáceo que se vuelven pardos con la edad, con olor afrutado. Se "
                "alimenta de hojarasca y acículas, aguanta bien el frío y alarga la temporada hasta el invierno.",
        "confusion": "Cortinarius violáceos, algunos muy tóxicos: tienen una telilla bajo el sombrero y "
                     "esporada color óxido. La de Lepista nuda es rosa pálido.",
    },
    "trompeta": {
        "desc": "Embudo gris negruzco sin láminas, con la cara externa casi lisa. Se camufla entre la "
                "hojarasca de hayedos y robledales húmedos; donde aparece una, suele haber muchas.",
        "confusion": "Pocas confusiones peligrosas. Craterellus cinereus es parecida y también comestible.",
    },
    "lengua_vaca": {
        "desc": "Bajo el sombrero no hay láminas sino pequeños aguijones quebradizos, lo que la hace muy "
                "fácil de reconocer. Sale bajo frondosas y coníferas hasta muy entrado el otoño; los "
                "ejemplares grandes amargan un poco.",
        "confusion": "Hydnum rufescens, más anaranjada y también comestible.",
    },
    "amanita_caesarea": {
        "desc": "Sombrero anaranjado intenso que nace de una volva blanca con forma de huevo, con láminas y "
                "pie amarillos. Muy amante del calor: encinares, alcornocales, castañares y rebollares tras "
                "las tormentas de final de verano.",
        "confusion": "Amanita muscaria, tóxica, con láminas y pie blancos y verrugas blancas. No recojas "
                     "nunca ejemplares en huevo cerrado: podrían ser Amanita phalloides, mortal.",
    },
}
