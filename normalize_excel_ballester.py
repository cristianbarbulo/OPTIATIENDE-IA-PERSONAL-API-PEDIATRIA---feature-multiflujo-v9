"""
normalize_excel_ballester.py - Normaliza Excel crudos → formato seed estándar

Caso de uso: tienes matrices (como "cobertura obras sociales.xlsx") con estructura
heterogénea. Este script:
- Lee el Excel de entrada (una o varias hojas)
- Aplica reglas de normalización (nombres de columnas, keys, valores)
- Genera un nuevo Excel con 4 hojas estándar: coberturas, precios, especialistas, preparaciones
- Ese Excel normalizado es compatible con seed_ballester_from_excel.py

Uso:
  python normalize_excel_ballester.py --in "cobertura obras sociales .xlsx" --out datos_ballester_normalizado.xlsx

Notas:
- El script es tolerante y hace el mejor esfuerzo con heurísticas y mapeos.
- Si algo no puede inferirse, lo deja vacío para que lo completes manualmente.
"""

import argparse
import logging
import re
from typing import Dict
import pandas as pd

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# === Utilidades ===
def slugify_service(text: str) -> str:
    if not isinstance(text, str):
        return ''
    t = text.strip().lower()
    t = re.sub(r"[áàä]", "a", t)
    t = re.sub(r"[éèë]", "e", t)
    t = re.sub(r"[íìï]", "i", t)
    t = re.sub(r"[óòö]", "o", t)
    t = re.sub(r"[úùü]", "u", t)
    t = re.sub(r"[^a-z0-9]+", "_", t)
    return t.strip("_")


def normalize_coberturas(df: pd.DataFrame) -> pd.DataFrame:
    """Intenta mapear una matriz de cobertura a columnas estándar.

    Intenta detectar columnas por nombres aproximados.
    """
    columns = {c.lower(): c for c in df.columns}

    # Heurísticas de posibles nombres
    obra_col = next((columns[c] for c in columns if 'obra' in c and 'social' in c), None)
    servicio_col = next((columns[c] for c in columns if 'servicio' in c or 'estudio' in c or 'especialidad' in c), None)
    cobertura_col = next((columns[c] for c in columns if 'cobertura' in c or 'status' in c), None)
    copago_col = next((columns[c] for c in columns if 'copago' in c or 'coseguro' in c), None)
    autoriz_col = next((columns[c] for c in columns if 'autoriz' in c), None)
    bono_at_col = next((columns[c] for c in columns if 'bono' in c and 'atenc' in c), None)
    bono_cons_col = next((columns[c] for c in columns if 'bono' in c and 'consulta' in c), None)
    max_slots_col = next((columns[c] for c in columns if 'max' in c and ('slot' in c or 'cupo' in c)), None)
    bono_contrib_col = next((columns[c] for c in columns if 'bono' in c and 'contrib' in c), None)

    out = pd.DataFrame()
    out['obra_social'] = df[obra_col] if obra_col else ''
    out['servicio_key'] = df[servicio_col].map(slugify_service) if servicio_col else ''
    out['cobertura'] = (df[cobertura_col].astype(str).str.upper()
                        if cobertura_col else 'COVERED')
    out['copago'] = pd.to_numeric(df[copago_col], errors='coerce').fillna(0).astype(int) if copago_col else 0
    out['requiere_autorizacion'] = df[autoriz_col].astype(str).str.contains('1|true|si|sí', case=False, regex=True) if autoriz_col else False
    out['requiere_bono_atencion'] = df[bono_at_col].astype(str).str.contains('1|true|si|sí', case=False, regex=True) if bono_at_col else False
    out['requiere_bono_consulta'] = df[bono_cons_col].astype(str).str.contains('1|true|si|sí', case=False, regex=True) if bono_cons_col else False
    out['max_slots_dia'] = pd.to_numeric(df[max_slots_col], errors='coerce').fillna(0).astype(int) if max_slots_col else 0
    out['bono_contribucion'] = pd.to_numeric(df[bono_contrib_col], errors='coerce').fillna(0).astype(int) if bono_contrib_col else 0
    return out


