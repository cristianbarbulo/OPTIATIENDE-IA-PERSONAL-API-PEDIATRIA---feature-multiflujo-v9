import logging
import os
from datetime import datetime, timedelta
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
# from interfaces.calendar_interface import CalendarInterface # Asumiendo que esta interfaz existe

class GoogleCalendarService(): # class GoogleCalendarService(CalendarInterface):
    CALENDAR_ID = config.GOOGLE_CALENDAR_ID
    TIMEZONE = pytz.timezone('America/Argentina/Buenos_Aires')
    APPOINTMENT_DURATION_MINUTES = 60

    def __init__(self):
        self.logger = logging.getLogger(config.TENANT_NAME)
        self.service = self._get_calendar_service()

    def _get_calendar_service(self):
        try:
            creds = service_account.Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar'])
            service = build('calendar', 'v3', credentials=creds)
            self.logger.info("Google Calendar conectado.")
            return service
        except Exception as e:
            self.logger.error(f"Error al inicializar Google Calendar Service: {e}", exc_info=True)
            return None

    def get_events(self, start_time_iso: str, end_time_iso: str, user_id: str) -> list:
        """
        CORREGIDO: Busca eventos futuros para un usuario específico.
        Esta función faltaba y causaba un error fatal.
        """
        if not self.service: return []
        try:
            self.logger.info(f"[GCAL] Buscando eventos para '{user_id}' entre {start_time_iso} y {end_time_iso}")
            events_result = self.service.events().list(
                calendarId=self.CALENDAR_ID,
                timeMin=start_time_iso,
                timeMax=end_time_iso,
                q=user_id, # Busca el ID del usuario en la descripción o título del evento
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            return events_result.get('items', [])
        except HttpError as e:
            self.logger.error(f"[GCAL] Error en get_events: {e}", exc_info=True)
            return []

    def get_available_slots(self, date_range: tuple, time_preference: str | None = None) -> list:
        """
        CORREGIDO: La firma y la lógica de esta función estaban desactualizadas.
        """
        if not self.service: return []
        start, end = date_range
        start = start.astimezone(self.TIMEZONE)
        end = end.astimezone(self.TIMEZONE)
        
        self.logger.info(f"[GCAL] Buscando slots entre {start.isoformat()} y {end.isoformat()}")

        try:
            events_result = self.service.events().list(
                calendarId=self.CALENDAR_ID, timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy='startTime'
            ).execute()
            busy_times = events_result.get('items', [])
        except HttpError as e:
            self.logger.error(f"Error al obtener eventos de Google Calendar: {e}")
            return []

        available_slots = []
        current_time = start
        
        if current_time.minute not in [0, 30]:
            current_time = current_time.replace(second=0, microsecond=0) + timedelta(minutes=(30 - current_time.minute % 30))

        while current_time + timedelta(minutes=self.APPOINTMENT_DURATION_MINUTES) <= end:
            is_free = True
            slot_end_time = current_time + timedelta(minutes=self.APPOINTMENT_DURATION_MINUTES)
            
            if not (9 <= current_time.hour < 18): is_free = False

            if is_free:
                for event in busy_times:
                    try:
                        start_dt = event['start'].get('dateTime')
                        end_dt = event['end'].get('dateTime')
                        
                        if start_dt and end_dt:
                            event_start = datetime.fromisoformat(start_dt).astimezone(self.TIMEZONE)
                            event_end = datetime.fromisoformat(end_dt).astimezone(self.TIMEZONE)
                            if max(current_time, event_start) < min(slot_end_time, event_end):
                                is_free = False
                                break
                        else:
                            self.logger.warning(f"[GCAL] Evento sin fechas válidas: {event}")
                    except (ValueError, TypeError) as e:
                        self.logger.warning(f"[GCAL] Error parseando fechas del evento: {e}")
                        continue
            
            if is_free: available_slots.append(current_time.isoformat())
            current_time += timedelta(minutes=30)

        self.logger.info(f"[GCAL] Encontrados {len(available_slots)} slots disponibles.")
        return available_slots

    def create_event(self, client_name: str, slot: dict) -> str:
        """
        Crea un evento en Google Calendar.
        """
        if not self.service:
            return None
            
        try:
            event = {
                'summary': f'Cita con {client_name}',
                'description': f'Cliente: {client_name}',
                'start': {
                    'dateTime': slot['start_time'],
                    'timeZone': str(self.TIMEZONE),
                },
                'end': {
                    'dateTime': slot['end_time'],
                    'timeZone': str(self.TIMEZONE),
                },
            }
            
            event = self.service.events().insert(calendarId=self.CALENDAR_ID, body=event).execute()
            self.logger.info(f"Evento creado: {event.get('id')}")
            return event.get('id')
            
        except Exception as e:
            self.logger.error(f"Error creando evento: {e}")
            return None

    def reschedule_event(self, event_id: str, new_slot: dict) -> bool:
        """
        Reprograma un evento existente.
        """
        if not self.service:
            return False
            
        try:
            event = self.service.events().get(calendarId=self.CALENDAR_ID, eventId=event_id).execute()
            
            event['start']['dateTime'] = new_slot['start_time']
            event['end']['dateTime'] = new_slot['end_time']
            
            updated_event = self.service.events().update(
                calendarId=self.CALENDAR_ID, eventId=event_id, body=event
            ).execute()
            
            self.logger.info(f"Evento reprogramado: {event_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error reprogramando evento: {e}")
            return False

    def cancel_event(self, event_id: str) -> bool:
        """
        Cancela un evento.
        """
        if not self.service:
            return False
            
        try:
            self.service.events().delete(calendarId=self.CALENDAR_ID, eventId=event_id).execute()
            self.logger.info(f"Evento cancelado: {event_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error cancelando evento: {e}")
            return False

    def get_event(self, event_id: str) -> dict | None:
        """
        Obtiene un evento específico.
        """
        if not self.service:
            return None
            
        try:
            event = self.service.events().get(calendarId=self.CALENDAR_ID, eventId=event_id).execute()
            return event
        except Exception as e:
            self.logger.error(f"Error obteniendo evento: {e}")
            return None
