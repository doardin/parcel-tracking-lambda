import json
import re
import requests
from twilio.rest import Client
from datetime import datetime
import os

def identify_provider(tracking_code):
    carriers = {
        "correios": r"^((?!ME)[A-Z]){2}\d{9}[A-Z]{2}$",
        "jadlog": r"^(1008|18\d\d)\d{10}$|^(?!957)\d{9,13}$",
        "buslog": r"(^BUS-[0-9]{8}$)|(^\d{8}$)",
        "azul": r"(^[A-Z]{3}-[A-Z]{2}[0-9]{8}$)|(^9[0-9]{7}$)|(^7[0-9]{1}[0-9]{6}$)|(^577[0-9]{8}$)|(^5[1-9]{1}[0-9]{6}$)|(^800[0-9]{1}[0-9]{7}$)|(^[A-Z]{2}[0-9]{8}$)",
        "latam": r"(^66[0-9]{6,12}$)|(^65[0-9]{6,12}$)|(^95[0-9]{6,12}$)|(^957[0-9]{6,12}$)|(^[LTM-]{4}(66|65|95|957)[0-9]{6,12}$)",
        "melhorenvio": r"^[ME]{2}.{9,}[A-Z]{2}$",
        "loggi": r"^LGI-[A-Z]{2}\w{9}[A-Z]{2}",
        "jet": r"^888[0-9]{12}$"
    }
    
    for carrier, pattern in carriers.items():
        if re.match(pattern, tracking_code):
            return carrier
    
    return None

def make_request(tracking_code, provider_type):
    url = 'https://api.melhorrastreio.com.br/graphql'
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    body = {
        "query": """
        mutation searchParcel ($tracker: TrackerSearchInput!) {
            result: searchParcel (tracker: $tracker) {
                id
                createdAt
                updatedAt
                lastStatus
                lastSyncTracker
                nextSyncTracker
                pudos {
                    type
                    trackingCode
                }
                trackers {
                    type
                    shippingService
                    trackingCode
                }
                trackingEvents {
                    trackerType
                    trackingCode
                    createdAt
                    translatedEventId
                    description
                    title
                    to
                    from
                    location {
                        zipcode
                        address
                        locality
                        number
                        complement
                        city
                        state
                        country
                    }
                    additionalInfo
                }
                pudoEvents {
                    pudoType
                    trackingCode
                    createdAt
                    translatedEventId
                    description
                    title
                    from
                    to
                    location {
                        zipcode
                        address
                        locality
                        number
                        complement
                        city
                        state
                        country
                    }
                    additionalInfo
                }
            }
        }
        """,
        "variables": {
            "tracker": {
                "trackingCode": tracking_code,
                "type": provider_type
            }
        }
    }

    response = requests.post(url, headers=headers, json=body)

    if response.status_code != 200:
        return {
            "message": "Unable to complete the request due to an error from the server."
        }

    return response.json()

def lambda_handler(event, context):
    try:
        wa_id = event.get('From')
        body = event.get('Body')
        to = event.get('To')
        
        if not body:
            return {
                "message": "Body is required."
            }

        tracking_code = body
        provider = identify_provider(tracking_code)
        
        if not provider:
            return {
                "message": "Provider could not be identified."
            }
        
        response_json = make_request(tracking_code, provider)
        
        if 'errors' in response_json:
            if isinstance(response_json['errors'], list):
                return response_json
            else:
                return {
                    "message": "Unable to complete the request."
                }
        else:
            return handle_message(response_json, wa_id, to)
    except Exception as e:
        return {
            "message": f"Error processing request: {str(e)}"
        }

def handle_message(response_json, from_, to_):
    account_sid = os.getenv("account_sid")
    auth_token = os.getenv("auth_token")
    client = Client(account_sid, auth_token)

    text = format_tracking_history(response_json["data"]["result"]["trackingEvents"])
    
    client.messages.create(
        from_=to_,
        body=f'{text}',
        to=from_
    )
    
    return {
        "message": "Message sent successfully."
    }

def format_tracking_history(tracking_events):
    return create_history_entry(tracking_events[0])


def create_history_entry(event):
    if not event.get("title"):
        return None
    
    created_at = format_date(event['createdAt'])
    entry = f"📦 Código de Rastreamento: *{event['trackingCode']}* \n📅 Data: {created_at} \nℹ️ Situação: {event['title']} \n📦 De: {event['from']}"
    if event.get("to"):
        entry += f"\n📬 Para: {event['to']}"
        
    if event.get("additionalInfo"):
        entry += f"\nℹ🔍 Informações adicionais: {event['additionalInfo']}"
    
    return entry

def format_date(date_str):
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return dt.strftime("%d/%m/%Y às %H:%M")