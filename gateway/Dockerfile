FROM python:3.12-slim

# No third-party packages: the gateway uses the standard library only.
WORKDIR /app
COPY gateway.py /app/gateway.py

RUN useradd --create-home --uid 10001 gateway \
    && chmod 0555 /app/gateway.py

USER 10001
EXPOSE 4318

ENV GATEWAY_LISTEN_PORT=4318 \
    GATEWAY_TENANTS=ubix,digiflow \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('GATEWAY_LISTEN_PORT','4318'), timeout=2)"]

CMD ["python3", "/app/gateway.py"]
