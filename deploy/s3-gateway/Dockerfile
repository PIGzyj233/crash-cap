ARG NGINX_IMAGE=nginx:1.29.1-alpine@sha256:42a516af16b852e33b7682d5ef8acbd5d13fe08fecadc7ed98605ba5e3b26ab8

FROM ${NGINX_IMAGE}

RUN addgroup -S -g 10001 crashcap \
    && adduser -S -D -H -u 10001 -G crashcap crashcap

COPY --chmod=0444 nginx.conf /etc/nginx/nginx.conf

USER 10001:10001
EXPOSE 9000
ENTRYPOINT ["/usr/sbin/nginx"]
CMD ["-g", "daemon off;"]
