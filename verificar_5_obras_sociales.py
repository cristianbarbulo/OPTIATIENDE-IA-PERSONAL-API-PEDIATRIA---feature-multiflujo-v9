"""
verificar_5_obras_sociales.py - Verificación detallada de 5 obras sociales

Muestra TODA la información cargada para confirmar que el Excel se respetó 100%
"""

import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

# Configurar encoding para Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Inicializar Firebase
if not firebase_admin._apps:
    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

db = firestore.client()

# Obras a verificar
obras_a_verificar = [
    'IOMA',
    'PASTELEROS (OSTPCHPYARA)',
    'BRISTOL MEDICINE',
    'ASI (asistencia sanatorial integral)',
    'ASSISTENCIAL SALUD'
]

print("=" * 100)
print("🔍 VERIFICACIÓN DETALLADA DE 5 OBRAS SOCIALES")
print("=" * 100)
print()

# Obtener todos los documentos
all_docs = {doc.to_dict().get('nombre_completo', ''): doc for doc in db.collection('ballester_obras_sociales').stream()}

for i, obra_nombre in enumerate(obras_a_verificar, 1):
    print(f"\n{'=' * 100}")
    print(f"📋 OBRA SOCIAL #{i}: {obra_nombre}")
    print('=' * 100)
    
    # Buscar por nombre completo (case insensitive)
    doc = None
    doc_id = None
    for nombre_completo, documento in all_docs.items():
        if nombre_completo.upper() == obra_nombre.upper():
            doc = documento
            doc_id = documento.id
            break
    
    if not doc:
        print(f"❌ NO ENCONTRADA en Firebase")
        continue
    
    data = doc.to_dict()
    
    print(f"\n📄 ID del documento: {doc_id}")
    print(f"📝 Nombre completo: {data.get('nombre_completo', 'N/A')}")
    
    servicios = data.get('servicios_cubiertos', {})
    print(f"\n✅ Servicios cubiertos: {len(servicios)}")
    print("-" * 100)
    
    for idx, (servicio_nombre, servicio_data) in enumerate(servicios.items(), 1):
        print(f"\n   {idx}. {servicio_nombre}")
        print(f"      └─ Cobertura: {servicio_data.get('cobertura', 'N/A')}")
        
        observaciones = servicio_data.get('observaciones', '')
        if observaciones:
            print(f"      └─ Observaciones: {observaciones[:200]}")
            if len(observaciones) > 200:
                print(f"         (... {len(observaciones) - 200} caracteres más)")
        
        bono = servicio_data.get('bono_contribucion', 0)
        if bono > 0:
            print(f"      └─ Bono contribución: ${bono:,}")
        
        bono_info = servicio_data.get('bono_info', '')
        if bono_info:
            print(f"      └─ Info bono: {bono_info}")
    
    print()

print("\n" + "=" * 100)
print("✅ VERIFICACIÓN COMPLETA")
print("=" * 100)
print(f"\nTotal de obras sociales en Firebase: {len(all_docs)}")

