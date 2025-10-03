"""
seed_ballester_from_excel.py - Importador rápido desde Excel → Firestore

Objetivo: cargar de forma RÁPIDA y EFICIENTE una base de datos de prueba
para el Centro Pediátrico Ballester V11 usando los Excel actuales.

Requisitos:
- pandas
- openpyxl
- firebase-admin ya configurado (como en memory.py)

Formato esperado (hojas sugeridas):
- "coberturas"        → obras sociales y servicios cubiertos
- "precios"           → precios particulares actualizados
- "especialistas"     → reglas especiales (Malacchia, Ametller, Travaglia)
- "preparaciones"     → instrucciones para estudios

El script es tolerante: si una hoja no existe, la salta y continua.

Uso:
  python seed_ballester_from_excel.py --file datos_ballester.xlsx \
      --tenant CENTRO_PEDIATRICO_BALLESTER

"""

import argparse
import logging
from typing import Dict, Any
import pandas as pd
from firebase_admin import firestore

import memory  # garantiza inicialización de firebase

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _safe_sheet(xls: pd.ExcelFile, name: str) -> pd.DataFrame | None:
    try:
        if name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=name)
            logger.info(f"[SEED] Hoja '{name}' cargada: {len(df)} filas")
            return df
    except Exception as e:
        logger.error(f"[SEED] Error leyendo hoja '{name}': {e}")
    return None


def seed_coberturas(db: firestore.Client, df: pd.DataFrame) -> None:
    """Importa coberturas a 'ballester_obras_sociales'.

    Columnas sugeridas mínimas:
    - obra_social, servicio_key, cobertura, copago, requiere_autorizacion,
      requiere_bono_atencion, requiere_bono_consulta, max_slots_dia, bono_contribucion
    """
    coll = db.collection('ballester_obras_sociales')
    grouped = df.groupby('obra_social')
    for obra, g in grouped:
        servicios: Dict[str, Any] = {}
        for _, row in g.iterrows():
            key = str(row.get('servicio_key', '') or row.get('servicio', '')).strip().lower().replace(' ', '_')
            if not key:
                continue
            servicios[key] = {
                'cobertura': str(row.get('cobertura', 'COVERED')).upper(),
                'copago': int(row.get('copago', 0) or 0),
                'requiere_autorizacion': bool(row.get('requiere_autorizacion', False)),
                'requiere_bono_atencion': bool(row.get('requiere_bono_atencion', False)),
                'requiere_bono_consulta': bool(row.get('requiere_bono_consulta', False)),
                'max_slots_dia': int(row.get('max_slots_dia', 0) or 0),
                'bono_contribucion': int(row.get('bono_contribucion', 0) or 0),
            }
        doc = {
            'nombre_completo': obra,
            'servicios_cubiertos': servicios,
        }
        coll.document(str(obra).upper()).set(doc)
        logger.info(f"[SEED] Coberturas → {obra}: {len(servicios)} servicios")


def seed_precios(db: firestore.Client, df: pd.DataFrame) -> None:
    """Importa precios particulares a 'ballester_configuracion/precios_particulares'.

    Columnas sugeridas mínimas:
    - categoria, servicio_key, precio
    """
    precios: Dict[str, Dict[str, int]] = {}
    for _, row in df.iterrows():
        categoria = str(row.get('categoria', 'otros')).strip().lower()
        servicio = str(row.get('servicio_key', '') or row.get('servicio', '')).strip()
        if not servicio:
            continue
        precio = int(row.get('precio', 0) or 0)
        precios.setdefault(categoria, {})[servicio] = precio

    db.collection('ballester_configuracion').document('precios_particulares').set({
        'fecha_actualizacion': pd.Timestamp.now().isoformat(),
        'version': pd.Timestamp.now().strftime('%Y%m%d-%H%M'),
        'precios': precios,
    })
    logger.info(f"[SEED] Precios → categorías: {len(precios)}")


def seed_especialistas(db: firestore.Client, df: pd.DataFrame) -> None:
    """Importa especialistas a 'ballester_configuracion/especialistas'.

    Columnas sugeridas mínimas:
    - nombre, especialidad, reglas_json (json con reglas), dias_atencion
    """
    especialistas: Dict[str, Any] = {}
    for _, row in df.iterrows():
        nombre = str(row.get('nombre', '')).strip()
        if not nombre:
            continue
        reglas = {}
        try:
            import json as _json
            reglas = _json.loads(row.get('reglas_json', '{}') or '{}')
        except Exception:
            reglas = {}
        especialistas[nombre.replace(' ', '_')] = {
            'nombre_completo': nombre,
            'especialidad': row.get('especialidad', ''),
            'dias_atencion': (row.get('dias_atencion', '') or '').split(',') if row.get('dias_atencion') else [],
            'reglas_especiales': reglas,
        }

    db.collection('ballester_configuracion').document('especialistas').set(especialistas)
    logger.info(f"[SEED] Especialistas → {len(especialistas)}")


def seed_preparaciones(db: firestore.Client, df: pd.DataFrame) -> None:
    """Importa preparaciones a 'ballester_configuracion/preparaciones_estudios'.

    Formatos soportados:
    - tipo=simple → columnas: servicio_key, instruccion
    - tipo=por_edad → columnas: servicio_key, grupo_edad, instruccion
    """
    data: Dict[str, Any] = {}
    for _, row in df.iterrows():
        tipo = (row.get('tipo') or 'simple').strip().lower()
        servicio = str(row.get('servicio_key', '')).strip()
        if not servicio:
            continue
        if tipo == 'por_edad':
            grupo = str(row.get('grupo_edad', '')).strip()
            if not grupo:
                continue
            data.setdefault(servicio, {}).setdefault(grupo, []).append(str(row.get('instruccion', '')).strip())
        else:
            data.setdefault(servicio, []).append(str(row.get('instruccion', '')).strip())

    db.collection('ballester_configuracion').document('preparaciones_estudios').set(data)
    logger.info(f"[SEED] Preparaciones → {len(data)} servicios")


def main():
    parser = argparse.ArgumentParser(description='Seed Ballester V11 desde Excel a Firestore')
    parser.add_argument('--file', required=True, help='Ruta al Excel con datos (xlsx)')
    parser.add_argument('--tenant', default='CENTRO_PEDIATRICO_BALLESTER', help='Nombre del tenant (para logs)')
    args = parser.parse_args()

    # Inicializa firestore usando memory.py
    db = firestore.client()
    xls = pd.ExcelFile(args.file)

    # Coberturas
    df = _safe_sheet(xls, 'coberturas')
    if df is not None and not df.empty:
        seed_coberturas(db, df)

    # Precios particulares
    df = _safe_sheet(xls, 'precios')
    if df is not None and not df.empty:
        seed_precios(db, df)

    # Especialistas
    df = _safe_sheet(xls, 'especialistas')
    if df is not None and not df.empty:
        seed_especialistas(db, df)

    # Preparaciones
    df = _safe_sheet(xls, 'preparaciones')
    if df is not None and not df.empty:
        seed_preparaciones(db, df)

    logger.info('[SEED] ✅ Base de datos de prueba importada correctamente')


if __name__ == '__main__':
    main()


