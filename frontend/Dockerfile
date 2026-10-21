FROM node:24-alpine AS build

ENV PNPM_HOME=/pnpm
ENV PATH=${PNPM_HOME}:${PATH}

RUN corepack enable

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend ./
ARG VITE_PRODUCT_ANALYTICS_SOURCE
ENV VITE_PRODUCT_ANALYTICS_SOURCE=${VITE_PRODUCT_ANALYTICS_SOURCE}
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29.8-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

USER nginx
