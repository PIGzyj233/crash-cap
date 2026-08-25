# syntax=docker/dockerfile:1.7

# Node and pnpm are kept at the versions declared by the frontend package;
# manifest digests make the build inputs reproducible.
ARG NODE_IMAGE=node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d
ARG NGINX_IMAGE=nginx:1.29.1-alpine@sha256:42a516af16b852e33b7682d5ef8acbd5d13fe08fecadc7ed98605ba5e3b26ab8

FROM ${NODE_IMAGE} AS builder

WORKDIR /opt/crashcap/frontend
RUN corepack enable && corepack prepare pnpm@11.10.0 --activate

COPY platform/frontend/package.json platform/frontend/pnpm-lock.yaml platform/frontend/pnpm-workspace.yaml platform/frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY platform/frontend/ ./

# Vite embeds these values at build time; callers may override them with
# --build-arg, while the Phase 1 defaults match the Compose contract.
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_USE_MOCK=false
ARG VITE_RAW_DOWNLOAD_ENABLED=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_USE_MOCK=${VITE_USE_MOCK} \
    VITE_RAW_DOWNLOAD_ENABLED=${VITE_RAW_DOWNLOAD_ENABLED}
RUN pnpm build

FROM ${NGINX_IMAGE} AS runtime

RUN addgroup -S -g 10001 crashcap \
    && adduser -S -D -H -u 10001 -G crashcap crashcap \
    && mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp \
    && chown -R 10001:10001 /tmp/nginx

COPY --from=builder --chown=10001:10001 /opt/crashcap/frontend/dist /usr/share/nginx/html
COPY --chown=10001:10001 tools/crashcap/ /usr/share/nginx/html/downloads/crashcap/
COPY platform/frontend/nginx.conf /etc/nginx/nginx.conf

# The Compose contract maps the trusted-intranet port to container port 80.
# All filesystem paths used by nginx are writable by the unprivileged user;
# the deployment runtime must provide its normal unprivileged-port policy.
USER 10001:10001
EXPOSE 80
ENTRYPOINT ["/usr/sbin/nginx"]
CMD ["-g", "daemon off;"]
