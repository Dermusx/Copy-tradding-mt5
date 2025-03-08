# Copy-tradding-mt5
AFCOPYTDMT5 

1. Requisitos:
bash:
pip install MetaTrader5 psutil
sudo apt-get install -y libicu-dev python3-dev

3. Ejecución Básica:
bash:
python multicopy_pro.py
4. Ejecución Avanzada (Docker):

bash:
# Construir imagen
docker build -t multicopy-pro .

# Ejecutar con montaje de config
docker run -d \
  --name multicopy \
  --cap-add NET_ADMIN \
  --ulimit nofile=1024:1024 \
  -v ./config.json:/app/config.json \
  multicopy-pro

  
Características Clave:

Arquitectura Multihilo: Cada par de cuentas se maneja en hilos independientes

Pool de Conexiones: Reutiliza conexiones MT5 para mejor performance

Balance de Recursos: Monitorización automática de CPU/Memoria

Sincronización Completa:

Copia de nuevas posiciones

Cierre automático

Actualización de SL/TP

Filtrado por símbolos

Reglas de Riesgo: Límites de drawdown y stop diario

Logs Unificados: Sistema centralizado de logging con rotación automática

5. Optimizaciones:

Reutilización de conexiones MT5

Procesamiento por lotes

Sincronización selectiva

Manejo eficiente de memoria

Tiempos de espera adaptativos

Este sistema está diseñado para manejar profesionalmente múltiples pares de cuentas simultáneamente con consumo mínimo de recursos y máxima estabilidad.