def normalize_bono_contribucion(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza la hoja de bonos de contribución del Excel de Ballester.
    
    Estructura esperada (matriz con columnas por tipo de servicio):
    - Col 0: número (ignorar)
    - Col 1: OBRA SOCIAL
    - Col 2: CONSULTAS (bonos)
    - Col 3: ESTUDIOS BAJA COMPLEJIDAD
    - Col 6: RESTO DE LOS ESTUDIOS
    - Col 7: POLISOMNO / POTENCIALES EVOCADOS
    """
    rows = []
    
    # Mapeo de columnas a servicios
    col_map = {
        2: 'consultas',
        3: 'estudios_baja_complejidad',
        6: 'ecografias',
        7: 'estudios_neurologicos'
    }
    
    for idx, row in df.iterrows():
        if idx < 2:  # Skip header rows
            continue
        
        obra_social = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
        if not obra_social or obra_social == 'nan':
            continue
        
        # Procesar cada columna de bono
        for col_idx, servicio_key in col_map.items():
            valor = row.iloc[col_idx] if col_idx < len(row) else None
            if pd.isna(valor) or valor == '' or valor == '-':
                continue
            
            # Extraer números de texto como "2.000 // ENDOCRINO: $10.000 // NEURO: $5.000"
            valor_str = str(valor).strip()
            
            # Caso simple: solo número
            try:
                bono = int(float(valor_str.replace('.', '').replace(',', '').replace('$', '').split()[0]))
                if bono > 0:
                    rows.append({
                        'obra_social': obra_social.upper(),
                        'servicio_key': servicio_key,
                        'bono_contribucion': bono
                    })
                continue
            except (ValueError, IndexError):
                pass
            
            # Caso complejo: texto con múltiples valores
            # Extraer primer número antes de "//"
            if '//' in valor_str or 'NEURO' in valor_str or 'ENDOCRINO' in valor_str:
                parts = valor_str.split('//')
                for part in parts:
                    try:
                        # Buscar patrón de número
                        import re
                        nums = re.findall(r'\$?(\d+[\.,]?\d*)', part)
                        if nums:
                            bono = int(float(nums[0].replace('.', '').replace(',', '')))
                            if bono > 0:
                                rows.append({
                                    'obra_social': obra_social.upper(),
                                    'servicio_key': servicio_key,
                                    'bono_contribucion': bono
                                })
                                break  # Solo tomar el primer valor de esta columna
                    except (ValueError, IndexError):
                        continue
    
    return pd.DataFrame(rows)


def normalize_precios(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza hoja de precios particulares.
    
    Formato esperado del Excel de Ballester:
    - Columna con nombre tipo "PRÁCTICAS PARTICULARES: fecha"
    - Columna "COBRO AL PACIENTE" o similar
    """
    columns = {c.lower(): c for c in df.columns}
    
    # Buscar columna de servicio
    servicio_col = next((columns[c] for c in columns if 'practica' in c or 'servicio' in c or 'estudio' in c), None)
    if not servicio_col:
        servicio_col = df.columns[0]  # Primera columna por defecto
    
    # Buscar columna de precio
    precio_col = next((columns[c] for c in columns if 'cobro' in c or 'precio' in c or 'arancel' in c or 'paciente' in c), None)
    
    if not servicio_col or not precio_col:
        logger.warning(f"No se encontraron columnas válidas para precios. Columnas: {df.columns.tolist()}")
        return pd.DataFrame(columns=['categoria', 'servicio_key', 'precio'])
    
    # Procesar filas
    rows = []
    categoria_actual = 'otros'
    
    for _, row in df.iterrows():
        servicio = str(row.get(servicio_col, '')).strip()
        precio_val = row.get(precio_col)
        
        # Detectar categorías (filas sin precio)
        if pd.isna(precio_val) or precio_val == '':
            if servicio and len(servicio) > 5:
                categoria_actual = slugify_service(servicio)
            continue
        
        # Procesar precio
        try:
            precio = int(pd.to_numeric(precio_val, errors='coerce') or 0)
        except Exception:
            precio = 0
        
        if precio > 0 and servicio:
            rows.append({
                'categoria': categoria_actual,
                'servicio_key': slugify_service(servicio),
                'nombre_completo': servicio,
                'precio': precio
            })
    
    return pd.DataFrame(rows)


def normalize_matrix_coberturas(df: pd.DataFrame) -> pd.DataFrame | None:
    """Convierte una matriz del estilo
    [OBRA SOCIAL | CONSULTAS | CONSULTA NEUROLOGÍA | ESTUDIOS NEUROLÓGICOS | VACUNAS | ECOGRAFÍAS | ...]
    con 'X' en celdas, a filas estándar para la hoja 'coberturas'.

    Mapeo adoptado (para pruebas rápidas):
    - CONSULTAS → servicio_key='consultas'
    - CONSULTA NEUROLOGÍA → 'neurologia_infantil'
    - ESTUDIOS NEUROLÓGICOS → 'ecografias'  (hack para pruebas: PEAT/PSG se resuelven por reglas)
    - VACUNAS → 'consultas'                  (se verifica luego en reglas)
    - ECOGRAFÍAS → 'ecografias'
    - OTRAS PRÁCTICAS → ignorado
    """
    # Identificar columnas por encabezados aproximados
    cols = {c.strip().lower(): c for c in df.columns if isinstance(c, str)}
    obra_col = next((cols[c] for c in cols if 'obra' in c and 'social' in c), None)
    if not obra_col:
        return None

    # Detectar servicios por headings
    service_headings_map: Dict[str, str] = {}
    for key, svc in (
        ('consultas', 'consultas'),
        ('consulta neurolog', 'neurologia_infantil'),
        ('estudios neurol', 'ecografias'),
        ('vacuna', 'consultas'),
        ('ecografia', 'ecografias'),
    ):
        col = next((cols[c] for c in cols if key in c), None)
        if col:
            service_headings_map[col] = svc

    if not service_headings_map:
        return None

    rows = []
    for _, row in df.iterrows():
        obra = str(row.get(obra_col, '')).strip()
        if not obra or obra.lower().startswith('obra social'):
            continue
        for col_name, service_key in service_headings_map.items():
            val = row.get(col_name, '')
            has_cov = False
            if pd.isna(val):
                has_cov = False
            elif isinstance(val, (int, float)):
                has_cov = val != 0
            else:
                txt = str(val).strip().lower()
                has_cov = bool(txt) and ('x' in txt or 'si' in txt or 'sí' in txt)
            if has_cov:
                rows.append({
                    'obra_social': obra,
                    'servicio_key': service_key,
                    'cobertura': 'COVERED',
                    'copago': 0,
                    'requiere_autorizacion': False,
                    'requiere_bono_atencion': False,
                    'requiere_bono_consulta': False,
                    'max_slots_dia': 0,
                    'bono_contribucion': 0,
                })
    if not rows:
        return None
    out = pd.DataFrame(rows)
    # Normalizar obra social a mayúsculas
    out['obra_social'] = out['obra_social'].str.upper()
    return out


def main():
    ap = argparse.ArgumentParser(description='Normaliza matrices Excel → formato seed estándar Ballester')
    ap.add_argument('--in', dest='inp', required=True, help='Excel de entrada (xlsx)')
    ap.add_argument('--out', dest='out', required=True, help='Excel de salida normalizado (xlsx)')
    ap.add_argument('--sheet', dest='sheet', default=None, help='Nombre de hoja si querés normalizar una sola')
    args = ap.parse_args()

    xls = pd.ExcelFile(args.inp)

    # Intentar detectar hojas por nombre aproximado
    # Si solo tenemos tu planilla “cobertura obras sociales”, la normalizamos a 'coberturas'
    cob_df = None
    for name in xls.sheet_names:
        low = name.lower()
        if any(k in low for k in ['cobertura', 'obras', 'sociales', 'coberturas']):
            cob_df = pd.read_excel(xls, sheet_name=name)
            break
    if args.sheet:
        cob_df = pd.read_excel(xls, sheet_name=args.sheet)

    # Construir Excel de salida
    with pd.ExcelWriter(args.out, engine='openpyxl') as writer:
        if cob_df is not None:
            # Primero intentar formato matriz (X por columnas)
            cob_norm = normalize_matrix_coberturas(cob_df)
            if cob_norm is None:
                # Fallback a formato tabular genérico
                cob_norm = normalize_coberturas(cob_df)
            cob_norm.to_excel(writer, sheet_name='coberturas', index=False)
            logger.info(f"[NORMALIZE] coberturas → {len(cob_norm)} filas")

        # Precios: buscar hoja con nombres conocidos o hoja exacta "precios"
        price_df = None
        for name in xls.sheet_names:
            low = name.lower()
            if any(k in low for k in ['precio', 'particular', 'arancel', 'cobro']):
                price_df = pd.read_excel(xls, sheet_name=name)
                logger.info(f"[NORMALIZE] Procesando hoja de precios: {name}")
                break
        if price_df is not None:
            price_norm = normalize_precios(price_df)
            price_norm.to_excel(writer, sheet_name='precios', index=False)
            logger.info(f"[NORMALIZE] precios → {len(price_norm)} filas")
        
        # Bono contribucion: normalizar matriz si existe
        bono_df = None
        for name in xls.sheet_names:
            low = name.lower()
            if 'bono' in low and 'contrib' in low:
                bono_df = pd.read_excel(xls, sheet_name=name)
                logger.info(f"[NORMALIZE] Procesando hoja de bonos: {name}")
                bono_norm = normalize_bono_contribucion(bono_df)
                bono_norm.to_excel(writer, sheet_name='bono_contribucion', index=False)
                logger.info(f"[NORMALIZE] bono_contribucion → {len(bono_norm)} filas normalizadas")
                break

        # Deja plantillas vacías para completar si hace falta
        if 'especialistas' not in writer.book.sheetnames:
            pd.DataFrame(columns=['nombre','especialidad','dias_atencion','reglas_json']).to_excel(writer, sheet_name='especialistas', index=False)
        if 'preparaciones' not in writer.book.sheetnames:
            pd.DataFrame(columns=['tipo','servicio_key','grupo_edad','instruccion']).to_excel(writer, sheet_name='preparaciones', index=False)

    logger.info(f"[NORMALIZE] ✅ Archivo normalizado: {args.out}")


if __name__ == '__main__':
    main()


