"""
seed_ballester_directo.py - Importación DIRECTA del Excel a Firestore

Respeta el Excel TAL CUAL:
- NO transforma nombres
- NO normaliza claves
- Carga TODO el contenido de cada celda
- X = CUBRE, vacío = NO CUBRE
- Mergea bonos con coberturas existentes o crea nuevas obras sociales
"""

import os
import sys
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re

# Configurar encoding para Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Inicializar Firebase
if not firebase_admin._apps:
    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"[OK] Firebase inicializado\n")

db = firestore.client()


def crear_id_documento(texto: str) -> str:
    """Crea un ID válido para Firestore (sin / y caracteres especiales)"""
    # Reemplazar caracteres problemáticos
    texto_limpio = texto.replace('/', '_').replace('\\', '_')
    texto_limpio = re.sub(r'[^\w\s\-\(\)\.áéíóúñÁÉÍÓÚÑ]', '_', texto_limpio)
    texto_limpio = re.sub(r'\s+', '_', texto_limpio)
    texto_limpio = texto_limpio.strip('_')
    return texto_limpio[:1500]  # Firestore limit


def limpiar_coleccion(collection_name: str):
    """Limpia completamente una colección"""
    print(f"🗑️  Limpiando colección: {collection_name}")
    batch = db.batch()
    count = 0
    for doc in db.collection(collection_name).stream():
        batch.delete(doc.reference)
        count += 1
        if count % 100 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"   ✅ {count} documentos eliminados\n")


def seed_precios_particulares():
    """Carga precios particulares TAL CUAL del Excel"""
    print("=" * 80)
    print("1️⃣  CARGANDO PRECIOS PARTICULARES")
    print("=" * 80)
    
    xls = pd.ExcelFile('clinica_ballester.xlsx')
    df = pd.read_excel(xls, sheet_name='precios')
    
    # Primera columna = nombre del servicio/práctica
    # Segunda columna = precio
    col_practica = df.columns[0]
    col_precio = df.columns[1]
    
    precios = {}
    
    for idx, row in df.iterrows():
        practica = str(row[col_practica]).strip() if pd.notna(row[col_practica]) else ''
        precio_val = row[col_precio]
        
        if not practica or practica == 'nan':
            continue
        
        # Si no tiene precio, es una categoría/sección
        if pd.isna(precio_val) or precio_val == '':
            continue
        
        try:
            precio = int(float(precio_val))
            if precio > 0:
                precios[practica] = {
                    'nombre': practica,
                    'precio': precio
                }
        except (ValueError, TypeError):
            continue
    
    # Guardar en Firebase
    doc_ref = db.collection('ballester_configuracion').document('precios_particulares')
    doc_ref.set({
        'precios': precios,
        'fecha_actualizacion': firestore.SERVER_TIMESTAMP
    })
    
    print(f"✅ {len(precios)} precios particulares cargados")
    print(f"   Ejemplos:")
    for i, (nombre, data) in enumerate(list(precios.items())[:5]):
        print(f"   - {nombre}: ${data['precio']:,}")
    print()


