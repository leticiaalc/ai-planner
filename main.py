import os
import json
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

import anthropic

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# =========================================================
# CONFIGURAÇÕES INICIAIS
# =========================================================

# Carrega variáveis do arquivo .env
load_dotenv()

# =========================================================
# CONFIGURAÇÕES INICIAIS
# =========================================================

# Carrega variáveis do arquivo .env
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ID do calendário.
# Recomendado: configurar no arquivo .env
# Exemplo no .env:
# CALENDAR_ID=abc123@group.calendar.google.com
CALENDAR_ID = os.getenv("CALENDAR_ID")

# Modo seguro.
# True = apenas simula as ações.
# False = altera a agenda de verdade.
DEMO_MODE = False

# Modelo do Claude.
# Pode ser configurado no .env.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Client da API da Anthropic / Claude
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# =========================================================
# CORES DO GOOGLE CALENDAR
# =========================================================
COLOR_MAP = {
    "reuniao_importante": "11",  # vermelho
    "trabalho": "1",             # azul
    "pessoal": "2",              # verde
    "pausa": "5",                # amarelo
    "almoco": "6",               # laranja
    "preparacao": "9",           # azul escuro
    "saude": "4",                # vermelho claro
    "estudo": "10",              # verde escuro
}

# =========================================================
# DETECÇÃO DE EVENTOS IMPORTANTES
# =========================================================
IMPORTANT_KEYWORDS = [
    "reunião importante",
    "reuniao importante",
    "cliente",
    "diretoria",
    "vp",
    "c-level",
    "clevel",
    "comitê",
    "comite",
    "apresentação",
    "apresentacao",
    "entrevista",
    "médico",
    "medico",
    "1:1",
    "mentoria",
    "estratégia",
    "estrategia",
]


def is_important_event(title: str) -> bool:
    """
    Verifica se um evento parece importante com base no título.
    Isso protege eventos sensíveis para que o agente não mude data/horário.
    """

    title_lower = title.lower()
    return any(keyword in title_lower for keyword in IMPORTANT_KEYWORDS)


# =========================================================
# AUTENTICAÇÃO COM GOOGLE CALENDAR
# =========================================================
def authenticate_google():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES,
        )

        creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

# =========================================================
# BUSCAR EVENTOS DA SEMANA
# =========================================================
def get_events(service):
    now = datetime.now(timezone.utc).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])

    formatted_events = []

    for event in events:
        title = event.get("summary", "Sem título")
        start = event["start"].get("dateTime", event["start"].get("date"))
        end = event["end"].get("dateTime", event["end"].get("date"))

        formatted_events.append({
            "id": event.get("id"),
            "titulo": title,
            "inicio": start,
            "fim": end,
            "descricao": event.get("description", ""),
            "cor_atual": event.get("colorId", "sem cor"),
            "importante": is_important_event(title),
        })

    return formatted_events

# =========================================================
# COLETAR TAREFAS SOLTAS DO USUÁRIO
# =========================================================
def collect_user_tasks():
    print("\n📝 Digite tarefas que ainda não estão na agenda.")
    print("Exemplo:")
    print("- preciso preparar uma apresentação para a demo da sprint até quinta às 17h")
    print("- estudar Python por 2 horas essa semana")
    print("- revisar currículo até sexta")
    print("\nDigite uma tarefa por linha.")
    print("Quando terminar, digite FIM.\n")

    tasks = []

    while True:
        task = input("> ")

        if task.strip().upper() == "FIM":
            break

        if task.strip():
            tasks.append(task.strip())

    return tasks

