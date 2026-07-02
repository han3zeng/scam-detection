# Roadmap

## Goal
[North Star](https://nordvpn.com/scam-text-checker/?srsltid=AfmBOopSHG3rMzrhukA3xY2oHgzxtwsWUoPVkqGpTRLEhBYnJ8WWKdfa)


## Overview
Originally, my plane is to make a traditional chinese version of nordvpn scam checker. However, after research, I reckon that the traditional-chinese scam data is not available so I pivot to emotional label service simply for demo.

So I should have 4 main elements.
1. Data pipeline 
2. Model training and deploy pipeline
3. Backend-service
4. Frontend-service

For now I will focus on 3 and 4 since I decide to use the existing [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small) model first for quick demo.



## Backend-service
Wrap fastAPI around the [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small) model to provides a emotion-label endpoint service. The service should be a docker container and deploy to google cloud run with a full CI/CD pipeline. Use google API gateway to handle cors and x-api-key verification.

Flow
```
Front end service -> api gateway -> cloud run (back end service)
```

The following content specifies the specs:

### CI/CD Pipeline
```
Push to main
  → run lint
  → run unit tests
  → build Docker image
  → push image to Google Artifact Registry
  → deploy image to Cloud Run
  → smoke test /health
```

### Docker image strategy
- docker download the model and built it into image with FastAPI service



### Google API Gateway

#### CORS
- The back-end service and front-end service will be at different domain, so please enable the CORS of back-end service

#### x-API-key

### Endpoint
2 basic endpoints
```
GET /health
GET /emotion
```
- health is simply to check if the service is running
- emotion endpoint is for frontend to get data response

### Features

#### Emotion End-point Data Format
Request Payload

```json
{
  "text": "你最近過得好嗎？",
  "top_k": 3
}
```

Response


```json
{
  "text": "你最近過得好嗎？",
  "prediction": {
    "label": "關切語調",
    "label_en": "concerned",
    "score": 0.82
  },
  "top_k": [
    { "label": "關切語調", "label_en": "concerned", "score": 0.82 },
    { "label": "疑問語調", "label_en": "questioning", "score": 0.11 },
    { "label": "平淡語氣", "label_en": "neutral", "score": 0.04 }
  ],
  "model": "Johnson8187/Chinese-Emotion-Small"
}
```


#### Input Validation
```python
text: str
max length: maybe 512 Chinese characters
empty text: reject
top_k: 1-8
```

## Supporting Service (Optional)
### Cloud Logging
- request logs
- error logs
- latency monitoring



## References
- [Scam Report - Ministry of Digital Affairs](https://fraudbuster.digiat.org.tw/accessibility/index)
- BERT > [XMLRoBERTa](https://huggingface.co/FacebookAI/xlm-roberta-large) > [xlm-roberta-large-xnli](https://huggingface.co/joeddav/xlm-roberta-large-xnli) > [Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small)
- https://chatgpt.com/c/6a45fb4c-799c-83e8-b36e-b280131c5bf2