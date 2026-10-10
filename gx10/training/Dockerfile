# GPU training image for the ASUS Ascent GX10 (GB10, arm64, CUDA 13).
#
# The NGC PyTorch container is the supported way to get a CUDA build that
# knows the GB10 (compute capability 12.1). pip wheels from download.pytorch.org
# run, but warn about the capability and were measured about 2x slower on
# DGX Spark class machines. 25.09 is the first tag NVIDIA lists for Spark;
# override BASE for a newer one.
#
#   docker build -t microgrid-train:gx10 -f gx10/training/Dockerfile gx10/training
ARG BASE=nvcr.io/nvidia/pytorch:25.09-py3
FROM ${BASE}

# torch comes from the base image and is left alone. pandas and pyarrow are
# pinned to the ranges in services/iems/training/requirements-training.txt,
# the versions the labellers and the trainer were written against.
RUN pip install --no-cache-dir "pandas>=2.1,<2.3" "pyarrow>=15,<19" \
        "onnx>=1.15" "onnxruntime>=1.17" "scikit-learn>=1.4" \
    && python -c "import onnx, onnxruntime, torch; print('torch', torch.__version__, 'onnxruntime', onnxruntime.__version__)"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Los_Angeles
WORKDIR /workspace
ENTRYPOINT ["bash", "gx10/training/train_all.sh"]
