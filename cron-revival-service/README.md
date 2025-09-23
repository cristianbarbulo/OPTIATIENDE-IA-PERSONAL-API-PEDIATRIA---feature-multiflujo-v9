# 🔄 Revival Cron Service - Multi-Cliente

Servicio independiente que ejecuta revival de conversaciones cada 6 horas para múltiples clientes.

## 🚀 Deploy en Render

### 1. Crear nuevo servicio Cron
- Repository: Este directorio
- Plan: Starter ($7/mes)
- Schedule: `0 */6 * * *` (cada 6 horas)

### 2. Variables de entorno requeridas

```bash
# === CONFIGURACIÓN PRINCIPAL ===
CRON_SECRET_KEY=tu_secret_key_seguro_123

# === CLIENTES ACTIVOS ===
ACTIVE_CLIENTS=[
  {
    "name": "Cliente1", 
    "url": "https://cliente1.onrender.com",
    "enabled": true
  },
  {
    "name": "Cliente2", 
    "url": "https://cliente2.onrender.com", 
    "enabled": true
  }
]

# === OPCIONALES ===
REQUEST_TIMEOUT=30
DRY_RUN=false
```

### 3. Configuración en cada cliente

Cada cliente debe tener las mismas variables:

```bash
REVIVAL_ENABLED=true
REVIVAL_SECRET_KEY=tu_secret_key_seguro_123  # ← MISMO que el cron
```

## 🔧 Testing

### Modo DRY_RUN
```bash
DRY_RUN=true  # Solo simula, no ejecuta realmente
```

### Test manual
```bash
python main.py
```

## 📊 Logs

El servicio genera logs detallados:
- ✅ Clientes procesados exitosamente
- ❌ Errores de conexión/timeout
- 📊 Resumen de cada ciclo

## 🛡️ Seguridad

- **Secret Key**: Validación en cada cliente
- **Timeout**: 30s máximo por cliente
- **Aislamiento**: No accede a datos directamente
- **Logs**: Sin información sensible

## 🔄 Funcionamiento

1. **Cron despierta** cada 6 horas
2. **Lee clientes activos** desde ACTIVE_CLIENTS
3. **Hace POST** a `/api/revival/process` de cada cliente
4. **Valida respuesta** y genera logs
5. **Continúa** con siguiente cliente

## 📞 Troubleshooting

### Error "No clientes activos"
- Verificar formato JSON de ACTIVE_CLIENTS
- Verificar que `enabled: true`

### Timeout en cliente
- Aumentar REQUEST_TIMEOUT
- Verificar que cliente esté activo

### HTTP 401/403
- Verificar CRON_SECRET_KEY coincida
- Verificar cliente tenga endpoint implementado
