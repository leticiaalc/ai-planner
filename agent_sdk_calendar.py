import os
import json
import asyncio
from typing import Any
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    tool,
    create_sdk_mcp_server,
    ToolAnnotations,
)

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# =========================================================
# CONFIGURAÇÕES INICIAIS
# =========================================================

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CALENDAR_ID = os.getenv("CALENDAR_ID")

# True = apenas simula as ações.
# False = altera a agenda de verdade.
DEMO_MODE = False

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Reutiliza a conexão com Google Calendar para evitar reautenticar em cada tool
google_service = None


# =========================================================
# CORES DO GOOGLE CALENDAR
# =========================================================

COLOR_MAP = {
    "reuniao_importante": "11",
    "trabalho": "1",
    "pessoal": "2",
    "pausa": "5",
    "almoco": "6",
    "preparacao": "9",
    "saude": "4",
    "estudo": "10",
}


# =========================================================
# EVENTOS IMPORTANTES
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
    """Identifica se um evento parece importante pelo título."""

    title_lower = title.lower()
    return any(keyword in title_lower for keyword in IMPORTANT_KEYWORDS)


# =========================================================
# AUTENTICAÇÃO GOOGLE
# =========================================================

def authenticate_google():
    """
    Autentica com o Google Calendar.

    Se token.json já existir, reutiliza a autenticação.
    Se não existir, abre o navegador para login.
    """

    print("🔐 Iniciando autenticação Google...")

    creds = None

    if os.path.exists("token.json"):
        print("📄 token.json encontrado.")
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        print("🌐 Abrindo navegador para login Google...")

        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES,
        )

        creds = flow.run_local_server(port=0)

        print("✅ Login Google concluído.")

        with open("token.json", "w") as token:
            token.write(creds.to_json())

        print("💾 token.json atualizado.")

    print("📅 Serviço do Google Calendar pronto.")

    return build("calendar", "v3", credentials=creds)


def get_google_service():
    """
    Cria ou reutiliza uma conexão com Google Calendar.

    Isso evita que cada tool tente autenticar novamente.
    """

    global google_service

    if google_service is None:
        print("🔌 Criando conexão única com Google Calendar...")
        google_service = authenticate_google()
        print("✅ Conexão Google Calendar criada.")

    return google_service


# =========================================================
# TOOL 1 — BUSCAR EVENTOS DA SEMANA
# =========================================================

@tool(
    "buscar_eventos_da_semana",
    "Busca os eventos existentes no Google Calendar nos próximos 7 dias.",
    {},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def buscar_eventos_da_semana(args: dict[str, Any]) -> dict[str, Any]:
    """
    Tool usada pelo agente para ler a agenda.

    O agente deve chamar essa tool antes de decidir o que criar ou atualizar.
    """

    print("\n🛠️ Tool chamada: buscar_eventos_da_semana")

    try:
        service = get_google_service()

        now = datetime.now(timezone.utc).isoformat()
        time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        print("📥 Buscando eventos dos próximos 7 dias...")

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

        print(f"✅ Eventos encontrados: {len(formatted_events)}")

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        formatted_events,
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as error:
        print("❌ Erro ao buscar eventos:")
        print(error)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Erro ao buscar eventos: {str(error)}",
                }
            ]
        }


# =========================================================
# TOOL 2 — CRIAR EVENTO
# =========================================================

