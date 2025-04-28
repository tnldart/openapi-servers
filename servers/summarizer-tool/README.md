# 📚 Local Summarizer Agent

This FastAPI server acts to summarize a given chunk of text.

It is assumed that you are running an ollama instance in an adjacent container with the default port available.

## 📦 Endpoints
### POST /summarize/text
Summarizes the given block of text

📥 Request

Body: 
```
{
    'text':'Your blob of text here. It can be unlimited, but is recommended to be within the context window of the LLM you are asking for a summary from.'
}
```

📤 Response:

```
{
    "status": "success",
    "summary": "A summary of your text."
}
```

### POST /summarize/chat
Not yet implemented. Summarizes an exported Open WebUI chat JSON blob.

## 🧩 Environment Variables
|Name|Description|Default|
|---|---|---|
|MODEL|The name of the model you are trying to reference. Should match the model in your ollama instance. | llama3|
|MODEL_URL|The URL path to the model you are trying to access.|http://host.docker.internal:11434|

