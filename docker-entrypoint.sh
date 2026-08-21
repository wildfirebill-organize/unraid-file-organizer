#!/bin/sh
set -e

# If started as root (the default on Unraid/CA), take ownership of the config
# volume so the unprivileged app user can persist settings, journals and logs,
# then drop privileges.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /config
  chown -R organizer:organizer /config
  exec gosu organizer "$@"
fi

exec "$@"
