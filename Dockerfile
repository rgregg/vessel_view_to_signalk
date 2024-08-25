FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends bluetooth bluez bluez-tools && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ADD requirements.txt /app
RUN ["pip", "install", "-r", "requirements.txt", "--no-cache-dir"]

COPY *.py /app/
ADD entrypoint.sh /app/
RUN ["mkdir", "-p", "/app/logs"]
CMD ["/app/entrypoint.sh"] 