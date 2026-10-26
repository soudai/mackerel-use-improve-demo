#!/bin/sh
set -eu
mkdir -p storage/logs storage/framework/cache/data storage/framework/sessions storage/framework/views bootstrap/cache
chmod -R a+rwX storage bootstrap/cache
exec docker-php-entrypoint "$@"
