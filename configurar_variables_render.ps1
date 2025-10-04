# Script para configurar variables de entorno en Render
$serviceId = "srv-d3g9i3r3fgac738qeapg"
$apiKey = "rnd_4Cu7nF3mFCV9f72RTa9czQJOLsXJ"

# Variables a configurar
$envVars = @{
    "TENANT_NAME" = "ballester"
    "CLIENT_NAME" = "Centro Pediátrico Ballester"
    "GOOGLE_CREDENTIALS_JSON" = '{"type":"service_account","project_id":"clinicaballester-de015","private_key_id":"da4db66c5e39508aa912e0bc6e5cde87b1bfe452","private_key":"-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDsZqB1B3KYz/g/\n54tp8GrP/pNS5okpT28D7Jc+krg1h+zpMbTVZdpX861OD0/QD4t/Lmf7u4M1E8rI\nZMilrRhW/x5g4KwMRe5P1WvreBQ+0o5+8T3aDESmgIzltCoMzqZGzfID7Dzc8NAt\n2FEdNBW5NiP1FLCSRg5Usteid61a5yoEkdwSIBlctTc5RVzn0Xz3gKfgXT1RetEW\n+UZvBDx8Iq4T3EqrupiX4UyhVfas5ExBS4+rAEAY2/RkodLIDMJ51o5p9S5aBZZV\n35S59k/CW5FNCsbXefT8t762BGs41CtDIbf1ySsuZ0XyYrzMkjUkwajGcdZGtpZu\nPSL/zbvBAgMBAAECggEAEyIWRAqLhZ81dDShFbyx5G4yDdBfUxLdBRgJwLR+yMRc\n0h3mCSyCcMJl6S63krsjWvKOU3NAghP9Ql1X2QLquKXS11vvyNmDGX6ISslP+Cqy\nAkezrhl2l/RJExFTIvC5x/rEpvkgjvBFpSRAImk0BebCH8SiKuCVKdlEtx9RDk2G\nB4Tz0c1TVWP+QTBveK02m/1JKlK3rm2EqDxeiSCQhsYi596UepNhhDRZ+xnzRPTA\nCkfq5aM3WGvOQnbBHXi1AEBGrK35Xp7UNtRg3ogBrrCdWQn6P56M/sw0zQ5hPfc2\nE659xqKcGMS126oI0rgvs6ZFk5j+12pp+Mtd7EzKcQKBgQD5cB++cP6XLIVVvNTy\nSLOU89FOA7DffCji7Y/fzlggDx0ITGoz/Ra1R8fTtMJ8DrrhoTvSlYNazj1WQZRI\n/Pay9qbvX0/5Hq/575TEDtCts6/aQh7Js8bNZ2ZylmI97YHkq7KUYDGJZ3Q7RLVI\nIJZXTv8dULxfXdVgEpzxteOIqQKBgQDynrPbpDBIWLAudQJt011oJ8p3q9xaHCkn\n6JGgkVgKjVm8zONVW0KfARla1ZT+Ugy/lDoa56gRYqW6UlmiJ8KUJEZw9uYF5KHQ\nffX7o6LRQuOmdPPRVf/vkbAnZQoPpNoTANydMHyIdPi7DNuVeoBmq0cNcFkgvXRl\ndvyYDqARWQKBgAXQz2ypRcZQi2tMU8qyVz2J0b935o/PXUStNUWKkhNtRsgCwBcm\nN3lSix4sgLxTu5e3IqXuRnm/hT6VmNd6zmWtyoaaOkscpA23wEgx8DucjOUR1ZXu\nUxxG5OSXDQNUnkquliNPetgxSUx4daGQ4PB4LwqH71xp26e5x177VqrBAoGBAPAb\nM3AZC1dtvd4cGm1KElSznGHWiVn8KJbASO6ZKII45Sg9tHWSvVnSop8MZElUNh2a\nue5KeD/MWqsMOHyL0Lr/M180WOxYGfPV1IxWoxlpkxX3BByVeZZDngs+qThWMyM/\nZRWDGJuK92VWEjHabBwvQUABgZMvK3QGz3BEeRDxAoGAHyOmi5Ov59+/lUoZUWzF\nnvZ81Cr46hyAjgRkcDX/Qm+9YPCtNEAnyc5llqv9++txppRAx08SBTnrfLzJfQ5F\nJMKZ0X4eUzIPBQ3EwLdYZ+Be4CEkHqWKsCdojXqiC9zqq4ThO09NxihKUedhYi1y\njDjKvgd5FNoXsS9uCqedOuw=\n-----END PRIVATE KEY-----\n","client_email":"firebase-adminsdk-fbsvc@clinicaballester-de015.iam.gserviceaccount.com","client_id":"103558247335107473989","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40clinicaballester-de015.iam.gserviceaccount.com","universe_domain":"googleapis.com"}'
    "WEBHOOK_VERIFY_TOKEN" = "ballester_webhook_2025_secure_token"
    "PORT" = "8080"
    "FLASK_ENV" = "production"
    "DEBUG" = "false"
    "LOG_LEVEL" = "INFO"
}

Write-Host "🚀 Configurando variables de entorno para servicio: $serviceId"
Write-Host "=" * 60

foreach ($key in $envVars.Keys) {
    Write-Host "Configurando $key..."
    
    # Intentar diferentes formatos
    $formats = @(
        $envVars[$key],  # Valor directo
        "`"$($envVars[$key])`"",  # Valor entre comillas
        "{`"envVarValue`": `"$($envVars[$key])`"}"  # Formato JSON
    )
    
    $success = $false
    foreach ($format in $formats) {
        try {
            $headers = @{
                "Accept" = "application/json"
                "Authorization" = "Bearer $apiKey"
                "Content-Type" = "application/json"
            }
            
            $response = Invoke-RestMethod -Uri "https://api.render.com/v1/services/$serviceId/env-vars/$key" -Method PUT -Headers $headers -Body $format
            Write-Host "✅ $key configurado correctamente"
            $success = $true
            break
        }
        catch {
            # Continuar con el siguiente formato
        }
    }
    
    if (-not $success) {
        Write-Host "❌ Error configurando $key"
    }
}

Write-Host "=" * 60
Write-Host "✅ Configuración completada"
Write-Host "🌐 Servicio URL: https://optiatiende-ballester.onrender.com"
Write-Host "📋 Dashboard: https://dashboard.render.com/web/$serviceId"
