FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends bluetooth bluez bluez-tools curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ADD requirements.txt /app
RUN ["pip", "install", "-r", "requirements.txt", "--no-cache-dir"]

COPY vvm_to_signalk/ /app/vvm_to_signalk
ADD entrypoint.sh /app/
RUN ["mkdir", "-p", "/app/logs"]

ENV APP_HEALTHCHECK=True
ENV APP_HEALTHCHECK_PORT=5000
ENV APP_HEALTHCHECK_IP=127.0.0.1

# Set up healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:5000/health || exit 1

CMD ["/app/entrypoint.sh"] 