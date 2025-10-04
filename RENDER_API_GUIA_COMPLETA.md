# 🚀 CREAR SERVICIO COMPLETO EN RENDER DESDE CERO

## 📋 Requisitos Previos
- API Key de Render
- Repositorio GitHub público
- PowerShell (Windows) o Terminal (Mac/Linux)

## 🔑 Paso 1: Obtener API Key
1. Ir a: https://dashboard.render.com
2. Account Settings → API Keys
3. Crear nueva API Key
4. Copiar la key (ej: `rnd_4Cu7nF3mFCV9f72RTa9czQJOLsXJ`)

## 🏗️ Paso 2: Crear Servicio con Variables Incluidas

### PowerShell (Windows):
```powershell
# Configuración
$apiKey = "TU_API_KEY_AQUI"
$ownerId = "tea-d14pi02li9vc73eqlqig"  # Tu Owner ID
$repoUrl = "https://github.com/usuario/repositorio"

# Headers
$headers = @{
    "Accept" = "application/json"
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
}

# Body del servicio con TODAS las variables incluidas
$body = @{
    type = "web_service"
    name = "mi-servicio-web"
    ownerId = $ownerId
    repo = $repoUrl
    branch = "main"
    autoDeploy = "yes"
    
    # ✅ VARIABLES DE ENTORNO INCLUIDAS DESDE EL INICIO
    envVars = @(
        @{ key = "TENANT_NAME"; value = "ballester" },
        @{ key = "CLIENT_NAME"; value = "Centro Pediátrico Ballester" },
        @{ key = "GOOGLE_CREDENTIALS_JSON"; value = '{"type":"service_account",...}' },
        @{ key = "WEBHOOK_VERIFY_TOKEN"; value = "mi_token_seguro" },
        @{ key = "PORT"; value = "8080" },
        @{ key = "FLASK_ENV"; value = "production" },
        @{ key = "DEBUG"; value = "false" },
        @{ key = "LOG_LEVEL"; value = "INFO" },
        @{ key = "OPENAI_API_KEY"; value = "sk-..." },
        @{ key = "WHATSAPP_API_KEY"; value = "tu_key_360dialog" }
    )
    
    # Configuración del servicio
    serviceDetails = @{
        plan = "starter"
        region = "oregon"
        runtime = "python"
        envSpecificDetails = @{
            pythonVersion = "3.11"
            buildCommand = "pip install -r requirements.txt"
            startCommand = "gunicorn main:app --bind 0.0.0.0:`$PORT --timeout 120 --workers 2"
        }
    }
} | ConvertTo-Json -Depth 10

# Crear servicio
$response = Invoke-RestMethod -Uri "https://api.render.com/v1/services" -Method POST -Headers $headers -Body $body

# Mostrar resultado
Write-Host "✅ Servicio creado:"
Write-Host "ID: $($response.service.id)"
Write-Host "URL: $($response.service.serviceDetails.url)"
Write-Host "Dashboard: $($response.service.dashboardUrl)"
```

### Bash (Mac/Linux):
```bash
#!/bin/bash

# Configuración
API_KEY="TU_API_KEY_AQUI"
OWNER_ID="tea-d14pi02li9vc73eqlqig"
REPO_URL="https://github.com/usuario/repositorio"

# Crear servicio con variables incluidas
curl --request POST \
     --url https://api.render.com/v1/services \
     --header 'accept: application/json' \
     --header 'content-type: application/json' \
     --header "authorization: Bearer $API_KEY" \
     --data '{
       "type": "web_service",
       "name": "mi-servicio-web",
       "ownerId": "'$OWNER_ID'",
       "repo": "'$REPO_URL'",
       "branch": "main",
       "autoDeploy": "yes",
       "envVars": [
         {"key": "TENANT_NAME", "value": "ballester"},
         {"key": "CLIENT_NAME", "value": "Centro Pediátrico Ballester"},
         {"key": "PORT", "value": "8080"},
         {"key": "FLASK_ENV", "value": "production"},
         {"key": "DEBUG", "value": "false"},
         {"key": "LOG_LEVEL", "value": "INFO"}
       ],
       "serviceDetails": {
         "plan": "starter",
         "region": "oregon",
         "runtime": "python",
         "envSpecificDetails": {
           "pythonVersion": "3.11",
           "buildCommand": "pip install -r requirements.txt",
           "startCommand": "gunicorn main:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2"
         }
       }
     }'
```

## 🔍 Paso 3: Verificar Variables Configuradas

```powershell
# Verificar variables del servicio creado
$serviceId = "srv-XXXXXXXXXXXXXX"  # ID del servicio creado
$response = Invoke-RestMethod -Uri "https://api.render.com/v1/services/$serviceId/env-vars" -Headers $headers

Write-Host "✅ Variables configuradas:"
$response | ForEach-Object { 
    Write-Host "  - $($_.envVar.key) = $($_.envVar.value)" 
}
```

## 📝 Paso 4: Agregar Variables Adicionales (Opcional)

Si necesitás agregar más variables después:

```powershell
# Agregar variable individual
$serviceId = "srv-XXXXXXXXXXXXXX"
$key = "NUEVA_VARIABLE"
$value = "valor_de_la_variable"

$body = "{`"envVarValue`": `"$value`"}"
$response = Invoke-RestMethod -Uri "https://api.render.com/v1/services/$serviceId/env-vars/$key" -Method PUT -Headers $headers -Body $body

Write-Host "✅ Variable $key agregada"
```

## 🎯 Estructura Completa del Body

```json
{
  "type": "web_service",
  "name": "nombre-del-servicio",
  "ownerId": "tea-XXXXXXXXXXXXXX",
  "repo": "https://github.com/usuario/repositorio",
  "branch": "main",
  "autoDeploy": "yes",
  "envVars": [
    {"key": "VARIABLE_1", "value": "valor1"},
    {"key": "VARIABLE_2", "value": "valor2"},
    {"key": "VARIABLE_3", "value": "valor3"}
  ],
  "serviceDetails": {
    "plan": "starter",
    "region": "oregon", 
    "runtime": "python",
    "envSpecificDetails": {
      "pythonVersion": "3.11",
      "buildCommand": "pip install -r requirements.txt",
      "startCommand": "gunicorn main:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2"
    }
  }
}
```

## ⚠️ Puntos Importantes

1. **Owner ID**: Se obtiene con `GET /v1/owners`
2. **Variables**: Se incluyen en `envVars` array al crear el servicio
3. **Comandos**: `buildCommand` y `startCommand` van en `envSpecificDetails`
4. **Runtime**: Debe especificarse como `python`
5. **Plan**: `starter` para servicios pagos (no se pueden crear free con API)

## 🚀 Resultado Final

Una vez ejecutado el script:
- ✅ Servicio creado automáticamente
- ✅ Todas las variables configuradas
- ✅ Deploy automático iniciado
- ✅ URL del servicio disponible
- ✅ Dashboard accesible

## 📞 Comandos Útiles

```powershell
# Listar servicios
Invoke-RestMethod -Uri "https://api.render.com/v1/services" -Headers $headers

# Obtener detalles de un servicio
Invoke-RestMethod -Uri "https://api.render.com/v1/services/SERVICE_ID" -Headers $headers

# Listar variables de entorno
Invoke-RestMethod -Uri "https://api.render.com/v1/services/SERVICE_ID/env-vars" -Headers $headers
```

---

**¡Con esto podés crear cualquier servicio en Render completamente configurado desde cero usando solo la API!** 🎉
