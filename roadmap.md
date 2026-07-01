## Steps
1. Fine-tune pre-trained model [BERT-Base-Chinese](https://huggingface.co/google-bert/bert-base-chinese) with data [line-msg-fact-check-tw](https://huggingface.co/datasets/Cofacts/line-msg-fact-check-tw)
2. 


## Goal
https://nordvpn.com/scam-text-checker/?srsltid=AfmBOopSHG3rMzrhukA3xY2oHgzxtwsWUoPVkqGpTRLEhBYnJ8WWKdfa

## Implementation

### Fine-tuning



## Phases
### 1
- Feature: Scam detection
    - BERT based model
- Architecture

### 2
- Feature: Explanation
    - LLM works with output of BERT-based model and create explanation

### Phase 3
#### Image Upload
- OCR extract texts

#### Manual Database System
```
If image: OCR extracts text
   ↓
Normalize text
   ↓
Extract entities:
   - URLs
   - email addresses
   - phone numbers
   ↓
Check extracted entities against threat-intel databases
```

##### Mix Score Calculation
```py
def scam_checker(message: str):
    urls = extract_urls(message)
    emails = extract_emails(message)
    phones = extract_phone_numbers(message)

    threat_results = {
        "urls": check_url_reputation(urls),
        "emails": check_email_reputation(emails),
        "phones": check_phone_reputation(phones),
    }

    ai_result = classify_message_with_model(message)

    final_score = combine_scores(
        url_score=threat_results["urls"],
        email_score=threat_results["emails"],
        phone_score=threat_results["phones"],
        text_score=ai_result["risk_score"],
    )

    return {
        "risk_score": final_score,
        "label": risk_label(final_score),
        "reasons": ai_result["reasons"],
        "entities": {
            "urls": urls,
            "emails": emails,
            "phones": phones,
        },
    }
```

## Background Knowledge
- The candidate model: [Llama-Taiwan](https://huggingface.co/lianghsun/Llama-3.2-Taiwan-3B)
    - It has larger params, and transformer-based
    - I suppose the capacity exceeding what I need
    - The scam detection only needs encoder part
