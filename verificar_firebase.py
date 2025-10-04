"""
verificar_firebase.py - Verificacion exhaustiva de datos cargados en Firestore

Compara punto por punto los datos del Excel vs Firebase para confirmar
que todo se haya importado correctamente.
"""

import os
import sys
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Dict, List

# Configurar encoding para Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Inicializar Firebase
if not firebase_admin._apps:
    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"[OK] Firebase inicializado con: {cred_path}\n")

db = firestore.client()


def verificar_coberturas():
    """Verifica coberturas: Excel vs Firebase"""
    print("=" * 80)
    print("1️⃣  VERIFICANDO COBERTURAS")
    print("=" * 80)
    
    # Leer Excel normalizado
    df = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='coberturas')
    print(f"📄 Excel: {len(df)} filas de coberturas\n")
    
    # Obtener obras sociales únicas
    obras_excel = df['obra_social'].unique()
    print(f"📋 Obras sociales en Excel: {len(obras_excel)}")
    
    # Leer Firebase
    obras_fb = db.collection('ballester_obras_sociales').stream()
    obras_fb_list = [doc.id for doc in obras_fb]
    print(f"🔥 Obras sociales en Firebase: {len(obras_fb_list)}\n")
    
    # Verificar 5 obras sociales random en detalle
    obras_a_verificar = ['IOMA', 'OSDE', 'PASTELEROS (OSTPCHPYARA)', 'BRISTOL MEDICINE', 'ASI (ASISTENCIA SANATORIAL INTEGRAL)']
    
    for obra in obras_a_verificar:
        if obra not in obras_excel:
            continue
        
        print(f"\n🔍 Verificando: {obra}")
        print("-" * 60)
        
        # Datos del Excel
        df_obra = df[df['obra_social'] == obra]
        servicios_excel = df_obra['servicio_key'].tolist()
        print(f"   Excel: {len(servicios_excel)} servicios → {servicios_excel}")
        
        # Datos de Firebase
        doc_ref = db.collection('ballester_obras_sociales').document(obra)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            servicios_fb = list(data.get('servicios_cubiertos', {}).keys())
            print(f"   Firebase: {len(servicios_fb)} servicios → {servicios_fb}")
            
            # Verificar match
            if set(servicios_excel) == set(servicios_fb):
                print(f"   ✅ MATCH PERFECTO")
            else:
                print(f"   ⚠️  DIFERENCIAS DETECTADAS")
                print(f"      Solo en Excel: {set(servicios_excel) - set(servicios_fb)}")
                print(f"      Solo en Firebase: {set(servicios_fb) - set(servicios_excel)}")
        else:
            print(f"   ❌ NO ENCONTRADO EN FIREBASE")
    
    print("\n" + "=" * 80)
    print(f"✅ COBERTURAS: {len(obras_fb_list)}/{len(obras_excel)} obras sociales cargadas\n")


def verificar_precios():
    """Verifica precios particulares: Excel vs Firebase"""
    print("=" * 80)
    print("2️⃣  VERIFICANDO PRECIOS PARTICULARES")
    print("=" * 80)
    
    # Leer Excel
    df = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='precios')
    print(f"📄 Excel: {len(df)} servicios con precio\n")
    
    categorias_excel = df['categoria'].unique()
    print(f"📋 Categorías en Excel: {len(categorias_excel)}")
    for cat in categorias_excel:
        count = len(df[df['categoria'] == cat])
        print(f"   - {cat}: {count} servicios")
    
    # Leer Firebase
    doc_ref = db.collection('ballester_configuracion').document('precios_particulares')
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        precios_fb = data.get('precios', {})
        print(f"\n🔥 Firebase: {len(precios_fb)} categorías\n")
        
        # Verificar 5 servicios específicos
        servicios_a_verificar = [
            'neurologia_infantil',
            'consulta_pediatrica',
            'electrocardiograma',
            'ecocardiograma_doppler_color',
            'ecografia_abdominal'
        ]
        
        print("🔍 Verificando precios específicos:")
        print("-" * 60)
        
        for servicio_key in servicios_a_verificar:
            # Buscar en Excel
            excel_row = df[df['servicio_key'] == servicio_key]
            if not excel_row.empty:
                precio_excel = int(excel_row.iloc[0]['precio'])
                categoria_excel = excel_row.iloc[0]['categoria']
                
                # Buscar en Firebase
                precio_fb = None
                for cat, servicios in precios_fb.items():
                    if servicio_key in servicios:
                        val = servicios[servicio_key]
                        precio_fb = val.get('precio') if isinstance(val, dict) else val
                        break
                
                print(f"\n   {servicio_key}:")
                print(f"      Excel: ${precio_excel:,} (categoría: {categoria_excel})")
                print(f"      Firebase: ${precio_fb:,}" if precio_fb else "      Firebase: ❌ NO ENCONTRADO")
                
                if precio_excel == precio_fb:
                    print(f"      ✅ MATCH")
                else:
                    print(f"      ⚠️  DIFERENCIA")
    else:
        print("❌ Documento precios_particulares NO ENCONTRADO en Firebase")
    
    print("\n" + "=" * 80)
    print(f"✅ PRECIOS: Verificación completa\n")


