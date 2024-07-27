FROM python:3.12

RUN apt-get update && \
    apt-get install -y bluetooth bluez bluez-tools 

COPY *.py ./
ADD requirements.txt ./
ADD entrypoint.sh ./

RUN ["pip", "install", "-r", "requirements.txt"]

CMD ["./entrypoint.sh"] 