def seed_coberturas():
    """Carga coberturas TAL CUAL del Excel"""
    print("=" * 80)
    print("2️⃣  CARGANDO COBERTURAS (OBRAS SOCIALES)")
    print("=" * 80)
    
    xls = pd.ExcelFile('clinica_ballester.xlsx')
    df = pd.read_excel(xls, sheet_name='coberturas')
    
    print(f"📄 Leyendo {len(df)} filas del Excel")
    print(f"📋 Columnas detectadas: {len(df.columns)}\n")
    
    # Primera columna = OBRA SOCIAL
    col_obra_social = df.columns[0]
    
    # Resto de columnas = servicios
    columnas_servicios = df.columns[1:]
    
    obras_cargadas = 0
    
    for idx, row in df.iterrows():
        obra_social = str(row[col_obra_social]).strip() if pd.notna(row[col_obra_social]) else ''
        
        # Saltar filas vacías o headers
        if not obra_social or obra_social == 'nan' or 'OBRA SOCIAL' in obra_social.upper():
            continue
        
        # Procesar cada servicio (columna)
        servicios_cubiertos = {}
        
        for col_servicio in columnas_servicios:
            nombre_servicio = str(col_servicio).strip()
            valor_celda = row[col_servicio]
            
            # Determinar si cubre
            cubre = False
            observaciones = ''
            
            if pd.notna(valor_celda):
                valor_str = str(valor_celda).strip().upper()
                
                # X o texto = CUBRE
                if valor_str and valor_str != '' and valor_str != 'NAN':
                    cubre = True
                    # Si no es solo una X, guardar el texto completo como observaciones
                    if valor_str != 'X':
                        observaciones = str(valor_celda).strip()
            
            # Si cubre, agregar servicio
            if cubre:
                servicios_cubiertos[nombre_servicio] = {
                    'cobertura': 'COVERED',
                    'nombre_completo': nombre_servicio,
                    'observaciones': observaciones if observaciones else ''
                }
        
        # Guardar en Firebase
        if servicios_cubiertos:
            doc_id = crear_id_documento(obra_social)
            doc_ref = db.collection('ballester_obras_sociales').document(doc_id)
            doc_ref.set({
                'nombre_completo': obra_social,
                'servicios_cubiertos': servicios_cubiertos,
                'fecha_actualizacion': firestore.SERVER_TIMESTAMP
            })
            obras_cargadas += 1
            
            if obras_cargadas <= 3:
                print(f"✅ {obra_social}")
                print(f"   Servicios cubiertos: {len(servicios_cubiertos)}")
                for srv_name in list(servicios_cubiertos.keys())[:2]:
                    srv_data = servicios_cubiertos[srv_name]
                    obs = srv_data.get('observaciones', '')
                    if obs:
                        print(f"   - {srv_name}: {obs[:60]}...")
                    else:
                        print(f"   - {srv_name}: CUBRE")
                print()
    
    print(f"✅ {obras_cargadas} obras sociales cargadas\n")