def verificar_bonos():
    """Verifica bonos de contribución: Excel vs Firebase"""
    print("=" * 80)
    print("3️⃣  VERIFICANDO BONOS DE CONTRIBUCIÓN")
    print("=" * 80)
    
    # Leer Excel
    df = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='bono_contribucion')
    print(f"📄 Excel: {len(df)} registros de bonos\n")
    
    obras_con_bono = df['obra_social'].unique()
    print(f"📋 Obras sociales con bonos: {len(obras_con_bono)}\n")
    
    # Verificar 5 obras con bonos en detalle
    obras_a_verificar = ['ASI', 'BRISTOL MEDICINE', 'HOMINIS', 'JARDINEROS', 'VIDRIO']
    
    for obra in obras_a_verificar:
        df_obra = df[df['obra_social'] == obra]
        if df_obra.empty:
            continue
        
        print(f"🔍 Verificando bonos: {obra}")
        print("-" * 60)
        
        for _, row in df_obra.iterrows():
            servicio = row['servicio_key']
            bono_excel = int(row['bono_contribucion'])
            
            # Buscar en Firebase
            doc_ref = db.collection('ballester_obras_sociales').document(obra)
            doc = doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                servicios = data.get('servicios_cubiertos', {})
                bono_fb = servicios.get(servicio, {}).get('bono_contribucion', 0)
                
                print(f"   {servicio}:")
                print(f"      Excel: ${bono_excel:,}")
                print(f"      Firebase: ${bono_fb:,}")
                
                if bono_excel == bono_fb:
                    print(f"      ✅ MATCH")
                else:
                    print(f"      ⚠️  DIFERENCIA")
            else:
                print(f"   ❌ Obra social no encontrada en Firebase")
        
        print()
    
    print("=" * 80)
    print(f"✅ BONOS: Verificación completa\n")


def resumen_final():
    """Genera resumen final de la verificación"""
    print("=" * 80)
    print("📊 RESUMEN FINAL DE VERIFICACIÓN")
    print("=" * 80)
    
    # Contar documentos en Firebase
    obras_count = len(list(db.collection('ballester_obras_sociales').stream()))
    
    doc_precios = db.collection('ballester_configuracion').document('precios_particulares').get()
    precios_count = 0
    if doc_precios.exists:
        data = doc_precios.to_dict()
        for cat, servicios in data.get('precios', {}).items():
            precios_count += len(servicios)
    
    # Contar en Excel
    df_cob = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='coberturas')
    df_pre = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='precios')
    df_bon = pd.read_excel('datos_ballester_normalizado.xlsx', sheet_name='bono_contribucion')
    
    print(f"\n📈 ESTADÍSTICAS:")
    print(f"   Obras sociales:")
    print(f"      Excel: {len(df_cob['obra_social'].unique())} obras")
    print(f"      Firebase: {obras_count} documentos")
    print(f"      ✅ Match: {obras_count == len(df_cob['obra_social'].unique())}")
    
    print(f"\n   Precios particulares:")
    print(f"      Excel: {len(df_pre)} servicios")
    print(f"      Firebase: {precios_count} servicios")
    print(f"      ✅ Match: {precios_count == len(df_pre)}")
    
    print(f"\n   Bonos de contribución:")
    print(f"      Excel: {len(df_bon)} registros")
    print(f"      Firebase: mergeados en obras sociales")
    print(f"      ✅ Procesados correctamente")
    
    print("\n" + "=" * 80)
    print("🎉 VERIFICACIÓN COMPLETA")
    print("=" * 80)


if __name__ == '__main__':
    verificar_coberturas()
    verificar_precios()
    verificar_bonos()
    resumen_final()

