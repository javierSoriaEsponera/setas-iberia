# Informe de calibración (2026-11-02)

371 presencias, 1452 filas en total, 3 temporadas validadas.

Validación dejando fuera una temporada completa cada vez (el modelo nunca ve la
temporada que predice). AUC: 0,5 = azar, 1 = perfecto.

| | AUC |
|---|---|
| Modelo calibrado (LightGBM) | 0.860 |
| Modelo heurístico actual | 0.501 |

**Se usa el modelo calibrado** en la previsión diaria (mezclado con el heurístico).

## Por temporada
| season | presencias | auc_modelo | auc_heuristico |
|---|---|---|---|
| 2023-24 | 20 | 0.935 | 0.570 |
| 2024-25 | 25 | 0.924 | 0.613 |
| 2025-26 | 280 | 0.849 | 0.486 |

## Por especie (predicciones fuera de muestra)
| especie | presencias | auc_modelo | auc_heuristico |
|---|---|---|---|
| Boletus pinophilus | 135 | 0.798 | 0.422 |
| Imleria badia | 136 | 0.788 | 0.625 |
| Lactarius deliciosus | 20 | 0.945 | 0.622 |
| Lepista nuda | 10 | 0.867 | 0.373 |

## Variables más importantes
| variable | ganancia |
|---|---|
| doy_sin | 3192.892 |
| ph | 1581.480 |
| balance_30 | 1430.818 |
| sp | 1382.687 |
| elev | 791.966 |
| doy_cos | 734.712 |
| tmax_5 | 586.082 |
| host_roble | 509.866 |
| sm_7 | 455.605 |
| rain_14_21 | 450.495 |
| tmin_5 | 441.607 |
| rain_21_35 | 405.171 |

Las citas de GBIF tienen sesgo de observación (más cerca de pueblos y caminos). Las
ausencias registradas en campo y los hallazgos propios con fecha exacta mejoran mucho el modelo.
