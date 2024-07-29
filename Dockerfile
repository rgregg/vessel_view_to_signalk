FROM python:3.12

RUN apt-get update && \
    apt-get install -y bluetooth bluez bluez-tools 

RUN ["mkdir", "-p", "/app/logs"]

WORKDIR /app

ADD requirements.txt /app
RUN ["pip", "install", "-r", "requirements.txt"]

COPY *.py /app/
ADD entrypoint.sh /app/

CMD ["/app/entrypoint.sh"] 