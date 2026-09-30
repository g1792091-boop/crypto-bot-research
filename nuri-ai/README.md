# 누리 AI — 나만의 AI 챗봇

설치 없이 브라우저에서 실행되는 챗봇 + 대시보드입니다. 하나의 대화 화면에서 여러 AI 엔진을 골라 씁니다.

## 엔진

| 엔진 | 어디서 | 필요한 것 |
|---|---|---|
| Claude (내장) | claude.ai 아티팩트 | 없음 (내 Claude 계정 사용량) |
| **누리 자체 엔진 (오프라인)** | `index.html` 독립 실행 | WebGPU 지원 브라우저(최신 Chrome/Edge). 처음 한 번 모델 다운로드 |
| ChatGPT (OpenAI API) | `index.html` | OpenAI API 키 |
| Claude (Anthropic API) | `index.html` | Anthropic API 키 |
| Gemini (Google API) | `index.html` | Google AI Studio API 키 |
| DeepSeek API | `index.html` | DeepSeek API 키 |
| OpenAI 호환 서버 | `index.html` | Ollama·LM Studio 등 서버 주소 |

자체 엔진은 [WebLLM](https://github.com/mlc-ai/web-llm)으로 오픈소스 모델(Qwen3.5, Qwen3, DeepSeek-R1 Distill, Llama 3.2, Gemma 2)을
내 컴퓨터 GPU에서 직접 돌립니다. 모델을 한 번 내려받으면 브라우저에 캐시되어 인터넷 없이 답하고, 대화 내용이 밖으로 나가지 않습니다.
다만 작은 모델이라 GPT·Claude·Gemini 같은 대형 모델보다 정확도와 지식이 부족합니다.

## 기능

- 스트리밍 답변, 마크다운(표·코드블록 복사), 추론 모델의 "생각 과정" 접기
- 대화 목록·검색·삭제, 답변 다시 생성, 질문 수정 후 재전송
- 텍스트 파일 첨부(.txt .md .csv .json 코드), Claude 내장 엔진에서는 이미지 첨부
- 기본 봇 7종(만능 비서, 코딩, 번역, 글쓰기, 공부 튜터, 요약, 건축 설계 상담) + **내 봇 만들기**(역할·규칙·추천 질문·창의성)
- 대시보드: 대화·질문·답변 수, 평균 응답 시간, 최근 14일 질문 수, 엔진별·봇별 사용량
- 대화 내보내기/불러오기(JSON). claude.ai에서는 대화가 내 계정에 동기화되고, 독립 실행 버전에서는 브라우저에 저장

## 실행 방법

- **GitHub Pages (추천)**: 저장소 Settings → Pages에서 브랜치를 지정하면 `https://<아이디>.github.io/<저장소>/nuri-ai/`로 열립니다.
- 또는 `nuri-ai/index.html`을 Chrome/Edge로 열기.

API 키는 이 브라우저의 localStorage에만 저장됩니다. 공용 컴퓨터에서는 쓰지 마세요.
일부 서비스(특히 DeepSeek, 사설 서버)는 브라우저 직접 호출(CORS)을 막을 수 있습니다.
