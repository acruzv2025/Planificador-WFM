#!/bin/bash

# El script se detendrá si un comando falla
set -o errexit

echo "--- Comprobando la existencia de DATABASE_URL ---"

# Comprueba si la variable DATABASE_URL está definida y no está vacía
if [ -z "${DATABASE_URL}" ]; then
  # Si no existe, muestra un mensaje y continúa sin ejecutar los comandos de la BD
  echo "DATABASE_URL no encontrada. Saltando la inicialización de la base de datos."
  echo "La aplicación se conectará a la base de datos al iniciarse."
else
  # Si SÍ existe, ejecuta los comandos de inicialización como antes
  echo "DATABASE_URL encontrada. Ejecutando la inicialización de la base de datos..."
  flask db-custom create-all
  flask db-custom seed
  echo "--- Inicialización de la base de datos completada. ---"
fi

# Finalmente, sin importar lo que pasó antes, inicia el servidor Gunicorn
echo "--- Iniciando el servidor Gunicorn... ---"
gunicorn app:app
