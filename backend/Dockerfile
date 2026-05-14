FROM python:3.12-slim

# IfcConvert + ifcopenshell deps. The ifcopenshell wheel ships its own bundled
# IfcConvert binary on most platforms; we also install OS libs it needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglu1-mesa \
        libxrender1 \
        ca-certificates \
        wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app

# Locate IfcConvert shipped with ifcopenshell wheel and put it on PATH.
RUN IFC_CONVERT=$(python -c "import ifcopenshell, os, glob; \
    base=os.path.dirname(ifcopenshell.__file__); \
    hits=glob.glob(base+'/**/IfcConvert*', recursive=True); \
    print(hits[0] if hits else '')") && \
    if [ -n "$IFC_CONVERT" ]; then ln -s "$IFC_CONVERT" /usr/local/bin/IfcConvert; \
    else echo "WARN: IfcConvert not bundled; install manually."; fi

ENV BIM_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