# =========================================================
# PROMPT DO AGENTE
# =========================================================
def build_prompt(events, user_tasks):
    return f"""
Você é um agente pessoal inteligente especializado em organização de agenda semanal.

Seu objetivo é reorganizar a agenda considerando produtividade, foco, bem-estar e importância dos compromissos.

REGRAS GERAIS:
- Não sobrepor eventos.
- Jornada de trabalho: 08:00 às 18:00.
- Máximo de 8 horas de trabalho por dia.
- Almoço entre 12:00 e 14:00, com no mínimo 1 hora.
- Não agendar trabalho durante o almoço.
- Evitar muitos blocos seguidos sem pausa.
- Criar momentos de descompressão se houver sobrecarga mental.

REGRAS PARA TAREFAS DIGITADAS:
- Interprete tarefas em linguagem natural.
- Identifique prazos quando existirem.
- Estime uma duração razoável para cada tarefa.
- Quebre tarefas grandes em blocos menores, se necessário.
- Encaixe as tarefas nos melhores horários livres.
- Se uma tarefa tiver prazo, ela deve ser agendada antes do prazo.
- Se o prazo for "quinta às 17h", a tarefa precisa estar concluída antes desse horário.
- Se a tarefa exigir preparação, crie blocos de foco realistas.
- Não coloque tarefas complexas no fim do dia, exceto se não houver alternativa.

REGRAS PARA EVENTOS EXISTENTES:
- Você pode alterar a cor de qualquer evento existente.
- Você pode diminuir a duração de eventos existentes, se isso melhorar a agenda.
- Você só pode alterar data ou horário de eventos menos importantes.
- Nunca altere data ou horário de eventos importantes.
- Nunca reduza a duração de eventos importantes.
- Se não tiver certeza se um evento é importante, trate como importante.
- Ao editar um evento existente, mantenha o mesmo id.

REUNIÕES IMPORTANTES:
- Eventos importantes devem receber categoria "reuniao_importante".
- Reuniões importantes devem ter uma agenda de preparação de 10 minutos antes.
- A preparação deve ter categoria "preparacao".
- Se já houver conflito antes da reunião, não crie preparação sobreposta.

CATEGORIAS PERMITIDAS:
- reuniao_importante
- trabalho
- pessoal
- pausa
- almoco
- preparacao
- saude
- estudo

EVENTOS ATUAIS:
{json.dumps(events, indent=2, ensure_ascii=False)}

TAREFAS DIGITADAS PELO USUÁRIO:
{json.dumps(user_tasks, indent=2, ensure_ascii=False)}

FORMATO DE SAÍDA:
Retorne APENAS JSON válido.
Não use markdown.
Não use bloco de código.
Não explique nada fora do JSON.

IMPORTANTE:
- Não gere ações para eventos que não precisam ser alterados.
- Só gere "update" se o evento realmente precisar mudar de cor, duração ou horário.
- Só gere "create" para novos eventos necessários.
- O campo "motivo" deve ter no máximo 80 caracteres.

Formato:

[
  {{
    "acao": "update",
    "id": "id_do_evento_existente",
    "titulo": "título",
    "data": "YYYY-MM-DD",
    "hora_inicio": "HH:MM",
    "hora_fim": "HH:MM",
    "categoria": "reuniao_importante | trabalho | pessoal | pausa | almoco | preparacao | saude | estudo",
    "motivo": "texto curto"
  }},
  {{
    "acao": "create",
    "titulo": "título",
    "data": "YYYY-MM-DD",
    "hora_inicio": "HH:MM",
    "hora_fim": "HH:MM",
    "categoria": "reuniao_importante | trabalho | pessoal | pausa | almoco | preparacao | saude | estudo",
    "motivo": "texto curto"
  }}
]
"""

# =========================================================
# CHAMADA CLAUDE VIA API
# =========================================================
def call_claude_api(prompt):
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10000,
        temperature=0,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    print(f"\n🧪 Stop reason: {response.stop_reason}")

    if response.stop_reason == "max_tokens":
        print("⚠️ A resposta foi cortada por limite de tokens. Aumente max_tokens ou reduza o JSON.")

    return response.content[0].text

# =========================================================
# MODO MANUAL
# =========================================================
def call_claude_manual(prompt):
    print("\n📋 COPIE ESTE PROMPT E COLE NO CLAUDE:\n")
    print(prompt)

    print("\n✏️ Cole aqui o JSON de resposta do Claude.")
    print("Quando terminar, digite FIM em uma linha separada:\n")

    lines = []

    while True:
        line = input()

        if line.strip().upper() == "FIM":
            break

        lines.append(line)

    return "\n".join(lines)

# =========================================================
# EXTRAIR JSON DA RESPOSTA
# =========================================================
def extract_json(response_text):
    cleaned = response_text.strip()

    cleaned = cleaned.replace("```json", "")
    cleaned = cleaned.replace("```", "")
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)

        if match:
            return json.loads(match.group(0))

        raise

