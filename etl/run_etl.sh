#!/usr/bin/env bash
# Ejecución programada del ETL. Cron (cada hora, 6-22h):  0 6-22 * * *  /opt/oee/etl/run_etl.sh >> /var/log/oee_etl.log 2>&1
# En Windows use el Programador de tareas apuntando a: python etl_paros.py --archivo <ruta>
set -euo pipefail
cd "$(dirname "$0")"
: "${DATABASE_URL:?defina DATABASE_URL}"
ARCHIVO="${OEE_ARCHIVO:-/mnt/planta/SEGUIMIENTO_TEMPERAS_Y_VINILOS.xlsm}"
# Copia local para no leer un archivo que Mantenimiento tiene abierto/bloqueado en la red
cp "$ARCHIVO" /tmp/oee_origen.xlsm
python3 etl_paros.py --archivo /tmp/oee_origen.xlsm "$@"
# Correcciones retroactivas: python3 etl_paros.py --archivo ... --reemplazar-desde $(date -d '-30 days' +%F)