@tool(
    "criar_evento",
    "Cria um novo evento no Google Calendar.",
    {
        "type": "object",
        "properties": {
            "titulo": {"type": "string"},
            "data": {"type": "string", "description": "Formato YYYY-MM-DD"},
            "hora_inicio": {"type": "string", "description": "Formato HH:MM"},
            "hora_fim": {"type": "string", "description": "Formato HH:MM"},
            "categoria": {
                "type": "string",
                "enum": [
                    "reuniao_importante",
                    "trabalho",
                    "pessoal",
                    "pausa",
                    "almoco",
                    "preparacao",
                    "saude",
                    "estudo",
                ],
            },
            "motivo": {"type": "string"},
        },
        "required": [
            "titulo",
            "data",
            "hora_inicio",
            "hora_fim",
            "categoria",
            "motivo",
        ],
    },
)
async def criar_evento(args: dict[str, Any]) -> dict[str, Any]:
    """
    Tool usada pelo agente para criar eventos novos.

    Exemplos:
    - almoço
    - pausa
    - preparação para reunião
    - bloco de foco
    - tarefa digitada pela pessoa usuária
    """

    print("\n🛠️ Tool chamada: criar_evento")
    print(json.dumps(args, ensure_ascii=False, indent=2))

    if DEMO_MODE:
        print("🧪 DEMO_MODE ativo. Evento não será criado de verdade.")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"[DEMO] Criaria evento: {args['titulo']}",
                }
            ]
        }

    try:
        service = get_google_service()

        print("📅 Montando evento para criação...")

        event = {
            "summary": args["titulo"],
            "start": {
                "dateTime": f"{args['data']}T{args['hora_inicio']}:00",
                "timeZone": "America/Sao_Paulo",
            },
            "end": {
                "dateTime": f"{args['data']}T{args['hora_fim']}:00",
                "timeZone": "America/Sao_Paulo",
            },
            "colorId": COLOR_MAP.get(args["categoria"], "1"),
            "description": f"Criado pelo agente. Motivo: {args.get('motivo', '')}",
        }

        print("🚀 Enviando evento para Google Calendar...")

        created = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event,
        ).execute()

        print("✅ Evento criado com sucesso.")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Evento criado com sucesso: {created.get('htmlLink')}",
                }
            ]
        }

    except Exception as error:
        print("❌ Erro ao criar evento:")
        print(error)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Erro ao criar evento: {str(error)}",
                }
            ]
        }


# =========================================================
# TOOL 3 — ATUALIZAR EVENTO EXISTENTE
# =========================================================

@tool(
    "atualizar_evento",
    "Atualiza um evento existente no Google Calendar.",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "titulo": {"type": "string"},
            "data": {"type": "string", "description": "Formato YYYY-MM-DD"},
            "hora_inicio": {"type": "string", "description": "Formato HH:MM"},
            "hora_fim": {"type": "string", "description": "Formato HH:MM"},
            "categoria": {
                "type": "string",
                "enum": [
                    "reuniao_importante",
                    "trabalho",
                    "pessoal",
                    "pausa",
                    "almoco",
                    "preparacao",
                    "saude",
                    "estudo",
                ],
            },
            "motivo": {"type": "string"},
        },
        "required": [
            "id",
            "titulo",
            "data",
            "hora_inicio",
            "hora_fim",
            "categoria",
            "motivo",
        ],
    },
)
async def atualizar_evento(args: dict[str, Any]) -> dict[str, Any]:
    """
    Tool usada pelo agente para atualizar eventos existentes.

    Regra de segurança:
    - evento importante só pode mudar de cor
    - evento não importante pode mudar título, data, hora e duração
    """

    print("\n🛠️ Tool chamada: atualizar_evento")
    print(json.dumps(args, ensure_ascii=False, indent=2))

    if DEMO_MODE:
        print("🧪 DEMO_MODE ativo. Evento não será atualizado de verdade.")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"[DEMO] Atualizaria evento: {args.get('titulo')}",
                }
            ]
        }

    try:
        service = get_google_service()

        print("🔎 Buscando evento existente no Google Calendar...")

        existing_event = service.events().get(
            calendarId=CALENDAR_ID,
            eventId=args["id"],
        ).execute()

        original_title = existing_event.get("summary", "")
        original_start = existing_event.get("start")
        original_end = existing_event.get("end")

        important = is_important_event(original_title)

        print(f"📌 Evento original: {original_title}")
        print(f"⭐ Importante: {important}")

        # Sempre pode mudar a cor do evento
        existing_event["colorId"] = COLOR_MAP.get(args["categoria"], "1")

        # Se for importante, preserva data, horário, duração e título
        if important:
            print("🔒 Evento importante: mantendo data e horário.")
            existing_event["summary"] = original_title
            existing_event["start"] = original_start
            existing_event["end"] = original_end

        # Se não for importante, permite otimização
        else:
            print("✏️ Evento não importante: aplicando mudanças sugeridas.")

            existing_event["summary"] = args["titulo"]
            existing_event["start"] = {
                "dateTime": f"{args['data']}T{args['hora_inicio']}:00",
                "timeZone": "America/Sao_Paulo",
            }
            existing_event["end"] = {
                "dateTime": f"{args['data']}T{args['hora_fim']}:00",
                "timeZone": "America/Sao_Paulo",
            }

        existing_description = existing_event.get("description", "")
        agent_note = f"\n\nAtualizado pelo agente. Motivo: {args.get('motivo', '')}"
        existing_event["description"] = existing_description + agent_note

        print("🚀 Enviando atualização para Google Calendar...")

        updated = service.events().update(
            calendarId=CALENDAR_ID,
            eventId=args["id"],
            body=existing_event,
        ).execute()

        print("✅ Evento atualizado com sucesso.")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Evento atualizado com sucesso: {updated.get('htmlLink')}",
                }
            ]
        }

    except Exception as error:
        print("❌ Erro ao atualizar evento:")
        print(error)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Erro ao atualizar evento: {str(error)}",
                }
            ]
        }


