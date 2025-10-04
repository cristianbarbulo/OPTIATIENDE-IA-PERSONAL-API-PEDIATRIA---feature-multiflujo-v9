# Script simple para configurar variables de entorno en Render
$serviceId = "srv-d3g9i3r3fgac738qeapg"
$apiKey = "rnd_4Cu7nF3mFCV9f72RTa9czQJOLsXJ"

Write-Host "Configurando variables de entorno para servicio: $serviceId"

# Variables a configurar
$envVars = @{
    "TENANT_NAME" = "ballester"
    "CLIENT_NAME" = "Centro Pediatrico Ballester"
    "WEBHOOK_VERIFY_TOKEN" = "ballester_webhook_2025_secure_token"
    "PORT" = "8080"
    "FLASK_ENV" = "production"
    "DEBUG" = "false"
    "LOG_LEVEL" = "INFO"
}

foreach ($key in $envVars.Keys) {
    Write-Host "Configurando $key..."
    
    try {
        $headers = @{
            "Accept" = "application/json"
            "Authorization" = "Bearer $apiKey"
            "Content-Type" = "application/json"
        }
        
        $body = "{`"envVarValue`": `"$($envVars[$key])`"}"
        $response = Invoke-RestMethod -Uri "https://api.render.com/v1/services/$serviceId/env-vars/$key" -Method PUT -Headers $headers -Body $body
        Write-Host "OK $key configurado correctamente"
    }
    catch {
        Write-Host "ERROR configurando $key : $($_.Exception.Message)"
    }
}

Write-Host "Configuracion completada"
Write-Host "Servicio URL: https://optiatiende-ballester.onrender.com"
