FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-osd tesseract-ocr-eng fontconfig \
    texlive-xetex texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
    fonts-lmodern tex-gyre fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
ENV DATA_DIR=/data OMP_THREAD_LIMIT=1
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
