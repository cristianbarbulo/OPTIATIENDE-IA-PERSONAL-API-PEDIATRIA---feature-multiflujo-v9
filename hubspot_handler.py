# hubspot_handler.py (Versión Final con Email)
import requests
import logging
import json
from config import HUBSPOT_API_KEY

# Usamos el logger para este módulo
logger = logging.getLogger(__name__)

# La URL base se mantiene como una constante global para el módulo
BASE_URL = "https://api.hubapi.com/crm/v3/objects/contacts"

def update_hubspot_contact(phone_number: str, name: str, last_message: str, lead_data: dict):
    """
    Busca un contacto en HubSpot por su número de teléfono. Si existe, lo actualiza.
    Si no existe, lo crea. Ahora incluye la lógica para manejar el email.
    """
    if not HUBSPOT_API_KEY:
        logger.warning("No se ha configurado la clave de API de HubSpot. Saltando la actualización.")
        return

    headers = {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json"
    }

    # Aseguramos que el número de teléfono esté limpio para HubSpot
    clean_phone_number = phone_number.replace('@c.us', '').replace('+', '')

    # --- 1. Buscar si el contacto ya existe (Lógica sin cambios) ---
    search_url = f"{BASE_URL}/search"
    search_payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "phone",
                "operator": "EQ",
                "value": clean_phone_number
            }]
        }],
        "properties": ["phone", "firstname", "lastname", "email"] # Pedimos también el email para no sobreescribirlo
    }

    try:
        response = requests.post(search_url, headers=headers, json=search_payload, timeout=10)
        response.raise_for_status()
        search_results = response.json()

        contact_id = None
        if search_results.get("total", 0) > 0:
            contact_id = search_results["results"][0]["id"]
            logger.info(f"Contacto encontrado en HubSpot con ID: {contact_id}")

        # --- 2. Preparar los datos a actualizar/crear ---
        properties_to_update = {
            'phone': clean_phone_number,
        }
        
        # El `last_message` ya no es relevante en el flujo asíncrono,
        # pero lo mantenemos por si se usa en el futuro.
        if last_message:
            properties_to_update['whatsapp_last_message'] = last_message
        
        if name and name.strip():
            properties_to_update['firstname'] = name

        # --- ¡TRADUCTOR DE PROPIEDADES MEJORADO! ---
        # Mapea las claves del JSON de la IA a los nombres internos de HubSpot.
        if lead_data:
            # ¡VERIFICAR! Asegúrate de que estos nombres internos coincidan con tu HubSpot.
            # El nombre interno para el email suele ser simplemente 'email'.
            prop_map = {
                "email": "email", # ¡NUEVO! Añadido para manejar el email.
                "customer_sector": "customer_sector_ia",
                "purchase_potential": "purchase_potential_ia",
                "lead_status": "lead_status_ia",
                "next_recommended_action": "next_recommended_action_ia" # Añadido para ser completo
            }
            for key, value in lead_data.items():
                # Solo actualizamos el campo si la IA encontró un valor y no es "Desconocido"
                if key in prop_map and value and value.lower() != "desconocido":
                    hubspot_key = prop_map[key]
                    properties_to_update[hubspot_key] = value

        # --- 3. Crear o Actualizar el contacto (Lógica sin cambios) ---
        payload = {"properties": properties_to_update}

        if contact_id:
            # Actualizar contacto existente
            update_url = f"{BASE_URL}/{contact_id}"
            update_response = requests.patch(update_url, headers=headers, json=payload, timeout=10)
            update_response.raise_for_status()
            logger.info(f"Contacto {contact_id} actualizado en HubSpot con: {properties_to_update}")
        else:
            # Crear nuevo contacto
            create_response = requests.post(BASE_URL, headers=headers, json=payload, timeout=10)
            create_response.raise_for_status()
            logger.info(f"Nuevo contacto para {clean_phone_number} creado en HubSpot con: {properties_to_update}")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Error en la API de HubSpot para {clean_phone_number}: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión o timeout con la API de HubSpot para {clean_phone_number}: {e}")
    except Exception as e:
        logger.error(f"Error inesperado en la integración con HubSpot: {e}", exc_info=True)
