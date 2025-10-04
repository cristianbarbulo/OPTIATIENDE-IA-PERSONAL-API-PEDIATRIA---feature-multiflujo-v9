"""
deploy_render.py - Crear servicio completo en Render automáticamente

Usa la API REST de Render para:
1. Crear servicio web
2. Configurar variables de entorno
3. Hacer deploy automático
"""

import requests
import json
import time
import sys

# Configurar encoding para Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Configuración
RENDER_API_KEY = "rnd_4Cu7nF3mFCV9f72RTa9czQJOLsXJ"
SERVICE_NAME = "optiatiende-ballester"
REPO_URL = "https://github.com/crisb/OPTICONNECTA-PEDIATRIA-BALLESTER"  # Ajustar si es necesario

# Headers para API de Render
headers = {
    "Authorization": f"Bearer {RENDER_API_KEY}",
    "Content-Type": "application/json"
}

def get_owner_id():
    """Obtener el owner ID del usuario"""
    print("🔍 Obteniendo información del usuario...")
    response = requests.get("https://api.render.com/v1/owners", headers=headers)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        owners = response.json()
        if owners:
            owner_id = owners[0]['owner']['id']
            print(f"✅ Owner ID: {owner_id}")
            return owner_id
    else:
        print(f"❌ Error obteniendo owner: {response.status_code} - {response.text}")
        return None

def create_service(owner_id):
    """Crear servicio web en Render"""
    print(f"\n🚀 Creando servicio: {SERVICE_NAME}")
    
    service_data = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "serviceDetails": {
            "buildCommand": "pip install -r requirements.txt",
            "startCommand": "gunicorn main:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2",
            "plan": "starter",
            "region": "oregon",
            "runtime": "python"
        }
    }
    
    response = requests.post("https://api.render.com/v1/services", 
                           headers=headers, 
                           json=service_data)
    
    if response.status_code == 201:
        service = response.json()
        service_id = service['id']
        print(f"✅ Servicio creado: {service_id}")
        print(f"🌐 URL: {service.get('serviceDetails', {}).get('url', 'Pendiente')}")
        return service_id
    else:
        print(f"❌ Error creando servicio: {response.status_code} - {response.text}")
        return None

