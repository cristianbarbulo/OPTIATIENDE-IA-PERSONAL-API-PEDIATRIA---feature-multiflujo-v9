import logging
from datetime import datetime, timedelta
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config


class GoogleAppointmentsService:
    """
    Provider de "Citas" sobre Google Calendar.
    - Lee ventanas de atención desde un calendario (GOOGLE_APPOINTMENTS_CALENDAR_ID)
    - Genera slots de tamaño fijo (APPOINTMENTS_SLOT_MINUTES)
    - Filtra con free/busy del calendario principal (GOOGLE_CALENDAR_ID)
    - Crea eventos en el calendario principal con placeholders de identidad
    """

    MAIN_CAL_ID = config.GOOGLE_CALENDAR_ID
    WINDOWS_CAL_ID = getattr(config, 'GOOGLE_APPOINTMENTS_CALENDAR_ID', None) or MAIN_CAL_ID
    TIMEZONE = pytz.timezone(config.TIMEZONE_CONFIG.get('zona_horaria', 'America/Argentina/Buenos_Aires'))
    SLOT_MIN = int(getattr(config, 'APPOINTMENTS_SLOT_MINUTES', 30))

    def __init__(self):
        self.logger = logging.getLogger(config.TENANT_NAME)
        self.service = self._get_calendar_service()

    def _get_calendar_service(self):
        try:
            creds = service_account.Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            self.logger.critical(f"[APPTS] Error inicializando Google API: {e}", exc_info=True)
            return None

    # --- Utilidades internas ---
    def _list_events(self, calendar_id: str, time_min_iso: str, time_max_iso: str) -> list:
        if not self.service:
            return []
        try:
            items = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])
            return items
        except HttpError as e:
            self.logger.error(f"[APPTS] Error listando eventos en {calendar_id}: {e}")
            return []

    def _freebusy(self, time_min_iso: str, time_max_iso: str) -> list:
        if not self.service:
            return []
        try:
            body = {
                "timeMin": time_min_iso,
                "timeMax": time_max_iso,
                "items": [{"id": self.MAIN_CAL_ID}],
            }
            resp = self.service.freebusy().query(body=body).execute()
            return resp.get('calendars', {}).get(self.MAIN_CAL_ID, {}).get('busy', [])
        except HttpError as e:
            self.logger.error(f"[APPTS] Error en freebusy: {e}")
            return []

    # --- API esperada por el handler ---
    def get_available_slots(self, date_range: tuple, time_preference: str | None = None) -> list:
        if not self.service:
            return []
        start_dt, end_dt = date_range
        start_dt = start_dt.astimezone(self.TIMEZONE)
        end_dt = end_dt.astimezone(self.TIMEZONE)
        self.logger.info(f"[APPTS] Generando slots {start_dt} -> {end_dt} (slot={self.SLOT_MIN}m)")

        # 1) Ventanas de atención (calendario de ventanas)
        ventanas = self._list_events(self.WINDOWS_CAL_ID, start_dt.isoformat(), end_dt.isoformat())
        if not ventanas:
            self.logger.warning("[APPTS] Sin ventanas de atención configuradas en el rango solicitado")
            return []

        # 2) Busy principal para evitar choques
        busy_blocks = self._freebusy(start_dt.isoformat(), end_dt.isoformat())

        def _overlaps(slot_start: datetime, slot_end: datetime) -> bool:
            for b in busy_blocks:
                try:
                    b_start = datetime.fromisoformat(b['start']).astimezone(self.TIMEZONE)
                    b_end = datetime.fromisoformat(b['end']).astimezone(self.TIMEZONE)
                    if max(slot_start, b_start) < min(slot_end, b_end):
                        return True
                except Exception:
                    continue
            return False

        slots_iso: list[str] = []
        for vent in ventanas:
            try:
                v_start_raw = vent.get('start', {}).get('dateTime')
                v_end_raw = vent.get('end', {}).get('dateTime')
                if not v_start_raw or not v_end_raw:
                    continue
                v_start = datetime.fromisoformat(v_start_raw).astimezone(self.TIMEZONE)
                v_end = datetime.fromisoformat(v_end_raw).astimezone(self.TIMEZONE)
                # Cortar la ventana en slots regulares
                current = v_start
                while current + timedelta(minutes=self.SLOT_MIN) <= v_end:
                    slot_end = current + timedelta(minutes=self.SLOT_MIN)
                    if not _overlaps(current, slot_end):
                        slots_iso.append(current.isoformat())
                    current += timedelta(minutes=self.SLOT_MIN)
            except Exception as e:
                self.logger.warning(f"[APPTS] Error procesando ventana: {e}")
                continue

        self.logger.info(f"[APPTS] Slots disponibles generados: {len(slots_iso)}")
        return slots_iso

    def create_event(self, client_name: str, slot: dict) -> str | None:
        if not self.service:
            return None
        try:
            start_time = slot['start_time']
            end_time = slot['end_time']
            phone_fallback = client_name if client_name else "Cliente WhatsApp"
            event = {
                'summary': f'Cita con {phone_fallback}',
                'description': f'Cliente: {phone_fallback}',
                'start': {'dateTime': start_time, 'timeZone': str(self.TIMEZONE)},
                'end': {'dateTime': end_time, 'timeZone': str(self.TIMEZONE)},
            }
            created = self.service.events().insert(calendarId=self.MAIN_CAL_ID, body=event).execute()
            return created.get('id')
        except Exception as e:
            self.logger.error(f"[APPTS] Error creando evento: {e}")
            return None

    def reschedule_event(self, event_id: str, new_slot: dict) -> bool:
        if not self.service:
            return False
        try:
            ev = self.service.events().get(calendarId=self.MAIN_CAL_ID, eventId=event_id).execute()
            ev['start']['dateTime'] = new_slot['start_time']
            ev['end']['dateTime'] = new_slot['end_time']
            self.service.events().update(calendarId=self.MAIN_CAL_ID, eventId=event_id, body=ev).execute()
            return True
        except Exception as e:
            self.logger.error(f"[APPTS] Error reprogramando evento: {e}")
            return False

    def cancel_event(self, event_id: str) -> bool:
        if not self.service:
            return False
        try:
            self.service.events().delete(calendarId=self.MAIN_CAL_ID, eventId=event_id).execute()
            return True
        except Exception as e:
            self.logger.error(f"[APPTS] Error cancelando evento: {e}")
            return False

    def get_event(self, event_id: str) -> dict | None:
        if not self.service:
            return None
        try:
            return self.service.events().get(calendarId=self.MAIN_CAL_ID, eventId=event_id).execute()
        except Exception as e:
            self.logger.error(f"[APPTS] Error obteniendo evento: {e}")
            return None