# =========================================================
# SERVIDOR MCP LOCAL
# =========================================================

calendar_server = create_sdk_mcp_server(
    name="calendar",
    version="1.0.0",
    tools=[
        buscar_eventos_da_semana,
        criar_evento,
        atualizar_evento,
    ],
)


# =========================================================
# COLETAR TAREFAS EM LINGUAGEM NATURAL
# =========================================================

def collect_user_tasks() -> list[str]:
    """
    Coleta tarefas soltas digitadas pela pessoa usuária.

    A pessoa pode digitar várias tarefas.
    Para finalizar, pode usar FIM, FINALIZAR, SAIR ou END.
    """

    print("\n📝 Digite tarefas que ainda não estão na agenda.")
    print("Exemplo: preciso preparar uma apresentação para a demo da sprint até quinta às 17h")
    print("Digite uma tarefa por linha.")
    print("Quando terminar, digite FIM.\n")

    tasks = []

    while True:
        task = input("> ")

        normalized_task = task.strip().upper()

        if normalized_task in ["FIM", "FINALIZAR", "SAIR", "END"]:
            print("✅ Entrada de tarefas finalizada.")
            break

        if task.strip():
            tasks.append(task.strip())

    return tasks


# =========================================================
# PROMPT DO AGENTE
# =========================================================

