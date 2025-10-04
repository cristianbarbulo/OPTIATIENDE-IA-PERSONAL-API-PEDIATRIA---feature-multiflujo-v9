# 🚀 VARIABLES DE RENDER PARA CENTRO PEDIÁTRICO BALLESTER

## ✅ CONFIGURACIÓN COMPLETA PARA DEPLOYMENT

### 📋 VARIABLES OBLIGATORIAS

#### 1. **Identificación del Cliente**
```
TENANT_NAME=ballester
CLIENT_NAME=Centro Pediátrico Ballester
```

#### 2. **OpenAI / GPT**
```
OPENAI_API_KEY=sk-proj-XXXXXXXXXXXXX
```
- **Dónde obtenerla**: https://platform.openai.com/api-keys
- **Importante**: Debe ser una API key válida con créditos

#### 3. **Firebase / Firestore**
```
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"clinicaballester-de015","private_key_id":"XXXXX"...}
```
- **Formato**: Todo el contenido del archivo `clinicaballester-de015-firebase-adminsdk-fbsvc-da4db66c5e.json` en UNA SOLA LÍNEA
- **Cómo prepararlo**: 
  1. Abrí el archivo JSON
  2. Copiá TODO el contenido
  3. Pegalo en una sola línea (sin saltos de línea)
  4. Ejemplo: `{"type":"service_account","project_id":"clinicaballester-de015",...}`

#### 4. **WhatsApp (360dialog)**
```
WHATSAPP_API_KEY=XXXXXXXXXXXXX
WHATSAPP_PHONE_NUMBER_ID=XXXXXXXXXXXXX
WHATSAPP_BUSINESS_ACCOUNT_ID=XXXXXXXXXXXXX
```
- **Dónde obtenerlas**: Panel de 360dialog
- **PHONE_NUMBER_ID**: El ID del número de WhatsApp que vas a usar
- **BUSINESS_ACCOUNT_ID**: ID de la cuenta de negocio

#### 5. **Webhook de 360dialog**
```
WEBHOOK_VERIFY_TOKEN=ballester_webhook_2025_secure_token
```
- **Importante**: Este token debe coincidir con el que configures en 360dialog
- **Sugerencia**: Usá un token único y seguro

#### 6. **API de la Clínica (OMNIA)**
```
CLINICA_API_BASE=https://api.clinicaballester.com/v1
CLINICA_API_KEY=XXXXXXXXXXXXX
```
- **Consultá con el proveedor de OMNIA** para obtener:
  - URL base de la API
  - API Key de autenticación

#### 7. **Contacto para Notificaciones**
```
NOTIFICATION_CONTACT=549XXXXXXXXXX
```
- **Formato**: Número de WhatsApp en formato internacional (549 + área + número)
- **Ejemplo**: `5491156975007` (para el 11-5697-5007)
- **Uso**: Recibe notificaciones de turnos confirmados y escalaciones

---

### 🔧 VARIABLES OPCIONALES (RECOMENDADAS)

#### 8. **Configuración del Puerto**
```
PORT=8080
```
- **Valor**: `8080` (estándar para Render)

#### 9. **Modo de Desarrollo**
```
FLASK_ENV=production
DEBUG=false
```

#### 10. **Logging**
```
LOG_LEVEL=INFO
```
- **Valores posibles**: `DEBUG`, `INFO`, `WARNING`, `ERROR`
- **Recomendado para producción**: `INFO`

---

## 📝 CÓMO CONFIGURAR EN RENDER

### Paso 1: Crear Web Service
1. Ir a https://dashboard.render.com
2. Click en "New +" → "Web Service"
3. Conectar tu repositorio de GitHub: `OPTICONNECTA-PEDIATRIA-BALLESTER`

### Paso 2: Configuración Básica
```
Name: optiatiende-ballester
Region: Oregon (US West)
Branch: main
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn main:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
```

### Paso 3: Plan
```
Instance Type: Starter ($7/month) o Free (para pruebas)
```

### Paso 4: Variables de Entorno
Click en "Advanced" → "Add Environment Variable"

Agregá TODAS las variables listadas arriba, una por una.

