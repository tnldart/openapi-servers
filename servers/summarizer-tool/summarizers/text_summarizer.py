import requests
from .base import BaseSummarizer
import os

MODEL_URL=os.environ.get('MODEL_URL')
MODEL=os.environ.get('MODEL')
SUMMARIZE_PROMPT = """You are the summarizing agent in a long chain of agents.
It is your job to responsibly capture the entirety of what is being described in incoming documents.
You can scrap small details, but you must make sure to hit all the major points.
These documents will be used in RAG down the line.


For example, given the following text:
"I've got updates on the tiny brains if\nyou are not familiar with brain\norganoids they are tiny human brains\nthat we can grow from stem cells you can\ngrow them in a literal jar if you want\nto but you can also hook them up to a\ncomputer or llm since a company called\nfinal spark decided to release brain\norganoid computation for industrial use\n"

You would respond with

"The speaker is discussing human brain stem cells being grown for industrial use."

Another example:
hi, i'\''m isopod (formerly hornet)\n \ni'\''m a software engineer\n \ni write code, make costumes, and write music

You would respond with
Isopod, formerly hornet, is a software engineer who makes costumes and writes music.

You always sanitize data. You always remove \n. You never mention yourself in your summaries. You never infer, only summarize what is presented. You never describe the text as summarized: you always just give the summary.
"""

class TextSummarizer(BaseSummarizer):
    def summarize(self, data):
        payload = {
            "model":MODEL,
            "system": SUMMARIZE_PROMPT,
            "prompt":data,
            "stream":False,
            "options":{
                "temperature":0.5
            }
        }
        url = MODEL_URL + '/api/generate'
        result = requests.post(url=url, json=payload)
        if result.status_code == 200:
            json_data = result.json()
            if 'response' in json_data:
                return {
                    'type': 'text',
                    'source': url,
                    'content': json_data['response']
                }
        print(result.content)
        return {
            'type': 'text',
            'source': url,
            'error': result.status_code   
        }


