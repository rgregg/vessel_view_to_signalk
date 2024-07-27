FROM python:3.12

RUN apt-get update && \
    apt-get install -y bluetooth bluez bluez-tools 

ADD requirements.txt ./
RUN ["pip", "install", "-r", "requirements.txt"]

COPY *.py ./
ADD entrypoint.sh ./

CMD ["./entrypoint.sh"] 