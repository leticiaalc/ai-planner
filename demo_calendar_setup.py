import os
import json
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
SCOPES = ["https://www.googleapis.com/auth/calendar"]

CALENDAR_ID = os.getenv("CALENDAR_ID")

TIMEZONE = "America/Sao_Paulo"

DEMO_EVENTS_FILE = "agenda_demo.json"


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


def load_demo_events():
    with open(DEMO_EVENTS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def delete_events(service):
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

    print(f"\n🧹 Eventos encontrados para apagar: {len(events)}\n")

    for event in events:
        event_id = event["id"]
        title = event.get("summary", "Sem título")

        service.events().delete(
            calendarId=CALENDAR_ID,
            eventId=event_id,
        ).execute()

        print(f"Apagado: {title}")

    print("\n✅ Limpeza finalizada!")


def create_events(service):
    events = load_demo_events()

    print(f"\n📅 Eventos de teste encontrados no JSON: {len(events)}\n")

    for item in events:
        event = {
            "summary": item["titulo"],
            "start": {
                "dateTime": f"{item['data']}T{item['hora_inicio']}:00",
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": f"{item['data']}T{item['hora_fim']}:00",
                "timeZone": TIMEZONE,
            },
        }

        service.events().insert(
            calendarId=CALENDAR_ID,
            body=event,
        ).execute()

        print(f"Criado: {item['titulo']} - {item['data']} {item['hora_inicio']}")

    print("\n✅ Eventos de teste criados!")


def show_menu():
    print("\n=== 🗓️ Setup da agenda de demo ===")
    print("1 - Limpar agenda dos próximos 7 dias")
    print("2 - Criar agendas de teste")
    print("3 - Limpar e criar agendas de teste")
    print("0 - Sair")

    return input("\nEscolha uma opção: ")


def main():
    service = authenticate_google()

    option = show_menu()

    if option == "1":
        confirm = input("\n⚠️ Digite SIM para confirmar a limpeza: ")

        if confirm.strip().upper() == "SIM":
            delete_events(service)
        else:
            print("Operação cancelada.")

    elif option == "2":
        create_events(service)

    elif option == "3":
        confirm = input("\n⚠️ Isso vai limpar e recriar a agenda. Digite SIM para continuar: ")

        if confirm.strip().upper() == "SIM":
            delete_events(service)
            create_events(service)
        else:
            print("Operação cancelada.")

    elif option == "0":
        print("Saindo...")

    else:
        print("Opção inválida.")


if __name__ == "__main__":
    main()