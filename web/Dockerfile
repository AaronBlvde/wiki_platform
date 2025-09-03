FROM python:3.12-slim

WORKDIR /wiki_platform
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5001
CMD ["python", "web.py"]