#!/bin/bash

NAME="tenants_back"                                                # Name of the application
DJANGODIR=/home/webmaster/tenants_back                             # Django project directory
SOCKFILE=/home/webmaster/tenants_back/run/gunicorn.sock            # we will communicate using this unix socket
USER=webmaster                                                     # the user to run as
GROUP=www-data                                                     # the group to run as (nginx user's group → can read the socket)
NUM_WORKERS=5                                                      # how many worker processes should Gunicorn spawn
DJANGO_SETTINGS_MODULE=tenants_back.settings                       # which settings file should Django use
DJANGO_WSGI_MODULE=tenants_back.wsgi                               # WSGI module name

echo "Starting $NAME as `whoami`"

# Activate the virtual environment
cd $DJANGODIR

echo ".env is activated"

source .env/bin/activate
export DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
export PYTHONPATH=$DJANGODIR:$PYTHONPATH

# --- Production env vars (edit before deploy) -----------------------------
export DJANGO_SECRET_KEY="replace-me-with-a-long-random-string"
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS=".example.com,example.com"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://example.com,https://*.example.com"
export DJANGO_BEHIND_TLS_PROXY=1

# Same-origin behind nginx → CORS off.
export DJANGO_CORS_ALLOW_ALL=0

export DB_NAME=tenants_back
export DB_USER=tenants_back
export DB_PASSWORD=replace-me
export DB_HOST=127.0.0.1
export DB_PORT=5432
# --------------------------------------------------------------------------

echo "export done"

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

echo "test done"


# Start your Django Unicorn
# Programs meant to be run under supervisor should not daemonize themselves (do not use --daemon)
exec .env/bin/gunicorn ${DJANGO_WSGI_MODULE}:application \
  --name $NAME \
  --workers $NUM_WORKERS \
  --user=$USER \
  --group=$GROUP \
  --umask=007 \
  --bind=unix:$SOCKFILE \
  --log-level=debug \
  --log-file=-