def seed_bonos_contribucion():
    """Mergea bonos de contribución con obras sociales existentes"""
    print("=" * 80)
    print("3️⃣  MERGEANDO BONOS DE CONTRIBUCIÓN")
    print("=" * 80)
    
    xls = pd.ExcelFile('clinica_ballester.xlsx')
    df = pd.read_excel(xls, sheet_name='bono_contribucion')
    
    print(f"📄 Leyendo {len(df)} filas de bonos\n")
    
    # Detectar headers (fila 1 tiene los nombres de servicios)
    headers_row = None
    for idx, row in df.iterrows():
        # Buscar fila que tenga "CONSULTAS" o similar
        for val in row:
            if pd.notna(val) and 'CONSULTAS' in str(val).upper():
                headers_row = idx
                break
        if headers_row is not None:
            break
    
    if headers_row is None:
        print("⚠️  No se encontró fila de headers en bono_contribucion")
        return
    
    # Leer headers de servicios
    headers = []
    for col_idx, val in enumerate(df.iloc[headers_row]):
        if pd.notna(val) and str(val).strip():
            headers.append((col_idx, str(val).strip()))
    
    print(f"📋 Servicios detectados en bonos: {len(headers)}")
    for col_idx, nombre in headers[:3]:
        print(f"   - Columna {col_idx}: {nombre[:60]}")
    print()
    
    # Procesar filas de datos (después de headers)
    bonos_mergeados = 0
    obras_nuevas = 0
    
    for idx in range(headers_row + 1, len(df)):
        row = df.iloc[idx]
        
        # Columna 1 = obra social (asumiendo col 1 después del número)
        obra_social = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
        
        if not obra_social or obra_social == 'nan':
            continue
        
        # Leer doc existente o crear nuevo
        doc_id = crear_id_documento(obra_social)
        doc_ref = db.collection('ballester_obras_sociales').document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            servicios = data.get('servicios_cubiertos', {})
        else:
            servicios = {}
            obras_nuevas += 1
        
        # Procesar bonos para cada servicio
        for col_idx, nombre_servicio in headers:
            valor_celda = row.iloc[col_idx] if col_idx < len(row) else None
            
            if pd.isna(valor_celda) or valor_celda == '' or valor_celda == '-':
                continue
            
            valor_str = str(valor_celda).strip()
            
            # Extraer números del texto
            nums = re.findall(r'\$?(\d+[\.,]?\d*)', valor_str)
            bonos_encontrados = []
            for num in nums:
                try:
                    bono = int(float(num.replace('.', '').replace(',', '')))
                    if bono > 0:
                        bonos_encontrados.append(bono)
                except (ValueError, TypeError):
                    continue
            
            # Agregar info de bono al servicio
            if not servicios.get(nombre_servicio):
                servicios[nombre_servicio] = {
                    'cobertura': 'COVERED',
                    'nombre_completo': nombre_servicio,
                    'observaciones': ''
                }
            
            if bonos_encontrados:
                servicios[nombre_servicio]['bono_contribucion'] = bonos_encontrados[0]
                servicios[nombre_servicio]['bono_info'] = valor_str
        
        # Guardar
        if servicios:
            doc_ref.set({
                'nombre_completo': obra_social,
                'servicios_cubiertos': servicios,
                'fecha_actualizacion': firestore.SERVER_TIMESTAMP
            }, merge=True)
            bonos_mergeados += 1
    
    print(f"✅ {bonos_mergeados} obras sociales actualizadas con bonos")
    print(f"✅ {obras_nuevas} obras sociales nuevas creadas desde bonos\n")


def verificar_carga():
    """Verifica la carga final"""
    print("=" * 80)
    print("🔍 VERIFICACIÓN FINAL")
    print("=" * 80)
    
    # Contar obras sociales
    obras = list(db.collection('ballester_obras_sociales').stream())
    print(f"📊 Obras sociales en Firebase: {len(obras)}")
    
    # Mostrar 3 ejemplos
    print(f"\n📋 Ejemplos de obras sociales cargadas:")
    for doc in obras[:3]:
        data = doc.to_dict()
        servicios = data.get('servicios_cubiertos', {})
        print(f"\n   {doc.id}:")
        print(f"   - Servicios: {len(servicios)}")
        for srv_name in list(servicios.keys())[:2]:
            srv_data = servicios[srv_name]
            bono = srv_data.get('bono_contribucion', 0)
            obs = srv_data.get('observaciones', '')
            if bono > 0:
                print(f"     * {srv_name}: ${bono:,} (bono)")
            elif obs:
                print(f"     * {srv_name}: {obs[:40]}...")
            else:
                print(f"     * {srv_name}: CUBRE")
    
    # Verificar precios
    doc_precios = db.collection('ballester_configuracion').document('precios_particulares').get()
    if doc_precios.exists:
        precios = doc_precios.to_dict().get('precios', {})
        print(f"\n📊 Precios particulares: {len(precios)} servicios")
    
    print("\n" + "=" * 80)
    print("🎉 IMPORTACIÓN COMPLETA")
    print("=" * 80)


if __name__ == '__main__':
    print("\n🚀 INICIANDO IMPORTACIÓN DIRECTA DESDE EXCEL")
    print("=" * 80)
    print("⚠️  IMPORTANTE: Esto borrará TODA la data existente\n")
    
    # Limpiar colecciones
    limpiar_coleccion('ballester_obras_sociales')
    limpiar_coleccion('ballester_configuracion')
    
    # Cargar datos
    seed_precios_particulares()
    seed_coberturas()
    seed_bonos_contribucion()
    
    # Verificar
    verificar_carga()

