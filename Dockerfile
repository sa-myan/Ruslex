# Independent, reproducible frontend build. No Node process in production.
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
# If a lockfile exists, use reproducible installs; otherwise use the
# initial bootstrap install. Generate and commit the lockfile on the VPS.
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi
COPY frontend/ ./
RUN npm run check && npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend:/app
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY tests/ /app/tests/
COPY --from=frontend /build/backend/frontend_static/ /app/backend/frontend_static/
RUN mkdir -p /app/backend/collected_static \
    && chmod -R a+rX /app \
    && chmod 755 /app /app/backend \
    && DJANGO_SECRET_KEY=build-only-do-not-use-in-production python /app/backend/manage.py collectstatic --noinput --clear \
    && su -s /bin/sh app -c 'cd /app/backend && DJANGO_SECRET_KEY=build-only-do-not-use-in-production DJANGO_SETTINGS_MODULE=siteconf.settings python -c "import siteconf.settings; import django; django.setup(); import dictionary.models; print(\"Settings and model imports passed as nonroot user\")"'
WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
