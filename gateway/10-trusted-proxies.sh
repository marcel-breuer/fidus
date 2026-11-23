#!/bin/sh
set -eu

trusted_proxies=${TRUSTED_PROXIES:-}
case "$trusted_proxies" in
    *[!0-9a-fA-F:./,]*)
        echo "TRUSTED_PROXIES may contain only IP/CIDR characters and commas" >&2
        exit 1
        ;;
esac
if [ -n "$trusted_proxies" ]; then
    case ",$trusted_proxies," in
        *,,*)
            echo "TRUSTED_PROXIES must not contain empty entries" >&2
            exit 1
            ;;
    esac
fi

include_file=/tmp/trusted_proxies.conf
: > "$include_file"
remaining=$trusted_proxies
while [ -n "$remaining" ]; do
    proxy=${remaining%%,*}
    printf 'set_real_ip_from %s;\n' "$proxy" >> "$include_file"
    case "$remaining" in
        *,*) remaining=${remaining#*,} ;;
        *) remaining= ;;
    esac
done

if [ -n "$trusted_proxies" ]; then
    printf '%s\n' \
        'real_ip_header X-Forwarded-For;' \
        'real_ip_recursive on;' >> "$include_file"
fi
