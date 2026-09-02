FROM python:3.13-slim
WORKDIR /app
COPY services/counterfactual/app.py /app/app.py
COPY services/common/environment_contract.py /app/common/environment_contract.py
EXPOSE 8080
CMD ["python", "/app/app.py"]
