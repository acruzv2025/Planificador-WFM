#!/bin/bash

# Con esta línea, el script se detendrá si un comando falla
set -o errexit

echo "--- Ejecutando comandos de inicialización de la base de datos ---"

# Ejecuta los comandos para crear las tablas y añadir los datos iniciales
# Tu código es inteligente y no volverá a crear el admin si ya existe, ¡perfecto!
flask db-custom create-all
flask db-custom seed

echo "--- Base de datos lista. Iniciando Gunicorn... ---"

# Finalmente, inicia el servidor Gunicorn
gunicorn app:app