def set_environment_variables(service_id):
    """Configurar variables de entorno"""
    print(f"\n⚙️  Configurando variables de entorno...")
    
    # Variables que ya tengo configuradas
    env_vars = {
        "TENANT_NAME": "ballester",
        "CLIENT_NAME": "Centro Pediátrico Ballester",
        "GOOGLE_CREDENTIALS_JSON": '{"type":"service_account","project_id":"clinicaballester-de015","private_key_id":"da4db66c5e39508aa912e0bc6e5cde87b1bfe452","private_key":"-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDsZqB1B3KYz/g/\\n54tp8GrP/pNS5okpT28D7Jc+krg1h+zpMbTVZdpX861OD0/QD4t/Lmf7u4M1E8rI\\nZMilrRhW/x5g4KwMRe5P1WvreBQ+0o5+8T3aDESmgIzltCoMzqZGzfID7Dzc8NAt\\n2FEdNBW5NiP1FLCSRg5Usteid61a5yoEkdwSIBlctTc5RVzn0Xz3gKfgXT1RetEW\\n+UZvBDx8Iq4T3EqrupiX4UyhVfas5ExBS4+rAEAY2/RkodLIDMJ51o5p9S5aBZZV\\n35S59k/CW5FNCsbXefT8t762BGs41CtDIbf1ySsuZ0XyYrzMkjUkwajGcdZGtpZu\\nPSL/zbvBAgMBAAECggEAEyIWRAqLhZ81dDShFbyx5G4yDdBfUxLdBRgJwLR+yMRc\\n0h3mCSyCcMJl6S63krsjWvKOU3NAghP9Ql1X2QLquKXS11vvyNmDGX6ISslP+Cqy\\nAkezrhl2l/RJExFTIvC5x/rEpvkgjvBFpSRAImk0BebCH8SiKuCVKdlEtx9RDk2G\\nB4Tz0c1TVWP+QTBveK02m/1JKlK3rm2EqDxeiSCQhsYi596UepNhhDRZ+xnzRPTA\\nCkfq5aM3WGvOQnbBHXi1AEBGrK35Xp7UNtRg3ogBrrCdWQn6P56M/sw0zQ5hPfc2\\nE659xqKcGMS126oI0rgvs6ZFk5j+12pp+Mtd7EzKcQKBgQD5cB++cP6XLIVVvNTy\\nSLOU89FOA7DffCji7Y/fzlggDx0ITGoz/Ra1R8fTtMJ8DrrhoTvSlYNazj1WQZRI\\n/Pay9qbvX0/5Hq/575TEDtCts6/aQh7Js8bNZ2ZylmI97YHkq7KUYDGJZ3Q7RLVI\\nIJZXTv8dULxfXdVgEpzxteOIqQKBgQDynrPbpDBIWLAudQJt011oJ8p3q9xaHCkn\\n6JGgkVgKjVm8zONVW0KfARla1ZT+Ugy/lDoa56gRYqW6UlmiJ8KUJEZw9uYF5KHQ\\nffX7o6LRQuOmdPPRVf/vkbAnZQoPpNoTANydMHyIdPi7DNuVeoBmq0cNcFkgvXRl\\ndvyYDqARWQKBgAXQz2ypRcZQi2tMU8qyVz2J0b935o/PXUStNUWKkhNtRsgCwBcm\\nN3lSix4sgLxTu5e3IqXuRnm/hT6VmNd6zmWtyoaaOkscpA23wEgx8DucjOUR1ZXu\\nUxxG5OSXDQNUnkquliNPetgxSUx4daGQ4PB4LwqH71xp26e5x177VqrBAoGBAPAb\\nM3AZC1dtvd4cGm1KElSznGHWiVn8KJbASO6ZKII45Sg9tHWSvVnSop8MZElUNh2a\\nue5KeD/MWqsMOHyL0Lr/M180WOxYGfPV1IxWoxlpkxX3BByVeZZDngs+qThWMyM/\\nZRWDGJuK92VWEjHabBwvQUABgZMvK3QGz3BEeRDxAoGAHyOmi5Ov59+/lUoZUWzF\\nnvZ81Cr46hyAjgRkcDX/Qm+9YPCtNEAnyc5llqv9++txppRAx08SBTnrfLzJfQ5F\\nJMKZ0X4eUzIPBQ3EwLdYZ+Be4CEkHqWKsCdojXqiC9zqq4ThO09NxihKUedhYi1y\\njDjKvgd5FNoXsS9uCqedOuw=\\n-----END PRIVATE KEY-----\\n","client_email":"firebase-adminsdk-fbsvc@clinicaballester-de015.iam.gserviceaccount.com","client_id":"103558247335107473989","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40clinicaballester-de015.iam.gserviceaccount.com","universe_domain":"googleapis.com"}',
        "WEBHOOK_VERIFY_TOKEN": "ballester_webhook_2025_secure_token",
        "PORT": "8080",
        "FLASK_ENV": "production",
        "DEBUG": "false",
        "LOG_LEVEL": "INFO"
    }
    
    # Variables que el usuario debe completar
    user_vars = {
        "OPENAI_API_KEY": "[COMPLETAR CON TU API KEY DE OPENAI]",
        "WHATSAPP_API_KEY": "[COMPLETAR CON TU API KEY DE 360DIALOG]",
        "WHATSAPP_PHONE_NUMBER_ID": "[COMPLETAR CON TU PHONE NUMBER ID DE 360DIALOG]",
        "WHATSAPP_BUSINESS_ACCOUNT_ID": "[COMPLETAR CON TU BUSINESS ACCOUNT ID DE 360DIALOG]",
        "CLINICA_API_BASE": "[COMPLETAR CON URL BASE DE LA API OMNIA]",
        "CLINICA_API_KEY": "[COMPLETAR CON API KEY DE OMNIA]",
        "NOTIFICATION_CONTACT": "[COMPLETAR CON TU NÚMERO DE WHATSAPP]"
    }
    
    # Combinar todas las variables
    all_vars = {**env_vars, **user_vars}
    
    # Configurar cada variable
    for key, value in all_vars.items():
        env_data = {
            "key": key,
            "value": value
        }
        
        response = requests.post(f"https://api.render.com/v1/services/{service_id}/env-vars",
                               headers=headers,
                               json=env_data)
        
        if response.status_code == 201:
            print(f"   ✅ {key}")
        else:
            print(f"   ⚠️  {key}: {response.status_code}")
    
    print(f"\n📝 Variables que necesitás completar:")
    for key, value in user_vars.items():
        print(f"   - {key}")

def get_service_url(service_id):
    """Obtener URL del servicio"""
    print(f"\n🔗 Obteniendo URL del servicio...")
    
    response = requests.get(f"https://api.render.com/v1/services/{service_id}", headers=headers)
    
    if response.status_code == 200:
        service = response.json()
        url = service.get('serviceDetails', {}).get('url')
        if url:
            print(f"🌐 URL del servicio: {url}")
            print(f"🔗 Webhook URL: {url}/webhook")
            return url
        else:
            print("⏳ Servicio aún desplegándose...")
            return None
    else:
        print(f"❌ Error obteniendo servicio: {response.status_code}")
        return None

def main():
    print("🚀 DEPLOY AUTOMÁTICO EN RENDER")
    print("=" * 50)
    
    # 1. Obtener owner ID
    owner_id = get_owner_id()
    if not owner_id:
        return
    
    # 2. Crear servicio
    service_id = create_service(owner_id)
    if not service_id:
        return
    
    # 3. Configurar variables
    set_environment_variables(service_id)
    
    # 4. Obtener URL
    url = get_service_url(service_id)
    
    print("\n" + "=" * 50)
    print("✅ DEPLOY COMPLETADO")
    print("=" * 50)
    print(f"\n📋 Servicio ID: {service_id}")
    if url:
        print(f"🌐 URL: {url}")
        print(f"🔗 Webhook: {url}/webhook")
    
    print(f"\n📝 PRÓXIMOS PASOS:")
    print(f"1. Ir a https://dashboard.render.com")
    print(f"2. Buscar servicio '{SERVICE_NAME}'")
    print(f"3. Completar las 7 variables marcadas con [COMPLETAR...]")
    print(f"4. El servicio se redesplegará automáticamente")
    print(f"5. Configurar webhook en 360dialog con: {url}/webhook")
    print(f"6. ¡Probar enviando 'Hola' por WhatsApp!")

if __name__ == "__main__":
    main()

