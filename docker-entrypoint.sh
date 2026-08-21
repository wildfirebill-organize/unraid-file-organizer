#!/bin/sh
set -e

# If started as root (the default on Unraid/CA), take ownership of the config
# volume so the unprivileged app user can persist settings, journals and logs,
# then drop privileges.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /config
  chown -R organizer:organizer /config
  if ! gosu organizer sh -c 'touch /config/.write_test && rm -f /config/.write_test' 2>/dev/null; then
    echo "WARNING: /config is still not writable after chown (host filesystem may not permit it)." >&2
    echo "         Settings will fail to save. Check host-side ownership of the /config mount." >&2
  fi
  exec gosu organizer "$@"
fi

exec "$@"