# =========================================================
# CRIAR EVENTO
# =========================================================
def create_single_event(service, event_data):
    event = {
        "summary": event_data["titulo"],
        "start": {
            "dateTime": f"{event_data['data']}T{event_data['hora_inicio']}:00",
            "timeZone": "America/Sao_Paulo",
        },
        "end": {
            "dateTime": f"{event_data['data']}T{event_data['hora_fim']}:00",
            "timeZone": "America/Sao_Paulo",
        },
        "colorId": COLOR_MAP.get(event_data["categoria"], "1"),
        "description": f"Criado pelo agente. Motivo: {event_data.get('motivo', '')}",
    }

    service.events().insert(
        calendarId=CALENDAR_ID,
        body=event,
    ).execute()

# =========================================================
# ATUALIZAR EVENTO EXISTENTE
# =========================================================
def update_existing_event(service, event_data):
    event_id = event_data["id"]

    existing_event = service.events().get(
        calendarId=CALENDAR_ID,
        eventId=event_id,
    ).execute()

    original_title = existing_event.get("summary", "")
    original_start = existing_event["start"]
    original_end = existing_event["end"]

    important = is_important_event(original_title)

    existing_event["colorId"] = COLOR_MAP.get(event_data["categoria"], "1")

    if important:
        existing_event["summary"] = original_title
        existing_event["start"] = original_start
        existing_event["end"] = original_end
    else:
        existing_event["summary"] = event_data["titulo"]
        existing_event["start"] = {
            "dateTime": f"{event_data['data']}T{event_data['hora_inicio']}:00",
            "timeZone": "America/Sao_Paulo",
        }
        existing_event["end"] = {
            "dateTime": f"{event_data['data']}T{event_data['hora_fim']}:00",
            "timeZone": "America/Sao_Paulo",
        }

    existing_description = existing_event.get("description", "")
    agent_note = f"\n\nAtualizado pelo agente. Motivo: {event_data.get('motivo', '')}"
    existing_event["description"] = existing_description + agent_note

    service.events().update(
        calendarId=CALENDAR_ID,
        eventId=event_id,
        body=existing_event,
    ).execute()

# =========================================================
# APLICAR AÇÕES NO CALENDÁRIO
# =========================================================
def apply_calendar_actions(service, actions):
    for action in actions:
        acao = action.get("acao")
        titulo = action.get("titulo", "Sem título")
        categoria = action.get("categoria", "trabalho")
        motivo = action.get("motivo", "")

        if DEMO_MODE:
            if acao == "update":
                print(f"[DEMO] Atualizaria: {titulo}")
                print(f"       Categoria/cor: {categoria}")
                print(f"       Motivo: {motivo}")
                print()
            elif acao == "create":
                print(f"[DEMO] Criaria: {titulo}")
                print(f"       Categoria/cor: {categoria}")
                print(f"       Motivo: {motivo}")
                print()
            continue

        if acao == "update":
            update_existing_event(service, action)

        elif acao == "create":
            create_single_event(service, action)

        else:
            print(f"⚠️ Ação ignorada: {acao}")

# =========================================================
# MENU CLI
# =========================================================
def select_mode():
    print("\n=== 🤖 Selecione o modo do agente ===")
    print("1 - Manual: usar Claude no navegador")
    print("2 - API: chamar Claude automaticamente")

    choice = input("\nEscolha 1 ou 2: ")

    if choice == "1":
        return "manual"

    if choice == "2":
        return "api"

    print("⚠️ Opção inválida. Usando modo manual.")
    return "manual"

# =========================================================
# EXECUÇÃO PRINCIPAL
# =========================================================
def main():
    mode = select_mode()

    print("\n🔐 Autenticando no Google Calendar...")
    service = authenticate_google()

    print("\n📅 Buscando eventos da semana...")
    events = get_events(service)

    print(f"\n📌 Eventos encontrados: {len(events)}")

    user_tasks = collect_user_tasks()

    prompt = build_prompt(events, user_tasks)

    if mode == "api":
        print("\n🤖 Chamando Claude via API...")
        response_text = call_claude_api(prompt)
    else:
        print("\n🧑‍💻 Modo manual selecionado...")
        response_text = call_claude_manual(prompt)

    print("\n📊 Resposta recebida:\n")
    print(response_text)


    try:
        actions = extract_json(response_text)
    except Exception as error:
        print("\n❌ Erro ao converter JSON.")
        print(error)

        if response_text.strip() and not response_text.strip().endswith("]"):
            print("\n⚠️ O JSON parece estar incompleto. Provável resposta truncada pelo limite de tokens.")

        return

    print("\n📅 Aplicando ações no calendário...\n")
    apply_calendar_actions(service, actions)

    print("\n✅ Finalizado!")


if __name__ == "__main__":
    main()