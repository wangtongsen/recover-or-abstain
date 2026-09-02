FROM python:3.13-slim
WORKDIR /app
COPY services/evaluator/app.py /app/app.py
COPY services/common/environment_contract.py /app/common/environment_contract.py
CMD ["python", "/app/app.py"]
