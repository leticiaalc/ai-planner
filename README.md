# 🤖 AI Weekly Planner Agent
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Claude](https://img.shields.io/badge/AI-Claude%20Anthropic-purple)
![Google Calendar](https://img.shields.io/badge/API-Google%20Calendar-green)
![Agent SDK](https://img.shields.io/badge/Agent-Claude%20SDK-orange)
![Status](https://img.shields.io/badge/status-active-success)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Um agente de IA que organiza automaticamente sua semana, integrando Claude (Anthropic) com Google Calendar.

Esse projeto demonstra, na prática, como construir agentes capazes de:

- interpretar linguagem natural
- tomar decisões
- interagir com APIs externas
- executar ações no mundo real

---

# 🚀 O que esse projeto faz

O agente:

- lê sua agenda do Google Calendar
- interpreta tarefas escritas em linguagem natural
- reorganiza sua semana
- cria novos eventos
- atualiza eventos existentes
- respeita regras como:
  - horário de trabalho
  - pausa para almoço
  - limite de carga diária
  - proteção de reuniões importantes

---

# 🧠 Conceitos abordados

- Agents (IA com autonomia)
- Prompt Engineering
- Tool Calling
- Integração com APIs externas
- MCP (Model Context Protocol)
- Claude API
- Claude Agent SDK

---

# 📁 Estrutura do projeto

```bash
.
├── main.py                     # Versão manual + API (sem Agent SDK)
├── agent_sdk_calendar.py       # Versão com Agent SDK
├── demo_calendar_setup.py      # Script para limpar/criar eventos de teste
├── agenda_demo.json            # Dados de exemplo para agenda
├── .env                        # Configurações (NÃO versionar)
├── .gitignore
├── credentials.json            # OAuth Google (NÃO versionar)
├── token.json                  # Token Google (gerado automaticamente)

```

---

# 🚀 Pré-requisitos

Antes de começar, você precisa ter:

- Python 3.10 ou superior
- Conta Google
- Conta no Claude → https://console.anthropic.com/
- Projeto configurado no Google Cloud com:
  - Google Calendar API ativada
  - OAuth configurado
  - arquivo `credentials.json` baixado

---

# ⚙️ Setup do projeto

## 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/ai-planner.git
cd ai-planner
```
## 2. Criar o arquivo .env

```bash
ANTHROPIC_API_KEY=sua_api_key
CALENDAR_ID=seu_calendario@group.calendar.google.com
```

## 3. Adicionar credenciais do Google

Coloque o arquivo:

```bash
credentials.json
```
na raiz do projeto.