**⚠️ IMPORTANTE para GOOGLE_CREDENTIALS_JSON**:
1. Abrí `credentials/clinicaballester-de015-firebase-adminsdk-fbsvc-da4db66c5e.json`
2. Copiá TODO el contenido
3. Pegalo en un editor de texto
4. Eliminá TODOS los saltos de línea (debe quedar en una sola línea)
5. Copiá esa línea y pegala como valor de `GOOGLE_CREDENTIALS_JSON`

### Paso 5: Deploy
1. Click en "Create Web Service"
2. Render comenzará el build y deploy automáticamente
3. Esperá a que diga "Live" (tarda 2-5 minutos)

---

## 🔗 CONFIGURAR WEBHOOK EN 360DIALOG

Una vez que tu servicio esté "Live" en Render:

1. Copiá tu URL de Render: `https://optiatiende-ballester.onrender.com`

2. Ir al panel de 360dialog: https://hub.360dialog.com

3. Configurar webhook:
   - **Webhook URL**: `https://optiatiende-ballester.onrender.com/webhook`
   - **Verify Token**: `ballester_webhook_2025_secure_token` (el mismo que pusiste en Render)
   - **Webhook Fields**: Seleccioná `messages`

4. Click en "Verify and Save"

---

## 🧪 TESTING RÁPIDO

### Test 1: Verificar que el servicio está vivo
```bash
curl https://optiatiende-ballester.onrender.com/health
```
Debe responder: `{"status": "ok"}`

### Test 2: Enviar mensaje de WhatsApp
Enviá desde tu celular al número de WhatsApp conectado:
```
Hola
```
El bot debe responder con el mensaje de bienvenida.

### Test 3: Probar flujo de agendamiento
```
QUIERO AGENDAR neurología
```
El bot debe:
1. Preguntarte por tu obra social
2. Preguntarte si sos paciente nuevo o existente
3. Pedirte DNI
4. Mostrar disponibilidad de turnos

### Test 4: Verificar coberturas
```
Tengo IOMA
```
El bot debe aplicar las reglas específicas de IOMA (solo consultas, no neurología).

---

## 📊 MONITOREO

### Logs en Render
1. Ir a tu servicio en Render
2. Click en "Logs"
3. Ver en tiempo real todos los mensajes procesados

### Firebase Console
https://console.firebase.google.com/u/5/project/clinicaballester-de015/firestore

Ver:
- `ballester_obras_sociales`: 99 documentos
- `ballester_configuracion/precios_particulares`: 67 servicios
- `conversations`: Se crean al chatear

---

## 🆘 TROUBLESHOOTING

### Error: "Firebase authentication failed"
- Verificá que `GOOGLE_CREDENTIALS_JSON` esté en UNA SOLA LÍNEA
- Verificá que el JSON sea válido

### Error: "OpenAI API key invalid"
- Verificá que la key sea válida en https://platform.openai.com/api-keys
- Verificá que tengas créditos disponibles

### Error: "Webhook verification failed"
- Verificá que `WEBHOOK_VERIFY_TOKEN` en Render coincida EXACTAMENTE con el de 360dialog
- Verificá que la URL sea correcta: `https://TU-SERVICIO.onrender.com/webhook`

### Bot no responde
1. Verificá logs en Render
2. Verificá que el webhook esté configurado en 360dialog
3. Verificá que el número de WhatsApp esté activo
4. Enviá mensaje de nuevo (a veces tarda 1-2 min la primera vez)

---

## ✅ CHECKLIST FINAL

Antes de ir a producción, verificá:

- [ ] Todas las variables están configuradas en Render
- [ ] GOOGLE_CREDENTIALS_JSON está en una sola línea
- [ ] Servicio está "Live" en Render
- [ ] Webhook configurado en 360dialog
- [ ] Test de "Hola" funciona
- [ ] Test de "QUIERO AGENDAR" funciona
- [ ] Firebase tiene las 99 obras sociales
- [ ] NOTIFICATION_CONTACT recibe notificaciones
- [ ] Logs en Render se ven claros

---

## 🎉 ¡LISTO PARA PRODUCCIÓN!

Una vez completado todo lo anterior, el sistema está 100% funcional y listo para que tu cliente lo use en producción con pacientes reales.

**Contacto para soporte**: Guardá este documento y los logs de Render para debugging.

