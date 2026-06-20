FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py bvls_worldmeet_export.py ./

ENV DATA_DIR=/data/bvls_worldmeet_results
ENV PORT=8501

RUN mkdir -p /data/bvls_worldmeet_results

EXPOSE 8501

CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true"]
