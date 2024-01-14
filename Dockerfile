FROM python:3.8

WORKDIR /app

COPY *.py *.sh requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

# Specify the command to run on container start
CMD ["python", "export-ics.py"]