def build_agent_prompt(user_tasks: list[str]) -> str:
    """
    Prompt principal do agente.

    Esse prompt define:
    - comportamento
    - regras
    - ferramentas disponíveis
    - limites de segurança
    """

    return f"""
Você é um agente pessoal inteligente de alto nível especializado em organização de agenda semanal.

Sua missão é agir como um assistente executivo pessoal:
- analisar a agenda existente
- interpretar tarefas soltas em linguagem natural
- criar eventos necessários
- atualizar eventos existentes quando fizer sentido
- melhorar a organização da semana
- proteger foco, produtividade e saúde mental

==================================================
PASSO OBRIGATÓRIO
==================================================

Sempre comece chamando a ferramenta:
buscar_eventos_da_semana

Depois de receber os eventos, analise a agenda antes de agir.

==================================================
TAREFAS SOLTAS DIGITADAS PELO USUÁRIO
==================================================

{json.dumps(user_tasks, ensure_ascii=False, indent=2)}

Interprete cada tarefa em linguagem natural.

Exemplos:
- "preciso preparar uma apresentação até quinta às 17h"
  → estimar duração
  → quebrar em blocos, se necessário
  → agendar antes de quinta às 17h

- "estudar Python por 2 horas essa semana"
  → criar bloco de estudo de 2h ou dois blocos de 1h

- "revisar currículo até sexta"
  → criar bloco antes de sexta

==================================================
REGRAS CRÍTICAS DE AGENDA
==================================================

- Nunca sobrepor eventos.
- Jornada de trabalho: 08:00 às 18:00.
- Máximo de 8 horas de trabalho por dia.
- Almoço obrigatório entre 12:00 e 14:00.
- O almoço deve ter no mínimo 1 hora.
- Nunca agendar trabalho durante o almoço.
- Evitar mais de 2 horas seguidas sem pausa.
- Criar pausas quando houver blocos longos.
- Criar descompressão quando houver sobrecarga mental.

==================================================
EVENTOS IMPORTANTES
==================================================

Considere importantes eventos com termos como:
- cliente
- diretoria
- VP
- C-level
- comitê
- apresentação
- entrevista
- médico
- 1:1
- mentoria
- estratégia

Regras para eventos importantes:
- Nunca alterar data.
- Nunca alterar horário.
- Nunca reduzir duração.
- Sempre atualizar categoria para "reuniao_importante".
- Sempre aplicar cor de reunião importante.
- Criar um evento de preparação de 10 minutos antes, se não houver conflito.

==================================================
EVENTOS EXISTENTES NÃO IMPORTANTES
==================================================

Você pode:
- alterar cor
- reduzir duração, se fizer sentido
- mover para outro horário livre
- mover para outro dia da semana
- ajustar título, se necessário

Mas só faça isso se melhorar a agenda.

==================================================
TAREFAS NOVAS
==================================================

Para tarefas novas, você deve:
- estimar duração realista
- escolher o melhor horário
- respeitar prazos explícitos
- priorizar manhã para tarefas complexas
- evitar final do dia para tarefas difíceis
- quebrar tarefas grandes em blocos menores

==================================================
MODELO DE ENERGIA HUMANA
==================================================

Use este padrão:
- 08:00–12:00: tarefas complexas e foco profundo
- 12:00–14:00: almoço
- 14:00–16:00: reuniões e tarefas médias
- 16:00–18:00: tarefas leves, revisão e planejamento

==================================================
CATEGORIAS PERMITIDAS
==================================================

Use apenas uma destas categorias:
- reuniao_importante
- trabalho
- pessoal
- pausa
- almoco
- preparacao
- saude
- estudo

==================================================
FERRAMENTAS DISPONÍVEIS
==================================================

Você pode e deve usar:
- buscar_eventos_da_semana
- criar_evento
- atualizar_evento

Importante:
- Não responda apenas com um plano.
- Use ferramentas para agir.
- Se DEMO_MODE estiver ativo, as ferramentas irão apenas simular as ações.
- Mesmo assim, você deve chamar as ferramentas normalmente.

==================================================
RESULTADO FINAL
==================================================

Depois de usar as ferramentas, entregue um resumo curto contendo:
- eventos criados
- eventos atualizados
- reuniões importantes destacadas
- melhorias de bem-estar adicionadas
"""


# =========================================================
# EXECUÇÃO PRINCIPAL
# =========================================================

async def main():
    """
    Fluxo principal:

    1. Coleta tarefas em linguagem natural.
    2. Configura as ferramentas do agente.
    3. Executa o agente.
    4. Mostra o resultado final.
    """

    user_tasks = collect_user_tasks()

    print("⚙️ Configurando agente...")

    options = ClaudeAgentOptions(
        mcp_servers={"calendar": calendar_server},
        allowed_tools=[
            "mcp__calendar__buscar_eventos_da_semana",
            "mcp__calendar__criar_evento",
            "mcp__calendar__atualizar_evento",
        ],
        tools=[],
        model=CLAUDE_MODEL,
    )

    print("🤖 Iniciando execução do agente...")

    async for message in query(
        prompt=build_agent_prompt(user_tasks),
        options=options,
    ):
        print("📨 Mensagem recebida do agente:", type(message).__name__)

        if isinstance(message, ResultMessage) and message.subtype == "success":
            print("\n✅ Resultado final do agente:\n")
            print(message.result)


# =========================================================
# PONTO DE ENTRADA
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())