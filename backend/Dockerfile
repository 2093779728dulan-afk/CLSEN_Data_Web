FROM python:3.14.7-slim-trixie

ARG MYSQL_GPG_KEY_SHA256=a4bcd9f16a53cc763f87b9955dbcdced33c7aa90296b157eb6ceef0f156f4327

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl gnupg \
    && curl --fail --location --silent --show-error \
        https://repo.mysql.com/RPM-GPG-KEY-mysql-2025 \
        --output /tmp/mysql.gpg.asc \
    && echo "${MYSQL_GPG_KEY_SHA256}  /tmp/mysql.gpg.asc" | sha256sum --check --strict \
    && gpg --dearmor --batch --yes \
        --output /usr/share/keyrings/mysql-archive-keyring.gpg \
        /tmp/mysql.gpg.asc \
    && echo "deb [signed-by=/usr/share/keyrings/mysql-archive-keyring.gpg] https://repo.mysql.com/apt/debian/ trixie mysql-8.4-lts" \
        > /etc/apt/sources.list.d/mysql.list \
    && rm -f /tmp/mysql.gpg.asc \
    && apt-get update \
    && apt-get install --yes --no-install-recommends mysql-community-client \
    && apt-get purge --yes --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app/backend

COPY backend/requirements.lock /tmp/requirements.lock
RUN python -m pip install --require-hashes --requirement /tmp/requirements.lock \
    && rm -f /tmp/requirements.lock

COPY backend /app/backend
COPY scripts /app/scripts
COPY ops /app/ops
COPY frontend /app/frontend
COPY tools /app/tools
COPY docs /app/docs
COPY .github /app/.github
COPY .gitignore /app/.gitignore

RUN python -m pip install --no-deps . \
    && chown -R app:app /app

USER app

ENTRYPOINT ["python", "-m", "app.deployment.entrypoint"]
CMD ["api"]
