ARG PG_IMAGE=postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

FROM ${PG_IMAGE} AS build

RUN apk add --no-cache \
    build-base \
    bzip2-dev \
    libssh2-dev \
    libxml2-dev \
    lz4-dev \
    meson \
    openssl-dev \
    pkgconf \
    python3 \
    yaml-dev \
    zlib-dev \
    zstd-dev

ADD --checksum=sha256:2517ec0a7f66be0f1bc77795c3a19cd41c4b106699321d3ac511bc539dd2bfca \
    https://github.com/pgbackrest/pgbackrest/archive/refs/tags/release/2.58.0.tar.gz \
    /tmp/pgbackrest.tar.gz

RUN tar -xzf /tmp/pgbackrest.tar.gz -C /tmp \
    && meson setup /tmp/build /tmp/pgbackrest-release-2.58.0 --buildtype=release \
    && meson compile -C /tmp/build

FROM ${PG_IMAGE}

RUN apk add --no-cache libbz2 libssh2 yaml

COPY --from=build /tmp/build/src/pgbackrest /usr/local/bin/pgbackrest
COPY --from=build /tmp/pgbackrest-release-2.58.0/LICENSE \
    /usr/share/licenses/pgbackrest/LICENSE

RUN ldd /usr/local/bin/pgbackrest \
    && test "$(pgbackrest version)" = "pgBackRest 2.58.0"

LABEL org.opencontainers.image.title="Xinao PostgreSQL with pgBackRest" \
      org.opencontainers.image.version="postgres-16.14_pgbackrest-2.58.0" \
      org.opencontainers.image.source="https://github.com/pgbackrest/pgbackrest/tree/release/2.58.0"
