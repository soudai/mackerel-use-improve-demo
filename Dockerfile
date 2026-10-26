FROM php:8.4-fpm-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git unzip libpq-dev libsqlite3-dev libonig-dev libicu-dev libxml2-dev libzip-dev \
    && docker-php-ext-install -j"$(nproc)" pdo_pgsql pdo_sqlite mbstring intl xml zip bcmath pcntl \
    && pecl install opentelemetry-1.2.1 && docker-php-ext-enable opentelemetry \
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY docker/php/demo.ini /usr/local/etc/php/conf.d/zz-demo.ini
COPY docker/php/fpm.conf /usr/local/etc/php-fpm.d/zz-demo.conf
COPY docker/php/entrypoint.sh /usr/local/bin/demo-entrypoint
RUN chmod +x /usr/local/bin/demo-entrypoint
WORKDIR /var/www/html
ENTRYPOINT ["demo-entrypoint"]
CMD ["php-fpm"]
